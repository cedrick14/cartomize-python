import pytest

from cartomize.sensor_profiles import (
    canonical_semantic_name, native_band_code, semantic_band_name,
    parse_landsat_product_identifier, quality_asset_role, sensor_from_text,
)


@pytest.mark.parametrize("value,expected", [
    ("red", "red"), ("Rouge", "red"), ("near infrared", "nir"),
    ("NIR", "nir"), ("SWIR16", "swir1"), ("swir_2", "swir2"),
    ("B8A", None),
])
def test_descriptive_semantic_aliases(value, expected):
    assert canonical_semantic_name(value) == expected


@pytest.mark.parametrize("value,expected", [
    ("B4", "B4"), ("B04", "B04"), ("SR_B4", "B4"),
    ("Band_4", "B4"), ("B8A", "B8A"), ("T33MUP_B02_10m.tif", "B02"),
])
def test_native_band_code_variants(value, expected):
    assert native_band_code(value) == expected


def test_numeric_band_requires_sensor_context():
    assert semantic_band_name("B4") is None
    assert semantic_band_name("B4", sensor="landsat-8") == "red"
    assert semantic_band_name("B4", sensor="landsat-5") == "nir"
    assert semantic_band_name("B04", sensor="sentinel-2") == "red"


@pytest.mark.parametrize("name,sensor,role", [
    ("LC08_L2SP_181063_20260817_20260820_02_T1_SR_B4.TIF", "landsat-8", "red"),
    ("LC09_L2SP_181063_20260817_20260820_02_T1_SR_B5.tif", "landsat-9", "nir"),
    ("LT05_L2SP_181063_20260817_20260820_02_T1_SR_B4.TIF", "landsat-5", "nir"),
    ("LE07_L2SP_181063_20260817_20260820_02_T1_SR_B3.TIF", "landsat-7", "red"),
    ("S2A_T33MUP_20260817T091031_B08_10m.tif", "sentinel-2", "nir"),
])
def test_sensor_context_resolves_native_codes(name, sensor, role):
    assert semantic_band_name(name, sensor=sensor) == role


def test_parse_landsat_collection_product_metadata():
    record = parse_landsat_product_identifier(
        "LC08_L2SP_181063_20260817_20260820_02_T1_SR_B4.TIF"
    )
    assert record["sensor"] == "landsat-8"
    assert record["path"] == "181" and record["row"] == "063"
    assert record["acquired_iso"] == "2026-08-17"
    assert record["collection"] == "02"
    assert record["band_map"]["B4"] == "red"


@pytest.mark.parametrize("value,sensor,role,kind", [
    ("QA_PIXEL.TIF", "landsat-8", "quality", "landsat_qa"),
    ("LC08_scene_QA_RADSAT.tif", "landsat-8", "saturation", "landsat_radsat"),
    ("SCL_20m.jp2", "sentinel-2", "quality", "sentinel_scl"),
    ("scene_classification_layer.tif", "sentinel-2", "quality", "sentinel_scl"),
])
def test_quality_asset_aliases(value, sensor, role, kind):
    assert quality_asset_role(value, sensor=sensor) == (role, kind)


@pytest.mark.parametrize("value,expected", [
    ("LC08_L2SP_181063_20260817_20260820_02_T1", "landsat-8"),
    ("LANDSAT 5", "landsat-5"),
    ("Sentinel-2A", "sentinel-2"),
])
def test_sensor_tokens(value, expected):
    assert sensor_from_text(value)[0] == expected
