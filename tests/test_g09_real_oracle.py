"""Literal geometric checks for the independent Python area/clipping oracle."""
import importlib.util
from pathlib import Path
import sys

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
try:
    spec = importlib.util.spec_from_file_location('g09_real_oracle', SCRIPTS / 'validate_vector_tabulation_real.py')
    oracle = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(oracle)
finally:
    sys.path.remove(str(SCRIPTS))


SQUARE = [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]


@pytest.mark.parametrize('bounds,expected', [
    (None, 100), ((0, 0, 10, 10), 100), ((2, 3, 8, 7), 24),
    ((-3, -2, 4, 5), 20), ((11, 0, 12, 10), 0), ((10, 0, 20, 10), 0),
    ((5, -1, 5, 11), 0), ((-1, -1, 11, 11), 100),
])
def test_rectangle_clipping_and_orientation(bounds, expected):
    assert oracle.ring_area(SQUARE, bounds) == pytest.approx(expected)
    assert oracle.ring_area(list(reversed(SQUARE)), bounds) == pytest.approx(expected)
    assert oracle.ring_area(SQUARE[:-1], bounds) == pytest.approx(expected)


@pytest.mark.parametrize('bounds,expected', [
    (None, 84), ((3, 3, 7, 7), 0), ((0, 0, 5, 10), 42),
    ((2, 2, 8, 8), 20), ((4, 0, 6, 10), 12),
])
def test_polygon_holes_are_subtracted_after_clipping(bounds, expected):
    hole = [[3, 3], [7, 3], [7, 7], [3, 7], [3, 3]]
    geometry = {'type': 'Polygon', 'coordinates': [SQUARE, hole]}
    assert oracle.polygon_area(geometry, bounds) == pytest.approx(expected)
    geometry['coordinates'] = [list(reversed(ring)) for ring in geometry['coordinates']]
    assert oracle.polygon_area(geometry, bounds) == pytest.approx(expected)


def test_concave_clipped_polygon_can_have_disconnected_intersections():
    # U shape: clipping its upper half leaves two disconnected rectangles.
    ring = [[0, 0], [6, 0], [6, 6], [4, 6], [4, 2], [2, 2], [2, 6], [0, 6], [0, 0]]
    assert oracle.ring_area(ring) == 28
    assert oracle.ring_area(ring, (-1, 3, 7, 7)) == 12
    assert oracle.ring_area(ring, (2, 3, 4, 7)) == 0


def test_triangle_intersections_and_large_projected_origin():
    triangle = [[0, 0], [8, 0], [0, 8], [0, 0]]
    assert oracle.ring_area(triangle, (0, 0, 4, 8)) == 24
    assert oracle.ring_area(triangle, (0, 0, 4, 4)) == 16
    offset = [(x + 3750000, y + 2890000) for x, y in triangle]
    assert oracle.ring_area(offset) == 32
    assert oracle.ring_area(offset, (3750000, 2890000, 3750004, 2890008)) == 24


def test_multipolygon_area_and_empty_polygons():
    shifted = [[x + 20, y] for x, y in SQUARE]
    geometry = {'type': 'MultiPolygon', 'coordinates': [[SQUARE], [shifted]]}
    assert oracle.polygon_area(geometry) == 200
    assert oracle.polygon_area(geometry, (5, -1, 25, 11)) == 100
    assert oracle.polygon_area({'type': 'Polygon', 'coordinates': []}) == 0
    assert oracle.polygon_area({'type': 'MultiPolygon', 'coordinates': []}) == 0


@pytest.mark.parametrize('bounds', [(4, 0, 3, 1), (0, 2, 1, 1), (0, 0, float('nan'), 1), (0, 1, 2)])
def test_invalid_bounds_are_refused(bounds):
    with pytest.raises(ValueError, match='bounds'):
        oracle.ring_area(SQUARE, bounds)


def test_nonfinite_coordinates_and_nonpolygon_inputs_are_refused():
    with pytest.raises(ValueError, match='finite'):
        oracle.ring_area([(0, 0), (1, float('inf')), (1, 0)])
    with pytest.raises(ValueError, match='Polygon'):
        oracle.polygon_area({'type': 'LineString', 'coordinates': [(0, 0), (1, 1)]})
