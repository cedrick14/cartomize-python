"""Coverage-driven imagery preparation shared by Python, CLI and the desktop."""
from dataclasses import dataclass
from http.client import HTTPException
from pathlib import Path
import copy
import math
import os
import shutil

import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.transform import from_origin
from shapely.geometry import mapping

from ._validation import frame, linear_factor
from .imagery import _check_cancel, _plan_imagery
from .imagery_audit import ImageryAudit, audit_imagery
from .imagery_pipeline import process_imagery
from .scenes import Scene, discover_scenes
from .preprocessing_plan import assess_preprocessing
from .imagery_recovery import recover_scene
from .atmospheric import dos1_scene
from .storage import new_directory, read_json, relocate_products, save_json


@dataclass(frozen=True)
class PreprocessedImagery:
    """Scientific outputs, the exact selected-scene audit and decision record."""
    manifest: Path
    products: tuple[dict, ...]
    diagnostic: ImageryAudit
    report: dict


def diagnostic_destination(destination):
    """Choose an unused sibling for a blocked run, never overwrite a report."""
    destination = Path(destination).expanduser().resolve()
    base = destination.with_name(destination.name + "_diagnostic")
    candidate, number = base, 2
    while candidate.exists():
        candidate = base.with_name(base.name + f"_{number}")
        number += 1
    return candidate


class ImageryCoverageError(ValueError):
    """Preparation stopped; diagnostic products remain available on disk."""
    def __init__(self, diagnostic, workflow_report=None):
        self.diagnostic = diagnostic
        self.manifest = diagnostic.manifest
        self.report = diagnostic.report
        self.workflow_report = workflow_report or {}
        threshold = self.report["parameters"]["coverage_threshold"]
        message = (f"Couverture utile insuffisante : {self.report['usable_percent']:.2f} % "
                   f"pour un seuil de {threshold:g} %. Aucun produit scientifique publié. "
                   f"Diagnostic : {self.manifest}")
        if not self.report["aoi_pixels"]:
            message = ("Aucun pixel de la grille ne représente la zone d’étude. "
                       "Choisir une résolution plus fine ou inclure les pixels touchés. "
                       f"Diagnostic : {self.manifest}")
        super().__init__(message)

    def preserve(self, destination, *, cancel=None):
        """Copy the diagnostic beyond a caller's atomic rollback boundary."""
        destination = Path(destination).expanduser().resolve()
        source_directory = self.workflow_report.get("download_directory")
        source_directory = Path(source_directory) if source_directory else None
        def replace(value):
            if isinstance(value, str) and source_directory and value.startswith(str(source_directory) + os.sep):
                return str(destination / "acquisitions") + value[len(str(source_directory)):]
            if isinstance(value, dict):
                return {key: replace(item) for key, item in value.items()}
            if isinstance(value, list):
                return [replace(item) for item in value]
            return value
        report = replace(copy.deepcopy(self.report))
        report.update(coverage=str(destination / "coverage.tif"), gaps=str(destination / "gaps.tif"))
        workflow = replace(copy.deepcopy(self.workflow_report))
        workflow.update(audit=str(destination / "report.json"), coverage=report["coverage"],
                        gaps=report["gaps"], products=[], preparation=None,
                        download_directory=str(destination / "acquisitions") if source_directory and source_directory.exists() else None)
        def copy_file(source, target):
            _check_cancel(cancel)
            with open(source, "rb") as reader, open(target, "xb") as writer:
                while True:
                    _check_cancel(cancel)
                    block = reader.read(1024 * 1024)
                    if not block:
                        break
                    writer.write(block)
            shutil.copystat(source, target)
            return target
        with new_directory(destination) as work:
            copy_file(self.diagnostic.coverage, work / "coverage.tif")
            copy_file(self.diagnostic.gaps, work / "gaps.tif")
            if source_directory and source_directory.exists():
                shutil.copytree(source_directory, work / "acquisitions", copy_function=copy_file)
            save_json(report, work / "report.json")
            save_json(workflow, work / "preprocessing.json")
            _check_cancel(cancel)
        return ImageryCoverageError(ImageryAudit(destination / "report.json",
            destination / "coverage.tif", destination / "gaps.tif", report), workflow)


def _catalog_config(value):
    if value is None:
        return None
    if isinstance(value, (str, Path)):
        value = read_json(value)
    if not isinstance(value, dict):
        raise ValueError("catalog doit être un objet de configuration STAC ou son fichier JSON.")
    accepted = {"endpoint", "collections", "datetime_range", "max_items", "max_bytes", "timeout",
                "band_mapping", "quality_asset", "quality_kind", "saturation_asset"}
    unknown = set(value) - accepted
    if unknown:
        raise ValueError("Paramètres de catalogue inconnus : " + ", ".join(sorted(unknown)))
    from .catalogs import _url
    result = {"collections": [], "max_items": 10, "max_bytes": 1_000_000_000,
              "timeout": 60, **value}
    result["endpoint"] = _url(result.get("endpoint", ""))
    if not isinstance(result["collections"], (list, tuple)) or any(
            not isinstance(v, str) or not v.strip() for v in result["collections"]):
        raise ValueError("collections doit être une liste d’identifiants de collections STAC.")
    for key, maximum in (("max_items", 1000), ("max_bytes", None)):
        number = result[key]
        if type(number) is not int or number < 1 or maximum is not None and number > maximum:
            raise ValueError(f"{key} doit être un entier positif" + (f" ≤ {maximum}." if maximum else "."))
    if type(result["timeout"]) not in (int, float) or not math.isfinite(result["timeout"]) or not 0 < result["timeout"] <= 300:
        raise ValueError("timeout doit être compris entre 0 et 300 secondes.")
    if result.get("datetime_range") is not None and (not isinstance(result["datetime_range"], str) or not result["datetime_range"].strip()):
        raise ValueError("datetime_range doit être une date ou un intervalle STAC explicite.")
    if "band_mapping" in result and (not isinstance(result["band_mapping"], dict) or any(
            not isinstance(key, str) or not key or not isinstance(role, str) or not role
            for key, role in result["band_mapping"].items())):
        raise ValueError("band_mapping doit associer des identifiants d’assets à des rôles spectraux textuels.")
    for key in ("quality_asset", "saturation_asset"):
        if key in result and (not isinstance(result[key], str) or not result[key].strip()):
            raise ValueError(f"{key} doit être un identifiant d’asset non vide.")
    if "quality_kind" in result and (not isinstance(result["quality_kind"], str) or result["quality_kind"] not in {"landsat_qa", "sentinel_scl", "valid_mask"}):
        raise ValueError("quality_kind doit être landsat_qa, sentinel_scl ou valid_mask.")
    return result


def _empty_audit(destination, zones, *, target_crs, resolution, band_order,
                 coverage_threshold, max_pixels, all_touched, cancel, **parameters):
    """An exact empty-coverage diagnostic when a catalog yields no usable scene."""
    zones = zones.to_crs(target_crs)
    cell = float(resolution) / linear_factor(target_crs)
    left, bottom, right, top = zones.total_bounds
    if not np.isfinite([left, bottom, right, top]).all():
        raise ValueError("La projection choisie ne peut pas représenter la zone d’étude.")
    left, bottom = math.floor(left / cell + 1e-9) * cell, math.floor(bottom / cell + 1e-9) * cell
    right, top = math.ceil(right / cell - 1e-9) * cell, math.ceil(top / cell - 1e-9) * cell
    width, height = round((right - left) / cell), round((top - bottom) / cell)
    if width < 1 or height < 1 or width * height > max_pixels:
        raise ValueError(f"Output grid is {width}×{height} pixels. Adjust AOI/resolution or max_pixels.")
    transform = from_origin(left, top, cell, cell)
    destination = Path(destination)
    profile = dict(driver="GTiff", width=width, height=height, crs=target_crs,
                   transform=transform, dtype="uint8", nodata=255, compress="lzw", tiled=True)
    count = 0
    with new_directory(destination) as work:
        with rasterio.open(work / "coverage.tif", "w", count=3, **profile) as coverage, \
                rasterio.open(work / "gaps.tif", "w", count=1, **profile) as gaps:
            for _, window in coverage.block_windows(1):
                _check_cancel(cancel)
                inside = geometry_mask(list(zones.geometry), out_shape=(int(window.height), int(window.width)),
                    transform=coverage.window_transform(window), invert=True, all_touched=all_touched)
                count += int(inside.sum())
                coverage.write(np.broadcast_to(np.where(inside, 0, 255).astype("uint8"), (3, *inside.shape)), window=window)
                gaps.write(np.where(inside, 1, 255).astype("uint8"), 1, window=window)
            coverage.descriptions = ("footprint", "present", "usable")
            gaps.set_band_description(1, "gap_reason")
            coverage.update_tags(CARTOMIZE_PRODUCT="imagery_coverage", coverage_method="target_grid_pixel_count",
                                 spectral_coherence="all_bands_same_scene", outside_aoi="255")
            gaps.update_tags(CARTOMIZE_PRODUCT="imagery_gaps", outside_aoi="255",
                classes="0:usable,1:outside_footprint,2:missing_data,3:quality_rejection")
            gaps.write_colormap(1, {0: (40, 120, 70, 255), 1: (90, 90, 90, 255),
                2: (210, 125, 35, 255), 3: (165, 65, 80, 255), 255: (0, 0, 0, 0)})
        from . import __version__
        report = dict(schema="cartomize.imagery.audit.v1", version=__version__, aoi_pixels=count,
            coverage=str(destination / "coverage.tif"), gaps=str(destination / "gaps.tif"),
            parameters=dict(parameters, crs=str(target_crs), resolution_m=resolution,
                band_order=list(band_order), width=width, height=height, transform=list(transform)[:6],
                max_pixels=max_pixels, all_touched=all_touched, coverage_threshold=coverage_threshold),
            scenes=[], assets=[], coverage_status="empty", threshold_met=False, recommended_action="additional_scenes",
            recommended_scene_ids=[], mosaic_recommended=False, coverage_method="target_grid_pixel_count",
            gap_classes={"0": "usable", "1": "outside_footprint", "2": "missing_data",
                         "3": "quality_rejection", "255": "outside_aoi"},
            notes=["No usable catalog scene was available; no scientific image was created."],
            **{f"{name}_{unit}": 0 for name in ("footprint", "present", "usable") for unit in ("pixels", "percent")})
        save_json(report, work / "report.json")
    return ImageryAudit(destination / "report.json", destination / "coverage.tif", destination / "gaps.tif", report)


def _snapshot(scenes, names, mask_clouds, mask_saturation):
    paths = {Path(scene.bands[name].path).resolve() for scene in scenes for name in names}
    paths.update(Path(path).resolve() for scene in scenes for path in (
        scene.quality if mask_clouds else None, scene.saturation if mask_saturation else None) if path)
    return {str(path): (path.stat().st_size, path.stat().st_mtime_ns) for path in paths}


def preprocess_imagery(scenes, destination, *, aoi, coverage_threshold=100., allow_partial=False,
                      catalog=None, multiband=True, separate_bands=False, composition=None,
                      band_order=None, target_crs=None, resolution=None, overlap="first",
                      resampling="nearest", mask_clouds=True, mask_saturation=True,
                      allow_mixed_dates=False, all_touched=False, max_pixels=250_000_000,
                      percentiles=(2, 98), gamma=1., atmospheric_method="auto",
                      progress=None, cancel=None, stage=None):
    """Audit, optionally replenish, select scenes, then prepare on a fixed grid.

    Production is blocked below ``coverage_threshold`` unless ``allow_partial``
    is explicit. Zero usable pixels always block. ``ImageryCoverageError``
    preserves the report and gap maps in a new sibling diagnostic directory.
    A lower threshold does not relabel partial actual coverage as complete.

    ``catalog`` is an optional STAC configuration, supplied by the caller.
    Network access occurs only when coverage is insufficient. Compatible scenes
    are downloaded within item/byte limits and retained only if they improve
    exact useful coverage. Dates and sensors are never mixed implicitly.
    For catalog-only runs pass scenes=[] and explicit bands, projected CRS and
    resolution. Cancellation/errors publish no scientific output directory.
    """
    _check_cancel(cancel)
    threshold = float(coverage_threshold)
    if not math.isfinite(threshold) or not 0 < threshold <= 100:
        raise ValueError("coverage_threshold doit être supérieur à 0 et inférieur ou égal à 100.")
    if type(allow_partial) is not bool:
        raise ValueError("allow_partial doit être un booléen explicite.")
    for name, value in (("mask_clouds", mask_clouds), ("mask_saturation", mask_saturation),
                        ("allow_mixed_dates", allow_mixed_dates), ("all_touched", all_touched),
                        ("multiband", multiband), ("separate_bands", separate_bands)):
        if type(value) is not bool:
            raise ValueError(f"{name} doit être un booléen explicite.")
    if type(max_pixels) is not int or max_pixels < 1:
        raise ValueError("max_pixels doit être un entier positif.")
    if atmospheric_method not in {"auto", "provider", "dos1"}:
        raise ValueError("atmospheric_method must be auto, provider or dos1.")
    if overlap not in {"first", "last"}:
        raise ValueError("overlap doit être first ou last.")
    if resampling not in {"nearest", "bilinear", "cubic", "average"}:
        raise ValueError("Méthode de rééchantillonnage non prise en charge.")
    if not (multiband or separate_bands or composition is not None):
        raise ValueError("Choisir au moins un produit : multibande, bandes séparées ou composition.")
    def announce_early(text):
        if stage:
            stage(text)
    config = _catalog_config(catalog)
    if aoi is None:
        raise ValueError("Une zone d’étude polygonale est requise en mode automatique.")
    zones = frame(aoi)
    if zones.empty or zones.geometry.isna().any() or zones.geometry.is_empty.any() or not zones.geometry.is_valid.all() or not zones.geom_type.isin(["Polygon", "MultiPolygon"]).all():
        raise ValueError("La zone d’étude doit contenir des polygones valides et non vides.")
    if isinstance(scenes, (str, Path)):
        scenes = discover_scenes(scenes)
    else:
        scenes = list(scenes) if scenes is not None else []
        if scenes and not all(isinstance(scene, Scene) for scene in scenes):
            scenes = discover_scenes(scenes)
    if not scenes and config is None:
        raise ValueError("Sélectionner des scènes ou configurer un catalogue STAC.")
    preprocessing_plan = assess_preprocessing(
        scenes, mask_clouds=mask_clouds, mask_saturation=mask_saturation
    ) if scenes else None
    if preprocessing_plan is not None:
        announce_early("N1 — Diagnostic radiométrique")
        announce_early("N2 — Diagnostic atmosphérique")
        announce_early("N3 — Contrôle qualité")
        announce_early("N4 — Diagnostic nuages et pixels non utilisables")
    initial_preprocessing_plan = copy.deepcopy(preprocessing_plan) if preprocessing_plan is not None else None
    recovery_records = []
    if preprocessing_plan is not None and config is not None and atmospheric_method in {"auto", "provider"}:
        needs_recovery = {
            scene["scene_id"]
            for scene in preprocessing_plan["scenes"]
            if any(level["status"] in {
                "required_but_unavailable", "missing_inputs", "unavailable"
            } for level in scene["levels"])
        }
        if needs_recovery:
            search_geometry = mapping(zones.to_crs(4326).geometry.union_all())
            recovered = []
            recovery_root = Path(destination).expanduser().resolve().with_name(
                Path(destination).expanduser().resolve().name + "_recovery"
            )
            for index, scene in enumerate(scenes):
                if scene.scene_id not in needs_recovery:
                    recovered.append(scene)
                    continue
                candidate, record = recover_scene(
                    scene,
                    recovery_root / f"scene_{index + 1:04d}",
                    config=config,
                    search_geometry=search_geometry,
                    band_order=band_order or tuple(scene.bands),
                    mask_clouds=mask_clouds,
                    mask_saturation=mask_saturation,
                    progress=None,
                    cancel=cancel,
                )
                recovery_records.append(record)
                recovered.append(candidate or scene)
            scenes = recovered
            preprocessing_plan = assess_preprocessing(
                scenes, mask_clouds=mask_clouds, mask_saturation=mask_saturation
            )
    if preprocessing_plan is not None and atmospheric_method in {"auto", "dos1"}:
        toa_ids = {
            scene["scene_id"]
            for scene in preprocessing_plan["scenes"]
            if any(level["name"] == "atmospheric_correction"
                   and level["status"] == "required_but_unavailable"
                   for level in scene["levels"])
        }
        if toa_ids:
            announce_early("N2 — Aucun Level-2/SR exact disponible ; évaluation du fallback DOS1")
            corrected = []
            for scene in scenes:
                if scene.scene_id not in toa_ids:
                    corrected.append(scene)
                    continue
                candidate = dos1_scene(
                    scene, mask_clouds=mask_clouds, mask_saturation=mask_saturation,
                    cancel=cancel,
                )
                recovery_records.append({
                    "scene_id": scene.scene_id,
                    "replacement_scene_id": candidate.scene_id,
                    "status": "corrected",
                    "reason": "dos1_local_fallback",
                    "retained": True,
                    "method": "dos1_reflectance_approximation",
                })
                corrected.append(candidate)
            scenes = corrected
            preprocessing_plan = assess_preprocessing(
                scenes, mask_clouds=mask_clouds, mask_saturation=mask_saturation
            )
            announce_early("N2 — Fallback DOS1 appliqué aux scènes TOA compatibles")
    if preprocessing_plan is not None:
        blockers = []
        for scene in preprocessing_plan["scenes"]:
            for level in scene["levels"]:
                if level["status"] in {
                    "insufficient_metadata", "required_but_unavailable",
                    "missing_inputs", "unavailable", "undetermined", "not_assessed"
                }:
                    blockers.append((scene["scene_id"], level["name"], level.get("missing", [])))
        if blockers:
            detail = "; ".join(
                f"{scene}: {name} ({', '.join(missing) or 'entrée manquante'})"
                for scene, name, missing in blockers
            )
            raise ValueError(
                "Prétraitement automatique bloqué après récupération des entrées : " + detail
            )
    if not scenes and (not band_order or target_crs is None or resolution is None):
        raise ValueError("Sans scène locale, définir band_order, target_crs projeté et resolution.")
    if resolution is not None and (not math.isfinite(float(resolution)) or float(resolution) <= 0):
        raise ValueError("resolution doit être positive, en mètres.")
    if target_crs is not None:
        linear_factor(target_crs)
    if band_order is not None and (isinstance(band_order, str) or not band_order or
            any(not isinstance(name, str) or not name.strip() for name in band_order) or len(set(band_order)) != len(band_order)):
        raise ValueError("band_order doit être une liste non vide de rôles spectraux uniques.")
    destination = Path(destination).expanduser().resolve()
    common = dict(aoi=zones, band_order=band_order, target_crs=target_crs, resolution=resolution,
                  resampling=resampling, mask_clouds=mask_clouds, mask_saturation=mask_saturation,
                  allow_mixed_dates=allow_mixed_dates, all_touched=all_touched, max_pixels=max_pixels)
    # Fix the complete target grid before selecting or downloading more scenes.
    if scenes:
        plan = _plan_imagery(scenes, **{k: v for k, v in common.items() if k not in {"mask_saturation", "all_touched"}}, cancel=cancel)
        common.update(band_order=plan["names"], target_crs=plan["crs"], resolution=plan["resolution"])
    def announce(text):
        announce_early(text)
    def callback(start, end):
        def update(done, total):
            if progress:
                progress(start + round((end - start) * done / max(1, total)), 10000)
        return update
    if progress:
        progress(0, 10000)
    requests, initial_report, final_audit, total_bytes = [], None, None, 0
    with new_directory(destination) as work:
        rounds = work / "rounds"
        def examine(selected, name, start, end):
            announce("Contrôle des bandes, des masques et de la couverture utile")
            return audit_imagery(selected, rounds / name, coverage_threshold=threshold,
                progress=callback(start, end), cancel=cancel, **common)
        audit = examine(scenes, "initial", 0, 1800) if scenes else None
        if audit:
            initial_report = copy.deepcopy(audit.report)
        needs_more = audit is None or audit.report["usable_percent"] + 1e-9 < threshold
        if config is not None and needs_more:
            from .catalogs import search_stac, download_stac, load_scenes_manifest, stac_asset_keys
            announce("Recherche des scènes complémentaires dans le catalogue choisi")
            search_geometry = mapping(zones.to_crs(4326).geometry.union_all())
            dates = config.get("datetime_range")
            if dates is None and scenes and not allow_mixed_dates:
                dates = scenes[0].acquired
            try:
                found = search_stac(config["endpoint"], intersects=search_geometry, datetime_range=dates,
                    collections=config["collections"], limit=config["max_items"], timeout=config["timeout"], cancel=cancel)
            except (OSError, ValueError, HTTPException) as exc:
                found = {"features": []}
                requests.append(dict(status="search_failed", reason=str(exc), retained=False))
            overrides = {key: config[key] for key in ("band_mapping", "quality_asset", "quality_kind", "saturation_asset") if key in config}
            existing_ids = {scene.scene_id for scene in scenes}
            items = found.get("features", [])
            for number, item in enumerate(items):
                _check_cancel(cancel)
                if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
                    requests.append(dict(status="rejected", reason="Identifiant STAC absent ou invalide.", retained=False))
                    continue
                record = dict(id=item.get("id"), collection=item.get("collection"), status="rejected", retained=False)
                requests.append(record)
                if item.get("id") in existing_ids:
                    record.update(reason="already_selected")
                    continue
                if total_bytes >= config["max_bytes"]:
                    record.update(reason="download_budget_exhausted")
                    break
                directory = work / "acquisitions" / f"scene_{number + 1:04d}"
                start = 1800 + round(4200 * number / max(1, len(items)))
                middle = start + round(1800 / max(1, len(items)))
                end = 1800 + round(4200 * (number + 1) / max(1, len(items)))
                transfer_started = False
                try:
                    keys = stac_asset_keys(item, band_order=common["band_order"],
                        include_quality=mask_clouds, include_saturation=mask_saturation, **overrides)
                    announce(f"Téléchargement de la scène complémentaire {number + 1}/{len(items)}")
                    transfer_started = True
                    manifest = download_stac(item, directory, assets=keys,
                        include_companions=False, max_bytes=config["max_bytes"] - total_bytes,
                        timeout=config["timeout"], progress=callback(start, middle), cancel=cancel)
                    size = read_json(directory / "download.json")["bytes"]
                    total_bytes += size
                    record["bytes"] = size
                    record["assets"] = list(keys)
                    load_options = dict(overrides)
                    if "band_mapping" in load_options:
                        load_options["band_mapping"] = {key: role for key, role in load_options["band_mapping"].items() if key in keys}
                    if not mask_clouds and load_options.get("quality_asset") not in keys:
                        load_options.pop("quality_asset", None)
                        load_options.pop("quality_kind", None)
                    if not mask_saturation and load_options.get("saturation_asset") not in keys:
                        load_options.pop("saturation_asset", None)
                    candidate = load_scenes_manifest(manifest, **load_options)[0]
                    if candidate.scene_id in existing_ids:
                        raise ValueError("La scène est déjà sélectionnée.")
                    if scenes and (candidate.sensor, candidate.level) != (scenes[0].sensor, scenes[0].level):
                        raise ValueError("Capteur ou niveau de traitement incompatible avec les scènes sélectionnées.")
                    if scenes and not allow_mixed_dates and (candidate.acquired is None or candidate.acquired != scenes[0].acquired):
                        raise ValueError("Date différente ou inconnue ; mélange temporel non autorisé.")
                    proposed = examine([*scenes, candidate], f"candidate_{number + 1:04d}", middle, end)
                    if proposed.report["usable_pixels"] <= (audit.report["usable_pixels"] if audit else 0):
                        raise ValueError("La scène n’ajoute aucun pixel utile à la zone d’étude.")
                    scenes.append(candidate)
                    existing_ids.add(candidate.scene_id)
                    audit = proposed
                    record.update(status="accepted", reason="useful_coverage_increased", retained=True,
                                  usable_percent=audit.report["usable_percent"])
                    if audit.report["usable_percent"] + 1e-9 >= threshold:
                        break
                except (ValueError, OSError, KeyError, HTTPException) as exc:
                    record["reason"] = str(exc)
                    if directory.exists():
                        shutil.rmtree(directory)
                    # A failed/budget-exceeded transfer has unknown partial bytes:
                    # do not start another transfer and exceed the configured cap.
                    if "bytes" not in record and transfer_started:
                        record["transfer_incomplete"] = True
                        break
        if audit is None:
            audit = _empty_audit(rounds / "empty", zones, **{k: v for k, v in common.items() if k != "aoi"},
                                 coverage_threshold=threshold, cancel=cancel)
        from . import __version__
        report = dict(schema="cartomize.imagery.automatic.v1", version=__version__, status="blocked",
            coverage_threshold=threshold, threshold_met=audit.report["usable_percent"] + 1e-9 >= threshold,
            allow_partial=allow_partial, usable_percent=audit.report["usable_percent"],
            selected_scene_ids=[], recommended_action=audit.report["recommended_action"],
            initial_usable_percent=initial_report["usable_percent"] if initial_report else 0.,
            catalog=config, acquisitions=requests, downloaded_bytes=total_bytes,
            download_directory=str(work / "acquisitions") if (work / "acquisitions").exists() else None,
            products=[], preparation=None, audit=str(audit.manifest), coverage=str(audit.coverage), gaps=str(audit.gaps),
            initial_preprocessing_plan=initial_preprocessing_plan,
            preprocessing_plan=preprocessing_plan, recovery=recovery_records)
        if not audit.report["usable_pixels"] or (not report["threshold_met"] and not allow_partial):
            _check_cancel(cancel)
            raise ImageryCoverageError(audit, report).preserve(diagnostic_destination(destination), cancel=cancel)
        recommended = set(audit.report["recommended_scene_ids"])
        selected = [scene for scene in scenes if scene.scene_id in recommended]
        snapshot = lambda: _snapshot(selected, common["band_order"], mask_clouds, mask_saturation)
        before = snapshot()
        # Re-audit exactly the selected scenes on the original target grid.
        final_audit = audit_imagery(selected, work / "diagnostic", coverage_threshold=threshold,
            progress=callback(6200, 7200), cancel=cancel, **common)
        if snapshot() != before:
            raise ValueError("Les fichiers source ont changé pendant le diagnostic. Relancer le traitement.")
        if not final_audit.report["usable_pixels"] or (final_audit.report["usable_percent"] + 1e-9 < threshold and not allow_partial):
            report.update(usable_percent=final_audit.report["usable_percent"], threshold_met=False)
            raise ImageryCoverageError(final_audit, report).preserve(diagnostic_destination(destination), cancel=cancel)
        announce("N5 — Préparation des scènes retenues" + (" et mosaïque" if len(selected) > 1 else ""))
        prepared = process_imagery(selected, work / "products", mosaic=len(selected) > 1,
            multiband=multiband, separate_bands=separate_bands, composition=composition,
            overlap=overlap, percentiles=percentiles, gamma=gamma,
            progress=callback(7400, 9800), cancel=cancel, stage=stage, **common)
        if snapshot() != before:
            raise ValueError("Les fichiers source ont changé pendant la préparation. Aucun produit publié.")
        product_report = read_json(prepared.products[0]["report"])
        if (product_report["aoi_pixels"] != final_audit.report["aoi_pixels"] or
                product_report["valid_pixels"] != final_audit.report["usable_pixels"]):
            raise RuntimeError("La couverture produite ne correspond pas au diagnostic ; aucun produit publié.")
        actual = final_audit.report["usable_percent"]
        report.update(status="complete" if actual + 1e-9 >= 100 else "partial", usable_percent=actual,
            threshold_met=actual + 1e-9 >= threshold, selected_scene_ids=[s.scene_id for s in selected],
            mosaic=len(selected) > 1, products=list(prepared.products), preparation=str(prepared.manifest),
            audit=str(final_audit.manifest), coverage=str(final_audit.coverage), gaps=str(final_audit.gaps),
            parameters=final_audit.report["parameters"],
            initial_preprocessing_plan=initial_preprocessing_plan,
            preprocessing_plan=assess_preprocessing(
                selected, mask_clouds=mask_clouds, mask_saturation=mask_saturation),
            recovery=recovery_records,
            atmospheric_method=atmospheric_method,
            executed_steps=[
                "radiometric_calibration",
                "quality_detection" if mask_clouds else "quality_detection_disabled",
                "cloud_masking" if mask_clouds else "cloud_masking_disabled",
                "grid_harmonization",
                "scene_selection",
                "mosaic" if len(selected) > 1 else "single_scene",
                "aoi_clip",
            ],
            quality_statistics=[dict(scene_id=scene["id"], **scene["quality_statistics"])
                                for scene in final_audit.report.get("scenes", [])
                                if scene.get("quality_statistics")])
        shutil.rmtree(rounds, ignore_errors=True)
        save_json(report, work / "preprocessing.json")
        replace = relocate_products(work, destination)
        report = replace(report)
        final_report = replace(final_audit.report)
        _check_cancel(cancel)
    final_audit = ImageryAudit(destination / "diagnostic" / "report.json",
        destination / "diagnostic" / "coverage.tif", destination / "diagnostic" / "gaps.tif", final_report)
    if progress:
        progress(10000, 10000)
    return PreprocessedImagery(destination / "preprocessing.json", tuple(report["products"]), final_audit, report)
