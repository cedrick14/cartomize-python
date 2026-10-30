"""Regression tests for vector persistence comparisons used by acceptance."""
from datetime import date, datetime
import importlib.util
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Point, MultiPolygon, box


@pytest.fixture
def compare():
    path = Path(__file__).parents[1] / 'scripts' / 'project_comparisons.py'
    spec = importlib.util.spec_from_file_location('project_comparisons', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.same


@pytest.fixture
def frame():
    result = gpd.GeoDataFrame({'id': [1, 2], 'count': [3, 4]},
                              geometry=[Point(0, 0), Point(1, 1)], crs=2154)
    result['total'] = [12.5, 15.0]
    return result


def test_geometry_column_position_is_not_a_data_error(compare, frame):
    compare(frame[['id', 'count', 'total', 'geometry']], frame)


def test_round_trip_geopackage(compare, frame, tmp_path):
    path = tmp_path / 'results.gpkg'
    frame.to_file(path, driver='GPKG', index=False)
    compare(gpd.read_file(path), frame)


def test_singleton_multi_promotion_preserves_geometry(compare):
    polygon = box(0, 0, 10, 10)
    original = gpd.GeoDataFrame({'id': [1]}, geometry=[polygon], crs=2154)
    reloaded = original.set_geometry([MultiPolygon([polygon])])
    compare(reloaded, original)


def test_additional_parts_are_never_discarded(compare):
    polygon = box(0, 0, 10, 10)
    original = gpd.GeoDataFrame({'id': [1]}, geometry=[polygon], crs=2154)
    changed = original.set_geometry([MultiPolygon([polygon, box(20, 20, 21, 21)])])
    with pytest.raises(AssertionError):
        compare(changed, original)


@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('representation', ['datetime64', 'python', 'numpy'])
def test_native_date_matches_only_exact_naive_midnight_without_mutation(
        compare, frame, reverse, representation):
    original = frame.copy()
    original['visit_date'] = pd.Series([date(2024, 2, 29), None], dtype=object)
    reloaded = frame.copy()
    if representation == 'datetime64':
        reloaded['visit_date'] = pd.Series(['2024-02-29', None], dtype='datetime64[ms]')
    else:
        value = (datetime(2024, 2, 29) if representation == 'python'
                 else np.datetime64('2024-02-29T00:00:00.000000000'))
        reloaded['visit_date'] = pd.Series([value, pd.NaT], dtype=object)
    original_copy, reloaded_copy = original.copy(deep=True), reloaded.copy(deep=True)

    compare(reloaded, original) if reverse else compare(original, reloaded)

    pd.testing.assert_frame_equal(original, original_copy, check_exact=True)
    pd.testing.assert_frame_equal(reloaded, reloaded_copy, check_exact=True)


@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('changed', [
    pd.Timestamp('2024-03-01'),
    pd.Timestamp('2024-02-29T01:00:00'),
    pd.Timestamp('2024-02-29T00:00:00.000001'),
    pd.Timestamp('2024-02-29T00:00:00.000000001'),
    pd.Timestamp('2024-02-29T00:00:00Z'),
    pd.Timestamp('2024-02-29T00:00:00+01:00'),
    '2024-02-29',
    '2024-02-29T00:00:00.000',
    None,
], ids=['different-day', 'hour', 'microsecond', 'nanosecond', 'utc',
        'timezone-offset', 'date-text', 'timestamp-text', 'missing-date'])
def test_date_normalization_never_hides_temporal_changes(compare, frame, reverse, changed):
    original = frame.copy()
    original['visit_date'] = pd.Series([date(2024, 2, 29), None], dtype=object)
    reloaded = frame.copy()
    reloaded['visit_date'] = pd.Series([changed, pd.NaT], dtype=object)
    with pytest.raises(AssertionError):
        compare(reloaded, original) if reverse else compare(original, reloaded)


@pytest.mark.parametrize('reverse', [False, True])
def test_date_normalization_keeps_missing_values_significant(compare, frame, reverse):
    original = frame.copy()
    original['visit_date'] = pd.Series([date(2024, 2, 29), None], dtype=object)
    reloaded = frame.copy()
    reloaded['visit_date'] = pd.Series(['2024-02-29', '2024-03-01'], dtype='datetime64[ms]')
    with pytest.raises(AssertionError):
        compare(reloaded, original) if reverse else compare(original, reloaded)


def test_date_normalization_preserves_real_timestamps_and_exact_precision(compare, frame):
    original = frame.copy()
    original['visit_date'] = pd.Series([date(2024, 2, 29), None], dtype=object)
    original['observed_at'] = pd.Series([pd.Timestamp('2024-02-29T12:34:56.123456789'), pd.NaT])
    reloaded = original.copy(deep=True)
    reloaded['visit_date'] = pd.Series(['2024-02-29', None], dtype='datetime64[ms]')
    timestamps = reloaded['observed_at'].copy(deep=True)
    compare(original, reloaded)
    pd.testing.assert_series_equal(reloaded['observed_at'], timestamps, check_exact=True)
    reloaded.loc[0, 'observed_at'] += pd.Timedelta(nanoseconds=1)
    with pytest.raises(AssertionError):
        compare(original, reloaded)


@pytest.mark.parametrize('change', ['value', 'float_value', 'missing_field',
                                    'attribute_order', 'row_order', 'crs', 'geometry'])
def test_real_differences_are_rejected(compare, frame, change):
    modified = frame.copy()
    if change == 'value':
        modified.loc[0, 'count'] += 1
    elif change == 'float_value':
        modified.loc[0, 'total'] += 1e-8
    elif change == 'missing_field':
        modified = modified.drop(columns='count')
    elif change == 'attribute_order':
        modified = modified[['count', 'id', 'geometry', 'total']]
    elif change == 'row_order':
        modified = modified.iloc[::-1]
    elif change == 'crs':
        modified = modified.set_crs(32631, allow_override=True)
    else:
        modified.loc[0, 'geometry'] = Point(20, 20)
    with pytest.raises(AssertionError):
        compare(modified, frame)
