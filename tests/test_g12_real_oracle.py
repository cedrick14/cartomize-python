"""Literal independent checks for the G12 arithmetic buffer-area references."""
import importlib.util
import math
from pathlib import Path
import sys

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
try:
    spec = importlib.util.spec_from_file_location("g12_real_oracle", SCRIPTS / "validate_vector_rings_real.py")
    oracle = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(oracle)
finally:
    sys.path.remove(str(SCRIPTS))


@pytest.mark.parametrize("radius,segments,expected", [
    (0, 1, 0), (1, 1, 2), (2, 1, 8), (3, 1, 18),
    (1, 2, 2 * math.sqrt(2)), (2, 2, 8 * math.sqrt(2)),
])
def test_disk_area_uses_regular_polygon_not_exact_circle(radius, segments, expected):
    assert oracle.regular_disk_area(radius, segments) == pytest.approx(expected)


def test_disk_areas_increase_to_circle_area_as_segments_increase():
    areas = [oracle.regular_disk_area(17, segments) for segments in (1, 2, 4, 16, 64, 1024)]
    assert areas == sorted(areas)
    assert all(value < math.pi * 17**2 for value in areas)
    assert math.pi * 17**2 - areas[-1] < 0.0004


@pytest.mark.parametrize("length,radius,expected", [(10, 0, 0), (10, 2, 48), (10, 4, 112), (0, 2, 8)])
def test_straight_capsule_area_separates_strip_and_end_caps(length, radius, expected):
    assert oracle.segment_buffer_area(length, radius, 1) == pytest.approx(expected)


@pytest.mark.parametrize("radius,expected", [(0, 24), (2, 72), (4, 136)])
def test_rectangle_perimeter_expansion_and_corner_area(radius, expected):
    assert oracle.rectangle_buffer_area(4, 6, radius, 1) == pytest.approx(expected)


@pytest.mark.parametrize("radius,expected", [(0, 232), (1, 326), (2, 416), (3, 502), (4, 584)])
def test_rectangular_hole_shrinks_then_disappears(radius, expected):
    assert oracle.perforated_rectangle_buffer_area(20, 14, 8, 6, radius, 1) == pytest.approx(expected)


def test_ring_areas_telescope_with_and_without_source_interior():
    cumulative = lambda radius: oracle.rectangle_buffer_area(4, 6, radius, 1)
    assert oracle.arithmetic_bands(cumulative, [2, 4]) == [48, 64]
    assert oracle.arithmetic_bands(cumulative, [2, 4], include_input=True) == [72, 64]
    disk = lambda radius: oracle.regular_disk_area(radius, 1)
    assert oracle.arithmetic_bands(disk, [2, 4]) == [8, 24]
    assert oracle.arithmetic_bands(disk, [2, 4], include_input=True) == [8, 24]


@pytest.mark.parametrize("value", [-1, math.inf, -math.inf, math.nan, True])
def test_nonfinite_negative_or_boolean_lengths_are_refused(value):
    with pytest.raises(ValueError, match="finite nonnegative"):
        oracle.regular_disk_area(value)
    with pytest.raises(ValueError, match="finite nonnegative"):
        oracle.segment_buffer_area(value, 2)


@pytest.mark.parametrize("segments", [0, -1, 1.5, True, "16"])
def test_subdivision_must_be_a_positive_integer(segments):
    with pytest.raises(ValueError, match="positive integer"):
        oracle.regular_disk_area(3, segments)


@pytest.mark.parametrize("distances", [[], [0], [-1], [1, 1], [2, 1], [1, math.inf], [True]])
def test_band_bounds_must_be_nonempty_positive_and_ordered(distances):
    with pytest.raises(ValueError):
        oracle.arithmetic_bands(oracle.regular_disk_area, distances)


@pytest.mark.parametrize("width,height,hole_width,hole_height", [
    (0, 4, 1, 1), (4, 0, 1, 1), (4, 4, 4, 2), (4, 4, 2, 4), (4, 4, 0, 2), (4, 4, 2, 0),
])
def test_invalid_rectangle_or_hole_dimensions_are_refused(width, height, hole_width, hole_height):
    with pytest.raises(ValueError):
        oracle.perforated_rectangle_buffer_area(width, height, hole_width, hole_height, 1)
