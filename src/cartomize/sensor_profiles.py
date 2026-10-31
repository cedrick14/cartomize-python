"""Central sensor/product registry for safe spectral-band recognition.

Automatic recognition is metadata/sensor aware. Numeric labels such as B4 are
never assigned a wavelength without a sensor context because Landsat missions
do not share the same band numbering. Descriptive aliases (red, nir, swir1...)
are safe across supported optical sensors.
"""
from __future__ import annotations

import re


SEMANTIC_ALIASES = {
    "coastal": "coastal", "coastalaerosol": "coastal", "aerosol": "coastal",
    "blue": "blue", "bleu": "blue",
    "green": "green", "vert": "green",
    "red": "red", "rouge": "red",
    "nir": "nir", "nearinfrared": "nir", "nearir": "nir", "procheinfrarouge": "nir",
    "nirnarrow": "nir_narrow", "narrownir": "nir_narrow", "nir8a": "nir_narrow",
    "swir1": "swir1", "swir16": "swir1", "shortwaveinfrared1": "swir1",
    "swir2": "swir2", "swir22": "swir2", "shortwaveinfrared2": "swir2",
    "rededge1": "rededge1", "rededge2": "rededge2", "rededge3": "rededge3",
    "watervapour": "water_vapour", "watervapor": "water_vapour",
    "cirrus": "cirrus", "pan": "pan", "panchromatic": "pan",
    "thermal": "thermal", "tir": "thermal",
}

LANDSAT_OLI = {
    "B1": "coastal", "B2": "blue", "B3": "green", "B4": "red",
    "B5": "nir", "B6": "swir1", "B7": "swir2", "B8": "pan", "B9": "cirrus",
}
LANDSAT_ETM_TM = {
    "B1": "blue", "B2": "green", "B3": "red", "B4": "nir",
    "B5": "swir1", "B7": "swir2",
}
LANDSAT_MSS_13 = {"B4": "green", "B5": "red", "B6": "nir", "B7": "nir2"}
LANDSAT_MSS_45 = {"B1": "green", "B2": "red", "B3": "nir", "B4": "nir2"}

SENTINEL2 = {
    "B01": "coastal", "B02": "blue", "B03": "green", "B04": "red",
    "B05": "rededge1", "B06": "rededge2", "B07": "rededge3",
    "B08": "nir", "B8A": "nir_narrow", "B09": "water_vapour",
    "B10": "cirrus", "B11": "swir1", "B12": "swir2",
}

LANDSAT_PRODUCT_RE = re.compile(
    r"(?P<prefix>L(?P<instrument>[COMET])(?P<satellite>\d{2}))_"
    r"(?P<level>L[12](?:TP|GT|GS|SP|SR))_"
    r"(?P<path>\d{3})(?P<row>\d{3})_"
    r"(?P<acquired>\d{8})_(?P<processed>\d{8})_"
    r"(?P<collection>\d{2})_(?P<tier>[A-Z0-9]+)",
    re.I,
)
SENTINEL_TILE_RE = re.compile(r"(?:^|_)(T\d{2}[A-Z]{3})(?:_|$)", re.I)
SENTINEL_DATETIME_RE = re.compile(r"(?:^|_)(\d{8}T\d{6})(?:_|$)", re.I)


def _flat(value) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).casefold())


def canonical_semantic_name(value):
    """Return a safe semantic role for descriptive names, else None."""
    token = _flat(value)
    return SEMANTIC_ALIASES.get(token)


def native_band_code(value):
    """Extract B1/B01/B8A from common native/alias spellings."""
    text = str(value).strip().upper()
    stem = re.sub(r"\.(?:TIF|TIFF|JP2|IMG|VRT)$", "", text)
    # Prefer explicit SR/TOA/BAND tokens; the final alternative accepts B02.
    match = re.search(
        r"(?:^|[_\-. ])(?:SR[_\-. ]*)?(?:BAND[_\-. ]*)?"
        r"(B?0?[1-9]|B?1[0-2]|B?8A)(?=$|[_\-. ])",
        stem,
    )
    if not match:
        compact = re.fullmatch(r"(?:SR)?(?:BAND)?(B?0?[1-9]|B?1[0-2]|B?8A)", re.sub(r"[^A-Z0-9]", "", stem))
        if not compact:
            return None
        token = compact.group(1)
    else:
        token = match.group(1)
    token = token if token.startswith("B") else "B" + token
    if token == "B08A":
        token = "B8A"
    return token


def sensor_from_text(value):
    """Infer only explicit sensor/platform tokens from text."""
    text = str(value).upper()
    landsat = re.search(r"(?:^|[^A-Z0-9])(L[COMET])(0?[1-9])(?:[^A-Z0-9]|$)", text)
    if landsat:
        prefix, number = landsat.groups()
        return f"landsat-{int(number)}", prefix
    named = re.search(r"LANDSAT[^0-9]*(0?[1-9])", text)
    if named:
        return f"landsat-{int(named.group(1))}", None
    if re.search(r"(?:SENTINEL[^0-9]*2|(?:^|[^A-Z0-9])S2[ABC]?(?:[^A-Z0-9]|$))", text):
        return "sentinel-2", None
    return None, None


def landsat_band_map(sensor: str, product_prefix: str | None = None):
    """Return reflective semantic mapping for a Landsat sensor/instrument."""
    try:
        mission = int(str(sensor).rsplit("-", 1)[-1])
    except (TypeError, ValueError):
        return {}
    prefix = (product_prefix or "").upper()
    if prefix.startswith("LM"):
        return LANDSAT_MSS_13 if mission <= 3 else LANDSAT_MSS_45
    if mission in {8, 9}:
        return LANDSAT_OLI
    if mission in {4, 5, 7}:
        return LANDSAT_ETM_TM
    if mission in {1, 2, 3}:
        return LANDSAT_MSS_13
    return {}


def semantic_band_name(value, *, sensor=None, product_prefix=None):
    """Resolve a descriptive alias or a sensor-aware native band code."""
    semantic = canonical_semantic_name(value)
    if semantic:
        return semantic
    if sensor is None:
        sensor, inferred_prefix = sensor_from_text(value)
        product_prefix = product_prefix or inferred_prefix
    code = native_band_code(value)
    if not code or not sensor:
        return None
    if sensor == "sentinel-2":
        if code[1:].isdigit():
            code = "B" + code[1:].zfill(2)
        return SENTINEL2.get(code)
    if str(sensor).startswith("landsat-"):
        if code != "B8A" and code[1:].isdigit():
            code = "B" + str(int(code[1:]))
        return landsat_band_map(sensor, product_prefix).get(code)
    return None


def parse_landsat_product_identifier(value):
    """Parse official Collection-style Landsat product identifiers."""
    match = LANDSAT_PRODUCT_RE.search(str(value).upper())
    if not match:
        return None
    data = match.groupdict()
    sensor = f"landsat-{int(data['satellite'])}"
    return {
        **data,
        "product_id": match.group(0),
        "sensor": sensor,
        "acquired_iso": f"{data['acquired'][:4]}-{data['acquired'][4:6]}-{data['acquired'][6:8]}",
        "band_map": landsat_band_map(sensor, data["prefix"]),
    }


def sentinel_identity(value):
    """Return tile/acquisition tokens when explicitly present in a Sentinel name."""
    text = str(value).upper()
    tile = SENTINEL_TILE_RE.search(text)
    acquired = SENTINEL_DATETIME_RE.search(text)
    return {
        "tile": tile.group(1).upper() if tile else None,
        "acquired": acquired.group(1) if acquired else None,
    }


def quality_asset_role(value, *, sensor=None):
    """Recognize quality companions only when their semantics are unambiguous."""
    token = _flat(value)
    if sensor and str(sensor).startswith("landsat-"):
        if token.endswith("qapixel") or token == "qapixel":
            return "quality", "landsat_qa"
        if token.endswith("qaradsat") or token == "qaradsat":
            return "saturation", "landsat_radsat"
    if sensor == "sentinel-2":
        if token.endswith("scl") or token in {"sceneclassification", "sceneclassificationlayer", "sceneclassificationmap"}:
            return "quality", "sentinel_scl"
        if token.endswith("qa60") or token == "qa60":
            return "quality", "sentinel_qa60"
    return None, None
