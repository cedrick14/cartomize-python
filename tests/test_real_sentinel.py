"""Offline regression with public, unchanged Sentinel-2 native pixel samples."""
import hashlib
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from shapely.geometry import box

import cartomize as cm


FIXTURE=Path(__file__).parent/'data'/'sentinel2_mvouti'


def test_real_sentinel_preprocessing_matches_same_product_c1_reference(tmp_path):
    provenance=json.loads((FIXTURE/'provenance.json').read_text(encoding='utf-8'))
    for asset in [*provenance['assets'].values(),*provenance['reference_assets'].values()]:
        path=FIXTURE/asset['local_file']
        assert hashlib.sha256(path.read_bytes()).hexdigest()==asset['sha256']
    scenes=cm.load_scenes_manifest(FIXTURE/'scenes.json')
    zones=gpd.GeoDataFrame({'name':['Mayombe']},geometry=[box(*provenance['bounds'])],crs=provenance['crs'])
    result=cm.preprocess_imagery(scenes,tmp_path/'real_output',aoi=zones,
                                band_order=['red','nir'],target_crs='EPSG:32733',resolution=10)
    assert result.report['status']=='partial'
    assert result.report['usable_percent']==pytest.approx(100*16040/16384)
    assert result.diagnostic.report['usable_pixels']==16040
    assert not result.report['mosaic']
    with rasterio.open(result.products[0]['multiband']) as prepared:
        values=prepared.read(masked=True)
        assert values.shape==(2,128,128)
        assert values.count()==16040*2
        for index,role in enumerate(('red','nir')):
            # Read the separately downloaded C1 observation of the same ESA
            # product; never manufacture its reference pixels from the input.
            reference=provenance['reference_comparison']['bands'][role]
            assert reference['difference_min']==reference['difference_max']==1000
            with rasterio.open(FIXTURE/(role+'.tif')) as raw, \
                    rasterio.open(FIXTURE/provenance['reference_assets'][role]['local_file']) as c1:
                c1_dn=c1.read(1).astype('float64')
                np.testing.assert_array_equal(c1_dn-raw.read(1).astype('float64'),1000)
                expected=c1_dn*.0001-.1
                assert prepared.transform==raw.transform==c1.transform
                assert prepared.crs==raw.crs==c1.crs
            np.testing.assert_allclose(values[index].compressed(),np.ma.array(expected,mask=values[index].mask).compressed(),rtol=1e-6,atol=2e-8)
    report=json.loads(Path(result.products[0]['report']).read_text(encoding='utf-8'))
    assert any('offset déclaré=-0.1, offset effectif=0' in note for note in report['scenes'][0]['notes'])
    ndvi=tmp_path/'real_ndvi.tif'
    cm.raster.ndvi(result.products[0]['multiband'],ndvi,red=1,nir=2)
    with rasterio.open(ndvi) as src:
        actual=src.read(1,masked=True)
        assert actual.count()==16040
        np.testing.assert_allclose(actual,(values[1]-values[0])/(values[1]+values[0]),rtol=2e-6,atol=2e-7)


def test_real_sentinel_missing_strip_blocks_and_preserves_diagnostic(tmp_path):
    provenance=json.loads((FIXTURE/'provenance.json').read_text(encoding='utf-8'))
    left,bottom,right,top=provenance['bounds']
    zones=gpd.GeoDataFrame(geometry=[box(left,bottom,right+20,top)],crs=provenance['crs'])
    with pytest.raises(cm.ImageryCoverageError) as error:
        cm.preprocess_imagery(FIXTURE/'scenes.json',tmp_path/'blocked',aoi=zones,
                              band_order=['red','nir'],target_crs='EPSG:32733',resolution=10)
    assert not (tmp_path/'blocked').exists()
    assert error.value.report['aoi_pixels']==130*128
    assert error.value.report['usable_pixels']==16040
    assert error.value.report['usable_percent']==pytest.approx(100*16040/(130*128))
    assert error.value.diagnostic.gaps.is_file()
    with rasterio.open(error.value.diagnostic.gaps) as source:
        gaps=source.read(1)
        np.testing.assert_array_equal(gaps[:,-2:],1)
        assert np.count_nonzero(gaps[:,:-2])==344
