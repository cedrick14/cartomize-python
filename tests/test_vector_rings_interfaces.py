"""G12 publication, terminal and plan contracts through the installed public API."""
from datetime import date
import hashlib
import json
from pathlib import Path
from threading import Event

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point, box

import cartomize as cm
from cartomize.cli import main
from cartomize.vector_io import write_geopackage
from cartomize.viewer_data import table_page


def sources(tmp_path):
    data = gpd.GeoDataFrame({'007': ['001', 'NA']},
        geometry=[Point(0, 0), Point(150, 0)], crs=32733)
    path = tmp_path / 'points.gpkg'
    write_geopackage(data, path, layer='123')
    return dict(data=str(path), distances=[50., 100., 250.], layer='123',
                id_field='007', mode='dissolved', area_unit='m2')


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def test_public_api_and_catalog_expose_rings_and_every_related_product():
    spec = next(row for row in cm.operation_catalog() if row['id'] == 'vector.buffer_rings')
    assert spec['output'] == 'vector' and spec['tool'] == 'vector'
    assert {field['name'] for field in spec['parameters'] if field['required']} == {'data', 'distances'}
    assert set(spec['products']) == {'primary', 'data', 'table', 'sources', 'balances', 'audit', 'summary'}
    assert callable(cm.buffer_rings) and cm.BufferRingsResult


@pytest.mark.parametrize('mode', ['dissolved', 'independent'])
def test_every_product_is_exactly_reopened_with_hashes_and_inputs_unchanged(tmp_path, mode):
    parameters = {**sources(tmp_path), 'mode': mode}
    original = Path(parameters['data']).read_bytes()
    expected = cm.buffer_rings(**parameters)
    progress = []
    destination = tmp_path / 'published'
    record = cm.execute_operation('vector.buffer_rings', parameters, destination,
                                  progress=lambda done, total: progress.append((done, total)))
    assert record['primary'] == record['products']['data']
    assert len(list(destination.iterdir())) == 9
    assert progress[-1] == (10000, 10000)
    assert all(a[0] <= b[0] for a, b in zip(progress, progress[1:]))
    for name in ('data', 'sources'):
        wanted = getattr(expected, name)
        saved = cm.read_file(record['products'][name], layer='features')
        pd.testing.assert_frame_equal(pd.DataFrame(saved.drop(columns='geometry')),
            pd.DataFrame(wanted.drop(columns='geometry')), check_dtype=False, check_exact=True)
        assert saved.crs == wanted.crs
        assert saved.geometry.to_wkb().tolist() == wanted.geometry.to_wkb().tolist()
    for name in ('table', 'balances'):
        saved = table_page(record['products'][name], size=100)['frame']
        pd.testing.assert_frame_equal(saved, getattr(expected, name), check_dtype=False, check_exact=True)
    assert cm.read_file(record['products']['sources'])['id_value'].tolist() == ['001', 'NA']
    audit = read_json(record['products']['audit'])
    assert audit['schema'] == 'cartomize.vector_rings.audit.v1'
    assert set(audit['tables']) == {'data', 'sources', 'table', 'balances'}
    for name, proof in audit['verified_files'].items():
        assert hashlib.sha256((destination / name).read_bytes()).hexdigest() == proof['sha256']
    assert record['metadata']['parameters']['mode'] == mode
    assert record['metadata']['input_features'] == 2
    for path in destination.glob('*.json'):
        assert '.cartomize-' not in path.read_text(encoding='utf-8')
    assert Path(parameters['data']).read_bytes() == original


def test_typed_source_labels_are_not_aggregated_or_converted_on_publication(tmp_path):
    values = ['001', 'NA', '', '1', 1, True, 2**64 - 1, date(2026, 10, 30)]
    data = gpd.GeoDataFrame({'code': pd.Series(values, dtype=object)},
        geometry=[Point(i * 30, 0) for i in range(len(values))], crs=32733)
    record = cm.execute_operation('vector.buffer_rings', dict(data=data, distances=[5, 10],
        id_field='code', mode='independent'), tmp_path / 'mixed')
    registry = cm.read_file(record['products']['sources'])
    assert registry['id_type'].tolist() == ['string'] * 4 + ['integer', 'boolean', 'integer', 'date']
    assert registry['id_value'].tolist() == ['001', 'NA', '', '1', '1', 'true', str(2**64 - 1), '2026-10-30']
    assert len(set(registry['source_id'])) == 8
    assert len(cm.read_file(record['products']['data'])) == 16
    assert data['code'].tolist() == values


@pytest.mark.parametrize('mode', ['dissolved', 'independent'])
def test_empty_sources_publish_complete_typed_products(tmp_path, mode):
    data = gpd.GeoDataFrame({'code': pd.Series(dtype='string')}, geometry=[], crs=32733)
    record = cm.execute_operation('vector.buffer_rings', dict(data=data, distances=[10, 20],
        id_field='code', mode=mode), tmp_path / mode)
    for name in ('data', 'sources'):
        reopened = cm.read_file(record['products'][name])
        assert reopened.empty and reopened.crs == data.crs
    for name in ('table', 'balances'):
        assert list(table_page(record['products'][name])['frame'].columns)
    assert read_json(record['products']['summary'])['totals']['union_ring_area'] == 0


@pytest.mark.parametrize('dedicated', [False, True])
def test_cli_uses_exact_layer_and_field_names_and_preserves_inputs(tmp_path, capsys, dedicated):
    parameters = sources(tmp_path)
    original = Path(parameters['data']).read_bytes()
    config = tmp_path / 'parameters.json'
    config.write_text(json.dumps(parameters), encoding='utf-8')
    destination = tmp_path / 'cli'
    args = (['buffer-rings', parameters['data'], str(destination), '--distances', '50', '100', '250',
             '--layer', '123', '--id-field', '007', '--mode', 'dissolved', '--area-unit', 'm2']
            if dedicated else ['process', 'vector.buffer_rings', str(config), str(destination)])
    assert main(args) == 0
    record = json.loads(capsys.readouterr().out)
    assert table_page(record['products']['table'])['frame']['upper_m'].tolist() == [50., 100., 250.]
    assert cm.read_file(record['products']['sources'])['id_value'].tolist() == ['001', 'NA']
    assert Path(parameters['data']).read_bytes() == original


def test_plan_chains_rings_into_g09_surface_tables(tmp_path):
    parameters = sources(tmp_path)
    classes = gpd.GeoDataFrame({'cover': ['Couverture simulée']},
                               geometry=[box(-300, -300, 500, 300)], crs=32733)
    classes_path = tmp_path / 'classes.gpkg'
    write_geopackage(classes, classes_path)
    plan = cm.processing_plan([
        dict(id='rings', operation='vector.buffer_rings', parameters=parameters),
        dict(id='surfaces', operation='vector.tabulate_area', parameters=dict(
            zones='@rings:data', classes=str(classes_path), zone_field='ring_id',
            class_field='cover', area_unit='m2')),
    ])
    manifest = Path(cm.run_plan(plan, tmp_path / 'plan'))
    result = read_json(manifest)
    rings = table_page(result['products']['rings']['table'])['frame']
    surfaces = table_page(result['products']['surfaces']['table'])['frame']
    assert surfaces['zone_value'].tolist() == rings['ring_id'].tolist()
    assert surfaces['area'].tolist() == pytest.approx(rings['area'].tolist(), abs=1e-6, rel=1e-10)
    assert surfaces['percentage'].tolist() == pytest.approx([100.] * 3)
    for product in result['products']['rings'].values():
        assert Path(product).is_file()
    assert '.cartomize-' not in manifest.read_text(encoding='utf-8')


def test_vector_readback_failure_rolls_back_the_whole_publication(tmp_path, monkeypatch):
    parameters = sources(tmp_path)
    import cartomize.vector_io as io
    writer = io.write_geopackage
    def fail(data, path, **kwargs):
        if Path(path).name == 'sources.gpkg':
            raise ValueError('Independent source readback mismatch')
        return writer(data, path, **kwargs)
    monkeypatch.setattr(io, 'write_geopackage', fail)
    with pytest.raises(ValueError, match='source readback'):
        cm.execute_operation('vector.buffer_rings', parameters, tmp_path / 'failed')
    assert not (tmp_path / 'failed').exists() and not list(tmp_path.glob('.cartomize-*'))


def test_changed_balance_csv_is_detected_before_publication(tmp_path, monkeypatch):
    parameters = sources(tmp_path)
    reader = pd.read_csv
    def changed(path, *args, **kwargs):
        result = reader(path, *args, **kwargs)
        if Path(path).name == 'balances.csv':
            result.loc[0, 'sum_ring_area'] += 1
        return result
    monkeypatch.setattr(pd, 'read_csv', changed)
    with pytest.raises(ValueError, match='readback.*balances'):
        cm.execute_operation('vector.buffer_rings', parameters, tmp_path / 'failed')
    assert not (tmp_path / 'failed').exists() and not list(tmp_path.glob('.cartomize-*'))


def test_cancellation_between_saved_products_rolls_back_and_preserves_sources(tmp_path):
    parameters = sources(tmp_path)
    original = Path(parameters['data']).read_bytes()
    event = Event()
    def stop_during_publication(done, total):
        if done > 8000:
            event.set()
    with pytest.raises(cm.ProcessingCancelled):
        cm.execute_operation('vector.buffer_rings', parameters, tmp_path / 'cancelled',
                             cancel=event, progress=stop_during_publication)
    assert not (tmp_path / 'cancelled').exists() and not list(tmp_path.glob('.cartomize-*'))
    assert Path(parameters['data']).read_bytes() == original


def test_multilayer_ambiguity_and_source_or_existing_destination_are_refused(tmp_path):
    parameters = sources(tmp_path)
    gpd.GeoDataFrame({'007': ['other']}, geometry=[Point(500, 0)], crs=32733).to_file(
        parameters['data'], layer='second')
    with pytest.raises(ValueError, match='layer|couche'):
        cm.execute_operation('vector.buffer_rings', {**parameters, 'layer': None}, tmp_path / 'ambiguous')
    assert not (tmp_path / 'ambiguous').exists()
    existing = tmp_path / 'existing'
    existing.mkdir()
    (existing / 'keep.txt').write_text('preserve me', encoding='utf-8')
    with pytest.raises(FileExistsError):
        cm.execute_operation('vector.buffer_rings', parameters, existing)
    with pytest.raises(ValueError, match='source'):
        cm.execute_operation('vector.buffer_rings', parameters, tmp_path)
    assert (existing / 'keep.txt').read_text(encoding='utf-8') == 'preserve me'


def test_plan_editor_roundtrip_keeps_numeric_named_source_fields_and_distance_list():
    pytest.importorskip('PySide6')
    from PySide6.QtWidgets import QApplication
    from cartomize.desktop_processing import OperationDialog
    app = QApplication.instance() or QApplication([])
    record = dict(id='rings', operation='vector.buffer_rings', parameters=dict(
        data='123', distances=[50, 100, 250], layer='007', id_field='0',
        metric_crs='EPSG:32733', mode='independent', include_input=True,
        quad_segs=32, area_unit='km2'))
    dialog = OperationDialog([], record)
    try:
        assert dialog.value()['parameters'] == record['parameters']
        assert 'balances' in [dialog.product.itemText(i) for i in range(dialog.product.count())]
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()
