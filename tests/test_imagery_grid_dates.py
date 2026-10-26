"""Native resolution and acquisition identity are preserved before mosaicking."""
import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.transform import Affine
from rasterio.vrt import WarpedVRT
from shapely.geometry import Polygon

import cartomize as cm
from cartomize.imagery import _plan_imagery


@pytest.mark.parametrize('angle', [0, 45, 90, 180])
def test_rotated_native_pixel_size_is_not_inflated_to_its_bounding_box(write_raster, tmp_path, angle):
    transform = Affine.translation(300000, 9500000)*Affine.rotation(angle)*Affine.scale(10, -10)
    path = write_raster('rotated.tif', np.ones((4, 4), dtype='float32'), transform=transform)
    scene = cm.Scene('one', {'red': path}, sensor='custom', acquired='2026-10-01')
    aoi = gpd.GeoDataFrame(geometry=[Polygon([transform*p for p in ((0, 0), (4, 0), (4, 4), (0, 4))])], crs=32733)
    audit = cm.audit_imagery([scene], tmp_path/'diagnostic', aoi=aoi, mask_clouds=False)
    product = cm.prepare_imagery([scene], tmp_path/'prepared.tif', aoi=aoi, mask_clouds=False)
    assert audit.report['parameters']['resolution_m'] == pytest.approx(10)
    with rasterio.open(product.path) as src:
        assert src.res == pytest.approx((10, 10))
    plan = _plan_imagery([scene], mask_clouds=False)
    assert plan['records'][0]['resolution_method'] == 'native_affine'
    assert plan['width'] > 0 and plan['height'] > 0
    if angle in (0, 90, 180):
        assert (plan['width'], plan['height']) == (4, 4)


def test_reprojected_default_grid_uses_actual_affine(write_raster):
    transform = Affine.translation(300000, 9500000)*Affine.rotation(45)*Affine.scale(10, -20)
    path = write_raster('rotated.tif', np.ones((8, 8), dtype='float32'), transform=transform)
    scene = cm.Scene('one', {'red': path}, sensor='custom', acquired='2026-10-01')
    same = _plan_imagery([scene], mask_clouds=False)
    assert same['resolution'] == pytest.approx(20)
    with rasterio.open(path) as src, WarpedVRT(src, crs='EPSG:32732') as proposed:
        expected = max(proposed.res)
    plan = _plan_imagery([scene], target_crs='EPSG:32732', mask_clouds=False)
    assert plan['resolution'] == pytest.approx(expected)
    assert plan['records'][0]['resolution_method'] == 'gdal_suggested_warp'


@pytest.mark.parametrize('missing', [None, '', '   '])
def test_blank_acquisition_cannot_bypass_unknown_date_guard(write_raster, tmp_path, missing):
    path = write_raster('source.tif', np.ones((3, 3), dtype='float32'))
    scenes = [cm.Scene(name, {'red': path}, sensor='custom', acquired=missing) for name in ('a', 'b')]
    assert all(s.acquired is None for s in scenes)
    with pytest.raises(ValueError, match='unknown'):
        cm.prepare_imagery(scenes, tmp_path/'rejected.tif', mask_clouds=False)
    assert not (tmp_path/'rejected.tif').exists()
    result = cm.prepare_imagery(scenes, tmp_path/'explicit.tif', mask_clouds=False, allow_mixed_dates=True)
    assert result.path.is_file()


def test_equivalent_iso_dates_share_one_acquisition(write_raster):
    path = write_raster('source.tif', np.ones((3, 3), dtype='float32'))
    scenes = [cm.Scene(name, {'red': path}, sensor='custom', acquired=date)
              for name, date in [('a', '2026-10-26'), ('b', ' 20261026 '), ('c', '2026-W44-1')]]
    assert _plan_imagery(scenes, mask_clouds=False)['dates'] == {'2026-10-26'}
    with pytest.raises(ValueError, match='Acquisition date'):
        cm.Scene('invalid', {'red': path}, sensor='custom', acquired=0)
