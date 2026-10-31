"""Safe recovery of missing quality companions or surface-reflectance scenes."""
from __future__ import annotations

from pathlib import Path
import re

from .catalogs import (_stac_profile, download_stac, load_scenes_manifest,
                       search_stac, stac_asset_keys)
from .imagery import _check_cancel


_LANDSAT_PATHROW = re.compile(r"_(\d{3})(\d{3})_")
_SENTINEL_TILE = re.compile(r"(?:^|_)(?:T)?(\d{2}[A-Z]{3})(?:_|$)", re.I)


def _item_date(item):
    properties = item.get("properties", {})
    value = properties.get("datetime") or properties.get("start_datetime")
    return value[:10] if isinstance(value, str) and len(value) >= 10 else None


def _landsat_pathrow(scene_id):
    match = _LANDSAT_PATHROW.search(str(scene_id))
    return (int(match.group(1)), int(match.group(2))) if match else None


def _sentinel_tile(scene_id):
    match = _SENTINEL_TILE.search(str(scene_id))
    return match.group(1).upper() if match else None


def identity_matches(scene, item):
    """Require a strong acquisition identity before automatic replacement."""
    _, sensor, _ = _stac_profile(item)
    if sensor != scene.sensor or _item_date(item) != scene.acquired:
        return False

    if scene.sensor.startswith("landsat-"):
        expected = _landsat_pathrow(scene.scene_id)
        if expected is None:
            return str(item.get("id")) == scene.scene_id
        properties = item.get("properties", {})
        path = properties.get("landsat:wrs_path")
        row = properties.get("landsat:wrs_row")
        if path is not None and row is not None:
            try:
                return (int(path), int(row)) == expected
            except (TypeError, ValueError):
                return False
        match = _LANDSAT_PATHROW.search(str(item.get("id", "")))
        return bool(match and (int(match.group(1)), int(match.group(2))) == expected)

    if scene.sensor == "sentinel-2":
        expected = _sentinel_tile(scene.scene_id)
        if expected is None:
            return str(item.get("id")) == scene.scene_id
        properties = item.get("properties", {})
        tile = properties.get("s2:mgrs_tile")
        if isinstance(tile, str):
            return tile.upper().lstrip("T") == expected.lstrip("T")
        found = _sentinel_tile(item.get("id", ""))
        return found == expected

    return str(item.get("id")) == scene.scene_id


def _needs_surface_reflectance(scene):
    return str(scene.level or "").upper() in {"L1C-TOA", "L1-TOA", "C2-L1"}


def recover_scene(scene, destination, *, config, search_geometry, band_order=None,
                  mask_clouds=True, mask_saturation=True, progress=None, cancel=None):
    """Recover one exact matching scene from a configured STAC catalog.

    Missing QA/SCL triggers a same-acquisition replacement. TOA/L1 inputs require
    the replacement to be a recognized surface-reflectance product. Ambiguous
    matches are refused rather than guessed.
    """
    _check_cancel(cancel)
    if config is None:
        return None, {
            "scene_id": scene.scene_id,
            "status": "not_attempted",
            "reason": "catalog_not_configured",
            "retained": False,
        }

    document = search_stac(
        config["endpoint"],
        intersects=search_geometry,
        datetime_range=scene.acquired or config.get("datetime_range"),
        collections=config["collections"],
        limit=config["max_items"],
        timeout=config["timeout"],
        cancel=cancel,
    )
    matches = [item for item in document.get("features", []) if identity_matches(scene, item)]
    if _needs_surface_reflectance(scene):
        matches = [item for item in matches if _stac_profile(item)[2] in {"C2-L2-SR", "L2A-SR"}]

    if not matches:
        return None, {
            "scene_id": scene.scene_id,
            "status": "unresolved",
            "reason": "no_exact_catalog_match",
            "retained": False,
        }
    if len(matches) > 1:
        return None, {
            "scene_id": scene.scene_id,
            "status": "ambiguous",
            "reason": "multiple_exact_catalog_matches",
            "candidate_ids": [item.get("id") for item in matches],
            "retained": False,
        }

    item = matches[0]
    overrides = {
        key: config[key]
        for key in ("band_mapping", "quality_asset", "quality_kind", "saturation_asset")
        if key in config
    }
    names = tuple(band_order) if band_order is not None else tuple(scene.bands)
    keys = stac_asset_keys(
        item,
        band_order=names,
        include_quality=mask_clouds,
        include_saturation=mask_saturation,
        **overrides,
    )
    directory = Path(destination)
    manifest = download_stac(
        item,
        directory,
        assets=keys,
        include_companions=False,
        max_bytes=config["max_bytes"],
        timeout=config["timeout"],
        progress=progress,
        cancel=cancel,
    )
    load_options = dict(overrides)
    if "band_mapping" in load_options:
        load_options["band_mapping"] = {
            key: role for key, role in load_options["band_mapping"].items() if key in keys
        }
    candidate = load_scenes_manifest(manifest, **load_options)[0]
    if candidate.sensor != scene.sensor or candidate.acquired != scene.acquired:
        raise ValueError("La scène récupérée ne correspond pas à l’acquisition locale.")
    if _needs_surface_reflectance(scene) and candidate.level not in {"C2-L2-SR", "L2A-SR"}:
        raise ValueError("Le catalogue n’a pas fourni un produit de réflectance de surface.")
    record = {
        "scene_id": scene.scene_id,
        "replacement_scene_id": candidate.scene_id,
        "status": "recovered",
        "reason": "surface_reflectance_replacement" if _needs_surface_reflectance(scene)
                  else "quality_companion_recovery",
        "assets": list(keys),
        "retained": True,
    }
    return candidate, record
