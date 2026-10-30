"""G07 partitions remain exact through publication, CLI, plans and table viewing."""
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from threading import Event

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Point, box

import cartomize as cm
from cartomize.cli import main
from cartomize.vector_io import write_geopackage
from cartomize.viewer_data import table_page


def sources(tmp_path):
    data = gpd.GeoDataFrame({
        'code': pd.Series(['001', 'NA', '003', '004'], dtype='string'),
        'identifier': pd.Series([2**53 + 1, 2**53 + 2, 2**53 + 3, 2**53 + 4], dtype='Int64'),
        'active': pd.Series([True, True, False, None], dtype='boolean'),
        'visited': [date(2026, 1, 1), date(2026, 2, 1), None, date(2026, 3, 1)],
        'nullable_date': [None] * 4,
    }, geometry=[Point(1, 1), Point(5, 5), Point(2, 2), None], crs=32733)
    data.attrs['_cartomize_temporal_fields'] = {'visited': 'date', 'nullable_date': 'date'}
    source = tmp_path / 'survey.gpkg'
    write_geopackage(data, source, layer='1')
    mask = tmp_path / 'mask.gpkg'
    write_geopackage(gpd.GeoDataFrame(geometry=[box(0, 0, 3, 3)], crs=32733), mask, layer='2')
    return source, mask


def test_selection_catalog_and_public_api_are_connected():
    spec = next(row for row in cm.operation_catalog() if row['id'] == 'vector.extract_features')
    assert spec['output'] == 'vector' and spec['tool'] == 'vector'
    assert set(spec['products']) == {'primary', 'data', 'rejected', 'report', 'audit', 'summary'}
    assert {p['name'] for p in spec['parameters'] if p['required']} == {'data'}
    assert callable(cm.extract_features) and cm.VectorSelectionResult


def test_publication_has_exact_partition_native_dates_and_typed_audit(tmp_path):
    source, mask = sources(tmp_path)
    digests = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (source, mask)}
    destination = tmp_path / 'selection'
    result = cm.execute_operation('vector.extract_features', dict(data=str(source), layer='1',
        filters=[dict(field='active', comparison='eq', value=True)], mask=str(mask), mask_layer='2',
        id_field='identifier'), destination)
    assert result['primary'] == result['products']['data']
    for path in result['products'].values():
        assert Path(path).is_file() and Path(path).is_relative_to(destination)
    selected = cm.read_file(result['products']['data'])
    rejected = cm.read_file(result['products']['rejected'])
    assert selected['code'].tolist() == ['001']
    assert rejected['code'].tolist() == ['NA', '003', '004']
    for name in ('data', 'rejected'):
        with sqlite3.connect(result['products'][name]) as connection:
            types = {row[1]: row[2] for row in connection.execute('PRAGMA table_info(features)')}
            assert types['visited'] == types['nullable_date'] == 'DATE'
            assert connection.execute('SELECT identifier FROM features ORDER BY rowid').fetchall() == (
                [(2**53 + 1,)] if name == 'data' else [(2**53 + 2,), (2**53 + 3,), (2**53 + 4,)])
    report = table_page(result['products']['report'])['frame']
    assert report['source_row'].tolist() == [0, 1, 2, 3]
    assert report['source_id'].tolist() == [str(2**53 + i) for i in range(1, 5)]
    assert report['selected'].tolist() == [True, False, False, False]
    assert report['output_row'].dropna().tolist() == [0]
    assert report['rejected_row'].dropna().tolist() == [0, 1, 2]
    audit = json.loads(Path(result['products']['audit']).read_text(encoding='utf-8'))
    assert audit['records'][0]['source_id'] == {'type': 'integer', 'value': str(2**53 + 1)}
    assert audit['records'][0]['rejected_row'] is None
    summary = json.loads(Path(result['products']['summary']).read_text(encoding='utf-8'))
    assert (summary['input_features'], summary['output_features'], summary['rejected_features']) == (4, 1, 3)
    assert summary['combinations'] == dict(both=1, attributes_only=1, spatial_only=1, neither=1)
    for path in destination.rglob('*.json'):
        assert '.cartomize-' not in path.read_text(encoding='utf-8')
    assert {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in digests} == digests


@pytest.mark.parametrize('comparison,value,selected_count', [('not_null', None, 4), ('eq', 'absent', 0)])
def test_empty_partition_is_a_reopenable_typed_layer(tmp_path, comparison, value, selected_count):
    source, _ = sources(tmp_path)
    result = cm.execute_operation('vector.extract_features', dict(data=str(source),
        filters=[dict(field='code', comparison=comparison, value=value)]), tmp_path / 'selection')
    data = cm.read_file(result['products']['data'])
    rejected = cm.read_file(result['products']['rejected'])
    assert len(data) == selected_count and len(rejected) == 4 - selected_count
    assert list(data.columns) == list(rejected.columns)
    assert data.crs == rejected.crs
    for name in ('data', 'rejected'):
        with sqlite3.connect(result['products'][name]) as connection:
            types = {row[1]: row[2] for row in connection.execute('PRAGMA table_info(features)')}
            assert types['visited'] == types['nullable_date'] == 'DATE'


@pytest.mark.parametrize('dedicated', [False, True])
def test_cli_keeps_native_date_filter_and_source_bytes(tmp_path, capsys, dedicated):
    source, _ = sources(tmp_path)
    original = source.read_bytes()
    filters = [dict(field='visited', comparison='ge', value='2026-02-01')]
    config = tmp_path / 'criteria.json'
    payload = filters if dedicated else dict(data=str(source), layer='1', filters=filters, id_field='code')
    config.write_text(json.dumps(payload), encoding='utf-8')
    destination = tmp_path / 'selection'
    args = (['extract-features', str(source), str(destination), '--filters', str(config),
             '--layer', '1', '--id-field', 'code'] if dedicated else
            ['process', 'vector.extract_features', str(config), str(destination)])
    assert main(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert cm.read_file(result['products']['data'])['code'].tolist() == ['NA', '004']
    assert cm.read_file(result['products']['rejected'])['code'].tolist() == ['001', '003']
    assert table_page(result['products']['report'])['frame']['source_id'].tolist() == ['001', 'NA', '003', '004']
    assert source.read_bytes() == original


def test_plan_chains_both_selection_products(tmp_path):
    source, mask = sources(tmp_path)
    plan = cm.processing_plan([
        dict(id='extract', operation='vector.extract_features', parameters=dict(
            data=str(source), filters=[dict(field='active', comparison='eq', value=True)])),
        dict(id='inside', operation='vector.extract_features', parameters=dict(
            data='@extract:data', mask=str(mask))),
        dict(id='outside', operation='vector.extract_features', parameters=dict(
            data='@extract:rejected', filters=[dict(field='visited', comparison='is_null')])),
    ])
    path = cm.run_plan(plan, tmp_path / 'plan')
    result = json.loads(Path(path).read_text(encoding='utf-8'))
    assert cm.read_file(result['products']['inside']['data'])['code'].tolist() == ['001']
    assert cm.read_file(result['products']['outside']['data'])['code'].tolist() == ['003']
    for product in result['products']['extract'].values():
        assert Path(product).is_file()
    assert '.cartomize-' not in Path(path).read_text(encoding='utf-8')


def test_failure_verifying_second_partition_publishes_nothing(tmp_path, monkeypatch):
    source, _ = sources(tmp_path)
    original = source.read_bytes()
    import cartomize.vector_io as io
    writer = io.write_geopackage
    def fail_rejected(data, path, **kwargs):
        if Path(path).name == 'rejected.gpkg':
            raise ValueError('Independent rejected readback mismatch')
        return writer(data, path, **kwargs)
    monkeypatch.setattr(io, 'write_geopackage', fail_rejected)
    with pytest.raises(ValueError, match='rejected readback'):
        cm.execute_operation('vector.extract_features', dict(data=str(source),
            filters=[dict(field='code', comparison='eq', value='001')]), tmp_path / 'failed')
    assert not (tmp_path / 'failed').exists() and not list(tmp_path.glob('.cartomize-*'))
    assert source.read_bytes() == original


def test_cancellation_during_publication_rolls_back_both_partitions(tmp_path, monkeypatch):
    source, _ = sources(tmp_path)
    event = Event()
    import cartomize.vector_io as io
    writer = io.write_geopackage
    def cancel_after_first(data, path, **kwargs):
        result = writer(data, path, **kwargs)
        event.set()
        return result
    monkeypatch.setattr(io, 'write_geopackage', cancel_after_first)
    with pytest.raises(cm.ProcessingCancelled):
        cm.execute_operation('vector.extract_features', dict(data=str(source),
            filters=[dict(field='code', comparison='eq', value='001')]), tmp_path / 'cancelled', cancel=event)
    assert not (tmp_path / 'cancelled').exists() and not list(tmp_path.glob('.cartomize-*'))


def test_multilayer_ambiguity_and_existing_destination_are_refused(tmp_path):
    source, _ = sources(tmp_path)
    gpd.GeoDataFrame({'value': [1]}, geometry=[Point(0, 0)], crs=32733).to_file(source, layer='second')
    parameters = dict(data=str(source), filters=[dict(field='code', comparison='eq', value='001')])
    with pytest.raises(ValueError, match='layer|couche'):
        cm.execute_operation('vector.extract_features', parameters, tmp_path / 'ambiguous')
    assert not (tmp_path / 'ambiguous').exists()
    existing = tmp_path / 'existing'
    existing.mkdir()
    (existing / 'keep.txt').write_text('preserve me', encoding='utf-8')
    with pytest.raises(FileExistsError):
        cm.execute_operation('vector.extract_features', {**parameters, 'layer': '1'}, existing)
    assert (existing / 'keep.txt').read_text(encoding='utf-8') == 'preserve me'


def test_audit_preserves_multiindex_labels_and_native_date_identifiers(tmp_path):
    data = gpd.GeoDataFrame({'when': [date(2026, 1, 1), date(2026, 1, 2)]},
        geometry=[Point(1, 1), Point(2, 2)], crs=32733,
        index=pd.MultiIndex.from_tuples([('NA', 2**53 + 1), ('001', 2**53 + 1)]))
    result = cm.execute_operation('vector.extract_features', dict(data=data, id_field='when',
        filters=[dict(field='when', comparison='eq', value='2026-01-01')]), tmp_path / 'dates')
    audit = json.loads(Path(result['products']['audit']).read_text(encoding='utf-8'))
    assert audit['records'][0]['source_id'] == dict(type='date', value='2026-01-01')
    assert audit['records'][0]['source_index'] == dict(type='tuple', items=['NA', dict(type='integer', value=str(2**53 + 1))])


@pytest.mark.parametrize('value', [1, 9])
def test_partition_uses_full_source_schema_without_user_supplied_hints(tmp_path, value):
    data = gpd.GeoDataFrame({'flag': [1, 0],
        'date_value': pd.Series([date(2026, 1, 1), None], dtype=object),
        'bool_value': pd.Series([True, None], dtype=object),
        'time_value': pd.Series([pd.Timestamp('2026-01-01T12:34:56.123'), None], dtype=object),
    }, geometry=[Point(0, 0), Point(1, 1)], crs=32733)
    assert not data.attrs
    result = cm.execute_operation('vector.extract_features', dict(data=data,
        filters=[dict(field='flag', comparison='eq', value=value)]), tmp_path / 'partitions')
    for product in ('data', 'rejected'):
        with sqlite3.connect(result['products'][product]) as connection:
            types = {row[1]: row[2] for row in connection.execute('PRAGMA table_info(features)')}
            assert types['date_value'] == 'DATE'
            assert types['time_value'] == 'DATETIME'
            assert types['bool_value'] == 'BOOLEAN'
    assert not data.attrs


def test_plan_editor_roundtrip_keeps_numeric_looking_layer_names():
    pytest.importorskip('PySide6')
    from PySide6.QtWidgets import QApplication
    from cartomize.desktop_processing import OperationDialog
    app = QApplication.instance() or QApplication([])
    record = dict(id='extract', operation='vector.extract_features', parameters=dict(
        data='survey.gpkg', layer='1', mask='mask.gpkg', mask_layer='2', id_field='3',
        filters=[dict(field='4', comparison='in', value=['001', 'NA'])],
        attribute_match='any', combination='or', predicate='covered_by', invert=True))
    dialog = OperationDialog([], record)
    try:
        returned = dialog.value()['parameters']
        for key, value in record['parameters'].items():
            assert returned[key] == value
        assert 'rejected' in [dialog.product.itemText(i) for i in range(dialog.product.count())]
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()
