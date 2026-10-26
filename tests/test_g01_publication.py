"""G01 publications preserve values and WKB or fail as one atomic bundle."""
from contextlib import closing
import csv
import json
import sqlite3
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from pyogrio.raw import write as raw_write
from pyproj import CRS
import pytest
import shapely
from shapely.geometry import GeometryCollection, LinearRing, LineString, MultiPolygon, Point, Polygon, box

import cartomize as cm
from cartomize.viewer_data import table_page


HAS_M = hasattr(shapely, 'has_m') and tuple(shapely.geos_version) >= (3, 12, 0)


def geopackage(path):
    """Read SQL values and decode GPKG blobs without the dataframe adapter."""
    with closing(sqlite3.connect(path)) as connection:
        geometry_name, kind, z, m = connection.execute(
            "SELECT column_name,geometry_type_name,z,m FROM gpkg_geometry_columns WHERE table_name='features'"
        ).fetchone()
        fields = connection.execute('PRAGMA table_info(features)').fetchall()
        attributes = [field[1] for field in fields if field[1] != geometry_name and not field[5]]
        columns = ','.join('"' + name.replace('"', '""') + '"' for name in attributes)
        values = connection.execute('SELECT ' + columns + ' FROM features').fetchall() if columns else []
        blobs = connection.execute('SELECT "' + geometry_name.replace('"', '""') + '" FROM features').fetchall()
    shapes = []
    for (blob,) in blobs:
        if blob is None:
            shapes.append(None)
            continue
        assert blob[:2] == b'GP'
        envelope_code = (blob[3] >> 1) & 7
        offset = 8 + {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}[envelope_code]
        shapes.append(shapely.from_wkb(blob[offset:]))
    return {'types': {field[1]: field[2].upper() for field in fields},
            'rows': [dict(zip(attributes, row)) for row in values],
            'geometries': shapes, 'geometry_schema': (kind, z, m)}


def wkb_values(geometries):
    return [None if geometry is None else geometry.wkb for geometry in geometries]


def assert_no_publication(tmp_path, destination):
    assert not destination.exists()
    assert not list(tmp_path.glob('.cartomize-*'))


@pytest.fixture
def typed_source(tmp_path):
    path = tmp_path / 'typed.gpkg'
    shapes = [Polygon([(0, 0), (2, 2), (0, 2), (2, 0), (0, 0)]), box(3, 0, 5, 2), None]
    raw_write(path, geometry=shapely.to_wkb(shapes), field_data=[
        np.array([2**60 + 3, 2**60 + 5, 2**60 + 7], dtype='int64'),
        np.array([2**60 + 3, 0, 2**53 + 1], dtype='int64'),
        np.array(['001', '002', '003'], dtype=object),
        np.array(['2024-02-29', '1970-01-01', '2024-03-02'], dtype='datetime64[D]'),
        np.array(['2024-02-29T10:30:00.123', '1970-01-01', '2024-03-02T10:00:00.250'], dtype='datetime64[ms]'),
        np.array([True, False, False], dtype=bool), np.array([8, 8, 8], dtype='int64'),
    ], fields=['identifier', 'nullable_bigint', 'code', 'survey_date', 'observed_at', 'approved', 'fid'],
        field_mask=[None, np.array([False, True, False]), None,
                    np.array([False, True, False]), np.array([False, True, False]),
                    np.array([False, True, False]), None],
        layer='features', driver='GPKG', geometry_type='Unknown', promote_to_multi=False,
        crs=CRS(32733).to_wkt(), gdal_tz_offsets={'observed_at': np.full(3, 100, dtype='int32')},
        layer_options={'FID': 'internal_fid', 'GEOMETRY_NAME': 'geom', 'SPATIAL_INDEX': 'NO'})
    return path


@pytest.mark.parametrize('operation', ['audit_geometries', 'repair_geometries'])
def test_bundle_keeps_exact_typed_attributes_original_layer_and_business_identifiers(tmp_path, typed_source, operation):
    original_bytes = typed_source.read_bytes()
    original = geopackage(typed_source)
    parameters = {'data': str(typed_source), 'id_field': 'identifier'}
    if operation == 'repair_geometries':
        parameters['missing'] = 'drop'
    record = cm.execute_operation('vector.' + operation, parameters, tmp_path / 'result')
    products = record['products']
    assert {'primary', 'data', 'before', 'issues', 'rejected', 'report', 'summary'} <= products.keys()
    assert all(Path(path).is_file() for path in products.values())
    expected_types = {'identifier': 'INTEGER', 'nullable_bigint': 'INTEGER', 'code': 'TEXT',
                      'survey_date': 'DATE', 'observed_at': 'DATETIME', 'approved': 'BOOLEAN', 'fid': 'INTEGER'}
    layers = {name: geopackage(products[name]) for name in ('before', 'data', 'rejected', 'issues')}
    for name in ('before', 'data', 'rejected'):
        assert {key: layers[name]['types'][key] for key in expected_types} == expected_types
    assert layers['before']['rows'] == original['rows']
    assert wkb_values(layers['before']['geometries']) == wkb_values(original['geometries'])
    if operation == 'audit_geometries':
        assert layers['data']['rows'] == original['rows']
        assert wkb_values(layers['data']['geometries']) == wkb_values(original['geometries'])
        assert layers['rejected']['rows'] == []
    else:
        assert layers['data']['rows'] == original['rows'][:2]
        assert layers['rejected']['rows'] == original['rows'][2:]
        assert layers['rejected']['geometries'] == [None]
        assert layers['data']['geometries'][0].geom_type == 'MultiPolygon'
        assert layers['data']['geometries'][0].area == 2.
        assert layers['data']['geometries'][1].wkb == original['geometries'][1].wkb
    assert [row['feature_id'] for row in layers['issues']['rows']] == [2**60 + 3, 2**60 + 7]
    with open(products['report'], encoding='utf-8-sig', newline='') as handle:
        report = list(csv.DictReader(handle))
    assert [row['feature_id'] for row in report] == [str(2**60 + value) for value in (3, 5, 7)]
    viewed = table_page(products['report'])['frame']
    assert viewed.feature_id.tolist() == [str(2**60 + value) for value in (3, 5, 7)]
    assert str(viewed.source_row.dtype) == 'Int64'
    if operation == 'repair_geometries':
        assert [row['output_row'] for row in report] == ['0', '1', '']
        assert [row['rejected_row'] for row in report] == ['', '', '0']
    summary = json.loads(Path(products['summary']).read_text())
    assert summary['input_features'] == 3
    assert summary['output_features'] == (3 if operation == 'audit_geometries' else 2)
    assert typed_source.read_bytes() == original_bytes


def test_audit_never_promotes_polygon_or_changes_xy_and_xyz_features(tmp_path):
    shapes = [box(0, 0, 2, 2), MultiPolygon([box(4, 0, 6, 2)]), Point(8, 0), Point(9, 0, 7.5)]
    source = gpd.GeoDataFrame({'identifier': ['A', 'B', 'C', 'D']}, geometry=shapes, crs=32733)
    result = cm.execute_operation('vector.audit_geometries',
        {'data': source, 'id_field': 'identifier'}, tmp_path / 'audit')
    for name in ('before', 'data'):
        assert wkb_values(geopackage(result['products'][name])['geometries']) == wkb_values(shapes)


def test_original_business_geometry_attribute_survives_publication(tmp_path):
    path = tmp_path / 'business_geometry.gpkg'
    shapes = [Point(0, 0), Point(1, 1)]
    raw_write(path, geometry=shapely.to_wkb(shapes),
        field_data=[np.array(['001', '002'], dtype=object), np.array(['label A', 'label B'], dtype=object)],
        fields=['identifier', 'geometry'], layer='features', driver='GPKG', geometry_type='Point',
        crs=CRS(32733).to_wkt(), layer_options={'GEOMETRY_NAME': 'geom'})
    original = path.read_bytes()
    result = cm.execute_operation('vector.audit_geometries',
        {'data': str(path), 'id_field': 'identifier'}, tmp_path / 'audit')
    for name in ('before', 'data'):
        layer = geopackage(result['products'][name])
        assert [row['geometry'] for row in layer['rows']] == ['label A', 'label B']
        assert wkb_values(layer['geometries']) == wkb_values(shapes)
    assert path.read_bytes() == original


def test_paginated_report_viewer_keeps_zero_prefix_empty_and_na_looking_labels(tmp_path):
    labels = ['001', 'NA', '', str(2**60 + 3)]
    source = gpd.GeoDataFrame({'identifier': labels}, geometry=[Point(i, 0) for i in range(4)], crs=32733)
    result = cm.execute_operation('vector.audit_geometries',
        {'data': source, 'id_field': 'identifier'}, tmp_path / 'audit')
    first = table_page(result['products']['report'], size=2)
    second = table_page(result['products']['report'], offset=2, size=2)
    assert first['more'] and not second['more']
    assert first['frame'].feature_id.tolist() == labels[:2]
    assert second['frame'].feature_id.tolist() == labels[2:]
    assert first['frame'].output_row.tolist() == [0, 1]
    assert second['frame'].output_row.tolist() == [2, 3]
    assert second['frame'].rejected_row.isna().all()
    assert second['frame'].duplicate_of_row.isna().all()
    assert str(second['frame'].duplicate_of_row.dtype) == 'Int64'


def test_mixed_dimension_collection_cannot_acquire_invented_z_in_a_published_bundle(tmp_path):
    geometry = GeometryCollection([Point(0, 0), Point(1, 1, 2)])
    source = gpd.GeoDataFrame({'identifier': ['mixed']}, geometry=[geometry], crs=32733)
    destination = tmp_path / 'audit'
    with pytest.raises(ValueError):
        cm.execute_operation('vector.audit_geometries', {'data': source, 'id_field': 'identifier'}, destination)
    assert source.geometry.iloc[0].wkb == geometry.wkb
    assert_no_publication(tmp_path, destination)


def test_nested_linear_ring_cannot_become_line_string_in_published_before_or_data(tmp_path):
    ring = LinearRing([(0, 0), (1, 0), (1, 1), (0, 0)])
    geometry = GeometryCollection([GeometryCollection([ring])])
    source = gpd.GeoDataFrame({'identifier': ['ring']}, geometry=[geometry], crs=32733)
    destination = tmp_path / 'audit'
    with pytest.raises(ValueError):
        cm.execute_operation('vector.audit_geometries', {'data': source, 'id_field': 'identifier'}, destination)
    assert source.geometry.iloc[0].geoms[0].geoms[0].geom_type == 'LinearRing'
    assert source.geometry.iloc[0].wkb == geometry.wkb
    assert_no_publication(tmp_path, destination)


@pytest.mark.parametrize('identifiers', [[1, '1'], ['a', 'a\x00b']], ids=['mixed_scalar_ids', 'nul_truncation'])
def test_identifiers_cannot_become_duplicates_during_export(tmp_path, identifiers):
    source = gpd.GeoDataFrame({'identifier': pd.Series(identifiers, dtype=object)},
                              geometry=[None, None], crs=32733)
    destination = tmp_path / 'audit'
    with pytest.raises(ValueError):
        cm.execute_operation('vector.audit_geometries', {'data': source, 'id_field': 'identifier'}, destination)
    assert source.identifier.tolist() == identifiers
    assert_no_publication(tmp_path, destination)


def test_submillisecond_utc_attribute_is_refused_without_rounding_or_partial_files(tmp_path, typed_source):
    with closing(sqlite3.connect(typed_source)) as connection:
        connection.execute("UPDATE features SET observed_at='2024-02-29T10:30:00.123456Z' WHERE internal_fid=1")
        connection.commit()
    original = typed_source.read_bytes()
    audit = cm.audit_geometries(typed_source, id_field='identifier')
    assert audit.data.observed_at.iloc[0] == pd.Timestamp('2024-02-29T10:30:00.123456Z')
    destination = tmp_path / 'audit'
    with pytest.raises(ValueError):
        cm.execute_operation('vector.audit_geometries',
            {'data': str(typed_source), 'id_field': 'identifier'}, destination)
    assert typed_source.read_bytes() == original
    assert_no_publication(tmp_path, destination)


@pytest.mark.skipif(not HAS_M, reason='M needs Shapely >= 2.1 and GEOS >= 3.12')
def test_measured_audit_export_is_explicitly_refused_without_partial_products(tmp_path):
    geometry = shapely.from_wkt('POINT M (1 2 123.5)')
    source = gpd.GeoDataFrame({'identifier': ['M']}, geometry=[geometry], crs=32733)
    assert cm.audit_geometries(source).data.geometry.iloc[0].wkb == geometry.wkb
    destination = tmp_path / 'audit'
    with pytest.raises(ValueError):
        cm.execute_operation('vector.audit_geometries', {'data': source}, destination)
    assert_no_publication(tmp_path, destination)


def test_empty_null_and_nonfinite_geometries_remain_distinct_in_diagnostic_files(tmp_path):
    shapes = [Point(), Polygon(), None, LineString([(0, 0), (np.inf, 1)])]
    source = gpd.GeoDataFrame({'identifier': ['empty-point', 'empty-polygon', 'null', 'infinite']},
                              geometry=shapes, crs=32733)
    result = cm.execute_operation('vector.audit_geometries',
        {'data': source, 'id_field': 'identifier'}, tmp_path / 'audit')
    for name in ('before', 'data', 'issues'):
        assert wkb_values(geopackage(result['products'][name])['geometries']) == wkb_values(shapes)
    summary = json.loads(Path(result['products']['summary']).read_text())
    assert summary['empty_geometries'] == 2
    assert summary['missing_geometries'] == summary['nonfinite_geometries'] == 1
    destination = tmp_path / 'repair'
    with pytest.raises(ValueError):
        cm.execute_operation('vector.repair_geometries', {'data': source}, destination)
    assert_no_publication(tmp_path, destination)
