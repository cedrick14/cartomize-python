"""The automatic coverage policy is identical in scripts, commands and plans."""
import importlib
import json
from functools import wraps
from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

import cartomize as cm
from cartomize.cli import main
from cartomize.processing import operation_spec


def _inputs(write_raster, tmp_path, *, complete=True):
    scenes = []
    for number, x in enumerate((300000, 300020) if complete else (300000,)):
        transform = from_origin(x, 9500000, 10, 10)
        source = write_raster(f'spectrum_{number}.tif',
            np.array([np.full((2, 2), 1000), np.full((2, 2), 3000)], dtype='int16'),
            transform=transform)
        quality = write_raster(f'quality_{number}.tif', np.ones((2, 2), dtype='uint8'),
                               transform=transform, nodata=255)
        scenes.append(dict(scene_id=f'S{number}', sensor='custom', level='L2',
            acquired='2026-10-01', quality=quality.name, quality_kind='valid_mask',
            bands={name: dict(path=source.name, index=index, scale=.0002,
                             unit='reflectance')
                   for index, name in enumerate(('red', 'nir'), 1)}))
    manifest = tmp_path / 'scenes.json'
    manifest.write_text(json.dumps(dict(schema='cartomize.scenes.v1', scenes=scenes)),
                        encoding='utf-8')
    aoi = tmp_path / 'zone.gpkg'
    gpd.GeoDataFrame(geometry=[box(300000, 9499980, 300040, 9500000)],
                     crs=32733).to_file(aoi)
    return manifest, aoi


def _parameters(manifest, aoi):
    return dict(sources=str(manifest), aoi=str(aoi), band_order=['red', 'nir'])


def _assert_product(path):
    with rasterio.open(path) as src:
        assert src.shape == (2, 4)
        assert src.descriptions == ('red', 'nir')
        np.testing.assert_allclose(src.read(1), .2)
        np.testing.assert_allclose(src.read(2), .6)
        assert src.dataset_mask().min() == 255


def test_automatic_api_cli_and_operator_produce_same_calibrated_grid(write_raster, tmp_path, capsys):
    manifest, aoi = _inputs(write_raster, tmp_path)
    direct = cm.preprocess_imagery(manifest, tmp_path/'api', aoi=aoi,
                                   band_order=['red', 'nir'])
    assert main(['preprocess-imagery', str(manifest), str(tmp_path/'cli'),
                 '--aoi', str(aoi), '--bands', 'red,nir']) == 0
    cli = json.loads(capsys.readouterr().out)
    registered = cm.execute_operation('imagery.preprocess', _parameters(manifest, aoi),
                                      tmp_path/'registered')
    document = json.loads(Path(registered['primary']).read_text(encoding='utf-8'))
    for report in (direct.report, cli, document):
        assert report['status'] == 'complete'
        assert report['threshold_met'] is True
        assert report['coverage_threshold'] == 100
        assert report['allow_partial'] is False
        audit = json.loads(Path(report['audit']).read_text(encoding='utf-8'))
        assert audit['usable_percent'] == 100
        assert audit['recommended_action'] == 'mosaic'
        assert audit['recommended_scene_ids'] == ['S0', 'S1']
        _assert_product(report['products'][0]['multiband'])
    assert {'audit', 'coverage', 'gaps', 'multiband', 'source_index'} <= registered['products'].keys()
    assert registered['metadata']['status'] == 'complete'


def test_automatic_named_products_feed_an_actual_ndvi_chain(write_raster, tmp_path):
    manifest, aoi = _inputs(write_raster, tmp_path)
    plan = cm.processing_plan([
        dict(id='prepared', operation='imagery.preprocess', parameters=_parameters(manifest, aoi)),
        dict(id='ndvi', operation='indices', parameters=dict(source='@prepared:multiband', indices=['NDVI'])),
    ])
    output = cm.run_plan(plan, tmp_path/'chain')
    report = json.loads(output.read_text(encoding='utf-8'))
    with rasterio.open(report['results']['ndvi']) as src:
        np.testing.assert_allclose(src.read(1), .5, rtol=1e-6)
        assert src.dataset_mask().min() == 255
    for name in ('audit', 'coverage', 'gaps', 'preparation', 'multiband', 'source_index', 'report'):
        assert Path(report['products']['prepared'][name]).is_file()
    for path in (tmp_path/'chain').rglob('*.json'):
        assert '.cartomize-' not in path.read_text(encoding='utf-8')


@pytest.mark.parametrize('entry', ['api', 'operation', 'plan'])
def test_coverage_refusal_keeps_diagnostics_beyond_atomic_rollback(
        write_raster, tmp_path, monkeypatch, entry):
    manifest, aoi = _inputs(write_raster, tmp_path, complete=False)
    from cartomize.imagery_automatic import ImageryCoverageError
    destination = tmp_path / entry
    later_calls = []
    indices_module = importlib.import_module('cartomize.indices')
    @wraps(indices_module.spectral_indices)
    def unexpected_index(*args, **kwargs):
        later_calls.append(True)
        raise AssertionError('A blocked preparation must stop its dependent steps.')
    monkeypatch.setattr(indices_module, 'spectral_indices', unexpected_index)
    with pytest.raises(ImageryCoverageError) as caught:
        if entry == 'api':
            cm.preprocess_imagery(manifest, destination, aoi=aoi, band_order=['red', 'nir'])
        elif entry == 'operation':
            cm.execute_operation('imagery.preprocess', _parameters(manifest, aoi), destination)
        else:
            cm.run_plan(cm.processing_plan([
                dict(id='prepared', operation='imagery.preprocess', parameters=_parameters(manifest, aoi)),
                dict(id='ndvi', operation='indices', parameters=dict(source='@prepared:multiband', indices=['NDVI'])),
            ]), destination)
    error = caught.value
    assert not destination.exists()
    assert not later_calls
    assert error.report['usable_percent'] == 50
    assert error.manifest.is_file()
    assert '.cartomize-' not in str(error.manifest)
    assert error.manifest.parent.parent == tmp_path
    assert error.diagnostic.coverage.is_file() and error.diagnostic.gaps.is_file()
    assert (error.manifest.parent/'preprocessing.json').is_file()
    with rasterio.open(error.diagnostic.gaps) as src:
        assert np.count_nonzero(src.read(1) == 1) == 4
    for path in error.manifest.parent.rglob('*.json'):
        assert '.cartomize-' not in path.read_text(encoding='utf-8')


def test_cli_failure_returns_actionable_diagnostic_and_nonzero_exit(write_raster, tmp_path, capsys):
    manifest, aoi = _inputs(write_raster, tmp_path, complete=False)
    destination = tmp_path / 'blocked'
    assert main(['preprocess-imagery', str(manifest), str(destination),
                 '--aoi', str(aoi), '--bands', 'red,nir']) == 2
    captured = capsys.readouterr()
    assert not captured.out
    error = json.loads(captured.err)
    assert error['error'] == 'insufficient_coverage'
    assert error['report']['usable_percent'] == 50
    for name in ('diagnostic', 'coverage', 'gaps'):
        assert Path(error[name]).is_file()
    assert not destination.exists()


@pytest.mark.parametrize('flags,threshold_met', [(['--allow-partial'], False),
                                               (['--coverage-threshold', '50'], True)])
def test_partial_cli_output_is_explicit_and_keeps_real_missing_pixels(
        write_raster, tmp_path, capsys, flags, threshold_met):
    manifest, aoi = _inputs(write_raster, tmp_path, complete=False)
    assert main(['preprocess-imagery', str(manifest), str(tmp_path/'partial'),
                 '--aoi', str(aoi), '--bands', 'red,nir', *flags]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['status'] == 'partial'
    assert report['threshold_met'] is threshold_met
    with rasterio.open(report['products'][0]['multiband']) as src:
        assert src.shape == (2, 4)
        np.testing.assert_array_equal(src.read_masks(1)[:, :2], 255)
        np.testing.assert_array_equal(src.read_masks(1)[:, 2:], 0)


def test_requested_separate_bands_are_named_without_a_removed_multiband(write_raster, tmp_path):
    manifest, aoi = _inputs(write_raster, tmp_path)
    result = cm.execute_operation('imagery.preprocess',
        {**_parameters(manifest, aoi), 'multiband': False, 'separate_bands': True}, tmp_path/'bands')
    assert 'multiband' not in result['products']
    for number, expected in ((1, .2), (2, .6)):
        with rasterio.open(result['products'][f'band_{number}']) as src:
            assert src.count == 1 and src.shape == (2, 4)
            np.testing.assert_allclose(src.read(1), expected)


def test_operation_declares_required_aoi_coverage_policy_and_outputs():
    spec = operation_spec('imagery.preprocess')
    parameters = {row['name']: row for row in spec['parameters']}
    assert parameters['aoi']['required'] is True
    assert parameters['coverage_threshold']['default'] == 100
    assert parameters['allow_partial']['default'] is False
    assert {'catalog', 'mask_clouds', 'band_order', 'resolution', 'target_crs'} <= parameters.keys()
    assert {'coverage', 'gaps', 'multiband', 'source_index'} <= set(spec['products'])
    with pytest.raises(ValueError):
        cm.processing_plan([dict(id='missing_aoi', operation='imagery.preprocess',
                                 parameters={'sources': 'scenes.json'})])


def test_cartographic_plan_with_aoi_uses_automatic_scientific_product(write_raster, tmp_path):
    manifest, aoi = _inputs(write_raster, tmp_path)
    plan = cm.plan_cartography([manifest], data_kind='scenes', aoi=str(aoi),
        composition=None, indices=['NDVI'], title='Couverture contrôlée', credits='Référence synthétique',
        processing_steps=[dict(id='red', operation='calculate',
            parameters=dict(expression='r', inputs={'r': ['@scientific', 1]}))])
    prepared = next(node for node in plan['nodes'] if node['operation'] == 'process'
                    and node['parameters']['operator'] == 'imagery.preprocess')
    assert prepared['parameters']['arguments']['coverage_threshold'] == 100
    assert prepared['parameters']['arguments']['allow_partial'] is False
    reference = '@'+prepared['id']+':multiband'
    ndvi = next(node for node in plan['nodes'] if node['operation'] == 'indices')
    red = next(node for node in plan['nodes'] if node['id'] == 'red')
    assert ndvi['parameters']['source'] == reference
    assert red['parameters']['arguments']['inputs']['r'][0] == reference
    report = json.loads(cm.run_plan(plan, tmp_path/'map', formats=['png'], dpi=72).read_text(encoding='utf-8'))
    with rasterio.open(report['results'][ndvi['id']]) as src:
        np.testing.assert_allclose(src.read(1), .5, rtol=1e-6)
    with rasterio.open(report['results']['red']) as src:
        np.testing.assert_allclose(src.read(1), .2)
    assert Path(report['outputs'][0]).is_file()


def _add_rgb_roles(manifest):
    document = json.loads(manifest.read_text(encoding='utf-8'))
    for scene in document['scenes']:
        scene['bands']['blue'] = dict(scene['bands']['red'])
        scene['bands']['green'] = dict(scene['bands']['red'])
    manifest.write_text(json.dumps(document), encoding='utf-8')


@pytest.mark.parametrize('entry', ['planned_map', 'direct_map'])
def test_cartographic_paths_stop_before_export_on_incomplete_aoi(write_raster, tmp_path, monkeypatch, entry):
    manifest, aoi = _inputs(write_raster, tmp_path, complete=False)
    _add_rgb_roles(manifest)
    exported = []
    def unexpected_export(*args, **kwargs):
        exported.append(True)
        raise AssertionError('An incomplete scene must not reach the map export.')
    monkeypatch.setattr(cm.Map, 'export', unexpected_export)
    destination = tmp_path / entry
    from cartomize.imagery_automatic import ImageryCoverageError
    with pytest.raises(ImageryCoverageError) as caught:
        if entry == 'planned_map':
            plan = cm.plan_cartography([manifest], data_kind='scenes', aoi=str(aoi))
            cm.run_plan(plan, destination, formats=['png'], dpi=72)
        else:
            cm.cartographic_workflow(manifest, destination, aoi=aoi, formats=['png'], dpi=72)
    assert not exported and not destination.exists()
    assert caught.value.manifest.is_file()
    assert '.cartomize-' not in str(caught.value.manifest)


def test_direct_cartographic_result_keeps_reopenable_automatic_paths(write_raster, tmp_path):
    manifest, aoi = _inputs(write_raster, tmp_path)
    _add_rgb_roles(manifest)
    product = cm.cartographic_workflow(manifest, tmp_path/'direct_map', aoi=aoi,
        formats=['png'], dpi=72, title='Mosaïque contrôlée', credits='Référence synthétique')
    document = json.loads(product.manifest.read_text(encoding='utf-8'))
    assert document['coverage_status'] == 'complete'
    assert document['threshold_met'] is True
    assert product.multiband == product.directory/document['multiband']
    for key in ('multiband', 'composite', 'preparation', 'preprocessing'):
        assert (product.directory/document[key]).is_file()
    assert product.maps[0].is_file()
    for path in product.directory.rglob('*.json'):
        assert '.cartomize-' not in path.read_text(encoding='utf-8')


def test_planned_partial_map_exposes_coverage_and_reopens_its_sources(write_raster, tmp_path):
    manifest, aoi = _inputs(write_raster, tmp_path, complete=False)
    _add_rgb_roles(manifest)
    plan = cm.plan_cartography([manifest], data_kind='scenes', aoi=str(aoi),
        allow_partial=True, title='Couverture partielle acceptée', credits='Référence synthétique')
    output = cm.run_plan(plan, tmp_path/'partial_map', formats=['png'], dpi=72)
    report = json.loads(output.read_text(encoding='utf-8'))
    assert report['coverage_status'] == 'partial'
    preparation = next(iter(report['imagery_preprocessing'].values()))
    assert preparation['status'] == 'partial'
    assert preparation['usable_percent'] == 50
    assert preparation['threshold_met'] is False
    assert preparation['allow_partial'] is True
    assert Path(preparation['manifest']).is_file() and Path(preparation['audit']).is_file()
    reopened = cm.Map.load(report['map_file'])
    assert reopened.layers
    assert all('.cartomize-' not in str(layer.data) for layer in reopened.layers)
    for path in (tmp_path/'partial_map').rglob('*.json'):
        assert '.cartomize-' not in path.read_text(encoding='utf-8')
