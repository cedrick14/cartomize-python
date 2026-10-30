"""Rehearse USGS-style band selection through coverage, harmonization and outputs."""
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

import cartomize as cm


_spec = importlib.util.spec_from_file_location(
    "create_imagery_demo", Path(__file__).parents[1] / "examples" / "create_imagery_demo.py")
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
create_demo = _module.create_demo


def test_one_usgs_scene_is_selected_and_clipped_to_aoi(tmp_path):
    inputs = create_demo(tmp_path / "inputs")
    result = cm.preprocess_imagery(inputs["selected_band_paths"], tmp_path / "one",
        aoi=inputs["zones"]["one_scene"], band_order=inputs["band_order"], resolution=30,
        composition="natural", separate_bands=True)
    assert result.report["mosaic"] is False
    assert result.report["selected_scene_ids"] == ["LC08_L2SP_181063_20260817_20260820_02_T1"]
    assert result.report["status"] == "complete"
    assert result.report["usable_percent"] == 100
    product = result.products[0]
    with rasterio.open(product["multiband"]) as image:
        assert image.count == 6 and image.shape == (30, 40)
        assert image.transform == from_origin(300300, 9499740, 30, 30)
        assert image.descriptions == tuple(inputs["band_order"])
        assert image.crs.to_epsg() == 32733
        # Pixel (0,0) is source row 10/column 10; the original SR calibration
        # must be applied once, while the scientific output stays un-stretched.
        assert image.read(1)[0, 0] == pytest.approx((12000 + 10 * 20 + 10 * 5) * .0000275 - .2)
        assert image.dataset_mask().min() == 255
    with rasterio.open(product["composition"]) as rgb:
        assert rgb.count == 4 and rgb.shape == (30, 40)
        assert rgb.dtypes == ("uint8",) * 4
    assert len(product["bands"]) == 6
    for band in product["bands"].values():
        assert Path(band["path"]).is_file()


def test_bands_and_aoi_alone_choose_a_common_projected_grid(tmp_path):
    inputs = create_demo(tmp_path / "inputs")
    result = cm.preprocess_imagery(inputs["selected_band_paths"], tmp_path / "automatic",
        aoi=inputs["zones"]["mosaic"], composition="natural")
    assert result.report["mosaic"] is True
    assert result.report["usable_percent"] == 100
    with rasterio.open(result.products[0]["multiband"]) as image:
        assert image.crs.to_epsg() == 32733
        assert image.res == (60, 60)
        assert image.shape == (15, 46)
        assert image.bounds == (300300, 9498840, 303060, 9499740)
        assert image.dataset_mask().min() == 255


@pytest.mark.parametrize("different_crs", [False, True])
def test_complementary_usgs_scenes_automatically_mosaic_and_harmonize(tmp_path, different_crs):
    inputs = create_demo(tmp_path / "inputs", different_crs=different_crs)
    result = cm.preprocess_imagery(inputs["scenes_directory"], tmp_path / "mosaic",
        aoi=inputs["zones"]["mosaic"], band_order=inputs["band_order"],
        target_crs=inputs["target_crs"], resolution=30, separate_bands=True,
        composition=("nir", "red", "green"))
    assert result.report["status"] == "complete" and result.report["mosaic"] is True
    assert len(result.report["selected_scene_ids"]) == 2
    assert result.report["recommended_action"] == "mosaic"
    assert result.report["usable_percent"] == 100
    product = result.products[0]
    with rasterio.open(product["multiband"]) as image:
        assert image.crs.to_epsg() == 32733
        assert image.transform == from_origin(300300, 9499740, 30, 30)
        assert image.shape == (30, 92)
        assert image.dataset_mask().min() == 255
        assert np.isfinite(image.read()).all()
    with rasterio.open(product["source_index"]) as sources:
        assert set(np.unique(sources.read(1))) == {1, 2}
        np.testing.assert_array_equal(sources.read(1)[:, :54], 1)
        np.testing.assert_array_equal(sources.read(1)[:, 54:], 2)
    preparation = json.loads(Path(product["report"]).read_text())
    assert preparation["upsampled_bands"]  # The 60 m source is honestly recorded.
    ndvi_path = cm.spectral_indices(product["multiband"], tmp_path / "ndvi.tif", ["NDVI"])
    with rasterio.open(ndvi_path) as ndvi:
        assert ndvi.shape == (30, 92)
        assert ndvi.read(1).min() > 0 and ndvi.read(1).max() < 1


def test_missing_scene_preserves_actionable_coverage_diagnostic(tmp_path):
    inputs = create_demo(tmp_path / "inputs")
    destination = tmp_path / "blocked"
    with pytest.raises(cm.ImageryCoverageError) as caught:
        cm.preprocess_imagery(inputs["scene_directories"][0], destination,
            aoi=inputs["zones"]["mosaic"], band_order=inputs["band_order"], resolution=30)
    error = caught.value
    assert not destination.exists()
    assert error.report["recommended_action"] == "additional_scenes"
    assert error.report["usable_percent"] == pytest.approx(100 * 54 / 92)
    with rasterio.open(error.diagnostic.gaps) as gaps:
        np.testing.assert_array_equal(gaps.read(1)[:, :54], 0)
        np.testing.assert_array_equal(gaps.read(1)[:, 54:], 1)
    assert error.manifest.is_file()


@pytest.mark.parametrize("gap, reason", [("cloud", 3), ("nodata", 2)])
def test_usgs_quality_and_nodata_gaps_block_incomplete_demo_output(tmp_path, gap, reason):
    inputs = create_demo(tmp_path / "inputs", gap=gap)
    destination = tmp_path / "blocked"
    with pytest.raises(cm.ImageryCoverageError) as caught:
        cm.preprocess_imagery(inputs["scenes_directory"], destination,
            aoi=inputs["zones"]["mosaic"], band_order=inputs["band_order"], resolution=30)
    assert not destination.exists()
    error = caught.value
    assert error.report["footprint_percent"] == 100
    assert error.report["usable_pixels"] == 30 * 92 - 36
    with rasterio.open(error.diagnostic.gaps) as gaps:
        assert np.count_nonzero(gaps.read(1) == reason) == 36
    assert error.workflow_report["products"] == []
