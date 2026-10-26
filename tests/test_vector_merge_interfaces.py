"""The merge contract survives CLI, plans, paged tables and downstream writes."""
from datetime import date
import json
from pathlib import Path
import sqlite3
from threading import Event

import geopandas as gpd
import numpy as np
import pandas as pd
from pyogrio.raw import write as raw_write
from pyproj import CRS
import pytest
import shapely
from shapely.geometry import Point

import cartomize as cm
from cartomize.cli import main


def sources(tmp_path, *, invalid=False):
    first, second = tmp_path / 'first.gpkg', tmp_path / 'second.gpkg'
    raw_write(first, geometry=shapely.to_wkb([Point(15, -4), Point(16, -5)]),
        fields=['identifier', 'code', 'survey_date', 'observed_at'],
        field_data=[np.array([2**53 + 1, 0], dtype='int64'),
                    np.array(['001', '002'], dtype=object),
                    np.array(['2024-02-29', 'NaT'], dtype='datetime64[D]'),
                    np.array(['2024-02-29T01:02:03.123', 'NaT'], dtype='datetime64[ms]')],
        field_mask=[np.array([False, True]), None, None, None],
        gdal_tz_offsets={'observed_at': np.array([100, 100], dtype=np.int32)},
        layer='survey', driver='GPKG', geometry_type='Point', crs=CRS(4326).to_wkt())
    gpd.GeoDataFrame({'identifier': ['bad' if invalid else str(2**60 + 3)],
                     'parcel': ['003'], 'survey_date': ['2025-01-01'],
                     'observed_at': ['2025-01-01T03:00:00.456+02:00']},
        geometry=[Point(17, -6)], crs=4326).to_file(second, layer='survey', index=False)
    identifiers = [layer['id'] for layer in cm.discover_vector_layers([first, second])]
    schema = {'identifier': 'int64', 'code': 'string', 'survey_date': 'date',
              'observed_at': 'datetime_utc', 'comment': {'type': 'string', 'default': ''}}
    mapping = {identifiers[1]: {'parcel': 'code'}}
    return [str(first), str(second)], schema, mapping


def json_file(path, document):
    path.write_text(json.dumps(document), encoding='utf-8')
    return str(path)


def assert_exact_attributes(path, layer):
    # SQLite supplies the oracle independently of Cartomize's typed reader.
    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            f'SELECT identifier, code, survey_date, observed_at, comment FROM "{layer}" ORDER BY rowid'
        ).fetchall()
        types = {row[1]: row[2].upper() for row in connection.execute(f'PRAGMA table_info("{layer}")')}
        storage = connection.execute(f'SELECT typeof(identifier) FROM "{layer}" ORDER BY rowid').fetchall()
    assert rows == [(2**53 + 1, '001', '2024-02-29', '2024-02-29T01:02:03.123Z', ''),
                    (None, '002', None, None, ''),
                    (2**60 + 3, '003', '2025-01-01', '2025-01-01T01:00:00.456Z', '')]
    assert storage == [('integer',), ('null',), ('integer',)]
    assert {name: types[name] for name in ('identifier', 'code', 'survey_date', 'observed_at')} == {
        'identifier': 'INTEGER', 'code': 'TEXT', 'survey_date': 'DATE', 'observed_at': 'DATETIME'}


def test_cli_inspection_mapping_and_merge_keep_exact_values_and_sources(tmp_path, capsys):
    paths, schema, mapping = sources(tmp_path)
    original = [Path(path).read_bytes() for path in paths]
    mappings = json_file(tmp_path / 'maps.json', mapping)
    assert main(['merge-options', *paths, '--field-maps', mappings]) == 0
    inspection = json.loads(capsys.readouterr().out)
    assert inspection['schema'] == 'cartomize.vector_merge_inspection.v1'
    assert inspection['feature_count'] == 3 and inspection['layer_count'] == 2
    assert 'parcel' not in inspection['suggested_schema']
    assert any(item['field'] == 'identifier' for item in inspection['conflicts'])
    assert main(['merge-layers', str(tmp_path / 'merged'), *paths,
                 '--field-maps', mappings, '--schema', json_file(tmp_path / 'schema.json', schema)]) == 0
    record = json.loads(capsys.readouterr().out)
    assert record['kind'] == 'vector'
    assert set(record['products']) == {'primary', 'data', 'manifest', 'report', 'issues'}
    assert record['primary'] == record['products']['data']
    assert all(Path(path).is_file() for path in record['products'].values())
    assert record['metadata']['source_count'] == 2
    assert record['metadata']['feature_count'] == 3
    assert_exact_attributes(record['primary'], 'features')
    assert [Path(path).read_bytes() for path in paths] == original


def test_generic_process_cli_exposes_same_merge_products(tmp_path, capsys):
    paths, schema, mapping = sources(tmp_path)
    parameters = json_file(tmp_path / 'parameters.json', dict(sources=paths, schema=schema, field_maps=mapping))
    assert main(['process', 'vector.merge_layers', parameters, str(tmp_path / 'processed')]) == 0
    record = json.loads(capsys.readouterr().out)
    document = json.loads(Path(record['products']['manifest']).read_text(encoding='utf-8'))
    assert document['schema'] == 'cartomize.vector_merge.v1'
    assert document['data'] == record['primary']
    assert document['conversion_error_count'] == 0
    assert_exact_attributes(record['primary'], 'features')


@pytest.mark.parametrize('reference', ['@merged:data', '@merged'])
def test_plan_buffer_retains_nullable_int64_dates_and_relocated_audits(tmp_path, reference):
    paths, schema, mapping = sources(tmp_path)
    plan = cm.processing_plan([
        dict(id='merged', operation='vector.merge_layers', parameters=dict(
            sources=paths, schema=schema, field_maps=mapping, target_crs=3857)),
        dict(id='buffered', operation='vector.buffer', parameters=dict(data=reference, distance=100)),
    ])
    manifest = cm.run_plan(plan, tmp_path / 'plan')
    document = json.loads(Path(manifest).read_text(encoding='utf-8'))
    products = document['products']['merged']
    merge = json.loads(Path(products['manifest']).read_text(encoding='utf-8'))
    assert merge['data'] == products['data']
    for name in ('data', 'report', 'issues', 'reprojection_manifest'):
        assert Path(merge[name]).is_file()
    projection = json.loads(Path(merge['reprojection_manifest']).read_text(encoding='utf-8'))
    assert Path(projection['report']).is_file()
    assert len(projection['layers']) == 2
    assert all(Path(layer['output']).is_file() for layer in projection['layers'])
    assert_exact_attributes(products['data'], 'features')
    assert_exact_attributes(document['results']['buffered'], 'result')
    buffered = cm.read_file(document['results']['buffered'])
    assert len(buffered) == 3 and buffered.geometry.is_valid.all()
    np.testing.assert_allclose(buffered.area, np.pi * 100**2, rtol=.01)
    assert not list(tmp_path.rglob('.cartomize-*'))
    for report in (tmp_path / 'plan').rglob('*.json'):
        assert '.cartomize-' not in report.read_text(encoding='utf-8')


@pytest.mark.parametrize('policy', ['error', 'null'])
def test_cli_conversion_policy_is_explicit_and_atomic(tmp_path, capsys, policy):
    paths, schema, mapping = sources(tmp_path, invalid=True)
    destination = tmp_path / 'merged'
    status = main(['merge-layers', str(destination), *paths,
        '--field-maps', json_file(tmp_path / 'maps.json', mapping),
        '--schema', json_file(tmp_path / 'schema.json', schema), '--on-conversion-error', policy])
    if policy == 'error':
        assert status != 0
        assert not destination.exists()
    else:
        assert status == 0
        record = json.loads(capsys.readouterr().out)
        assert record['metadata']['conversion_error_count'] == 1
        with sqlite3.connect(record['primary']) as connection:
            assert connection.execute('SELECT identifier FROM features ORDER BY rowid').fetchall() == [
                (2**53 + 1,), (None,), (None,)]
        issues = pd.read_csv(record['products']['issues'], keep_default_na=False)
        assert len(issues) == 1 and json.loads(issues['value'].iloc[0]) == 'bad'
        assert issues['action'].iloc[0] == 'null'
    assert not list(tmp_path.rglob('.cartomize-*'))


def test_cancellation_removes_nested_operation_products(tmp_path):
    paths, schema, mapping = sources(tmp_path)
    cancel = Event()
    def after_conversion(completed, total):
        if completed == total - 1:
            cancel.set()
    with pytest.raises(cm.ProcessingCancelled):
        cm.execute_operation('vector.merge_layers', dict(sources=paths, schema=schema,
            field_maps=mapping, target_crs=3857), tmp_path / 'cancelled',
            progress=after_conversion, cancel=cancel)
    assert not (tmp_path / 'cancelled').exists()
    assert not list(tmp_path.rglob('.cartomize-*'))


def test_public_reader_and_paged_table_keep_integer_null_and_temporal_values(tmp_path):
    from cartomize.viewer_data import table_page
    paths, schema, mapping = sources(tmp_path)
    result = cm.merge_layers(paths, tmp_path / 'merged', schema=schema, field_maps=mapping)
    data = cm.read_file(result.data)
    assert int(data.identifier.iloc[0]) == 2**53 + 1
    assert pd.isna(data.identifier.iloc[1])
    assert int(data.identifier.iloc[2]) == 2**60 + 3
    assert data.survey_date.iloc[0] == date(2024, 2, 29)
    assert data.observed_at.iloc[2] == pd.Timestamp('2025-01-01T01:00:00.456Z')
    first, second = table_page(result.data, size=1), table_page(result.data, offset=1, size=2)
    assert first['more'] and not second['more']
    assert int(first['frame'].identifier.iloc[0]) == 2**53 + 1
    assert pd.isna(second['frame'].identifier.iloc[0])
    assert int(second['frame'].identifier.iloc[1]) == 2**60 + 3


def test_table_model_displays_full_large_identifier_and_blank_null(tmp_path):
    pytest.importorskip('PySide6')
    from PySide6.QtCore import Qt
    from cartomize.desktop_tables import FrameModel
    from cartomize.viewer_data import table_page
    paths, schema, mapping = sources(tmp_path)
    result = cm.merge_layers(paths, tmp_path / 'merged', schema=schema, field_maps=mapping)
    frame = table_page(result.data)['frame'][['identifier']]
    model = FrameModel(frame)
    assert model.data(model.index(0, 0)) == str(2**53 + 1)
    assert model.data(model.index(1, 0)) == ''
    assert model.data(model.index(2, 0)) == str(2**60 + 3)
    assert model.data(model.index(0, 0), Qt.ItemDataRole.UserRole) == 2**53 + 1
    assert model.data(model.index(1, 0), Qt.ItemDataRole.UserRole) is None


def test_operation_catalog_advertises_merge_types_policies_and_products():
    operation = next(item for item in cm.operation_catalog() if item['id'] == 'vector.merge_layers')
    assert operation['output'] == 'vector' and operation['tool'] == 'vector'
    assert set(operation['products']) == {'primary', 'data', 'manifest', 'report', 'issues'}
    parameters = {item['name']: item for item in operation['parameters']}
    assert parameters['sources']['required']
    assert {'schema', 'field_maps', 'target_crs', 'reprojection_options'} <= parameters.keys()
    assert {key: parameters[key]['default'] for key in
            ('conversion_errors', 'missing_fields', 'extra_fields')} == {
                'conversion_errors': 'error', 'missing_fields': 'null', 'extra_fields': 'error'}
