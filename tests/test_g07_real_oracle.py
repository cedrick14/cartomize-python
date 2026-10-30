"""Check the independent acceptance oracle with literal geometric expectations."""
import importlib.util
from pathlib import Path
import sys

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
try:
    spec = importlib.util.spec_from_file_location('g07_real_oracle', SCRIPTS / 'validate_vector_selection_real.py')
    oracle = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(oracle)
finally:
    sys.path.remove(str(SCRIPTS))


@pytest.mark.parametrize('point,expected', [
    ((1, 1), True), ((5, 5), False), ((-1, 1), False),
    ((0, 0), False), ((0, 3), False), ((3, 3), False),
    ((4, 3), False), ((10, 5), False), ((8, 8), True),
])
def test_strict_polygon_membership_includes_holes_and_boundaries(point, expected):
    mask = {'type': 'Polygon', 'coordinates': [
        [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]],
        [[3, 3], [7, 3], [7, 7], [3, 7], [3, 3]],
    ]}
    assert oracle.point_within(point, mask) is expected
    # Reversing either ring must not change strict membership.
    mask['coordinates'] = [list(reversed(ring)) for ring in mask['coordinates']]
    assert oracle.point_within(point, mask) is expected


def test_multipolygon_membership_keeps_distinct_parts():
    mask = {'type': 'MultiPolygon', 'coordinates': [
        [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]],
        [[[4, 0], [6, 0], [6, 2], [4, 2], [4, 0]]],
    ]}
    assert oracle.point_within((1, 1), mask)
    assert oracle.point_within((5, 1), mask)
    assert not oracle.point_within((3, 1), mask)
    assert not oracle.point_within((4, 1), mask)


def test_oracle_refuses_unsupported_mask_geometry():
    with pytest.raises(ValueError, match='polygon masks only'):
        oracle.point_within((0, 0), {'type': 'LineString', 'coordinates': [[0, 0], [1, 1]]})
