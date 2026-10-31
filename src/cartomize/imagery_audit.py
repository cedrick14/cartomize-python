"""Exact, windowed diagnosis of multispectral coverage before preparation."""
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
import json
import math
import tempfile

import numpy as np
import rasterio
from rasterio.enums import ColorInterp, Resampling
from rasterio.features import geometry_mask
from rasterio.vrt import WarpedVRT

from .imagery import (_calibrate, _check_cancel, _plan_imagery,
                      _quality_categories, _quality_category_names)
from .raster import _read
from .scenes import Scene, discover_scenes
from .storage import new_directory, save_json


@dataclass(frozen=True)
class ImageryAudit:
    """Published diagnostic products and their in-memory report."""
    manifest: Path
    coverage: Path
    gaps: Path
    report: dict


def _footprint(source, destination, cancel):
    """Represent every source-grid cell, ignoring its data and validity masks.

    Keeping the native affine grid preserves rotated footprints and the same
    warp support as the actual bands. Equal native grids share this raster.
    """
    profile = dict(driver="GTiff", width=source.width, height=source.height,
                   count=1, transform=source.transform, crs=source.crs,
                   dtype="uint8", nodata=0, compress="lzw", tiled=True,
                   blockxsize=256, blockysize=256, BIGTIFF="IF_SAFER")
    with rasterio.open(destination, "w", **profile) as dst:
        for _, window in dst.block_windows(1):
            _check_cancel(cancel)
            dst.write(np.ones((int(window.height), int(window.width)), dtype="uint8"),
                      1, window=window)


def _statistics(counts, denominator):
    result = {}
    for name, value in zip(("footprint", "present", "usable"), counts):
        result[f"{name}_pixels"] = int(value)
        result[f"{name}_percent"] = 100. * int(value) / denominator if denominator else 0.
    return result


def audit_imagery(scenes, destination, *, aoi, band_order=None, target_crs=None,
                  resolution=None, resampling="nearest", mask_clouds=True,
                  mask_saturation=True, allow_mixed_dates=False, all_touched=False,
                  max_pixels=250_000_000, coverage_threshold=100., progress=None,
                  cancel=None):
    """Diagnose scene coverage on the exact grid used by ``prepare_imagery``.

    The three coverage bands describe source footprints, finite source data
    after their declared NoData/masks, and usable data after requested quality
    masks. A pixel requires every selected band from one acquisition; bands
    from different scenes never complete one another. Percentages count AOI
    pixels on the target grid, not fractional polygon areas or sampled data.

    ``coverage.tif`` stores 0/1 and 255 outside the AOI. ``gaps.tif`` uses
    0=usable, 1=outside common band footprints, 2=missing data,
    3=quality rejection, and 255=outside AOI. The destination must be new.
    A scene recommendation is advisory and never modifies the selected inputs.
    """
    _check_cancel(cancel)
    if aoi is None:
        raise ValueError("An AOI is required to diagnose imagery coverage.")
    coverage_threshold = float(coverage_threshold)
    if not np.isfinite(coverage_threshold) or not 0 < coverage_threshold <= 100:
        raise ValueError("coverage_threshold must be greater than 0 and at most 100.")
    if not isinstance(scenes, (str, Path)):
        scenes = list(scenes)
        if scenes and not all(isinstance(scene, Scene) for scene in scenes):
            scenes = discover_scenes(scenes)
    plan = _plan_imagery(scenes, aoi=aoi, band_order=band_order,
        target_crs=target_crs, resolution=resolution, resampling=resampling,
        mask_clouds=mask_clouds, allow_mixed_dates=allow_mixed_dates,
        max_pixels=max_pixels, cancel=cancel)
    scenes, names = plan["scenes"], plan["names"]
    destination = Path(destination).expanduser().resolve()
    coverage_path, gaps_path = destination / "coverage.tif", destination / "gaps.tif"
    manifest_path = destination / "report.json"
    profile = dict(driver="GTiff", width=plan["width"], height=plan["height"],
                   crs=plan["crs"], transform=plan["transform"], count=3,
                   dtype="uint8", nodata=255, compress="lzw", tiled=True,
                   blockxsize=256, blockysize=256, BIGTIFF="IF_SAFER")
    warp_options = dict(crs=plan["crs"], transform=plan["transform"],
                        width=plan["width"], height=plan["height"],
                        dtype="float32", nodata=np.nan,
                        resampling=Resampling[resampling])
    total = len(plan["records"]) + math.ceil(plan["width"] / 256) * math.ceil(plan["height"] / 256)
    done = 0
    if progress:
        progress(0, total)
    counts = np.zeros(3, dtype="int64")
    scene_counts = np.zeros((len(scenes), 3), dtype="int64")
    quality_counts = [dict() for _ in scenes]
    aoi_pixels = 0

    with new_directory(destination) as work:
        with tempfile.TemporaryDirectory(prefix=".calibration-", dir=work) as temporary:
            scratch = Path(temporary)
            with ExitStack() as stack:
                readers, footprint_readers = [], {}

                def reader(path):
                    dataset = stack.enter_context(rasterio.open(path))
                    return stack.enter_context(WarpedVRT(dataset, **warp_options))

                def quality_reader(path):
                    dataset = stack.enter_context(rasterio.open(path))
                    return stack.enter_context(WarpedVRT(
                        dataset, crs=plan["crs"], transform=plan["transform"],
                        width=plan["width"], height=plan["height"],
                        dtype="float64", nodata=np.nan, resampling=Resampling.nearest))

                quality_readers = []
                for scene_index, scene in enumerate(scenes):
                    bands = []
                    for band_index, name in enumerate(names):
                        _check_cancel(cancel)
                        asset = scene.bands[name]
                        with rasterio.open(asset.path) as source:
                            key = (str(source.crs), tuple(source.transform), source.width, source.height)
                            if key not in footprint_readers:
                                path = scratch / f"footprint_{len(footprint_readers)}.tif"
                                _footprint(source, path, cancel)
                                footprint_readers[key] = reader(path)
                        path = scratch / f"s{scene_index}_b{band_index}_present.tif"
                        _calibrate(asset, scene, path, False, False, cancel)
                        present = reader(path)
                        if mask_clouds or (mask_saturation and scene.saturation is not None):
                            path = scratch / f"s{scene_index}_b{band_index}_usable.tif"
                            _calibrate(asset, scene, path, mask_clouds, mask_saturation, cancel)
                            usable = reader(path)
                        else:
                            usable = present
                        bands.append((footprint_readers[key], present, usable))
                        done += 1
                        if progress:
                            progress(done, total)
                    readers.append(bands)

                with rasterio.open(work / "coverage.tif", "w", **profile) as coverage, \
                     rasterio.open(work / "gaps.tif", "w", **{**profile, "count": 1}) as gaps:
                    for _, window in coverage.block_windows(1):
                        _check_cancel(cancel)
                        shape = (int(window.height), int(window.width))
                        inside = geometry_mask(plan["geometries"], out_shape=shape,
                            transform=coverage.window_transform(window), invert=True,
                            all_touched=all_touched)
                        aoi_pixels += int(inside.sum())
                        combined = np.zeros((3, *shape), dtype=bool)
                        cache = {}
                        for scene_index, bands in enumerate(readers):
                            common = np.broadcast_to(inside, (3, *shape)).copy()
                            for band in bands:
                                for kind, raster in enumerate(band):
                                    key = id(raster)
                                    if key not in cache:
                                        cache[key] = ~np.ma.getmaskarray(_read(raster, 1, window=window))
                                    common[kind] &= cache[key]
                            scene_counts[scene_index] += common.sum(axis=(1, 2))
                            quality = quality_readers[scene_index]
                            if quality is not None:
                                quality_values = _read(quality[0], 1, window=window)
                                categories = _quality_categories(quality_values, quality[1])
                                domain = common[0]
                                summary = quality_counts[scene_index]
                                for name, category in categories.items():
                                    summary[name] = summary.get(name, 0) + int((domain & category).sum())
                            combined |= common
                        counts += combined.sum(axis=(1, 2))
                        encoded = np.where(inside[None, :, :], combined, 255).astype("uint8")
                        coverage.write(encoded, window=window)
                        reasons = np.full(shape, 255, dtype="uint8")
                        reasons[inside] = 1
                        reasons[combined[0]] = 2
                        reasons[combined[1]] = 3
                        reasons[combined[2]] = 0
                        gaps.write(reasons, 1, window=window)
                        done += 1
                        if progress:
                            progress(done, total)
                    coverage.descriptions = ("footprint", "present", "usable")
                    coverage.colorinterp = (ColorInterp.gray, ColorInterp.undefined, ColorInterp.undefined)
                    coverage.update_tags(CARTOMIZE_PRODUCT="imagery_coverage",
                        coverage_method="target_grid_pixel_count", spectral_coherence="all_bands_same_scene",
                        outside_aoi="255", CARTOMIZE_CLASSES=json.dumps({
                            "0": ["Non couvert", "#5a5a5a"], "1": ["Couvert", "#287846"]}, ensure_ascii=False))
                    gaps.set_band_description(1, "gap_reason")
                    gaps.update_tags(CARTOMIZE_PRODUCT="imagery_gaps", outside_aoi="255",
                        classes="0:usable,1:outside_footprint,2:missing_data,3:quality_rejection",
                        CARTOMIZE_CLASSES=json.dumps({
                            "0": ["Donnée utilisable", "#287846"], "1": ["Hors emprise", "#5a5a5a"],
                            "2": ["Donnée absente", "#d27d23"], "3": ["Qualité exclue", "#a54150"]}, ensure_ascii=False))
                    gaps.write_colormap(1, {0: (40, 120, 70, 255), 1: (90, 90, 90, 255),
                        2: (210, 125, 35, 255), 3: (165, 65, 80, 255), 255: (0, 0, 0, 0)})

        def quality_summary(index, scene):
            if scene.quality is None:
                return None
            denominator = int(scene_counts[index, 0])
            result = {"kind": scene.quality_kind, "evaluated_pixels": denominator}
            for name in _quality_category_names(scene.quality_kind):
                value = int(quality_counts[index].get(name, 0))
                result[f"{name}_pixels"] = value
                result[f"{name}_percent"] = 100. * value / denominator if denominator else 0.
            return result

        summaries = []
        for i, scene in enumerate(scenes):
            item = dict(index=i + 1, id=scene.scene_id, sensor=scene.sensor,
                level=scene.level, acquired=scene.acquired,
                quality_mask=str(Path(scene.quality).resolve()) if scene.quality else None,
                saturation_mask=str(Path(scene.saturation).resolve()) if scene.saturation else None,
                **_statistics(scene_counts[i], aoi_pixels))
            quality = quality_summary(i, scene)
            if quality is not None:
                item["quality_statistics"] = quality
            summaries.append(item)
        statistics = _statistics(counts, aoi_pixels)
        complete = statistics["usable_percent"] + 1e-9 >= coverage_threshold
        eligible = [item for item in summaries if item["usable_percent"] + 1e-9 >= coverage_threshold]
        contributors = [item for item in summaries if item["usable_pixels"] > 0]
        if eligible:
            best = max(eligible, key=lambda item: item["usable_pixels"])
            action, recommended = "single_scene", [best["id"]]
        else:
            action = "mosaic" if complete else "additional_scenes"
            recommended = [item["id"] for item in contributors]
        parameters = dict(band_order=list(names), crs=str(plan["crs"]),
            resolution_m=plan["resolution"], width=plan["width"], height=plan["height"],
            transform=list(plan["transform"])[:6], resampling=resampling,
            mask_clouds=mask_clouds, mask_saturation=mask_saturation,
            allow_mixed_dates=allow_mixed_dates, all_touched=all_touched,
            coverage_threshold=coverage_threshold, max_pixels=max_pixels,
            aoi=str(Path(aoi).expanduser().resolve()) if isinstance(aoi, (str, Path)) else None)
        from . import __version__
        report = dict(schema="cartomize.imagery.audit.v1", version=__version__,
            coverage=str(coverage_path), gaps=str(gaps_path), parameters=parameters,
            aoi_pixels=aoi_pixels, **statistics, scenes=summaries, assets=plan["records"],
            coverage_status="empty" if counts[2] == 0 else "complete" if statistics["usable_percent"] + 1e-9 >= 100 else "partial",
            threshold_met=complete,
            recommended_action=action, recommended_scene_ids=recommended,
            mosaic_recommended=bool(len(contributors) > 1 and counts[2] > scene_counts[:, 2].max()),
            coverage_method="target_grid_pixel_count",
            quality_statistics_scope="per_scene_common_band_footprint_on_target_grid",
            gap_classes={"0": "usable", "1": "outside_footprint", "2": "missing_data",
                         "3": "quality_rejection", "255": "outside_aoi"},
            notes=["All selected bands must be present in the same scene for a pixel to count.",
                   "Percentages use AOI pixels on the target grid; they are not fractional polygon areas.",
                   "Recommendations do not change the selected sources or authorize mixing dates.",
                   "Quality statistics are reported per scene on its common selected-band footprint; scene counts are not additive where scenes overlap."])
        if not aoi_pixels:
            report["notes"].append("The AOI contains no target-grid pixel under the selected boundary rule; choose a finer grid or all_touched=True.")
        save_json(report, work / "report.json")
        _check_cancel(cancel)
    if progress:
        progress(total, total)
    return ImageryAudit(manifest_path, coverage_path, gaps_path, report)
