"""The same image diagnostic and preparation settings across public entry points."""
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

import cartomize as cm
from cartomize.cli import main
from cartomize.processing import operation_spec


def inputs(write_raster, tmp_path):
    scenes = []
    for index, x in enumerate([300000, 300020]):
        data = np.full((2, 2, 2), index + 1, dtype='float32')
        path = write_raster(f'scene_{index}.tif', data,
                            transform=from_origin(x, 9500000, 10, 10))
        scenes.append(dict(scene_id=f'S{index}', sensor='custom', acquired='2026-10-01',
            bands={'red': {'path': path.name, 'index': 1},
                   'nir': {'path': path.name, 'index': 2}}))
    manifest = tmp_path / 'scenes.json'
    manifest.write_text(json.dumps(dict(schema='cartomize.scenes.v1', scenes=scenes)))
    aoi = tmp_path / 'zone.gpkg'
    gpd.GeoDataFrame(geometry=[box(300000, 9499980, 300040, 9500000)], crs=32733).to_file(aoi)
    return manifest, aoi


def test_audit_python_cli_and_registered_chain_agree(write_raster, tmp_path, capsys):
    manifest, aoi = inputs(write_raster, tmp_path)
    direct = cm.audit_imagery(manifest, tmp_path/'direct', aoi=aoi,
                             band_order=['red', 'nir'], mask_clouds=False)
    assert main(['audit-imagery', str(manifest), str(tmp_path/'cli'), '--aoi', str(aoi),
                 '--bands', 'red,nir', '--without-cloud-mask']) == 0
    cli = json.loads(capsys.readouterr().out)
    parameters = dict(sources=str(manifest), aoi=str(aoi), band_order=['red', 'nir'],
                      mask_clouds=False, resolution=10.)
    plan = cm.processing_plan([dict(id='coverage', operation='imagery.audit', parameters=parameters)])
    run = json.loads(cm.run_plan(plan, tmp_path/'chain').read_text())
    registered = json.loads(Path(run['results']['coverage']).read_text())
    for report in (direct.report, cli, registered):
        assert report['usable_percent'] == 100
        assert report['aoi_pixels'] == 8
        assert report['recommended_action'] == 'mosaic'
        assert report['recommended_scene_ids'] == ['S0', 'S1']
    for name, expected_bands in [('coverage', 3), ('gaps', 1)]:
        with rasterio.open(run['products']['coverage'][name]) as src:
            assert src.count == expected_bands
    assert '.cartomize-' not in Path(run['results']['coverage']).read_text()


def test_prepare_operator_preserves_expert_grid_and_provenance(write_raster, tmp_path):
    manifest, aoi = inputs(write_raster, tmp_path)
    result = cm.execute_operation('prepare', dict(sources=str(manifest), aoi=str(aoi),
        band_order=['red', 'nir'], target_crs='EPSG:32733', resolution=5., overlap='last',
        resampling='nearest', mask_clouds=False, mask_saturation=False,
        all_touched=True, max_pixels=100), tmp_path/'prepared')
    with rasterio.open(result['primary']) as src:
        assert src.res == (5., 5.)
        assert src.shape == (4, 8)
        assert src.tags()['overlap'] == 'last'
        np.testing.assert_equal(src.read(1)[:, :4], 1)
        np.testing.assert_equal(src.read(1)[:, 4:], 2)
    assert Path(result['products']['result_source_index']).is_file()
    required = {'resolution', 'overlap', 'resampling', 'mask_saturation', 'all_touched', 'max_pixels'}
    assert required <= {p['name'] for p in operation_spec('prepare')['parameters']}


def test_cli_audit_requires_aoi_and_reports_invalid_quality(write_raster, tmp_path, capsys):
    manifest, aoi = inputs(write_raster, tmp_path)
    destination = tmp_path/'missing_quality'
    assert main(['audit-imagery', str(manifest), str(destination), '--aoi', str(aoi)]) == 2
    assert 'quality' in capsys.readouterr().err.lower()
    assert not destination.exists()
