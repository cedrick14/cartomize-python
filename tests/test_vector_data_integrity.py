"""Reference cases for identifiers, missing measurements and survey joins."""
import numpy as np
import pandas as pd
import geopandas as gpd
from geopandas.testing import assert_geodataframe_equal
from shapely.geometry import Point, box
import pytest

from cartomize.vector_workflows import select_attributes, spatial_summary, join_attributes


def points_with(values, dtype, *, column='identifier'):
    return gpd.GeoDataFrame(
        {column: pd.Series(values, dtype=dtype), 'record': list(range(len(values)))},
        geometry=[Point(i, 0) for i in range(len(values))], crs=32631)


@pytest.mark.parametrize('dtype,base', [('int64', 2**53), ('Int64', 2**53),
                                     ('uint64', 2**64-3), ('UInt64', 2**64-3)])
@pytest.mark.parametrize('comparison,expected', [('eq', [1]), ('ne', [0, 2]),
                                               ('lt', [0]), ('le', [0, 1]),
                                               ('gt', [2]), ('ge', [1, 2])])
def test_exact_integer_identifiers_and_text_thresholds(dtype, base, comparison, expected):
    values = [base, base+1, base+2] + ([None] if dtype[0].isupper() else [])
    source = points_with(values, dtype)
    original = source.copy()
    result = select_attributes(source, 'identifier', comparison, str(base+1))
    assert result['record'].tolist() == expected
    assert result['identifier'].dtype == source['identifier'].dtype
    assert result.crs == source.crs
    assert_geodataframe_equal(source, original)


@pytest.mark.parametrize('text', ['9007199254740993.0', '9.007199254740993e15'])
def test_exact_decimal_and_scientific_notation_for_identifiers(text):
    source = points_with([2**53, 2**53+1, None], 'Int64')
    assert select_attributes(source, 'identifier', 'eq', text)['record'].tolist() == [1]


@pytest.mark.parametrize('comparison,expected', [('eq', []), ('ne', [0, 1, 2]),
                                               ('lt', [0]), ('le', [0]),
                                               ('gt', [1, 2]), ('ge', [1, 2])])
def test_fractional_threshold_does_not_round_to_large_neighbour(comparison, expected):
    source = points_with([2**53, 2**53+1, 2**53+2, None], 'Int64')
    result = select_attributes(source, 'identifier', comparison, '9007199254740992.5')
    assert result['record'].tolist() == expected


def test_unsigned_boundaries_empty_fields_and_out_of_range_thresholds():
    source = points_with([0, 2**64-1, None], 'UInt64')
    assert select_attributes(source, 'identifier', 'gt', '-0.5')['record'].tolist() == [0, 1]
    assert select_attributes(source, 'identifier', 'le', '-0.5').empty
    assert select_attributes(source, 'identifier', 'lt', '18446744073709551615.5')['record'].tolist() == [0, 1]
    assert select_attributes(source, 'identifier', 'ge', '18446744073709551615.5').empty
    assert select_attributes(source, 'identifier', 'lt', '1e10000')['record'].tolist() == [0, 1]
    assert select_attributes(source, 'identifier', 'gt', '-1e10000')['record'].tolist() == [0, 1]
    for values in [[], [None, None]]:
        empty = points_with(values, 'Int64')
        assert select_attributes(empty, 'identifier', 'eq', '1').empty
        assert select_attributes(empty, 'identifier', 'ne', '1').empty


def test_integer_membership_preserves_large_values_and_missing_policy():
    source = points_with([0, 2**63, 2**64-2, 2**64-1, None], 'UInt64')
    choices = ['0', str(2**64-1), '0.5', '-1', '1e10000']
    assert select_attributes(source, 'identifier', 'in', choices)['record'].tolist() == [0, 3]
    assert select_attributes(source, 'identifier', 'not_in', choices)['record'].tolist() == [1, 2]
    assert select_attributes(source, 'identifier', 'in', [pd.NA, str(2**64-1)])['record'].tolist() == [3, 4]


@pytest.mark.parametrize('value', ['not a number', 'NaN', 'Infinity', '-Infinity'])
def test_integer_filter_errors_are_explicit(value):
    source = points_with([1, None], 'Int64')
    with pytest.raises(ValueError, match='finite'):
        select_attributes(source, 'identifier', 'eq', value)
    with pytest.raises(ValueError, match='finite'):
        select_attributes(source, 'identifier', 'in', [value])
    with pytest.raises(ValueError, match='missing values'):
        select_attributes(source, 'identifier', 'eq', None)


def test_boolean_datetime_and_float_filters_keep_their_meaning():
    source = points_with([True, False, None], 'boolean', column='flag')
    assert select_attributes(source, 'flag', 'eq', True)['record'].tolist() == [0]
    with pytest.raises(ValueError, match='Boolean'):
        select_attributes(source, 'flag', 'eq', 'true')
    source['date'] = pd.to_datetime(['2026-01-01', '2026-02-01', None])
    assert select_attributes(source, 'date', 'ge', '2026-02-01')['record'].tolist() == [1]
    source['measurement'] = pd.Series([1.5, 2.5, None], dtype='Float64')
    assert select_attributes(source, 'measurement', 'gt', '1.75')['record'].tolist() == [1]


@pytest.mark.parametrize('dtype', ['float64', 'Float64', 'Int64'])
def test_zonal_sum_distinguishes_unknown_zero_and_no_observation(dtype):
    zones = gpd.GeoDataFrame({'zone': ['unknown', 'zero', 'measured', 'empty']},
                            geometry=[box(i*10, 0, i*10+9, 9) for i in range(4)],
                            crs=32631, index=[3, 3, 8, 10])
    observations = gpd.GeoDataFrame(
        {'production': pd.Series([None, None, 0, 2, 3], dtype=dtype)},
        geometry=[Point(1, 1), Point(2, 2), Point(11, 1), Point(21, 1), Point(22, 2)], crs=32631)
    original = observations.copy()
    result = spatial_summary(zones, observations, field='production', statistic='sum')
    assert pd.isna(result['sum_production'].iloc[0])
    assert result['sum_production'].iloc[1:].tolist() == [0, 5, 0]
    assert result.index.tolist() == [3, 3, 8, 10]
    assert result['zone'].tolist() == zones['zone'].tolist()
    assert_geodataframe_equal(observations, original)


@pytest.fixture
def survey_sources():
    source = points_with([2, None, 1, None, 9, 9], 'Int64')
    source['name'] = ['B', 'unknown-1', 'A', 'unknown-2', 'unmatched-1', 'unmatched-2']
    table = pd.DataFrame({'code': pd.Series([1, None, 2, None, 8, 8], dtype='Int64'),
                          'population': [100, 500, 200, 600, 800, 900]})
    return source, table


@pytest.mark.parametrize('how,expected_records', [('left', [0, 1, 2, 3, 4, 5]), ('inner', [0, 2])])
def test_null_keys_are_unmatched_and_only_matchable_keys_control_cardinality(survey_sources, how, expected_records):
    source, table = survey_sources
    original_source, original_table = source.copy(), table.copy()
    result = join_attributes(source, table, left_on='identifier', right_on='code',
                             how=how, validate='one_to_one')
    assert result['record'].tolist() == expected_records
    assert result.set_index('record')['population'].loc[[0, 2]].tolist() == [200, 100]
    if how == 'left':
        assert result.set_index('record')['population'].loc[[1, 3, 4, 5]].isna().all()
        assert result['name'].tolist() == source['name'].tolist()
        assert result.geometry.equals(source.geometry)
    assert result.crs == source.crs
    assert_geodataframe_equal(source, original_source)
    pd.testing.assert_frame_equal(table, original_table)


def test_explicit_null_match_preserves_all_correspondences_and_order(survey_sources):
    source, table = survey_sources
    result = join_attributes(source, table, left_on='identifier', right_on='code',
                             validate='many_to_many', null_keys='match')
    assert result['record'].tolist() == [0, 1, 1, 2, 3, 3, 4, 5]
    assert result.loc[result['record'].eq(1), 'population'].tolist() == [500, 600]
    with pytest.raises(pd.errors.MergeError):
        join_attributes(source, table, left_on='identifier', right_on='code', null_keys='match')


def test_matchable_duplicate_keys_still_enforce_cardinality():
    source = points_with([1, 1, 2, None], 'Int64')
    table = pd.DataFrame({'identifier': pd.Series([1, 2, 2, None], dtype='Int64'),
                          'survey': ['first-1', 'first-2', 'second-2', 'unknown']})
    for cardinality in ['one_to_one', 'one_to_many', 'many_to_one']:
        with pytest.raises(pd.errors.MergeError, match='not unique'):
            join_attributes(source, table, left_on='identifier', validate=cardinality)
    result = join_attributes(source, table, left_on='identifier', validate='many_to_many')
    assert result['record'].tolist() == [0, 1, 2, 2, 3]
    assert result.loc[result['record'].eq(2), 'survey'].tolist() == ['first-2', 'second-2']
    assert pd.isna(result['survey'].iloc[-1])


@pytest.mark.parametrize('side', ['left', 'right', 'both'])
def test_error_policy_rejects_missing_keys_on_either_side(survey_sources, side):
    source, table = survey_sources
    if side == 'left':
        table = table.dropna(subset=['code'])
    elif side == 'right':
        source = source.dropna(subset=['identifier'])
    with pytest.raises(ValueError, match='missing values'):
        join_attributes(source, table, left_on='identifier', right_on='code', null_keys='error')
    with pytest.raises(ValueError, match='null_keys'):
        join_attributes(source, table, left_on='identifier', right_on='code', null_keys='automatic')


def test_empty_table_and_all_missing_keys_keep_left_records():
    source = points_with([None, None], 'Int64')
    table = pd.DataFrame({'identifier': pd.Series([None, None], dtype='Int64'), 'value': [7, 8]})
    for right in [table, table.iloc[:0]]:
        result = join_attributes(source, right, left_on='identifier', validate='one_to_one')
        assert result['record'].tolist() == [0, 1]
        assert result['value'].isna().all()
        assert join_attributes(source, right, left_on='identifier', how='inner').empty
