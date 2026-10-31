"""Hybrid cloud-quality helpers for optical imagery."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.vrt import WarpedVRT

from .imagery import _check_cancel
from .scenes import Scene


SENTINEL_SPECTRAL_METHOD = "sentinel_spectral_fallback_v1"


def _calibrated_reader(stack, band, reference):
    source = stack.enter_context(rasterio.open(band.path))
    if source.crs is None:
        raise ValueError(f"Spectral cloud source has no CRS: {band.path}")
    vrt = stack.enter_context(WarpedVRT(
        source,
        crs=reference.crs,
        transform=reference.transform,
        width=reference.width,
        height=reference.height,
        resampling=Resampling.bilinear,
        dtype="float64",
        nodata=np.nan,
    ))
    return vrt, band


def _read_reflectance(vrt, band, window):
    values = vrt.read(band.index, window=window, masked=True).astype("float64")
    data = values.data * band.scale + band.offset
    valid = ~np.ma.getmaskarray(values) & np.isfinite(data)
    if band.nodata is not None:
        valid &= values.data != band.nodata
    return data, valid


def sentinel_spectral_cloud_mask(scene, destination, *, cancel=None):
    """Create a conservative cloud-validity mask for Sentinel-2 L2A.

    The fallback is intentionally ancillary to SCL: it targets opaque/bright
    clouds that SCL may leave as bare soil/unclassified. It requires B02, B04,
    NIR and B11/SWIR1. Thresholds follow the structure and current ranges
    documented for Sen2Cor cloud filtering (NDVI and B2/B11, B8/B11, B4/B11
    ratios), but this is not a reimplementation of the full Sen2Cor processor.
    """
    if not isinstance(scene, Scene):
        raise TypeError("scene must be a Scene.")
    if scene.sensor != "sentinel-2" or scene.quality_kind != "sentinel_scl":
        return None
    nir_name = "nir_narrow" if "nir_narrow" in scene.bands else "nir" if "nir" in scene.bands else None
    required = {"blue", "red", "swir1"}
    if nir_name is None or not required.issubset(scene.bands):
        return None
    names = ["blue", "red", nir_name, "swir1"]
    if "green" in scene.bands:
        names.append("green")
    if any(str(scene.bands[name].unit).lower() != "reflectance" for name in names):
        return None

    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    from contextlib import ExitStack
    with ExitStack() as stack:
        reference = stack.enter_context(rasterio.open(scene.bands["blue"].path))
        if reference.crs is None:
            raise ValueError(f"Sentinel blue band has no CRS: {scene.bands['blue'].path}")
        readers = {name: _calibrated_reader(stack, scene.bands[name], reference) for name in names}
        profile = reference.profile.copy()
        profile.update(
            driver="GTiff", count=1, dtype="uint8", nodata=255,
            compress="lzw", tiled=True, blockxsize=256, blockysize=256,
            BIGTIFF="IF_SAFER",
        )
        cloud_pixels = 0
        observed_pixels = 0
        with rasterio.open(destination, "w", **profile) as dst:
            for _, window in dst.block_windows(1):
                _check_cancel(cancel)
                data = {}
                valid = None
                for name, (vrt, band) in readers.items():
                    values, available = _read_reflectance(vrt, band, window)
                    data[name] = values
                    valid = available if valid is None else valid & available
                blue, red = data["blue"], data["red"]
                nir, swir = data[nir_name], data["swir1"]
                eps = 1e-6
                ndvi = (nir - red) / (nir + red + eps)
                b2_b11 = blue / (swir + eps)
                nir_b11 = nir / (swir + eps)
                red_b11 = red / (swir + eps)
                if "green" in data:
                    visible = (blue + data["green"] + red) / 3.0
                else:
                    visible = (blue + red) / 2.0

                # Conservative high-confidence cloud candidate.
                potential = (
                    valid
                    & (blue >= 0.15)
                    & (visible >= 0.15)
                    & (ndvi < 0.36)
                    & (b2_b11 >= 0.70)
                    & (b2_b11 <= 4.0)
                    & (nir_b11 >= 0.90)
                    & (red_b11 <= 6.0)
                )
                # Sen2Cor-like water safeguard: bright-blue water with NIR below red.
                water_like = valid & (b2_b11 > 2.0) & (blue < 0.20) & (nir < red)
                cloud = potential & ~water_like
                mask = np.full(valid.shape, 255, dtype="uint8")
                mask[valid & ~cloud] = 1
                mask[cloud] = 0
                dst.write(mask, 1, window=window)
                observed_pixels += int(valid.sum())
                cloud_pixels += int(cloud.sum())
            dst.set_band_description(1, "spectral_cloud_valid")
            dst.update_tags(
                CARTOMIZE_PRODUCT="sentinel_spectral_cloud_mask",
                method=SENTINEL_SPECTRAL_METHOD,
                semantics="1=valid,0=spectral_cloud,255=insufficient_spectral_data",
                required_bands="blue,red,nir_or_nir_narrow,swir1",
            )
    return {
        "path": destination,
        "method": SENTINEL_SPECTRAL_METHOD,
        "observed_pixels": observed_pixels,
        "cloud_pixels": cloud_pixels,
        "cloud_percent": 100.0 * cloud_pixels / observed_pixels if observed_pixels else 0.0,
    }


def augment_sentinel_cloud_masks(scenes, destination, *, cancel=None, stage=None):
    """Attach runtime spectral fallback masks to compatible Sentinel-2 scenes."""
    destination = Path(destination)
    augmented = []
    reports = []
    for index, scene in enumerate(scenes):
        _check_cancel(cancel)
        result = sentinel_spectral_cloud_mask(
            scene, destination / f"scene_{index + 1:04d}_spectral_cloud.tif", cancel=cancel
        )
        if result is None:
            augmented.append(scene)
            reports.append({
                "scene_id": scene.scene_id,
                "status": "not_available",
                "method": SENTINEL_SPECTRAL_METHOD,
                "reason": "requires Sentinel-2 SCL plus reflectance blue/red/nir/swir1",
            })
            continue
        if stage:
            stage(
                f"N4 — Détection spectrale de secours : {result['cloud_pixels']} pixels "
                f"({result['cloud_percent']:.3f} %) pour {scene.scene_id}"
            )
        augmented.append(replace(
            scene,
            spectral_cloud=result["path"],
            spectral_cloud_method=result["method"],
            notes=tuple(scene.notes) + (
                f"Spectral cloud fallback {result['method']}: "
                f"{result['cloud_pixels']} pixels détectés ({result['cloud_percent']:.4f} %).",
            ),
        ))
        reports.append({
            "scene_id": scene.scene_id,
            "status": "applied",
            **{k: (str(v) if isinstance(v, Path) else v) for k, v in result.items()},
        })
    return augmented, reports
