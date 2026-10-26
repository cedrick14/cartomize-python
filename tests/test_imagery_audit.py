import json
import threading

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from affine import Affine
from rasterio.transform import from_origin
from shapely.geometry import box

from cartomize import Band, ProcessingCancelled, Scene, prepare_imagery
from cartomize.imagery import _quality_valid
from cartomize.imagery_audit import audit_imagery


def _aoi(left=300000, right=300040, bottom=9499990, top=9500000):
    return gpd.GeoDataFrame(geometry=[box(left, bottom, right, top)], crs=32733)


def _scene(write_raster, name, red, nir=None, *, x=300000, quality=None):
    transform = from_origin(x, 9500000, 10, 10)
    bands = {"red": write_raster(f"{name}_red.tif", np.asarray(red, dtype="float32"), transform=transform)}
    if nir is not None:
        bands["nir"] = write_raster(f"{name}_nir.tif", np.asarray(nir, dtype="float32"), transform=transform)
    return Scene(name, bands, sensor="custom", acquired="2026-10-26",
                 quality=quality, quality_kind="valid_mask" if quality is not None else None)


def test_distinguishes_footprint_missing_data_quality_and_outside_aoi(write_raster, tmp_path):
    quality = write_raster("quality.tif", np.array([[1, 1, 0, 1]], dtype="uint8"), nodata=None)
    scene = _scene(write_raster, "A", [[1, -9999, 3, 4]], [[2, 2, 2, 2]], quality=quality)
    result = audit_imagery([scene], tmp_path / "audit", aoi=_aoi(right=300060))
    assert result.report["aoi_pixels"] == 6
    assert [result.report[f"{name}_pixels"] for name in ("footprint", "present", "usable")] == [4, 3, 2]
    assert result.report["usable_percent"] == pytest.approx(100 / 3)
    assert result.report["coverage_status"] == "partial"
    assert result.report["recommended_action"] == "additional_scenes"
    with rasterio.open(result.gaps) as src:
        assert src.read(1).tolist() == [[0, 2, 3, 0, 1, 1]]
    with rasterio.open(result.coverage) as src:
        assert src.descriptions == ("footprint", "present", "usable")
        assert src.read().tolist() == [[[1, 1, 1, 1, 0, 0]], [[1, 0, 1, 1, 0, 0]], [[1, 0, 0, 1, 0, 0]]]
    report = json.loads(result.manifest.read_text(), parse_constant=lambda value: pytest.fail(value))
    assert report["schema"] == "cartomize.imagery.audit.v1"
    assert report["coverage"] == str(result.coverage)
    assert not list(result.manifest.parent.glob(".calibration-*"))
    from cartomize.viewer_data import raster_info
    assert raster_info(result.coverage)["native_rgb"] is False
    assert set(raster_info(result.coverage)["classes"]) == {0., 1.}
    assert set(raster_info(result.gaps)["classes"]) == {0., 1., 2., 3.}


def test_adjacent_scenes_recommend_mosaic_and_match_prepared_grid(write_raster, tmp_path):
    scenes = [_scene(write_raster, "A", [[1, 2]], [[11, 12]]),
              _scene(write_raster, "B", [[3, 4]], [[13, 14]], x=300020)]
    aoi = _aoi()
    result = audit_imagery(scenes, tmp_path / "audit", aoi=aoi, mask_clouds=False)
    assert result.report["recommended_action"] == "mosaic"
    assert result.report["recommended_scene_ids"] == ["A", "B"]
    assert result.report["mosaic_recommended"] is True
    assert result.report["coverage_status"] == "complete"
    assert [s["usable_percent"] for s in result.report["scenes"]] == [50., 50.]
    prepared = prepare_imagery(scenes, tmp_path / "prepared.tif", aoi=aoi, mask_clouds=False)
    with rasterio.open(result.coverage) as audit, rasterio.open(prepared.path) as image:
        assert audit.transform == image.transform and audit.crs == image.crs and audit.shape == image.shape
        np.testing.assert_array_equal(audit.read(3) == 1, np.isfinite(image.read()).all(axis=0))
    assert result.report["usable_percent"] == prepared.report["coverage_percent"]


def test_complementary_bands_from_different_scenes_do_not_create_a_spectrum(write_raster, tmp_path):
    scenes = [_scene(write_raster, "A", [[1, -9999]], [[-9999, 2]]),
              _scene(write_raster, "B", [[-9999, 3]], [[4, -9999]])]
    result = audit_imagery(scenes, tmp_path / "audit", aoi=_aoi(right=300020), mask_clouds=False)
    assert result.report["footprint_percent"] == 100
    assert result.report["present_pixels"] == result.report["usable_pixels"] == 0
    assert result.report["coverage_status"] == "empty"
    assert result.report["recommended_scene_ids"] == []
    with rasterio.open(result.gaps) as src:
        assert src.read(1).tolist() == [[2, 2]]


def test_common_band_footprint_is_intersection_before_scene_union(write_raster, tmp_path):
    red = write_raster("red.tif", np.ones((1, 2), dtype="float32"))
    nir = write_raster("nir.tif", np.ones((1, 2), dtype="float32"),
                       transform=from_origin(300020, 9500000, 10, 10))
    scene = Scene("A", {"red": red, "nir": nir}, sensor="custom")
    result = audit_imagery([scene], tmp_path / "audit", aoi=_aoi(), mask_clouds=False)
    assert result.report["footprint_pixels"] == result.report["usable_pixels"] == 0
    with rasterio.open(result.gaps) as src:
        assert src.read(1).tolist() == [[1, 1, 1, 1]]


def test_best_single_scene_uses_the_expert_coverage_threshold(write_raster, tmp_path):
    scenes = [_scene(write_raster, "A", [[1, 2, 3, 4]]),
              _scene(write_raster, "B", [[1, 2]])]
    result = audit_imagery(scenes, tmp_path / "audit", aoi=_aoi(right=300050),
                           mask_clouds=False, coverage_threshold=80)
    assert result.report["usable_percent"] == 80
    assert result.report["coverage_status"] == "partial"
    assert result.report["threshold_met"] is True
    assert result.report["recommended_action"] == "single_scene"
    assert result.report["recommended_scene_ids"] == ["A"]
    assert result.report["mosaic_recommended"] is False


@pytest.mark.parametrize("outside", [False, True])
def test_all_clouds_and_external_aoi_publish_empty_diagnoses(write_raster, tmp_path, outside):
    quality = write_raster("clouds.tif", np.zeros((1, 4), dtype="uint8"), nodata=None)
    scene = _scene(write_raster, "A", [[1, 2, 3, 4]], quality=quality)
    aoi = _aoi(left=400000, right=400040) if outside else _aoi()
    result = audit_imagery([scene], tmp_path / "audit", aoi=aoi)
    assert result.report["coverage_status"] == "empty"
    assert result.report["usable_percent"] == 0
    assert result.report["recommended_action"] == "additional_scenes"
    with rasterio.open(result.gaps) as src:
        assert np.all(src.read(1) == (1 if outside else 3))


def test_aoi_holes_are_nodata_not_missing_scenes(write_raster, tmp_path):
    scene = _scene(write_raster, "A", np.ones((3, 3)))
    polygon = box(300000, 9499970, 300030, 9500000).difference(box(300010, 9499980, 300020, 9499990))
    aoi = gpd.GeoDataFrame(geometry=[polygon], crs=32733)
    result = audit_imagery([scene], tmp_path / "audit", aoi=aoi, mask_clouds=False)
    assert result.report["aoi_pixels"] == 8
    assert result.report["usable_percent"] == 100
    with rasterio.open(result.coverage) as src:
        assert np.all(src.read()[:, 1, 1] == 255)
        assert src.read(3, masked=True).count() == 8
    with rasterio.open(result.gaps) as src:
        assert src.read(1)[1, 1] == 255


@pytest.mark.parametrize("resampling", ["nearest", "bilinear", "cubic", "average"])
def test_rotated_footprints_and_quality_match_preparation(write_raster, tmp_path, resampling):
    transform = Affine.translation(300020, 9500000) * Affine.rotation(35) * Affine.scale(10, -10)
    data = np.ones((3, 3), dtype="float32")
    data[1, 1] = -9999
    path = write_raster("rotated.tif", data, transform=transform)
    quality = write_raster("rotated_mask.tif", np.array([[1, 1, 0], [1, 1, 1], [1, 1, 1]], dtype="uint8"),
                           nodata=None, transform=transform)
    scene = Scene("rotated", {"red": path}, sensor="custom", quality=quality, quality_kind="valid_mask")
    with rasterio.open(path) as src:
        aoi = gpd.GeoDataFrame(geometry=[box(*src.bounds)], crs=src.crs)
    result = audit_imagery([scene], tmp_path / "audit", aoi=aoi, resolution=5, resampling=resampling)
    prepared = prepare_imagery([scene], tmp_path / "prepared.tif", aoi=aoi, resolution=5, resampling=resampling)
    assert result.report["footprint_pixels"] < result.report["aoi_pixels"]
    assert result.report["usable_pixels"] <= result.report["present_pixels"] <= result.report["footprint_pixels"]
    with rasterio.open(result.coverage) as audit, rasterio.open(prepared.path) as image:
        np.testing.assert_array_equal(audit.read(3) == 1, np.isfinite(image.read(1)))


def test_geographic_source_and_projected_target_match_preparation(write_raster, tmp_path):
    transform = from_origin(15., -4., .0001, .0001)
    path = write_raster("geographic.tif", np.ones((4, 4), dtype="float32"), transform=transform, crs=4326)
    scene = Scene("A", {"red": path}, sensor="custom")
    with rasterio.open(path) as src:
        aoi = gpd.GeoDataFrame(geometry=[box(*src.bounds)], crs=src.crs)
    kwargs = dict(aoi=aoi, target_crs=32733, resolution=10, mask_clouds=False)
    result = audit_imagery([scene], tmp_path / "audit", **kwargs)
    prepared = prepare_imagery([scene], tmp_path / "prepared.tif", **kwargs)
    assert result.report["usable_percent"] == prepared.report["coverage_percent"]
    with rasterio.open(result.coverage) as audit, rasterio.open(prepared.path) as image:
        np.testing.assert_array_equal(audit.read(3) == 1, np.isfinite(image.read(1)))


def test_nonzero_float_valid_masks_and_provider_masks(write_raster, tmp_path):
    mask = np.ma.array([[0., .25, 1., np.nan, .5]], mask=[[False, False, False, False, True]])
    assert _quality_valid(mask, "valid_mask").tolist() == [[False, True, True, False, False]]
    quality = write_raster("fractional.tif", np.array([[0., .25, 1., np.nan]], dtype="float32"), nodata=None)
    scene = _scene(write_raster, "A", [[10, 20, 30, 40]], quality=quality)
    result = audit_imagery([scene], tmp_path / "audit", aoi=_aoi())
    prepared = prepare_imagery([scene], tmp_path / "prepared.tif", aoi=_aoi())
    assert result.report["usable_percent"] == prepared.report["coverage_percent"] == 50
    with rasterio.open(prepared.path) as src:
        assert src.read(1, masked=True).compressed().tolist() == [20., 30.]


def test_cancellation_and_invalid_inputs_publish_nothing(write_raster, tmp_path):
    scene = _scene(write_raster, "A", [[1, 2, 3, 4]])
    event = threading.Event()
    def stop(done, total):
        if done >= 1:
            event.set()
    with pytest.raises(ProcessingCancelled):
        audit_imagery([scene], tmp_path / "cancelled", aoi=_aoi(), mask_clouds=False,
                      cancel=event, progress=stop)
    assert not (tmp_path / "cancelled").exists()
    for threshold in (0, 101, float("nan")):
        with pytest.raises(ValueError, match="coverage_threshold"):
            audit_imagery([scene], tmp_path / "invalid", aoi=_aoi(), coverage_threshold=threshold)
    with pytest.raises(ValueError, match="lacks bands"):
        audit_imagery([scene], tmp_path / "missing", aoi=_aoi(), band_order=["nir"], mask_clouds=False)
    with pytest.raises(ValueError, match="no quality"):
        audit_imagery([scene], tmp_path / "missing_qa", aoi=_aoi())
    assert not (tmp_path / "invalid").exists()
    assert not (tmp_path / "missing").exists()
    assert not (tmp_path / "missing_qa").exists()
    existing = tmp_path / "existing"
    existing.mkdir()
    (existing / "preserve.txt").write_text("unchanged")
    with pytest.raises(FileExistsError):
        audit_imagery([scene], existing, aoi=_aoi(), mask_clouds=False)
    assert (existing / "preserve.txt").read_text() == "unchanged"
