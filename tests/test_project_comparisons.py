"""Regression tests for vector persistence comparisons used by acceptance."""
import importlib.util
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import Point


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
