"""Scientific regressions for calibrated zones, affine grids and input protection."""
import math
import threading

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.transform import Affine, from_origin
from shapely.affinity import affine_transform
from shapely.geometry import LineString, Point, Polygon, box

import cartomize as cm
from cartomize import raster as raster_module


def _zones(*geometries, **attributes):
    return gpd.GeoDataFrame(attributes, geometry=list(geometries), crs=32733)


def _scaled(write_raster, name="scaled.tif", *, scale=.5, offset=-1):
    path = write_raster(name, np.array([[0, 10, -9999], [20, 30, 40]], dtype="int16"))
    with rasterio.open(path, "r+") as dst:
        dst.scales = (scale,)
        dst.offsets = (offset,)
        dst.set_band_unit(1, "reflectance")
    return path


def test_zonal_physical_default_raw_opt_in_and_provenance(write_raster):
    source = _scaled(write_raster)
    zones = _zones(box(300000, 9499980, 300030, 9500000))
    physical = cm.raster.zonal_stats(source, zones, block_size=1)
    raw = cm.raster.zonal_stats(source, zones, value_mode="raw", block_size=2)
    assert list(physical.columns) == ["geometry", "count", "min", "max", "mean", "sum", "std"]
    assert physical["count"].tolist() == raw["count"].tolist() == [5]
    np.testing.assert_allclose(physical.loc[0, ["min", "max", "mean", "sum", "std"]].astype(float),
                               [-1, 19, 9, 45, np.sqrt(50)])
    np.testing.assert_allclose(raw.loc[0, ["min", "max", "mean", "sum", "std"]].astype(float),
                               [0, 40, 20, 100, np.sqrt(200)])
    metadata = physical.attrs["cartomize"]
    assert metadata["source"] == str(source.resolve())
    assert metadata["value_mode"] == "physical"
    assert metadata["applied_scale"] == .5 and metadata["applied_offset"] == -1
    assert metadata["unit"] == "reflectance" and metadata["std_ddof"] == 0
    assert raw.attrs["cartomize"]["applied_scale"] == 1
    assert raw.attrs["cartomize"]["applied_offset"] == 0
    assert raw.attrs["cartomize"]["unit"] is None
    assert "count" not in zones and "cartomize" not in zones.attrs


@pytest.mark.parametrize("scale, offset", [(-.5, 3), (0, 7)])
def test_zonal_negative_and_zero_calibration(write_raster, scale, offset):
    source = _scaled(write_raster, scale=scale, offset=offset)
    zones = _zones(box(300000, 9499980, 300030, 9500000))
    result = cm.raster.zonal_stats(source, zones, block_size=1)
    expected = np.array([0, 10, 20, 30, 40])*scale+offset
    np.testing.assert_allclose(result.loc[0, ["min", "max", "mean", "sum", "std"]].astype(float),
                               [expected.min(), expected.max(), expected.mean(), expected.sum(), expected.std()])


def test_zonal_coverage_outside_image_empty_geometries_and_duplicate_indices(write_raster):
    source = _scaled(write_raster)
    zones = _zones(box(300000, 9499980, 300040, 9500000),
                   box(300100, 9499980, 300110, 9500000), None, Polygon(),
                   count=[91, 92, 93, 94])
    zones.index = [0, 0, 1, 1]
    result = cm.raster.zonal_stats(source, zones, prefix="zs_", include_coverage=True, block_size=1)
    assert list(result.index) == [0, 0, 1, 1] and result.crs == zones.crs
    assert result["count"].tolist() == [91, 92, 93, 94]
    assert result["zs_count"].tolist() == [5, 0, 0, 0]
    assert result["zs_zone_pixels"].tolist() == [8, 2, 0, 0]
    assert result["zs_raster_pixels"].tolist() == [6, 0, 0, 0]
    np.testing.assert_allclose(result["zs_coverage_percent"], [62.5, 0, np.nan, np.nan], equal_nan=True)
    assert result["zs_mean"].iloc[0] == 9
    assert result["zs_mean"].iloc[1:].isna().all()
    assert result.attrs["cartomize"]["columns"]["coverage_percent"] == "zs_coverage_percent"


def test_zonal_coverage_masks_nonfinite_zero_and_categorical_codes(write_raster):
    data = np.array([[0, 1, 2], [np.nan, np.inf, -9999]], dtype="float64")
    source = write_raster("masked-values.tif", data, mask=[[1, 0, 1], [1, 1, 0]])
    with rasterio.open(source, "r+") as dst:
        dst.scales = (.5,)
        dst.offsets = (1,)
    zones = _zones(box(300000, 9499980, 300030, 9500000))
    result = cm.raster.zonal_stats(source, zones, include_coverage=True)
    assert result.loc[0, "count"] == 2 and result.loc[0, "zone_pixels"] == 6
    assert result.loc[0, "raster_pixels"] == 6
    assert result.loc[0, "coverage_percent"] == pytest.approx(100/3)
    assert result.loc[0, "mean"] == 1.5
    assert set(cm.raster.class_areas(source)["class"]) == {0, 2}
    with rasterio.open(source) as src:
        assert raster_module._read(src, 1)[0, 0] == 0


def test_zonal_explicit_source_mask_takes_precedence_over_numeric_nodata(write_raster):
    data = np.array([[0, 1], [0, 3]], dtype="int16")
    explicit = write_raster("explicit-mask.tif", data, nodata=0, mask=np.ones((2, 2)))
    ordinary = write_raster("ordinary-nodata.tif", data, nodata=0)
    zones = _zones(box(300000, 9499980, 300020, 9500000))
    masked = cm.raster.zonal_stats(explicit, zones, include_coverage=True, block_size=1)
    declared = cm.raster.zonal_stats(ordinary, zones, include_coverage=True, block_size=1)
    assert masked.loc[0, "count"] == 4 and masked.loc[0, "coverage_percent"] == 100
    assert masked.loc[0, "min"] == 0 and masked.loc[0, "mean"] == 1
    assert declared.loc[0, "count"] == 2 and declared.loc[0, "coverage_percent"] == 50
    assert declared.loc[0, "min"] == 1 and declared.loc[0, "mean"] == 2
    assert "explicit mask takes precedence" in masked.attrs["cartomize"]["mask_rule"]


def test_zonal_small_zone_pixel_rule_and_holes(write_raster):
    source = write_raster("ones.tif", np.ones((3, 3), dtype="uint8"), nodata=None)
    tiny = _zones(box(300001, 9499998, 300002, 9499999))
    centers = cm.raster.zonal_stats(source, tiny, include_coverage=True, block_size=1)
    touched = cm.raster.zonal_stats(source, tiny, include_coverage=True, all_touched=True, block_size=1)
    assert centers.loc[0, "zone_pixels"] == centers.loc[0, "count"] == 0
    assert np.isnan(centers.loc[0, "coverage_percent"])
    assert touched.loc[0, "zone_pixels"] == touched.loc[0, "count"] == 1
    assert touched.loc[0, "coverage_percent"] == 100
    outer = box(300000, 9499970, 300030, 9500000)
    hole = box(300010, 9499980, 300020, 9499990)
    donut = _zones(Polygon(outer.exterior.coords, [hole.exterior.coords]))
    result = cm.raster.zonal_stats(source, donut, include_coverage=True, block_size=1)
    assert result.loc[0, "zone_pixels"] == result.loc[0, "raster_pixels"] == result.loc[0, "count"] == 8


@pytest.mark.parametrize("angle", [45, 90, 180])
def test_zonal_extended_coverage_on_rotated_grid(write_raster, angle):
    transform = Affine.translation(300000, 9500000)*Affine.rotation(angle)*Affine.scale(10, -10)
    source = write_raster("rotated.tif", np.array([[0, 1], [2, 3]], dtype="int16"), transform=transform)
    zone = Polygon([transform*point for point in ((-2, 0), (2, 0), (2, 2), (-2, 2))])
    zones = _zones(zone).to_crs(4326)
    result = cm.raster.zonal_stats(source, zones, include_coverage=True, block_size=1)
    assert result.crs == zones.crs
    assert result.loc[0, "zone_pixels"] == 8
    assert result.loc[0, "raster_pixels"] == result.loc[0, "count"] == 4
    assert result.loc[0, "coverage_percent"] == 50
    assert result.loc[0, "mean"] == 1.5


@pytest.mark.parametrize("transform", [
    Affine(10, 0, 300000, 0, -10, 9500000),
    Affine(8, 6, 300000, 6, -8, 9500000),
    Affine(10, 2, 300000, 3, -10, 9500000),
])
@pytest.mark.parametrize("all_touched", [False, True])
@pytest.mark.parametrize("with_hole", [False, True])
def test_zonal_boundary_selection_is_block_invariant_and_matches_exact_oracle(
        write_raster, transform, all_touched, with_hole):
    data = np.arange(144, dtype="int16").reshape(12, 12)
    source = write_raster("boundary.tif", data, transform=transform)
    if with_hole:
        pixel_zone = Polygon([(.5, .5), (11.5, .5), (11.5, 11.5), (.5, 11.5)],
                             holes=[[(2.5, 2.5), (9.5, 2.5), (2.5, 9.5)]])
    else:
        pixel_zone = Polygon([(0, 0), (12, 0), (0, 12)])
    world = affine_transform(pixel_zone, [transform.a, transform.b, transform.d,
                                         transform.e, transform.c, transform.f])
    inverse = ~transform
    # The specification is expressed on one global inverse grid. Build a small
    # independent per-cell oracle, including centers/edges exactly on a boundary.
    zone = affine_transform(world, [inverse.a, inverse.b, inverse.d,
                                    inverse.e, inverse.c, inverse.f])
    left, top, right, bottom = zone.bounds
    selected = []
    for row in range(math.floor(top), math.ceil(bottom)):
        for col in range(math.floor(left), math.ceil(right)):
            cell = box(col, row, col+1, row+1) if all_touched else Point(col+.5, row+.5)
            if zone.intersects(cell):
                selected.append((row, col))
    observed = [(row, col) for row, col in selected if 0 <= row < 12 and 0 <= col < 12]
    expected = np.array([data[row, col] for row, col in observed])
    records = []
    for size in (1, 3, 512):
        result = cm.raster.zonal_stats(source, _zones(world), include_coverage=True,
                                       all_touched=all_touched, block_size=size)
        assert result.loc[0, "zone_pixels"] == len(selected)
        assert result.loc[0, "raster_pixels"] == result.loc[0, "count"] == len(observed)
        assert result.loc[0, "sum"] == expected.sum()
        assert result.loc[0, "mean"] == pytest.approx(expected.mean())
        assert result.loc[0, "std"] == pytest.approx(expected.std())
        records.append(result.loc[0, ["count", "zone_pixels", "raster_pixels", "sum"]].tolist())
    assert records[0] == records[1] == records[2]


def test_zonal_blockwise_moments_remain_stable_with_large_offset(write_raster, monkeypatch):
    data = 1e12+(np.arange(70*90).reshape(70, 90) % 13)*.25
    source = write_raster("large-offset.tif", data)
    zones = _zones(box(300000, 9499300, 300900, 9500000))
    original = raster_module._read
    sizes = []
    def bounded_read(src, band, **kwargs):
        window = kwargs["window"]
        sizes.append((window.width, window.height))
        return original(src, band, **kwargs)
    monkeypatch.setattr(raster_module, "_read", bounded_read)
    progress = []
    result = cm.raster.zonal_stats(source, zones, block_size=7, progress=lambda done, total: progress.append((done, total)))
    assert max(width for width, _ in sizes) <= 7 and max(height for _, height in sizes) <= 7
    assert len(sizes) > 1 and progress == [(1, 1)]
    assert result.loc[0, "count"] == data.size
    assert result.loc[0, "mean"] == pytest.approx(data.mean(), rel=0, abs=.001)
    assert result.loc[0, "std"] == pytest.approx(data.std(), abs=.0001)
    assert result.loc[0, "sum"] == pytest.approx(data.sum(), rel=1e-14)


def test_zonal_budget_preflight_precedes_reads_and_checks_all_zones(write_raster, monkeypatch):
    source = _scaled(write_raster)
    zones = _zones(box(300000, 9499990, 300010, 9500000),
                   box(300000, 9499980, 300040, 9500000))
    def unexpected_read(*args, **kwargs):
        pytest.fail("Budget must be checked for all zones before reading raster pixels")
    monkeypatch.setattr(raster_module, "_read", unexpected_read)
    with pytest.raises(ValueError, match="position 1.*max_zone_pixels"):
        cm.raster.zonal_stats(source, zones, include_coverage=True, max_zone_pixels=7, block_size=1)


def test_zonal_cancellation_before_and_during_blocks(write_raster, monkeypatch):
    source = _scaled(write_raster)
    zones = _zones(box(300000, 9499980, 300030, 9500000))
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(cm.ProcessingCancelled):
        cm.raster.zonal_stats(source, zones, cancel=cancel)
    cancel.clear()
    original = raster_module._read
    calls = []
    def stop_after_read(*args, **kwargs):
        calls.append(kwargs["window"])
        values = original(*args, **kwargs)
        cancel.set()
        return values
    monkeypatch.setattr(raster_module, "_read", stop_after_read)
    with pytest.raises(cm.ProcessingCancelled):
        cm.raster.zonal_stats(source, zones, block_size=1, cancel=cancel)
    assert len(calls) == 1 and list(zones.columns) == ["geometry"]


def test_zonal_prefix_collision_and_invalid_geometry_are_explicit(write_raster):
    source = _scaled(write_raster)
    zones = _zones(box(300000, 9499980, 300030, 9500000), mean=[17], zs_count=[4])
    with pytest.raises(ValueError, match="prefix.*mean"):
        cm.raster.zonal_stats(source, zones)
    with pytest.raises(ValueError, match="prefix.*zs_count"):
        cm.raster.zonal_stats(source, zones, prefix="zs_")
    bowtie = Polygon([(300000, 9500000), (300020, 9499980), (300000, 9499980), (300020, 9500000)])
    with pytest.raises(ValueError, match="invalid geometry"):
        cm.raster.zonal_stats(source, _zones(bowtie))
    for geometry in (Point(300005, 9499995), LineString([(300005, 9499995), (300025, 9499995)])):
        with pytest.raises(ValueError, match="Polygon or MultiPolygon"):
            cm.raster.zonal_stats(source, _zones(geometry))


@pytest.mark.parametrize("options", [
    {"value_mode": "guess"}, {"prefix": None}, {"prefix": "bad\x00"},
    {"block_size": 0}, {"block_size": True}, {"block_size": 2049},
    {"max_zone_pixels": 0}, {"max_zone_pixels": 3.5}, {"max_zone_pixels": True},
    {"all_touched": "true"}, {"include_coverage": "false"}, {"band": True},
    {"progress": 2}, {"cancel": False},
])
def test_zonal_invalid_parameters(write_raster, options):
    source = _scaled(write_raster)
    with pytest.raises(ValueError):
        cm.raster.zonal_stats(source, _zones(box(300000, 9499980, 300030, 9500000)), **options)


def test_zonal_complex_data_rejected_and_geographic_statistics_supported(write_raster):
    complex_source = write_raster("complex.tif", np.full((2, 2), 1+2j, dtype="complex64"), nodata=None)
    with pytest.raises(ValueError, match="complex"):
        cm.raster.zonal_stats(complex_source, _zones(box(300000, 9499980, 300020, 9500000)))
    source = write_raster("geographic.tif", np.array([[0, 1], [2, 3]], dtype="int16"),
                          crs=4326, transform=from_origin(15, -5, .01, .01))
    zones = gpd.GeoDataFrame(geometry=[box(15, -5.02, 15.02, -5)], crs=4326)
    result = cm.raster.zonal_stats(source, zones, include_coverage=True)
    assert result.loc[0, "mean"] == 1.5 and result.loc[0, "coverage_percent"] == 100


def test_relations_use_actual_affine_corners(write_raster):
    transform = Affine.translation(300000, 9500000)*Affine.rotation(45)*Affine.scale(10, -10)
    source = write_raster("diamond.tif", np.ones((2, 2), dtype="uint8"), transform=transform, nodata=None)
    footprint = Polygon([transform*point for point in ((0, 0), (2, 0), (2, 2), (0, 2))])
    report = cm.analyze_relations([source, _zones(footprint)], metric_crs=32733)
    assert report["pairs"][0]["relation"] == "equal"
    assert report["pairs"][0]["intersection_m2"] == pytest.approx(400)
    # This polygon is inside the bounding rectangle but outside the true image.
    outside = box(*footprint.bounds).difference(footprint).geoms[0].representative_point().buffer(.1)
    report = cm.analyze_relations([source, _zones(outside)], metric_crs=32733)
    pair = report["pairs"][0]
    assert pair["relation"] == "disjoint" and pair["intersection_m2"] == 0
    assert pair["distance_m"] == pytest.approx(footprint.distance(outside))


def test_valid_footprint_path_cannot_be_overwritten(write_raster, tmp_path):
    source = write_raster("source.tif", np.zeros((2, 2), dtype="int16"))
    footprint = tmp_path/"footprint.geojson"
    _zones(box(300000, 9499980, 300020, 9500000)).to_file(footprint)
    before = {path: path.read_bytes() for path in (source, footprint)}
    with pytest.raises(ValueError, match="every input"):
        cm.mask_background(source, footprint, valid_footprint=footprint, overwrite=True)
    for path, content in before.items():
        assert path.read_bytes() == content
