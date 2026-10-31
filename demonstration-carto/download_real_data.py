"""Télécharge une petite emprise de données Sentinel-2 L2A réelles pour la démonstration Cartomize.

Aucune image synthétique n'est générée. La scène est recherchée dans Earth Search
sur une période fixe, puis sélectionnée selon la couverture SCL réellement
observable sur l'emprise de démonstration. Les bandes restent dans leurs valeurs
source et leur calibration est lue par Cartomize depuis les métadonnées STAC.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import hashlib
import json
import math
import shutil
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.windows import Window, from_bounds, bounds as window_bounds
from rasterio.warp import transform_bounds

import cartomize as cm
from cartomize.clouds import sentinel_spectral_cloud_candidates

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
STAC_ENDPOINT = "https://earth-search.aws.element84.com/v1"
COLLECTION = "sentinel-2-l2a"
DATE_RANGE = "2022-06-01T00:00:00Z/2025-09-30T23:59:59Z"
DRY_MONTHS = {6, 7, 8, 9}

# Fenêtre d'analyse de démonstration à Kinshasa.
# Il ne s'agit PAS d'une limite administrative.
AOI_BBOX_WGS84 = (15.28, -4.34, 15.34, -4.28)
# Vue pédagogique plus large : la zone d'étude apparaît comme un rectangle
# plus petit à l'intérieur de la scène candidate.
PREVIEW_BBOX_WGS84 = (15.255, -4.365, 15.365, -4.255)
MAX_GLOBAL_CLOUD = 25.0
MIN_AOI_USABLE = 95.0
VALID_SCL = {2, 4, 5, 6, 7}


def _https(href: str) -> str:
    if href.startswith("s3://sentinel-cogs/"):
        return "https://sentinel-cogs.s3.us-west-2.amazonaws.com/" + href[len("s3://sentinel-cogs/"):]
    if href.startswith("s3://"):
        bucket, _, key = href[5:].partition("/")
        return f"https://{bucket}.s3.amazonaws.com/{key}"
    return href


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _asset(item: dict, role: str) -> tuple[str, dict]:
    preferred = {
        "blue": ("blue", "B02"),
        "green": ("green", "B03"),
        "red": ("red", "B04"),
        "nir": ("nir", "B08"),
        "swir1": ("swir16", "swir1", "B11"),
        "scl": ("scl", "SCL"),
    }[role]
    for key in preferred:
        asset = item.get("assets", {}).get(key)
        if asset and "tiff" in str(asset.get("type", "")).lower():
            return key, asset
    for key, asset in item.get("assets", {}).items():
        if "tiff" not in str(asset.get("type", "")).lower():
            continue
        if role == "scl" and key.lower() == "scl":
            return key, asset
        for band in asset.get("eo:bands", asset.get("bands", [])):
            common = str(band.get("common_name", band.get("eo:common_name", ""))).lower()
            name = str(band.get("name", "")).upper()
            if common == role or (role == "blue" and name == "B02") or (role == "green" and name == "B03") or (role == "red" and name == "B04") or (role == "nir" and name == "B08") or (role == "swir1" and name == "B11"):
                return key, asset
    raise KeyError(f"Asset {role} absent de {item.get('id')}")


def _window(src, bbox=AOI_BBOX_WGS84) -> Window:
    bounds = transform_bounds("EPSG:4326", src.crs, *bbox, densify_pts=21)
    raw = from_bounds(*bounds, transform=src.transform)
    col0 = max(0, math.floor(raw.col_off))
    row0 = max(0, math.floor(raw.row_off))
    col1 = min(src.width, math.ceil(raw.col_off + raw.width))
    row1 = min(src.height, math.ceil(raw.row_off + raw.height))
    if col1 <= col0 or row1 <= row0:
        raise ValueError("L'emprise ne recouvre pas l'asset.")
    return Window(col0, row0, col1 - col0, row1 - row0)


def _read_remote(href: str):
    href = _https(href)
    env = rasterio.Env(
        GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
        CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif,.tiff",
        GDAL_HTTP_MULTIRANGE="YES",
        GDAL_HTTP_MERGE_CONSECUTIVE_RANGES="YES",
        AWS_NO_SIGN_REQUEST="YES",
    )
    env.__enter__()
    try:
        src = rasterio.open(href)
    except Exception:
        env.__exit__(None, None, None)
        raise
    return env, src


def _scl_metrics(item: dict) -> dict:
    """Measure footprint and SCL usability against the complete AOI.

    Uncovered AOI area counts as unusable. This prevents choosing a clean tile
    that touches only a small corner of the study window.
    """
    from shapely.geometry import box
    from shapely.ops import transform as shapely_transform
    from pyproj import Transformer

    _, asset = _asset(item, "scl")
    env, src = _read_remote(asset["href"])
    try:
        transformer = Transformer.from_crs("EPSG:4326", src.crs, always_xy=True)
        aoi = shapely_transform(transformer.transform, box(*AOI_BBOX_WGS84))
        footprint = box(*src.bounds)
        overlap = aoi.intersection(footprint)
        footprint_percent = 0.0 if aoi.area <= 0 else 100.0 * overlap.area / aoi.area
        if overlap.is_empty:
            return {"footprint_percent": 0.0, "scl_valid_in_overlap_percent": 0.0, "usable_aoi_percent": 0.0}
        data = src.read(1, window=_window(src), masked=True)
    finally:
        src.close()
        env.__exit__(None, None, None)
    observed = ~np.ma.getmaskarray(data)
    if not data.size:
        observed_overlap = valid_overlap = 0.0
    else:
        valid = observed & np.isin(data.data, tuple(VALID_SCL))
        observed_overlap = 100.0 * float(observed.sum()) / float(data.size)
        # The denominator includes NoData inside the raster bounds. This is
        # essential for Sentinel granules whose MGRS raster extent is complete
        # but whose actual swath occupies only part of the tile.
        valid_overlap = 100.0 * float(valid.sum()) / float(data.size)
    return {
        "footprint_percent": float(footprint_percent),
        "observed_in_overlap_percent": float(observed_overlap),
        "scl_valid_in_overlap_percent": float(valid_overlap),
        "usable_aoi_percent": float(footprint_percent * valid_overlap / 100.0),
    }


def _calibrated_remote_window(item: dict, role: str, target_bounds, target_shape, *, nearest=False):
    key, asset = _asset(item, role)
    env, src = _read_remote(asset["href"])
    try:
        raw = from_bounds(*target_bounds, transform=src.transform)
        col0 = max(0, math.floor(raw.col_off))
        row0 = max(0, math.floor(raw.row_off))
        col1 = min(src.width, math.ceil(raw.col_off + raw.width))
        row1 = min(src.height, math.ceil(raw.row_off + raw.height))
        if col1 <= col0 or row1 <= row0:
            raise ValueError(f"Asset {role} does not cover the target window.")
        window = Window(col0, row0, col1 - col0, row1 - row0)
        arr = src.read(
            1,
            window=window,
            out_shape=target_shape,
            resampling=Resampling.nearest if nearest else Resampling.bilinear,
        )
        numeric = {}
        raster_bands = asset.get("raster:bands") or []
        if raster_bands and isinstance(raster_bands[0], dict):
            numeric.update(raster_bands[0])
        bands = asset.get("bands") or asset.get("eo:bands") or []
        if bands and isinstance(bands[0], dict):
            numeric.update(bands[0])
        nodata = numeric.get("nodata", src.nodata)
        valid = np.isfinite(arr)
        if nodata is not None:
            valid &= arr != nodata
        if nearest:
            return arr.astype("float64"), valid
        scale = float(numeric.get("scale", numeric.get("raster:scale", 1.0)))
        offset = float(numeric.get("offset", numeric.get("raster:offset", 0.0)))
        if (
            item.get("properties", {}).get("earthsearch:boa_offset_applied") is True
            and not key.lower().endswith("-jp2")
            and "tiff" in str(asset.get("type", "")).lower()
        ):
            offset = 0.0
        return arr.astype("float64") * scale + offset, valid
    finally:
        src.close()
        env.__exit__(None, None, None)


def _hybrid_cloud_metrics(item: dict, scl_metrics: dict) -> dict:
    """Evaluate SCL and the same spectral fallback used by Cartomize N4."""
    _, blue_asset = _asset(item, "blue")
    env, blue_src = _read_remote(blue_asset["href"])
    try:
        window = _window(blue_src)
        target_bounds = window_bounds(window, blue_src.transform)
        target_shape = (int(window.height), int(window.width))
    finally:
        blue_src.close()
        env.__exit__(None, None, None)

    data = {}
    valid = None
    for role in ("blue", "green", "red", "nir", "swir1"):
        values, available = _calibrated_remote_window(
            item, role, target_bounds, target_shape
        )
        data[role] = values
        valid = available if valid is None else valid & available
    scl, scl_observed = _calibrated_remote_window(
        item, "scl", target_bounds, target_shape, nearest=True
    )
    valid &= scl_observed
    scl_valid = np.isin(scl.astype("uint8"), tuple(VALID_SCL))

    spectral_cloud = sentinel_spectral_cloud_candidates(
        data["blue"], data["green"], data["red"],
        data["nir"], data["swir1"], valid
    )
    hybrid_valid = valid & scl_valid & ~spectral_cloud
    denominator = float(hybrid_valid.size)
    hybrid_percent = 100.0 * float(hybrid_valid.sum()) / denominator if denominator else 0.0
    spectral_percent = 100.0 * float(spectral_cloud.sum()) / float(valid.sum()) if valid.any() else 0.0
    return {
        **scl_metrics,
        "spectral_cloud_percent": float(spectral_percent),
        "hybrid_usable_percent": float(
            scl_metrics["footprint_percent"] * hybrid_percent / 100.0
        ),
    }


def _copy_window(item: dict, role: str, destination: Path, *, bbox=AOI_BBOX_WGS84) -> tuple[str, dict]:
    key, asset = _asset(item, role)
    env, src = _read_remote(asset["href"])
    try:
        window = _window(src, bbox=bbox)
        array = src.read(1, window=window)
        profile = src.profile.copy()
        profile.update(
            driver="GTiff",
            width=int(window.width),
            height=int(window.height),
            count=1,
            transform=src.window_transform(window),
            compress="lzw",
            tiled=True,
            blockxsize=256,
            blockysize=256,
            BIGTIFF="IF_SAFER",
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(destination, "w", **profile) as dst:
            dst.write(array, 1)
            if src.descriptions and src.descriptions[0]:
                dst.set_band_description(1, src.descriptions[0])
            if src.units and src.units[0]:
                dst.set_band_unit(1, src.units[0])
            dst.update_tags(**src.tags())
            dst.update_tags(1, **src.tags(1))
    finally:
        src.close()
        env.__exit__(None, None, None)
    local = deepcopy(asset)
    local["href"] = destination.name
    return key, local


def _download_small_file(href: str, destination: Path) -> None:
    request = Request(_https(href), headers={"User-Agent": "Cartomize demonstration"})
    with urlopen(request, timeout=90) as response:
        content = response.read(20_000_001)
    if len(content) > 20_000_000:
        raise ValueError("Métadonnées distantes trop volumineuses.")
    destination.write_bytes(content)


def main() -> None:
    if DATA.exists():
        shutil.rmtree(DATA)
    DATA.mkdir(parents=True)

    collection = cm.search_stac(
        STAC_ENDPOINT,
        bbox=AOI_BBOX_WGS84,
        datetime_range=DATE_RANGE,
        collections=[COLLECTION],
        limit=250,
    )
    candidates = []
    for item in collection["features"]:
        try:
            for role in ("blue", "green", "red", "nir", "swir1", "scl"):
                _asset(item, role)
        except KeyError:
            continue
        timestamp = str(item.get("properties", {}).get("datetime") or "")
        try:
            month = int(timestamp[5:7])
        except (TypeError, ValueError):
            continue
        if month not in DRY_MONTHS:
            continue
        cloud = item.get("properties", {}).get("eo:cloud_cover")
        if cloud is None:
            continue
        cloud = float(cloud)
        if not math.isfinite(cloud) or cloud > MAX_GLOBAL_CLOUD:
            continue
        candidates.append((cloud, item))
    if not candidates:
        raise RuntimeError("Aucune scène Sentinel-2 L2A compatible trouvée dans la période fixée.")

    tested = []
    item_by_id = {}
    for cloud, item in sorted(candidates, key=lambda row: (row[0], row[1].get("id", "")))[:30]:
        metrics = _scl_metrics(item)
        tested.append({"id": item["id"], "cloud_cover": cloud, **metrics})
        item_by_id[item["id"]] = item

    # Only scenes with meaningful AOI coverage are worth the more expensive
    # spectral check. Evaluate the best SCL candidates with the same hybrid
    # rule used later by Cartomize N4.
    shortlist = [
        row for row in tested
        if row["footprint_percent"] >= 95.0 and row.get("observed_in_overlap_percent", 0) >= 95.0
    ]
    shortlist.sort(key=lambda row: (row["cloud_cover"], -row["usable_aoi_percent"], row["id"]))
    hybrid_tested = []
    for row in shortlist[:12]:
        hybrid = _hybrid_cloud_metrics(item_by_id[row["id"]], row)
        hybrid_tested.append(hybrid)
    if not hybrid_tested:
        raise RuntimeError("Aucune scène Sentinel-2 ne couvre suffisamment l'emprise pour le diagnostic hybride.")
    hybrid_tested.sort(
        key=lambda row: (-row["hybrid_usable_percent"], row["cloud_cover"], row["id"])
    )
    winner = hybrid_tested[0]
    if winner["hybrid_usable_percent"] < MIN_AOI_USABLE:
        raise RuntimeError(
            f"Meilleure scène après contrôle hybride : {winner['hybrid_usable_percent']:.2f} % utilisable "
            f"(SCL {winner['usable_aoi_percent']:.2f} %, nuages spectraux supplémentaires "
            f"{winner['spectral_cloud_percent']:.2f} %), sous le seuil de {MIN_AOI_USABLE:g} %. "
            "Changer la période ou l'emprise; ne pas relâcher le contrôle."
        )
    selected = item_by_id[winner["id"]]
    tested = sorted(
        [
            next((hybrid for hybrid in hybrid_tested if hybrid["id"] == row["id"]), row)
            for row in tested
        ],
        key=lambda row: (
            -row.get("hybrid_usable_percent", row["usable_aoi_percent"]),
            row["cloud_cover"],
            row["id"],
        ),
    )

    coords = [
        [AOI_BBOX_WGS84[0], AOI_BBOX_WGS84[1]],
        [AOI_BBOX_WGS84[2], AOI_BBOX_WGS84[1]],
        [AOI_BBOX_WGS84[2], AOI_BBOX_WGS84[3]],
        [AOI_BBOX_WGS84[0], AOI_BBOX_WGS84[3]],
        [AOI_BBOX_WGS84[0], AOI_BBOX_WGS84[1]],
    ]
    aoi = {
        "type": "FeatureCollection",
        "name": "emprise_demonstration_kinshasa",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
        "features": [{
            "type": "Feature",
            "properties": {
                "name": "Fenêtre de démonstration Kinshasa",
                "scope": "emprise d'analyse; pas une limite administrative",
            },
            "geometry": {"type": "Polygon", "coordinates": [coords]},
        }],
    }
    (DATA / "aoi.geojson").write_text(json.dumps(aoi, indent=2, ensure_ascii=False), encoding="utf-8")

    local_item = deepcopy(selected)
    local_item["links"] = []
    local_assets = {}
    file_by_role = {
        "blue": "B02.tif",
        "green": "B03.tif",
        "red": "B04.tif",
        "nir": "B08.tif",
        "swir1": "B11.tif",
        "scl": "SCL.tif",
    }
    source_assets = {}
    for role, filename in file_by_role.items():
        source_key, source_asset = _asset(selected, role)
        key, local_asset = _copy_window(selected, role, DATA / filename)
        local_assets[key] = local_asset
        source_assets[role] = {"key": source_key, "href": _https(source_asset["href"])}

    # Preserve a wider view of the same selected Sentinel-2 acquisition.
    # This view is used only for the instructional visualization of spatial
    # coverage before the AOI clip; scientific products still use the AOI.
    input_dir = DATA / "input_scene"
    input_dir.mkdir(parents=True, exist_ok=True)
    input_local = deepcopy(selected)
    input_local["links"] = []
    input_assets = {}
    input_source_assets = {}
    for role, filename in {
        "blue": "B02.tif", "green": "B03.tif", "red": "B04.tif", "scl": "SCL.tif"
    }.items():
        source_key, source_asset = _asset(selected, role)
        key, local_asset = _copy_window(
            selected, role, input_dir / filename, bbox=PREVIEW_BBOX_WGS84
        )
        local_asset["href"] = filename
        input_assets[key] = local_asset
        input_source_assets[role] = {
            "key": source_key,
            "href": _https(source_asset["href"]),
        }
    input_local["assets"] = input_assets
    (input_dir / "source_item.json").write_text(
        json.dumps(input_local, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    metadata_key = next((key for key in selected.get("assets", {}) if key.lower() in {"product-metadata", "product_metadata"}), None)
    if metadata_key:
        metadata_asset = deepcopy(selected["assets"][metadata_key])
        try:
            _download_small_file(metadata_asset["href"], DATA / "MTD_MSIL2A.xml")
        except HTTPError as exc:
            if exc.code != 404:
                raise
            # Earth Search COGs normally carry explicit raster:bands scale/offset.
            # A stale optional product-metadata link must not invalidate those
            # declared coefficients; scene_from_stac will still fail below if
            # any selected band actually lacks calibration.
            source_assets["product_metadata"] = {
                "key": metadata_key,
                "href": _https(selected["assets"][metadata_key]["href"]),
                "status": "remote_404_not_required_for_declared_stac_calibration",
            }
        else:
            metadata_asset["href"] = "MTD_MSIL2A.xml"
            local_assets[metadata_key] = metadata_asset
            source_assets["product_metadata"] = {
                "key": metadata_key,
                "href": _https(selected["assets"][metadata_key]["href"]),
                "status": "downloaded",
            }

    local_item["assets"] = local_assets
    (DATA / "source_item.json").write_text(json.dumps(local_item, indent=2, ensure_ascii=False), encoding="utf-8")

    # Cartomize lit la calibration STAC / métadonnées ici. Une calibration absente
    # fait échouer la préparation au lieu d'être devinée.
    scene = cm.scene_from_stac(local_item, base=DATA)
    manifest = {
        "schema": "cartomize.scenes.v1",
        "scenes": [{
            "scene_id": scene.scene_id,
            "sensor": scene.sensor,
            "acquired": scene.acquired,
            "level": scene.level,
            "quality": Path(scene.quality).name if scene.quality else None,
            "quality_kind": scene.quality_kind,
            "notes": list(scene.notes),
            "bands": {
                name: {
                    "path": Path(band.path).name,
                    "index": band.index,
                    "scale": band.scale,
                    "offset": band.offset,
                    "nodata": band.nodata,
                    "unit": band.unit,
                }
                for name, band in scene.bands.items()
                if name in {"blue", "green", "red", "nir", "swir1"}
            },
        }],
    }
    (DATA / "scenes.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    files = {}
    for path in sorted(DATA.rglob("*")):
        if path.is_file():
            files[str(path.relative_to(DATA))] = {
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
    properties = selected.get("properties", {})
    input_properties = selected.get("properties", {})
    provenance = {
        "schema": "cartomize.demonstration.real-data.v1",
        "data_are_synthetic": False,
        "source": "Earth Search / Sentinel-2 Level-2A",
        "stac_endpoint": STAC_ENDPOINT,
        "collection": COLLECTION,
        "search_datetime": DATE_RANGE,
        "search_bbox_wgs84": list(AOI_BBOX_WGS84),
        "selected_item_id": selected["id"],
        "selected_datetime": properties.get("datetime"),
        "platform": properties.get("platform"),
        "mgrs_tile": properties.get("s2:mgrs_tile"),
        "global_cloud_cover_percent": float(properties.get("eo:cloud_cover")),
        "aoi_footprint_percent_before_processing": winner["footprint_percent"],
        "aoi_observed_in_overlap_percent": winner["observed_in_overlap_percent"],
        "aoi_scl_valid_in_overlap_percent": winner["scl_valid_in_overlap_percent"],
        "aoi_scl_usable_percent_before_processing": winner["usable_aoi_percent"],
        "aoi_hybrid_usable_percent_before_processing": winner["hybrid_usable_percent"],
        "aoi_spectral_cloud_percent_before_processing": winner["spectral_cloud_percent"],
        "input_scene": {
            "item_id": selected["id"],
            "datetime": input_properties.get("datetime"),
            "platform": input_properties.get("platform"),
            "global_cloud_cover_percent": float(input_properties.get("eo:cloud_cover")),
            "aoi_scl_usable_percent": winner["usable_aoi_percent"],
            "aoi_spectral_cloud_percent": winner["spectral_cloud_percent"],
            "aoi_hybrid_usable_percent": winner["hybrid_usable_percent"],
            "local_item": "input_scene/source_item.json",
            "preview_bbox_wgs84": list(PREVIEW_BBOX_WGS84),
            "source_assets": input_source_assets,
        },
        "selection_candidates": tested,
        "source_assets": source_assets,
        "calibration_notes": list(scene.notes),
        "files": files,
        "aoi_note": "Fenêtre d'analyse définie pour la démonstration; elle n'est pas présentée comme une limite administrative.",
    }
    (DATA / "provenance.json").write_text(json.dumps(provenance, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: provenance[k] for k in (
        "selected_item_id", "selected_datetime", "global_cloud_cover_percent",
        "aoi_scl_usable_percent_before_processing"
    )}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
