"""Independent partitions, native types and geometry policies for G07."""
from datetime import date, datetime
from decimal import Decimal
import json
import threading

import geopandas as gpd
from geopandas.testing import assert_geodataframe_equal
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import GeometryCollection, LineString, Point, Polygon, box

from cartomize.algebra import ProcessingCancelled
from cartomize.vector_io import read_vector, write_geopackage
from cartomize.vector_selection import VectorSelectionResult, extract_features
from cartomize.vector_workflows import select_attributes, select_location


def records():
    result = gpd.GeoDataFrame({
        'identifier': pd.Series([2**63 + i for i in range(6)], dtype='UInt64'),
        'flag': pd.Series([True, True, False, False, True, False], dtype='boolean'),
        'value': pd.Series([10, 20, 30, 40, None, 60], dtype='Int64'),
        'visit_date': pd.Series([date(2026, 1, 1), date(2026, 2, 1), None,
                                 date(2026, 3, 1), date(2026, 4, 1), None], dtype=object),
        'name': pd.Series(['a', 'b', 'c', 'd', None, 'f'], dtype='string'),
        'reason': ['original'] * 6,
    }, geometry=[Point(1, 1, 5), Point(9, 9, 6), Point(2, 2, 7), Point(8, 8, 8),
                 None, GeometryCollection()], crs=3857)
    result.index = pd.MultiIndex.from_tuples([('A', 1), ('A', 1), ('B', 2),
                                              ('B', 2), ('C', 3), ('C', 3)])
    result = result.rename_geometry('shape')
    result.attrs = {'_cartomize_temporal_fields': {'visit_date': 'date'}, 'source_note': 'unchanged'}
    return result


def mask():
    return gpd.GeoDataFrame(geometry=[box(0, 0, 3, 3), box(1, 1, 4, 4)], crs=3857)


def assert_partition(source, result, selected_rows):
    selected_rows = list(selected_rows)
    rejected_rows = [row for row in range(len(source)) if row not in selected_rows]
    assert isinstance(result, VectorSelectionResult)
    assert_geodataframe_equal(result.data, source.iloc[selected_rows])
    assert_geodataframe_equal(result.rejected, source.iloc[rejected_rows])
    assert result.data.attrs == source.attrs == result.rejected.attrs
    assert result.report.source_row.tolist() == list(range(len(source)))
    assert result.report.source_index.tolist() == list(source.index)
    assert result.report.index.tolist() == list(range(len(source)))
    assert result.report.loc[result.report.selected, 'source_row'].tolist() == selected_rows
    assert result.report.loc[~result.report.selected, 'source_row'].tolist() == rejected_rows
    assert result.report.loc[result.report.selected, 'output_row'].tolist() == list(range(len(selected_rows)))
    assert result.report.loc[~result.report.selected, 'rejected_row'].tolist() == list(range(len(rejected_rows)))
    assert result.report.loc[result.report.selected, 'rejected_row'].isna().all()
    assert result.report.loc[~result.report.selected, 'output_row'].isna().all()
    for selected, part in [(True, result.data), (False, result.rejected)]:
        rows = result.report.loc[result.report.selected == selected, 'source_row'].tolist()
        assert part.geometry.to_wkb().tolist() == source.iloc[rows].geometry.to_wkb().tolist()
    assert result.summary['input_features'] == len(source)
    assert result.summary['output_features'] == len(selected_rows)
    assert result.summary['rejected_features'] == len(rejected_rows)
    assert sum(result.summary['reason_counts'].values()) == len(source)
    json.dumps(result.summary, allow_nan=False)


@pytest.mark.parametrize('combination,invert,selected', [
    ('and', False, [0]), ('or', False, [0, 1, 2, 4]),
    ('and', True, [1, 2, 3, 4, 5]), ('or', True, [3, 5]),
])
def test_four_combinations_partition_every_row_without_attribute_or_geometry_changes(combination, invert, selected):
    source = records()
    before = source.copy()
    result = extract_features(source, filters=[dict(field='flag', comparison='eq', value=True)],
                              mask=mask(), combination=combination, invert=invert,
                              id_field='identifier')
    assert_partition(source, result, selected)
    assert_geodataframe_equal(source, before)
    assert result.summary['combinations'] == {'both': 1, 'attributes_only': 2,
                                              'spatial_only': 1, 'neither': 2}
    assert result.report.source_id.dtype == source.identifier.dtype
    assert result.report.source_id.tolist() == source.identifier.tolist()
    assert result.report.spatial_match.tolist() == [True, False, True, False, False, False]
    assert result.report.geometry_status.tolist() == ['valid', 'valid', 'valid', 'valid', 'missing', 'empty']
    assert 'reason' in result.data and set(result.data.reason) <= {'original'}
    if invert:
        assert set(result.report.loc[~result.report.selected, 'reason']) == {'excluded_by_inversion'}
    else:
        assert result.report.loc[3, 'reason'] == 'attribute_and_spatial_no_match'


@pytest.mark.parametrize('match,selected', [('all', [0]), ('any', [0, 1, 2, 4])])
def test_multiple_attribute_criteria_have_independent_counts_and_missing_reasons(match, selected):
    source = records()
    result = extract_features(source, filters=[dict(field='flag', comparison='eq', value=True),
                                               dict(field='value', comparison='in', value=['10', '30'])],
                              attribute_match=match)
    assert_partition(source, result, selected)
    assert result.report.spatial_match.isna().all()
    assert result.summary['combinations'] is None
    assert result.summary['blocks']['spatial'] == {'enabled': False, 'matched': None, 'unmatched': None}
    assert result.report.attribute_2_reason.tolist() == ['matched', 'no_match', 'matched', 'no_match',
                                                        'missing_value', 'no_match']
    assert result.summary['criteria'][1]['matched'] == 2


def test_integer_thresholds_and_membership_do_not_round_in_a_combined_selection():
    source = records()
    selected = extract_features(source, filters=[dict(field='identifier', comparison='ge', value=str(2**63 + 1)),
                                                dict(field='identifier', comparison='lt', value=Decimal(2**63 + 3) + Decimal('.5'))])
    assert_partition(source, selected, [1, 2, 3])
    assert selected.summary['parameters']['filters'][1]['value'] == {
        'type': 'decimal', 'value': str(Decimal(2**63 + 3) + Decimal('.5'))}
    selected = extract_features(source, filters=[dict(field='identifier', comparison='in',
                                                     value=[str(2**63 + 1), str(2**63 + 3)])], mask=mask(),
                                combination='or')
    assert_partition(source, selected, [0, 1, 2, 3])


@pytest.mark.parametrize('value', [[1], [0], ['true'], [True, 1], [False, 'false']])
def test_boolean_membership_never_interprets_numbers_or_text_as_boolean(value):
    source = records()
    with pytest.raises(ValueError, match='Boolean'):
        extract_features(source, filters=[dict(field='flag', comparison='in', value=value)])
    with pytest.raises(ValueError, match='Boolean'):
        select_attributes(source, 'flag', 'not_in', value)


def test_boolean_and_null_membership_are_explicit_and_exact():
    source = records()
    source['flag'] = pd.array([True, False, None, True, False, None], dtype='boolean')
    yes = extract_features(source, filters=[dict(field='flag', comparison='in', value=[True, None])])
    assert_partition(source, yes, [0, 2, 3, 5])
    no = extract_features(source, filters=[dict(field='flag', comparison='not_in', value=[True])])
    assert_partition(source, no, [1, 4])
    assert no.report.attribute_1_reason.tolist() == ['no_match', 'matched', 'missing_value',
                                                   'no_match', 'matched', 'missing_value']


@pytest.mark.parametrize('dtype', ['Float64', object])
def test_numeric_membership_validates_types_and_never_matches_boolean_one(dtype):
    source = records().iloc[:3].copy()
    source['number'] = pd.Series([1.0, 1.5, None], index=source.index, dtype=dtype)
    result = extract_features(source, filters=[dict(field='number', comparison='in', value=['1.5', None])])
    assert_partition(source, result, [1, 2])
    for value in [True, False, 'Infinity', '-Infinity']:
        with pytest.raises(ValueError, match='numeric'):
            extract_features(source, filters=[dict(field='number', comparison='in', value=[value])])


@pytest.mark.parametrize('comparison,value,rows', [
    ('eq', str(2**53 + 1), [1]), ('ne', str(2**53 + 1), [0, 2, 3, 4]),
    ('gt', '9007199254740992.5', [1, 2]), ('lt', '9007199254740992.5', [0, 3, 4]),
    ('ge', str(2**53 + 1), [1, 2]), ('le', str(2**53 + 1), [0, 1, 3, 4]),
    ('in', [str(2**53 + 1), '1.5'], [1, 3]), ('in', ['0.1', None], [4, 5]),
    ('not_in', [str(2**53 + 1), '1.5'], [0, 2, 4]),
])
def test_mixed_numeric_object_fields_preserve_adjacent_large_integers(comparison, value, rows):
    source = records()
    source['number'] = pd.Series([2**53, 2**53 + 1, 2**53 + 2, 1.5, 0.1, None],
                                 index=source.index, dtype=object)
    result = extract_features(source, filters=[dict(field='number', comparison=comparison, value=value)])
    assert result.summary['source_attribute_types']['number'] == 'float64'
    assert_partition(source, result, rows)
    for invalid_comparison, invalid_value in [('eq', True), ('in', [True]), ('not_in', [False])]:
        with pytest.raises(ValueError, match='boolean'):
            select_attributes(source, 'number', invalid_comparison, invalid_value)


@pytest.mark.parametrize('comparison,value', [('eq', str(2**53 + 1)),
                                             ('in', [str(2**53 + 1)])])
def test_mixed_numeric_categories_keep_exact_large_integer_values(comparison, value):
    source = records().iloc[:3].copy()
    source['number'] = pd.Categorical.from_codes(
        [0, 1, -1], categories=pd.Index([2**53 + 1, 1.5], dtype=object))
    result = extract_features(source, filters=[dict(field='number', comparison=comparison, value=value)])
    assert_partition(source, result, [0])
    assert isinstance(result.data['number'].dtype, pd.CategoricalDtype)


def test_unordered_integer_categories_compare_numeric_values_without_category_order():
    source = records().iloc[:3].copy()
    source['number'] = pd.Categorical.from_codes(
        [0, 1, -1], categories=pd.Index([2**53 + 1, 2**53], dtype=object), ordered=False)
    result = extract_features(source, filters=[dict(field='number', comparison='gt', value=str(2**53))])
    assert_partition(source, result, [0])
    membership = select_attributes(source, 'number', 'in', [str(2**53 + 1)])
    assert_geodataframe_equal(membership, source.iloc[[0]])


@pytest.mark.parametrize('kind,invalid,fragment', [('int64', 'invalid', 'numeric'),
                                                 ('float64', True, 'numeric'),
                                                 ('boolean', 1, 'Boolean')])
def test_all_missing_declared_fields_still_validate_filter_types(kind, invalid, fragment):
    source = records().iloc[:2].copy()
    source['unknown'] = pd.Series([None, None], index=source.index, dtype=object)
    source.attrs['_cartomize_declared_fields'] = {'unknown': kind}
    with pytest.raises(ValueError, match=fragment):
        extract_features(source, filters=[dict(field='unknown', comparison='in', value=[invalid])])


@pytest.mark.parametrize('comparison,value,selected', [
    ('ge', '2026-02-01', [1, 3, 4]), ('eq', date(2026, 3, 1), [3]),
    ('in', ['2026-01-01', date(2026, 3, 1), None], [0, 2, 3, 5]),
    ('not_in', ['2026-01-01'], [1, 3, 4]), ('is_null', None, [2, 5]),
])
def test_native_date_filters_and_membership(comparison, value, selected):
    source = records()
    result = extract_features(source, filters=[dict(field='visit_date', comparison=comparison, value=value)])
    assert_partition(source, result, selected)
    assert_geodataframe_equal(select_attributes(source, 'visit_date', comparison, value), result.data)


@pytest.mark.parametrize('value', ['2026-01-01T00:00:00', '2026-01-01T12:00:00Z',
                                  datetime(2026, 1, 1), pd.Timestamp('2026-01-01'), 20260101])
def test_date_filter_never_truncates_a_time_or_invents_a_calendar_date(value):
    with pytest.raises(ValueError, match='date'):
        extract_features(records(), filters=[dict(field='visit_date', comparison='eq', value=value)])


def test_native_date_file_roundtrip_and_empty_date_schema(tmp_path):
    source = gpd.GeoDataFrame({'day': pd.Series([date(2026, 1, 1), None, date(2026, 2, 1)], dtype=object),
                               'unknown_day': pd.Series([None] * 3, dtype=object)},
                              geometry=[Point(i, 0) for i in range(3)], crs=3857)
    source.attrs['_cartomize_temporal_fields'] = {'day': 'date', 'unknown_day': 'date'}
    filename = tmp_path / 'native.gpkg'
    write_geopackage(source, filename, layer='observations')
    loaded = read_vector(filename, layer='observations')
    result = extract_features(filename, filters=[dict(field='day', comparison='ge', value='2026-02-01')])
    assert_partition(loaded, result, [2])
    assert result.summary['parameters']['layer'] == 'observations'
    with pytest.raises(ValueError, match='date'):
        extract_features(filename, filters=[dict(field='unknown_day', comparison='eq', value='2026-01-01T01:00:00')])


@pytest.mark.parametrize('aware', [False, True])
def test_timestamp_objects_preserve_nanoseconds_and_timezone_awareness(aware):
    base = pd.Timestamp('2026-01-01T12:00:00.000000001' + ('+01:00' if aware else ''))
    source = records().iloc[:3].copy()
    source['instant'] = pd.Series([base, base + pd.Timedelta(1, 'ns'), None], index=source.index, dtype=object)
    result = extract_features(source, filters=[dict(field='instant', comparison='eq', value=base.isoformat())])
    assert_partition(source, result, [0])
    result = extract_features(source, filters=[dict(field='instant', comparison='in', value=[(base + pd.Timedelta(1, 'ns')).isoformat()])])
    assert_partition(source, result, [1])
    inconsistent = base.tz_localize(None) if aware else base.tz_localize('UTC')
    with pytest.raises(ValueError, match='timezone awareness'):
        extract_features(source, filters=[dict(field='instant', comparison='eq', value=inconsistent)])


def test_timezone_aware_comparisons_match_instants_without_normalizing_source():
    source = records().iloc[:2].copy()
    source['instant'] = pd.Series([pd.Timestamp('2026-01-01T12:00:00+01:00'),
                                  pd.Timestamp('2026-01-01T12:00:00Z')], index=source.index, dtype=object)
    result = extract_features(source, filters=[dict(field='instant', comparison='eq', value='2026-01-01T11:00:00Z')])
    assert_partition(source, result, [0])


@pytest.mark.parametrize('value', ['now', 'today', '12:00', '01/02/2026', '2026/01/02',
                                  'January 2 2026', '2026-01-01T12:00:00.1234567891'])
@pytest.mark.parametrize('comparison', ['eq', 'in'])
def test_timestamp_filters_refuse_relative_ambiguous_and_overprecise_text(value, comparison):
    source = records().iloc[:2].copy()
    source['instant'] = pd.Series([pd.Timestamp('2026-01-01'), None], index=source.index, dtype=object)
    with pytest.raises(ValueError, match='ISO'):
        extract_features(source, filters=[dict(field='instant', comparison=comparison,
                                               value=[value] if comparison == 'in' else value)])


@pytest.mark.parametrize('value', ['2026-01-01T11:00:00.123456789Z',
                                  '2026-01-01 12:30:00.123456789+01:30',
                                  '2026-01-01T06:00:00.123456789-0500'])
def test_iso_offset_timestamp_text_retains_every_nanosecond(value):
    source = records().iloc[:2].copy()
    source['instant'] = pd.Series([pd.Timestamp('2026-01-01T12:30:00.123456789+01:30'),
                                  pd.Timestamp('2026-01-01T12:30:00.123456788+01:30')],
                                 index=source.index, dtype=object)
    result = extract_features(source, filters=[dict(field='instant', comparison='in', value=[value])])
    assert_partition(source, result, [0])


def test_missing_and_empty_geometries_have_reasons_and_are_invertible():
    source = records()
    result = extract_features(source, mask=mask())
    assert_partition(source, result, [0, 2])
    assert result.report.reason.tolist() == ['selected', 'spatial_no_match', 'selected',
                                            'spatial_no_match', 'missing_geometry', 'empty_geometry']
    assert result.report.attribute_match.isna().all()
    inverted = extract_features(source, mask=mask(), invert=True)
    assert_partition(source, inverted, [1, 3, 4, 5])


@pytest.mark.parametrize('predicate', ['intersects', 'within', 'contains', 'covers', 'covered_by',
                                      'touches', 'overlaps', 'crosses', 'disjoint'])
def test_predicates_keep_existing_union_semantics(predicate):
    source = records()
    result = extract_features(source, mask=mask(), predicate=predicate)
    assert_geodataframe_equal(result.data, select_location(source, mask(), predicate=predicate))


def test_union_is_evaluated_as_a_whole_including_internal_mask_boundaries():
    source = gpd.GeoDataFrame({'record': ['across seam', 'outer boundary', 'outside']},
                              geometry=[LineString([(0.5, 1), (1.5, 1)]), Point(0, 1), Point(3, 1)], crs=3857)
    region = gpd.GeoDataFrame(geometry=[box(0, 0, 1, 2), box(1, 0, 2, 2), None, GeometryCollection()], crs=3857)
    within = extract_features(source, mask=region, predicate='within')
    assert_partition(source, within, [0])
    covered = extract_features(source, mask=region, predicate='covered_by')
    assert_partition(source, covered, [0, 1])
    assert covered.summary['mask']['usable_features'] == 2
    assert covered.summary['mask']['missing_geometries'] == 1
    assert covered.summary['mask']['empty_geometries'] == 1


def test_spatial_mask_is_reprojected_without_reprojecting_source_records():
    source = gpd.GeoDataFrame({'name': ['origin', 'outside']}, geometry=[Point(0, 0, 5), Point(1_000_000, 0, 7)], crs=3857)
    region = gpd.GeoDataFrame(geometry=[box(-1, -1, 1, 1)], crs=4326)
    before = region.copy()
    result = extract_features(source, mask=region)
    assert_partition(source, result, [0])
    assert_geodataframe_equal(region, before)
    assert result.summary['mask']['original_crs'] == 'EPSG:4326'
    assert result.summary['mask']['aligned_crs'] == 'EPSG:3857'


@pytest.mark.parametrize('predicate,rows', [('intersects', []), ('within', []), ('disjoint', [0, 1, 2, 3])])
def test_empty_mask_has_explicit_set_semantics(predicate, rows):
    source = records()
    region = gpd.GeoDataFrame(geometry=[None, GeometryCollection()], crs=3857)
    result = extract_features(source, mask=region, predicate=predicate)
    assert_partition(source, result, rows)
    assert result.summary['mask']['union_empty'] is True


def test_empty_source_returns_typed_empty_partition_and_complete_summary():
    source = records().iloc[:0].copy()
    result = extract_features(source, filters=[dict(field='visit_date', comparison='ge', value='2026-01-01')], mask=mask())
    assert_partition(source, result, [])
    assert result.report.output_row.dtype == 'Int64'
    assert result.report.attribute_match.dtype == 'boolean'
    assert result.summary['combinations'] == dict(both=0, attributes_only=0, spatial_only=0, neither=0)


@pytest.mark.parametrize('bad,fragment', [
    (Polygon([(0, 0), (2, 2), (0, 2), (2, 0), (0, 0)]), 'invalid'),
    (Point(float('inf'), 1), 'nonfinite'),
    (Point(1, 1, float('nan')), 'nonfinite'),
])
@pytest.mark.parametrize('where', ['source', 'mask'])
def test_spatial_selection_refuses_invalid_and_nonfinite_coordinates(bad, fragment, where):
    source = gpd.GeoDataFrame({'flag': [True]}, geometry=[bad if where == 'source' else Point(1, 1)], crs=3857)
    region = gpd.GeoDataFrame(geometry=[bad if where == 'mask' else box(0, 0, 2, 2)], crs=3857)
    with pytest.raises(ValueError, match=fragment):
        extract_features(source, mask=region)
    if where == 'source':
        result = extract_features(source, filters=[dict(field='flag', comparison='eq', value=True)])
        assert_partition(source, result, [0])
        assert result.report.geometry_status.tolist() == ['not_evaluated']


def test_explicit_multilayer_selection_for_source_and_mask(tmp_path):
    source = gpd.GeoDataFrame({'name': ['a', 'b']}, geometry=[Point(1, 1), Point(9, 9)], crs=3857)
    filename = tmp_path / 'source.gpkg'
    source.to_file(filename, driver='GPKG', layer='first', index=False)
    source.iloc[:1].to_file(filename, driver='GPKG', layer='second', index=False)
    region_path = tmp_path / 'mask.gpkg'
    mask().to_file(region_path, driver='GPKG', layer='region', index=False)
    mask().to_file(region_path, driver='GPKG', layer='other', index=False)
    with pytest.raises(ValueError, match='multiple layers'):
        extract_features(filename, filters=[dict(field='name', comparison='eq', value='a')])
    with pytest.raises(ValueError, match='multiple layers'):
        extract_features(filename, layer='first', mask=region_path)
    with pytest.raises(ValueError, match='Unknown vector layer'):
        extract_features(filename, layer='unknown', mask=mask())
    result = extract_features(filename, layer='first', mask=region_path, mask_layer='region')
    assert result.data.name.tolist() == ['a']
    assert result.summary['parameters']['layer'] == 'first'
    assert result.summary['parameters']['mask_layer'] == 'region'


@pytest.mark.parametrize('parameters,fragment', [
    ({}, 'at least one'), ({'filters': {}}, 'list'),
    ({'filters': [{'field': 'flag'}]}, 'requires field and comparison'),
    ({'filters': [{'field': 'flag', 'comparison': 'eq'}]}, 'requires a value'),
    ({'filters': [{'field': 'flag', 'comparison': 'eq', 'value': True, 'expression': '1'}]}, 'only'),
    ({'filters': [{'field': 'flag', 'comparison': []}]}, 'comparison name'),
    ({'filters': [{'field': 'missing', 'comparison': 'eq', 'value': 1}]}, 'existing'),
    ({'filters': [{'field': 'shape', 'comparison': 'is_null'}]}, 'attribute'),
    ({'filters': [{'field': 'flag', 'comparison': 'sql', 'value': True}]}, 'Unsupported'),
    ({'attribute_match': 'none'}, 'attribute_match'), ({'combination': 'xor'}, 'combination'),
    ({'predicate': 'nearest'}, 'predicate'), ({'invert': 1}, 'boolean'),
    ({'progress': 1}, 'callable'), ({'mask_layer': 'a'}, 'at least one'),
])
def test_invalid_parameters_fail_explicitly(parameters, fragment):
    with pytest.raises(ValueError, match=fragment):
        extract_features(records(), **parameters)


def test_duplicate_fields_and_nonunique_or_missing_ids_are_rejected():
    source = records()
    filters = [dict(field='flag', comparison='eq', value=True)]
    with pytest.raises(ValueError, match='unique'):
        extract_features(source, filters=filters, id_field='flag')
    with pytest.raises(ValueError, match='nonmissing'):
        extract_features(source, filters=filters, id_field='value')
    source.columns = ['flag' if name == 'name' else name for name in source.columns]
    with pytest.raises(ValueError, match='field names must be unique'):
        extract_features(source, filters=filters)


def test_literal_text_never_becomes_code_or_a_regular_expression():
    source = records()
    for literal in ['.*', '__import__("os")', 'a or 1=1', '${HOME}']:
        result = extract_features(source, filters=[dict(field='name', comparison='contains', value=literal)])
        assert_partition(source, result, [])


@pytest.mark.parametrize('cancel_at', [0, 500, 3000, 5000, 5500, 8000, 10000])
def test_cancellation_at_each_stage_never_returns_a_partition_or_modifies_sources(cancel_at):
    source, region = records(), mask()
    source_before, mask_before = source.copy(), region.copy()
    event = threading.Event()
    seen = []
    def progress(done, total):
        assert total == 10000
        seen.append(done)
        if done >= cancel_at:
            event.set()
    with pytest.raises(ProcessingCancelled):
        extract_features(source, filters=[dict(field='flag', comparison='eq', value=True)],
                         mask=region, progress=progress, cancel=event)
    assert seen == sorted(seen)
    assert_geodataframe_equal(source, source_before)
    assert_geodataframe_equal(region, mask_before)


def test_preexisting_cancellation_wins_before_file_access():
    event = threading.Event()
    event.set()
    with pytest.raises(ProcessingCancelled):
        extract_features('/nonexistent/source.gpkg', mask='/nonexistent/mask.gpkg', cancel=event)
