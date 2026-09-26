"""Scientific products, optional display branches and connected map production."""
import json
from pathlib import Path
import numpy as np
import pytest
import rasterio
import cartomize as cm


def scene(write_raster, *, bands=(2,3,4,5,6,7), quality=True, date='20260817', tile='181063'):
    prefix=f'LC08_L2SP_{tile}_{date}_20260820_02_T1'
    paths=[write_raster(f'{prefix}_SR_B{i}.TIF',np.full((12,12),10000+i*1000,dtype='uint16'),nodata=0) for i in bands]
    if quality:paths.append(write_raster(f'{prefix}_QA_PIXEL.TIF',np.full((12,12),64,dtype='uint16'),nodata=0))
    return paths


def test_plan_preserves_swir_and_uses_requested_composition(write_raster,tmp_path):
    paths=scene(write_raster)
    plan=cm.plan_cartography(paths,data_kind='scenes',composition='swir',indices=['NDMI'],title='Carte',credits='Test')
    prepared=next(n for n in plan['nodes'] if n['operation']=='prepare')
    assert prepared['parameters']['bands']==['blue','green','red','nir','swir1','swir2']
    report=json.loads(cm.run_plan(plan,tmp_path/'planned',formats=['png'],dpi=72).read_text())
    scientific=report['results'][prepared['id']]
    with rasterio.open(scientific) as src:
        assert src.count==6 and src.descriptions[-2:]==('swir1','swir2')
        np.testing.assert_allclose(src.read(6,masked=True),17000*.0000275-.2,rtol=1e-6)
    rgb=next(n for n in plan['nodes'] if n['operation']=='composite')
    with rasterio.open(report['results'][rgb['id']]) as src:assert src.tags()['source_bands']=='(6, 4, 3)'
    assert json.loads(Path(report['quality_report']).read_text())['valid']
    assert Path(report['outputs'][0]).is_file()


def test_two_band_analysis_does_not_require_rgb(write_raster,tmp_path):
    plan=cm.plan_cartography(scene(write_raster,bands=(4,5)),data_kind='scenes',composition=None,indices=['NDVI'])
    assert not any(n['operation']=='composite' for n in plan['nodes'])
    assert next(n for n in plan['nodes'] if n['operation']=='prepare')['parameters']['bands']==['red','nir']
    assert cm.run_plan(plan,tmp_path/'two-bands',formats=['png'],dpi=72).is_file()


def test_scene_errors_are_caught_before_execution(write_raster):
    paths=scene(write_raster,quality=False)
    with pytest.raises(ValueError,match='QA/SCL'):cm.plan_cartography(paths,data_kind='scenes')
    with pytest.raises(ValueError,match='indices'):cm.plan_cartography(paths,data_kind='scenes',mask_clouds=False,band_order=['blue','green','red','nir'],indices=['NDMI'])
    with pytest.raises(ValueError,match='composition'):cm.plan_cartography(paths,data_kind='scenes',mask_clouds=False,band_order=['red','nir'])
    second=scene(write_raster,date='20260818',tile='182063')
    with pytest.raises(ValueError,match='Dates'):cm.plan_cartography(paths+second,data_kind='scenes',mask_clouds=False)


def test_direct_workflow_preserves_all_imported_bands(write_raster,tmp_path):
    product=cm.cartographic_workflow(scene(write_raster),tmp_path/'direct',formats=['png'],dpi=72)
    with rasterio.open(product.multiband) as src:assert src.descriptions==('blue','green','red','nir','swir1','swir2')


def test_landcover_assessment_proposes_classification_before_layout(write_raster):
    report=cm.assess_project(scene(write_raster),data_kind='scenes',goal='landcover')
    tools=[s['tool'] for s in report['steps']]
    assert tools.index('prepare')<tools.index('classification')<tools.index('project')<tools.index('mapping')
