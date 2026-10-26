"""Independent checks of typed concatenation, provenance and publication.

SQLite supplies the attribute oracle: reading an integer field with NULL through
the default NumPy driver would itself round values larger than 2**53. Geometry
expectations come from the input WKB, or the independent Mercator formula.
"""
from __future__ import annotations

import csv
from datetime import date, datetime, timezone
import json
import math
from pathlib import Path
import sqlite3
import threading

import geopandas as gpd
import numpy as np
import pandas as pd
import pyarrow as pa
import pyogrio
from pyogrio.raw import write as raw_write
from pyproj import CRS
import pytest
import shapely
from shapely.geometry import GeometryCollection, LineString, LinearRing, MultiPoint, MultiPolygon, Point, Polygon

from cartomize import ProcessingCancelled
from cartomize.vector_merge import inspect_merge, merge_layers


PROVENANCE_KEYS = {
    'source_id', 'source_name', 'source_path', 'source_layer', 'source_row',
}


def frame(attributes=None, *, geometry=None, crs=4326):
    attributes = attributes or {}
    if geometry is None:
        length = len(next(iter(attributes.values()))) if attributes else 1
        geometry = [Point(float(i), float(i)) for i in range(length)]
    return gpd.GeoDataFrame(attributes, geometry=geometry, crs=crs)


def sources_named(*frames):
    return [{'data': data, 'name': f'survey_{i}'} for i, data in enumerate(frames)]


def manifest(result):
    def reject_constant(value):
        raise AssertionError(f'Nonstandard JSON constant: {value}')
    return json.loads(Path(result.manifest).read_text(encoding='utf-8'),
                      parse_constant=reject_constant)


def identifiers(sources):
    return [layer['id'] for layer in inspect_merge(sources)['layers']]


def quote_identifier(value):
    return '"' + value.replace('"', '""') + '"'


def rows(path, *fields):
    selected = ', '.join(quote_identifier(field) for field in fields)
    with sqlite3.connect(path) as connection:
        return connection.execute(f'SELECT {selected} FROM features ORDER BY rowid').fetchall()


def column_types(path):
    with sqlite3.connect(path) as connection:
        return {row[1]: row[2].upper()
                for row in connection.execute('PRAGMA table_info(features)')}


def read_exact(path):
    mapping = {
        pa.int32(): pd.Int32Dtype(), pa.int64(): pd.Int64Dtype(),
        pa.bool_(): pd.BooleanDtype(), pa.string(): pd.StringDtype(),
    }
    return pyogrio.read_dataframe(path, layer='features', use_arrow=True,
        datetime_as_string=True, arrow_to_pandas_kwargs={'types_mapper': mapping.get})


def csv_rows(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def assert_unpublished(destination, before):
    assert not destination.exists()
    assert set(destination.parent.iterdir()) == before


def test_inspection_matches_renamed_fields_and_reports_null_counts():
    first = frame({'plot': ['001', '002'],
                   'count': pd.Series([7, None], dtype='Int64')})
    second = frame({'parcel': ['003'], 'observations': pd.Series([2], dtype='Int64')})
    sources = sources_named(first, second)
    ids = identifiers(sources)
    mapping = {ids[0]: {'plot': 'parcel_id', 'count': 'visits'},
               ids[1]: {'parcel': 'parcel_id', 'observations': 'visits'}}
    inspection = inspect_merge(sources, field_maps=mapping)
    assert inspection['schema'] == 'cartomize.vector_merge_inspection.v1'
    assert CRS(inspection['common_crs']) == CRS(4326)
    assert inspection['conflicts'] == []
    assert inspection['suggested_schema'] == {
        'parcel_id': {'type': 'string', 'nullable': True},
        'visits': {'type': 'int64', 'nullable': True},
    }
    fields = {field['name']: field for field in inspection['layers'][0]['fields']}
    assert fields['count']['type'] == 'int64'
    assert fields['count']['null_count'] == 1
    assert fields['count']['target'] == 'visits'
    assert fields['plot']['target'] == 'parcel_id'
    assert identifiers(sources) == ids


def test_automatic_union_preserves_large_nullable_integers_and_row_provenance(tmp_path):
    first = frame({'identifier': pd.Series([2**60 + 3, None], dtype='Int64'),
                   'left_value': ['A', 'B']}, geometry=[Point(2, 3), Point(4, 5)])
    first.index = [99, 99]
    second = frame({'identifier': pd.Series([2**53 + 1], dtype='Int64'),
                    'right_value': ['C']}, geometry=[Point(6, 7)])
    sources = sources_named(first, second)
    ids = identifiers(sources)
    result = merge_layers(sources, tmp_path / 'merged')
    record = manifest(result)
    assert record['schema'] == 'cartomize.vector_merge.v1'
    assert record['status'] == 'complete'
    assert record['feature_count'] == 3
    assert record['source_count'] == 2
    assert set(record['provenance_columns']) == PROVENANCE_KEYS
    assert len(set(record['provenance_columns'].values())) == 5
    assert result.summary['provenance_columns'] == record['provenance_columns']
    assert Path(result.data).name == 'merged.gpkg'
    assert Path(result.report).is_file() and Path(result.issues).is_file()
    assert rows(result.data, 'identifier', 'left_value', 'right_value') == [
        (2**60 + 3, 'A', None), (None, 'B', None), (2**53 + 1, None, 'C'),
    ]
    provenance = record['provenance_columns']
    assert rows(result.data, *(provenance[key] for key in
        ('source_id', 'source_name', 'source_path', 'source_layer', 'source_row'))) == [
            (ids[0], 'survey_0', None, None, 0),
            (ids[0], 'survey_0', None, None, 1),
            (ids[1], 'survey_1', None, None, 0),
        ]
    assert read_exact(result.data).geometry.to_wkb().tolist() == (
        first.geometry.to_wkb().tolist() + second.geometry.to_wkb().tolist())
    assert first.index.tolist() == [99, 99]
    assert int(first['identifier'].iloc[0]) == 2**60 + 3
    assert pd.isna(first['identifier'].iloc[1])


def test_file_reader_preserves_int64_null_and_declared_temporal_types(tmp_path):
    source = tmp_path / 'source.gpkg'
    integers = np.array([2**53 + 1, 2**60 + 3, 0, 2**63 - 1, -2**63], dtype='int64')
    nulls = np.array([False, False, True, False, False])
    days = np.array(['2024-02-29', '1970-01-01', 'NaT', '2000-12-31', '2038-01-19'],
                    dtype='datetime64[D]')
    moments = np.array(['2024-02-29T01:02:03.123', '1970-01-01T00:00:00.001',
                        'NaT', '2000-12-31T23:59:59.999', '2038-01-19T03:14:07.123'],
                       dtype='datetime64[ms]')
    raw_write(source, geometry=shapely.to_wkb([Point(i, i) for i in range(5)]),
        field_data=[integers, np.array([True, False, False, True, False]), days, moments],
        fields=['identifier', 'verified', 'survey_date', 'observed_at'],
        field_mask=[nulls, nulls, None, None], layer='observations', driver='GPKG',
        geometry_type='Point', crs=CRS(4326).to_wkt(), promote_to_multi=False)
    original = source.read_bytes()
    inspection = inspect_merge({'path': source, 'layer': 'observations'})
    observed = {item['name']: item for item in inspection['layers'][0]['fields']}
    assert {name: item['type'] for name, item in observed.items()} == {
        'identifier': 'int64', 'verified': 'boolean',
        'survey_date': 'date', 'observed_at': 'datetime',
    }
    assert all(item['null_count'] == 1 for item in observed.values())
    result = merge_layers({'path': source, 'layer': 'observations'}, tmp_path / 'merged')
    assert [row[0] for row in rows(result.data, 'identifier')] == [
        2**53 + 1, 2**60 + 3, None, 2**63 - 1, -2**63,
    ]
    types = column_types(result.data)
    assert {field: types[field] for field in observed} == {
        'identifier': 'INTEGER', 'verified': 'BOOLEAN',
        'survey_date': 'DATE', 'observed_at': 'DATETIME',
    }
    assert rows(result.data, 'survey_date', 'observed_at')[0] == (
        '2024-02-29', '2024-02-29T01:02:03.123')
    provenance = manifest(result)['provenance_columns']
    assert rows(result.data, provenance['source_path'], provenance['source_layer']) == [
        (str(source.resolve()), 'observations'),
    ] * 5
    assert source.read_bytes() == original


def test_conflicting_automatic_types_require_an_explicit_schema(tmp_path):
    sources = sources_named(frame({'value': pd.Series([7], dtype='Int64')}),
                            frame({'value': ['007']}))
    inspection = inspect_merge(sources)
    conflict = next(item for item in inspection['conflicts'] if item['field'] == 'value')
    assert set(conflict['types']) == {'int64', 'string'}
    assert conflict['reason']
    destination = tmp_path / 'invalid'
    before = set(tmp_path.iterdir())
    with pytest.raises(ValueError):
        merge_layers(sources, destination)
    assert_unpublished(destination, before)
    result = merge_layers(sources, tmp_path / 'explicit', schema={'value': 'string'})
    assert rows(result.data, 'value') == [('7',), ('007',)]


@pytest.mark.parametrize('integer,allowed', [(7, True), (2**60, True), (2**53 + 1, False)])
def test_automatic_integer_float_union_checks_exact_representability(tmp_path, integer, allowed):
    sources = sources_named(frame({'value': pd.Series([integer], dtype='Int64')}),
                            frame({'value': [1.5]}))
    destination = tmp_path / 'merged'
    if allowed:
        result = merge_layers(sources, destination)
        assert column_types(result.data)['value'] in {'REAL', 'FLOAT', 'DOUBLE'}
        assert rows(result.data, 'value') == [(float(integer),), (1.5,)]
    else:
        before = set(tmp_path.iterdir())
        with pytest.raises(ValueError):
            merge_layers(sources, destination)
        assert_unpublished(destination, before)


def test_field_maps_rename_drop_and_leave_unspecified_fields_unchanged(tmp_path):
    sources = sources_named(frame({'plot': ['001'], 'obsolete': [99], 'count': [2]}),
                            frame({'parcel': ['002'], 'count': [3]}))
    first, second = identifiers(sources)
    result = merge_layers(sources, tmp_path / 'merged', field_maps={
        first: {'plot': 'identifier', 'obsolete': None}, second: {'parcel': 'identifier'},
    })
    assert rows(result.data, 'identifier', 'count') == [('001', 2), ('002', 3)]
    assert 'obsolete' not in column_types(result.data)


@pytest.mark.parametrize('mapping_case', ['unknown_source', 'unknown_field', 'collision'])
def test_invalid_field_maps_never_publish(tmp_path, mapping_case):
    sources = sources_named(frame({'left': [1], 'right': [2]}))
    ident = identifiers(sources)[0]
    mapping = {
        'unknown_source': {'absent_source_id': {'left': 'target'}},
        'unknown_field': {ident: {'missing': 'target'}},
        'collision': {ident: {'left': 'target', 'right': 'target'}},
    }[mapping_case]
    before = set(tmp_path.iterdir())
    destination = tmp_path / 'invalid'
    with pytest.raises(ValueError):
        merge_layers(sources, destination, field_maps=mapping)
    assert_unpublished(destination, before)


def test_provenance_names_avoid_business_fields_case_insensitively(tmp_path):
    business = {'CM_SOURCE_ID': ['parcel_001'], 'cm_source_name': ['original_name'],
                'cm_source_path': ['original_path'], 'cm_source_layer': ['original_layer'],
                'cm_source_row': pd.Series([2**60 + 3], dtype='Int64'),
                'cm_source_id_': ['existing_suffix'], 'fid': pd.Series([44], dtype='Int64')}
    result = merge_layers(frame(business), tmp_path / 'merged')
    provenance = manifest(result)['provenance_columns']
    assert set(provenance) == PROVENANCE_KEYS
    assert not ({name.casefold() for name in business} &
                {name.casefold() for name in provenance.values()})
    assert rows(result.data, *business) == [
        ('parcel_001', 'original_name', 'original_path', 'original_layer',
         2**60 + 3, 'existing_suffix', 44),
    ]
    assert rows(result.data, provenance['source_row']) == [(0,)]


def test_missing_fields_null_defaults_and_empty_strings_are_distinct(tmp_path):
    sources = sources_named(frame({'code': ['', None, '001']}), frame({'other': ['dropped']}))
    result = merge_layers(sources, tmp_path / 'merged', schema={
        'code': 'string', 'count': {'type': 'int64', 'default': 9, 'nullable': False},
    }, extra_fields='drop')
    assert rows(result.data, 'code', 'count') == [('', 9), (None, 9), ('001', 9), (None, 9)]


def test_missing_fields_error_rejects_absence_without_publishing(tmp_path):
    before = set(tmp_path.iterdir())
    destination = tmp_path / 'merged'
    with pytest.raises(ValueError):
        merge_layers(frame({'known': [1]}), destination,
                     schema={'known': 'int64', 'required': 'string'}, missing_fields='error')
    assert_unpublished(destination, before)


def test_extra_fields_require_explicit_drop(tmp_path):
    source = frame({'keep': [2], 'discard': ['secret']})
    before = set(tmp_path.iterdir())
    with pytest.raises(ValueError):
        merge_layers(source, tmp_path / 'invalid', schema={'keep': 'int64'})
    assert_unpublished(tmp_path / 'invalid', before)
    result = merge_layers(source, tmp_path / 'valid', schema={'keep': 'int64'}, extra_fields='drop')
    assert 'discard' not in column_types(result.data)
    assert rows(result.data, 'keep') == [(2,)]


def test_conversion_null_policy_records_errors_then_applies_defaults(tmp_path):
    source = frame({'count': ['7', 'not_an_integer', None, '']})
    result = merge_layers(source, tmp_path / 'merged', schema={
        'count': {'type': 'int64', 'nullable': False, 'default': 9},
    }, conversion_errors='null')
    assert rows(result.data, 'count') == [(7,), (9,), (9,), (9,)]
    assert len(csv_rows(result.issues)) == 2


def test_nullable_false_blocks_residual_nulls_even_under_conversion_null_policy(tmp_path):
    before = set(tmp_path.iterdir())
    destination = tmp_path / 'merged'
    with pytest.raises(ValueError):
        merge_layers(frame({'count': ['bad']}), destination,
            schema={'count': {'type': 'int64', 'nullable': False}}, conversion_errors='null')
    assert_unpublished(destination, before)


@pytest.mark.parametrize('kind,values,expected', [
    ('int64', ['001', '+7', '-3', '1e3', 4.0, None], [1, 7, -3, 1000, 4, None]),
    ('float64', ['1.25', -2, 2**60, None], [1.25, -2.0, float(2**60), None]),
    ('boolean', [True, False, 0, 1, 'true', 'false', '0', '1', None],
                [1, 0, 0, 1, 1, 0, 0, 1, None]),
    ('string', ['001', '', 'école', None], ['001', '', 'école', None]),
])
def test_explicit_scalar_conversions_preserve_values_and_nulls(tmp_path, kind, values, expected):
    result = merge_layers(frame({'value': pd.Series(values, dtype=object)}),
        tmp_path / 'merged', schema={'value': kind})
    assert rows(result.data, 'value') == [(value,) for value in expected]


@pytest.mark.parametrize('kind,value', [
    ('int64', 1.25), ('int64', '1.2'),
    ('int64', 2**63), ('int64', -2**63 - 1),
    ('float64', float('inf')), ('float64', 'nan'), ('float64', 'inf'),
    ('float64', 2**53 + 1), ('float64', '9007199254740993'),
    ('boolean', 2), ('boolean', -1), ('boolean', 'yes'), ('boolean', ''),
    ('date', '2023-02-29'), ('date', '2024-02-29T01:02:03'),
    ('datetime', '2024-02-29T01:02:03Z'),
    ('datetime', '2024-02-29T01:02:03.123456'),
    ('datetime_utc', '2024-02-29T01:02:03'),
    ('datetime_utc', '2024-02-29T01:02:03.123456Z'),
])
def test_strict_conversions_reject_loss_or_ambiguous_values(tmp_path, kind, value):
    destination = tmp_path / 'merged'
    before = set(tmp_path.iterdir())
    source = frame({'value': pd.Series([value], dtype=object)})
    with pytest.raises((ValueError, OverflowError)):
        merge_layers(source, destination, schema={'value': kind})
    assert_unpublished(destination, before)


def test_date_datetime_and_utc_have_distinct_storage_and_explicit_time_conversion(tmp_path):
    source = frame({
        'day': [date(2024, 2, 29), '1970-01-01', None],
        'naive': [datetime(2024, 2, 29, 1, 2, 3, 123000), '1970-01-01T00:00:00.001', None],
        'aware': ['2024-07-01T12:30:00.123+02:00',
                  datetime(2024, 1, 1, 12, 30, tzinfo=timezone.utc), None],
    })
    result = merge_layers(source, tmp_path / 'merged', schema={
        'day': 'date', 'naive': 'datetime', 'aware': 'datetime_utc',
    })
    types = column_types(result.data)
    assert (types['day'], types['naive'], types['aware']) == ('DATE', 'DATETIME', 'DATETIME')
    stored = rows(result.data, 'day', 'naive', 'aware')
    assert stored[0] == ('2024-02-29', '2024-02-29T01:02:03.123', '2024-07-01T10:30:00.123Z')
    assert pd.Timestamp(stored[1][2]) == pd.Timestamp('2024-01-01T12:30:00Z')
    assert stored[2] == (None, None, None)


def test_file_datetimes_are_not_truncated_or_assumed_utc_before_validation(tmp_path):
    source = tmp_path / 'times.gpkg'
    raw_write(source, geometry=shapely.to_wkb([Point(0, 0)]),
        field_data=[np.array(['2024-02-29T01:02:03.123'], dtype='datetime64[ms]')],
        fields=['instant'], layer='observations', driver='GPKG', geometry_type='Point',
        crs=CRS(4326).to_wkt(), layer_options={'SPATIAL_INDEX': 'NO'})
    with sqlite3.connect(source) as connection:
        connection.execute('UPDATE observations SET instant = ?',
                           ('2024-02-29T01:02:03.123456',))
    original = source.read_bytes()
    before = set(tmp_path.iterdir())
    for kind in ('datetime', 'datetime_utc'):
        destination = tmp_path / kind
        with pytest.raises(ValueError):
            merge_layers(source, destination, schema={'instant': kind})
        assert_unpublished(destination, before)
    assert source.read_bytes() == original


@pytest.mark.parametrize('count', [0, 2])
def test_empty_and_all_null_layers_keep_declared_output_field_types(tmp_path, count):
    source = frame({'placeholder': [None] * count}, geometry=[Point(1, 2)] * count)
    schema = {name: kind for name, kind in [
        ('identifier', 'int64'), ('verified', 'boolean'), ('survey_date', 'date'),
        ('observed_at', 'datetime'), ('label', 'string'),
    ]}
    result = merge_layers(source, tmp_path / 'merged', schema=schema, extra_fields='drop')
    types = column_types(result.data)
    assert {key: types[key] for key in schema} == {
        'identifier': 'INTEGER', 'verified': 'BOOLEAN', 'survey_date': 'DATE',
        'observed_at': 'DATETIME', 'label': 'TEXT',
    }
    assert manifest(result)['feature_count'] == count
    assert rows(result.data, *schema) == [(None,) * 5] * count


@pytest.mark.parametrize('schema', [
    {'value': 'unsupported'}, {'value': {'type': 'int64', 'nullable': 'yes'}},
    {'geometry': 'string'}, {'GEOMETRY': 'string'},
    {'Code': 'string', 'code': 'string'},
])
def test_invalid_or_colliding_schema_refused_before_publication(tmp_path, schema):
    before = set(tmp_path.iterdir())
    destination = tmp_path / 'merged'
    with pytest.raises((TypeError, ValueError)):
        merge_layers(frame({'value': [1]}), destination, schema=schema, extra_fields='drop')
    assert_unpublished(destination, before)


@pytest.mark.parametrize('option,value', [
    ('conversion_errors', 'ignore'), ('missing_fields', 'ignore'),
    ('extra_fields', 'ignore'), ('recursive', 'yes'),
])
def test_invalid_policies_are_not_silently_accepted(tmp_path, option, value):
    before = set(tmp_path.iterdir())
    destination = tmp_path / 'merged'
    with pytest.raises((TypeError, ValueError)):
        merge_layers(frame({'value': [1]}), destination, **{option: value})
    assert_unpublished(destination, before)


def test_overlapping_polygons_are_concatenated_without_union_or_promotion(tmp_path):
    polygon = Polygon([(0, 0), (2, 0), (2, 2), (0, 2)])
    overlap = Polygon([(1, 1), (3, 1), (3, 3), (1, 3)])
    multiple = MultiPolygon([Polygon([(5, 5), (6, 5), (6, 6), (5, 6)])])
    first = frame({'identifier': ['a', 'b']}, geometry=[polygon, overlap])
    second = frame({'identifier': ['c']}, geometry=[multiple])
    result = merge_layers(sources_named(first, second), tmp_path / 'merged')
    output = read_exact(result.data)
    assert output.geometry.geom_type.tolist() == ['Polygon', 'Polygon', 'MultiPolygon']
    assert output.geometry.to_wkb().tolist() == [polygon.wkb, overlap.wkb, multiple.wkb]
    assert len(output) == 3
    assert shapely.area(output.geometry.to_numpy()).sum() == pytest.approx(9.)


def test_null_empty_xy_and_xyz_features_are_not_removed_or_changed(tmp_path):
    original = [Point(1, 2, 17.5), None, Point(), Point(4, 5), Point(6, 7, -3)]
    first = frame({'identifier': ['a', 'b', 'c']}, geometry=original[:3])
    second = frame({'identifier': ['d', 'e']}, geometry=original[3:])
    result = merge_layers(sources_named(first, second), tmp_path / 'merged')
    output = read_exact(result.data)
    assert output.geometry.to_wkb().tolist() == [item.wkb if item is not None else None for item in original]
    assert output.identifier.tolist() == ['a', 'b', 'c', 'd', 'e']


def test_heterogeneous_geometry_layer_declares_optional_z_and_preserves_each_wkb(tmp_path):
    original = [Point(1, 2), Point(3, 4, 5), MultiPoint([(0, 0, 1), (1, 2, 3)]),
                LineString([(0, 0), (1, 2)]),
                Polygon([(0, 0), (2, 0), (2, 2), (0, 0)]), Point(), None]
    source = frame({'identifier': list(range(len(original)))}, geometry=original)
    result = merge_layers(source, tmp_path / 'merged')
    output = read_exact(result.data)
    assert output.geometry.to_wkb().tolist() == [
        item.wkb if item is not None else None for item in original]
    with sqlite3.connect(result.data) as connection:
        declarations = connection.execute(
            'SELECT geometry_type_name, z, m FROM gpkg_geometry_columns '
            'WHERE table_name = ?', ('features',)).fetchall()
    assert declarations == [('GEOMETRY', 2, 0)]


def test_invalid_polygon_is_retained_without_implicit_repair(tmp_path):
    polygon = Polygon([(0, 0), (2, 2), (0, 2), (2, 0), (0, 0)])
    assert not polygon.is_valid
    result = merge_layers(frame({'identifier': [1]}, geometry=[polygon]), tmp_path / 'merged')
    output = read_exact(result.data)
    assert output.geometry.iloc[0].wkb == polygon.wkb
    assert not output.geometry.iloc[0].is_valid


def test_mixed_crs_requires_explicit_target_and_transforms_only_coordinates(tmp_path):
    first = frame({'identifier': pd.Series([2**53 + 1, None], dtype='Int64')},
                  geometry=[Point(15, -4), Point(0, 0)], crs=4326)
    second = frame({'identifier': pd.Series([2**60 + 3], dtype='Int64')},
                   geometry=[Point(1000, 2000)], crs=3857)
    sources = sources_named(first, second)
    assert inspect_merge(sources)['common_crs'] is None
    before = set(tmp_path.iterdir())
    with pytest.raises(ValueError):
        merge_layers(sources, tmp_path / 'implicit')
    assert_unpublished(tmp_path / 'implicit', before)
    result = merge_layers(sources, tmp_path / 'explicit', target_crs=3857)
    output = read_exact(result.data)
    assert CRS(output.crs) == CRS(3857)
    expected_x = 6378137.0 * math.radians(15)
    expected_y = 6378137.0 * math.log(math.tan(math.pi / 4 + math.radians(-4) / 2))
    assert (output.geometry.iloc[0].x, output.geometry.iloc[0].y) == pytest.approx(
        (expected_x, expected_y), abs=1e-6)
    assert output.geometry.iloc[2].wkb == second.geometry.iloc[0].wkb
    assert rows(result.data, 'identifier') == [(2**53 + 1,), (None,), (2**60 + 3,)]
    audit_path = Path(manifest(result)['reprojection_manifest'])
    assert audit_path.is_file()
    audit = json.loads(audit_path.read_text(encoding='utf-8'))
    assert audit['schema'] == 'cartomize.vector_reprojection.v1'
    assert audit['status'] == 'complete' and audit['layer_count'] == 2
    assert all(Path(layer['output']).is_file() for layer in audit['layers'])
    assert all('.cartomize-' not in layer['output'] for layer in audit['layers'])


def test_reprojection_uses_original_operation_selection_and_leaves_dropped_attributes_out(tmp_path):
    from cartomize.vector_reprojection import inspect_reprojection
    sources = sources_named(frame({
        'identifier': pd.Series([2**53 + 1], dtype='Int64'),
        'nested_to_drop': [[1, 2, 3]],
    }, geometry=[Point(15, -4)]))
    inspection = inspect_reprojection(sources, 3857)
    layer = inspection['layers'][0]
    operation = layer['catalogue']['operations'][0]
    result = merge_layers(sources, tmp_path / 'merged', schema={'identifier': 'int64'},
        extra_fields='drop', target_crs=3857,
        reprojection_options={'operations': {layer['id']: operation['id']}})
    audit = json.loads(Path(manifest(result)['reprojection_manifest']).read_text(encoding='utf-8'))
    assert audit['layers'][0]['selection'] == 'explicit'
    assert audit['layers'][0]['operation']['id'] == operation['id']
    assert audit['layers'][0]['name'] == layer['id']
    assert rows(result.data, 'identifier') == [(2**53 + 1,)]
    assert 'nested_to_drop' not in column_types(result.data)


@pytest.mark.parametrize('unknown', ['source_id', 'operation_id'])
def test_unknown_explicit_reprojection_selection_never_falls_back(tmp_path, unknown):
    sources = sources_named(frame({'identifier': [1]}, geometry=[Point(15, -4)]))
    ident = identifiers(sources)[0]
    selection = {'missing_source' if unknown == 'source_id' else ident: 'missing_operation'}
    destination = tmp_path / 'merged'
    before = set(tmp_path.iterdir())
    with pytest.raises(ValueError):
        merge_layers(sources, destination, target_crs=3857,
                     reprojection_options={'operations': selection, 'require_best': False})
    assert_unpublished(destination, before)


def test_missing_crs_is_not_assigned_from_other_layers_or_target(tmp_path):
    missing = frame({'value': [1]}, crs=None)
    before = set(tmp_path.iterdir())
    destination = tmp_path / 'merged'
    with pytest.raises(ValueError):
        merge_layers(sources_named(missing, frame({'value': [2]})), destination, target_crs=4326)
    assert_unpublished(destination, before)


@pytest.mark.parametrize('when', ['before_start', 'after_progress'])
def test_cancellation_never_publishes_partial_batch(tmp_path, when):
    event = threading.Event()
    progress_calls = []
    if when == 'before_start':
        event.set()
    def progress(done, total):
        progress_calls.append((done, total))
        if done >= 1:
            event.set()
    before = set(tmp_path.iterdir())
    destination = tmp_path / 'merged'
    with pytest.raises(ProcessingCancelled):
        merge_layers(sources_named(frame({'value': [1]}), frame({'value': [2]})),
                     destination, cancel=event, progress=progress)
    assert_unpublished(destination, before)
    if when == 'after_progress':
        assert progress_calls


def test_existing_output_and_source_directory_are_protected(tmp_path):
    source = tmp_path / 'input.gpkg'
    frame({'identifier': pd.Series([2**60 + 3], dtype='Int64')}).to_file(source, layer='sites')
    original = source.read_bytes()
    existing = tmp_path / 'existing'
    existing.mkdir()
    sentinel = existing / 'keep.txt'
    sentinel.write_text('keep exactly', encoding='utf-8')
    for destination in (existing, source, tmp_path):
        with pytest.raises((ValueError, FileExistsError)):
            merge_layers(source, destination)
    assert sentinel.read_text(encoding='utf-8') == 'keep exactly'
    assert source.read_bytes() == original


def test_late_bad_source_never_publishes_earlier_valid_features(tmp_path):
    sources = sources_named(frame({'count': ['12']}), frame({'count': ['invalid']}))
    destination = tmp_path / 'merged'
    before = set(tmp_path.iterdir())
    with pytest.raises(ValueError):
        merge_layers(sources, destination, schema={'count': 'int64'})
    assert_unpublished(destination, before)


@pytest.mark.parametrize('outcome', ['write_error', 'cancel_after_write'])
def test_failure_after_physical_write_cleans_staging_and_publishes_nothing(tmp_path, monkeypatch, outcome):
    event = threading.Event()
    actual_write = pyogrio.raw.write
    staged = []
    def interrupted_write(path, *args, **kwargs):
        actual_write(path, *args, **kwargs)
        assert Path(path).is_file()
        staged.append(Path(path))
        if outcome == 'write_error':
            raise OSError('Simulated storage failure after writing the dataset.')
        event.set()
    monkeypatch.setattr(pyogrio.raw, 'write', interrupted_write)
    before = set(tmp_path.iterdir())
    destination = tmp_path / 'merged'
    with pytest.raises(OSError if outcome == 'write_error' else ProcessingCancelled):
        merge_layers(frame({'identifier': [1, 2]}), destination, cancel=event)
    assert staged
    assert all(not path.exists() for path in staged)
    assert_unpublished(destination, before)


@pytest.mark.parametrize('nested', [False, True])
def test_standalone_rings_are_rejected_before_entering_native_writer(tmp_path, monkeypatch, nested):
    ring = LinearRing([(0, 0), (1, 0), (1, 1), (0, 0)])
    geometry = GeometryCollection([ring]) if nested else ring
    def forbidden_write(*args, **kwargs):
        pytest.fail('Standalone LinearRing must be rejected before the native writer.')
    monkeypatch.setattr(pyogrio.raw, 'write', forbidden_write)
    destination = tmp_path / 'merged'
    before = set(tmp_path.iterdir())
    with pytest.raises(ValueError):
        merge_layers(frame({'identifier': [1]}, geometry=[geometry]), destination)
    assert_unpublished(destination, before)


def test_collection_with_mixed_dimensions_is_refused_if_driver_invents_z(tmp_path):
    geometry = GeometryCollection([Point(1, 2), Point(3, 4, 5)])
    before_wkb = geometry.wkb
    destination = tmp_path / 'merged'
    before = set(tmp_path.iterdir())
    with pytest.raises(ValueError):
        merge_layers(frame({'identifier': [1]}, geometry=[geometry]), destination)
    assert geometry.wkb == before_wkb
    assert_unpublished(destination, before)


@pytest.mark.parametrize('kind', ['nonfinite', 'measured'])
def test_nonfinite_coordinates_and_measures_are_never_silently_normalized(tmp_path, kind):
    if kind == 'measured' and not hasattr(shapely, 'has_m'):
        pytest.skip('Measured ordinates require a Shapely build that exposes M.')
    geometry = (Point(float('inf'), 1) if kind == 'nonfinite'
                else shapely.from_wkt('POINT M (1 2 9)'))
    destination = tmp_path / 'merged'
    before = set(tmp_path.iterdir())
    with pytest.raises(ValueError):
        merge_layers(frame({'identifier': [1]}, geometry=[geometry]), destination)
    assert_unpublished(destination, before)


def test_embedded_nul_text_is_refused_instead_of_truncated(tmp_path):
    destination = tmp_path / 'merged'
    before = set(tmp_path.iterdir())
    with pytest.raises(ValueError):
        merge_layers(frame({'code': ['before\x00after']}), destination)
    assert_unpublished(destination, before)


@pytest.mark.parametrize('same_source', [False, True], ids=['across_sources', 'within_source'])
def test_inspection_exposes_case_collisions_so_explicit_maps_can_resolve_them(tmp_path, same_source):
    if same_source:
        source = frame({'Name': ['capital'], 'name': ['lowercase']})
        sources = sources_named(source)
    else:
        sources = sources_named(frame({'Name': ['capital']}), frame({'name': ['lowercase']}))
    inspection = inspect_merge(sources)
    assert set(inspection['suggested_schema']) == {'Name', 'name'}
    assert any(conflict['field'] in {'Name', 'name'} and conflict['reason']
               for conflict in inspection['conflicts'])
    assert [{field['name'] for field in layer['fields']} for layer in inspection['layers']] == (
        [{'Name', 'name'}] if same_source else [{'Name'}, {'name'}])
    destination = tmp_path / 'unresolved'
    before = set(tmp_path.iterdir())
    with pytest.raises(ValueError):
        merge_layers(sources, destination)
    assert_unpublished(destination, before)
    ids = [layer['id'] for layer in inspection['layers']]
    mapping = ({ids[0]: {'Name': 'capital_name', 'name': 'lowercase_name'}} if same_source
               else {ids[0]: {'Name': 'canonical_name'}, ids[1]: {'name': 'canonical_name'}})
    resolved = inspect_merge(sources, field_maps=mapping)
    assert resolved['conflicts'] == []
    result = merge_layers(sources, tmp_path / 'resolved', field_maps=mapping)
    if same_source:
        assert rows(result.data, 'capital_name', 'lowercase_name') == [('capital', 'lowercase')]
        assert list(source.columns) == ['Name', 'name', 'geometry']
    else:
        assert rows(result.data, 'canonical_name') == [('capital',), ('lowercase',)]


def test_inspection_exposes_reserved_memory_attribute_for_explicit_renaming(tmp_path):
    geometries = [Point(2, 3), Point(4, 5)]
    source = gpd.GeoDataFrame({'geometry': ['parcel_001', None], 'shape': geometries},
                              geometry='shape', crs=4326)
    inspection = inspect_merge(source)
    layer = inspection['layers'][0]
    assert {field['name'] for field in layer['fields']} == {'geometry'}
    assert 'geometry' in inspection['suggested_schema']
    assert any(conflict['field'] == 'geometry' and conflict['reason']
               for conflict in inspection['conflicts'])
    destination = tmp_path / 'unresolved'
    before = set(tmp_path.iterdir())
    with pytest.raises(ValueError):
        merge_layers(source, destination)
    assert_unpublished(destination, before)
    mapping = {layer['id']: {'geometry': 'geom_label'}}
    assert inspect_merge(source, field_maps=mapping)['conflicts'] == []
    result = merge_layers(source, tmp_path / 'resolved', field_maps=mapping)
    assert rows(result.data, 'geom_label') == [('parcel_001',), (None,)]
    assert read_exact(result.data).geometry.to_wkb().tolist() == [item.wkb for item in geometries]
    assert source.geometry.name == 'shape'
    assert source['geometry'].iloc[0] == 'parcel_001'
    assert pd.isna(source['geometry'].iloc[1])


@pytest.mark.parametrize('null_count', [0, 2], ids=['empty', 'all_null'])
@pytest.mark.parametrize('reverse', [False, True], ids=['unknown_first', 'known_first'])
def test_untyped_null_memory_field_adopts_concrete_type_without_order_dependence(tmp_path, null_count, reverse):
    unknown = frame({'identifier': pd.Series([None] * null_count, dtype=object)},
                    geometry=[Point(i, i) for i in range(null_count)])
    concrete = frame({'identifier': pd.Series([2**60 + 3], dtype='Int64')})
    ordered = [concrete, unknown] if reverse else [unknown, concrete]
    sources = sources_named(*ordered)
    inspection = inspect_merge(sources)
    unknown_profile = inspection['layers'][1 if reverse else 0]['fields'][0]
    assert unknown_profile['dtype'] == 'object'
    assert unknown_profile['untyped_null'] is True
    assert unknown_profile['null_count'] == null_count
    assert inspection['conflicts'] == []
    assert inspection['suggested_schema']['identifier'] == {'type': 'int64', 'nullable': True}
    result = merge_layers(sources, tmp_path / 'merged')
    expected = ([2**60 + 3] + [None] * null_count if reverse
                else [None] * null_count + [2**60 + 3])
    assert rows(result.data, 'identifier') == [(value,) for value in expected]
    assert column_types(result.data)['identifier'] == 'INTEGER'
    assert unknown['identifier'].dtype == object


@pytest.mark.parametrize('count', [0, 2], ids=['empty_file', 'null_text_rows'])
def test_declared_null_text_file_field_keeps_its_type_and_requires_explicit_conversion(tmp_path, count):
    source = tmp_path / 'declared_text.gpkg'
    raw_write(source, geometry=shapely.to_wkb([Point(i, i) for i in range(count)]),
        field_data=[np.full(count, None, dtype=object)], fields=['identifier'],
        field_mask=[np.ones(count, dtype=bool)], layer='survey', driver='GPKG',
        geometry_type='Point', crs=CRS(4326).to_wkt())
    with sqlite3.connect(source) as connection:
        declared = {row[1]: row[2] for row in connection.execute('PRAGMA table_info(survey)')}
        assert declared['identifier'] == 'TEXT'
    concrete = frame({'identifier': pd.Series([7], dtype='Int64')})
    sources = [{'path': source, 'layer': 'survey'}, {'data': concrete, 'name': 'numeric'}]
    inspection = inspect_merge(sources)
    assert inspection['layers'][0]['fields'][0]['type'] == 'string'
    assert any(conflict['field'] == 'identifier' and set(conflict['types']) == {'string', 'int64'}
               for conflict in inspection['conflicts'])
    before = set(tmp_path.iterdir())
    destination = tmp_path / 'unresolved'
    with pytest.raises(ValueError):
        merge_layers(sources, destination)
    assert_unpublished(destination, before)
    result = merge_layers(sources, tmp_path / 'explicit', schema={'identifier': 'string'})
    assert rows(result.data, 'identifier') == [(None,)] * count + [('7',)]
    assert column_types(result.data)['identifier'] == 'TEXT'


def test_file_attribute_named_geometry_survives_reader_and_can_be_mapped(tmp_path):
    source = tmp_path / 'business_geometry.gpkg'
    geometries = [Point(2, 3), Point(4, 5)]
    raw_write(source, geometry=shapely.to_wkb(geometries),
        field_data=[np.array(['parcel outline', None], dtype=object),
                    np.array(['business alias', 'second alias'], dtype=object),
                    np.array([2**53 + 1, 0], dtype='int64'),
                    np.array(['2024-02-29', 'NaT'], dtype='datetime64[D]')],
        fields=['geometry', 'geometry_', 'identifier', 'survey_date'],
        field_mask=[None, None, np.array([False, True]), None],
        layer='survey', driver='GPKG', geometry_type='Point', crs=CRS(4326).to_wkt(),
        layer_options={'GEOMETRY_NAME': 'geom', 'FID': 'internal_fid'})
    with sqlite3.connect(source) as connection:
        assert connection.execute('SELECT column_name FROM gpkg_geometry_columns').fetchall() == [('geom',)]
        assert connection.execute('SELECT geometry, identifier FROM survey ORDER BY internal_fid').fetchall() == [
            ('parcel outline', 2**53 + 1), (None, None)]
    original = source.read_bytes()
    inspection = inspect_merge({'path': source, 'layer': 'survey'})
    layer = inspection['layers'][0]
    fields = {field['name']: field for field in layer['fields']}
    assert set(fields) == {'geometry', 'geometry_', 'identifier', 'survey_date'}
    assert fields['geometry']['type'] == 'string'
    assert fields['geometry']['null_count'] == 1
    assert fields['survey_date']['type'] == 'date'
    assert any(conflict['field'] == 'geometry' for conflict in inspection['conflicts'])
    mapping = {layer['id']: {'geometry': 'geom_label'}}
    assert inspect_merge(source, field_maps=mapping)['conflicts'] == []
    result = merge_layers(source, tmp_path / 'merged', field_maps=mapping)
    assert rows(result.data, 'geom_label', 'geometry_', 'identifier', 'survey_date') == [
        ('parcel outline', 'business alias', 2**53 + 1, '2024-02-29'),
        (None, 'second alias', None, None),
    ]
    assert column_types(result.data)['survey_date'] == 'DATE'
    assert read_exact(result.data).geometry.to_wkb().tolist() == [item.wkb for item in geometries]
    assert source.read_bytes() == original
