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
from urllib.request import Request, urlopen

import numpy as np
import rasterio
from rasterio.windows import Window, from_bounds
from rasterio.warp import transform_bounds

import cartomize as cm

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
STAC_ENDPOINT = "https://earth-search.aws.element84.com/v1"
COLLECTION = "sentinel-2-l2a"
DATE_RANGE = "2024-06-01T00:00:00Z/2024-09-30T23:59:59Z"

# Fenêtre d'analyse de démonstration à Kinshasa.
# Il ne s'agit PAS d'une limite administrative.
AOI_BBOX_WGS84 = (15.28, -4.34, 15.34, -4.28)
MAX_GLOBAL_CLOUD = 20.0
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
            if common == role or (role == "blue" and name == "B02") or (role == "green" and name == "B03") or (role == "red" and name == "B04") or (role == "nir" and name == "B08"):
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
    if not observed.any():
        valid_overlap = 0.0
    else:
        valid = observed & np.isin(data.data, tuple(VALID_SCL))
        valid_overlap = 100.0 * float(valid.sum()) / float(observed.sum())
    return {
        "footprint_percent": float(footprint_percent),
        "scl_valid_in_overlap_percent": float(valid_overlap),
        "usable_aoi_percent": float(footprint_percent * valid_overlap / 100.0),
    }


def _copy_window(item: dict, role: str, destination: Path) -> tuple[str, dict]:
    key, asset = _asset(item, role)
    env, src = _read_remote(asset["href"])
    try:
        window = _window(src)
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
        limit=100,
    )
    candidates = []
    for item in collection["features"]:
        try:
            for role in ("blue", "green", "red", "nir", "scl"):
                _asset(item, role)
        except KeyError:
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
    for cloud, item in sorted(candidates, key=lambda row: (row[0], row[1].get("id", "")))[:24]:
        metrics = _scl_metrics(item)
        tested.append({"id": item["id"], "cloud_cover": cloud, **metrics})
    tested.sort(key=lambda row: (-row["usable_aoi_percent"], -row["footprint_percent"], row["cloud_cover"], row["id"]))
    winner = tested[0]
    if winner["usable_aoi_percent"] < MIN_AOI_USABLE:
        raise RuntimeError(
            f"Meilleure scène : {winner['usable_aoi_percent']:.2f} % de l'emprise réellement utilisable "
            f"(empreinte {winner['footprint_percent']:.2f} %, SCL valide dans le recouvrement "
            f"{winner['scl_valid_in_overlap_percent']:.2f} %), sous le seuil de {MIN_AOI_USABLE:g} %. "
            "Changer la période ou l'emprise; ne pas relâcher le contrôle."
        )
    selected = next(item for _, item in candidates if item["id"] == winner["id"])

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
        "scl": "SCL.tif",
    }
    source_assets = {}
    for role, filename in file_by_role.items():
        source_key, source_asset = _asset(selected, role)
        key, local_asset = _copy_window(selected, role, DATA / filename)
        local_assets[key] = local_asset
        source_assets[role] = {"key": source_key, "href": _https(source_asset["href"])}

    metadata_key = next((key for key in selected.get("assets", {}) if key.lower() in {"product-metadata", "product_metadata"}), None)
    if metadata_key:
        metadata_asset = deepcopy(selected["assets"][metadata_key])
        _download_small_file(metadata_asset["href"], DATA / "MTD_MSIL2A.xml")
        metadata_asset["href"] = "MTD_MSIL2A.xml"
        local_assets[metadata_key] = metadata_asset
        source_assets["product_metadata"] = {"key": metadata_key, "href": _https(selected["assets"][metadata_key]["href"])}

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
                if name in {"blue", "green", "red", "nir"}
            },
        }],
    }
    (DATA / "scenes.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    files = {}
    for path in sorted(DATA.iterdir()):
        if path.is_file():
            files[path.name] = {"bytes": path.stat().st_size, "sha256": _sha256(path)}
    properties = selected.get("properties", {})
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
        "aoi_scl_valid_in_overlap_percent": winner["scl_valid_in_overlap_percent"],
        "aoi_scl_usable_percent_before_processing": winner["usable_aoi_percent"],
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
