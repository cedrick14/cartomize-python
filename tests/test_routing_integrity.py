"""Reference distances and topology for point attachment to road networks."""
import hashlib
import importlib
import threading

import geopandas as gpd
import numpy as np
import pytest
from geopandas.testing import assert_geodataframe_equal
from pyproj import CRS
from shapely.geometry import LineString, MultiLineString, Point

import cartomize as cm


def network(*lines, crs=32631):
    return gpd.GeoDataFrame({'road': range(len(lines))},
        geometry=[LineString(line) for line in lines], crs=crs)


@pytest.mark.parametrize('reverse_source', [False, True])
@pytest.mark.parametrize('start,end', [((400, 0), (600, 0)), ((600, 0), (400, 0))])
def test_two_points_on_same_edge_use_only_the_section_between_them(reverse_source, start, end):
    coordinates = [(0, 0), (1000, 0)]
    roads = network(coordinates[::-1] if reverse_source else coordinates)
    route = cm.shortest_path(roads, start, end, max_snap_m=0)
    row = route.iloc[0]
    assert row.distance_m == pytest.approx(200)
    assert row.start_snap_m == row.end_snap_m == 0
    assert row.snap_method == 'edge' and row.route_status == 'ok'
    assert row.nodes == 2
    assert list(row.geometry.coords) == [start, end]
    assert row.geometry.is_valid and route.crs == roads.crs


def test_node_mode_retains_existing_vertex_attachment():
    roads = network([(0, 0), (1000, 0)])
    route = cm.shortest_path(roads, (400, 0), (600, 0), snap='node').iloc[0]
    assert route.distance_m == 1000
    assert route.start_snap_m == route.end_snap_m == 400
    assert route.snap_method == 'node' and route.route_status == 'ok'
    assert list(route.geometry.coords) == [(0, 0), (1000, 0)]
    with pytest.raises(ValueError, match='nœud.*rattachement'):
        cm.shortest_path(roads, (400, 0), (600, 0), snap='node', max_snap_m=399)


def test_attachment_distances_are_excluded_and_tolerance_is_inclusive():
    roads = network([(0, 0), (1000, 0)])
    route = cm.shortest_path(roads, (400, 30), (600, -40), max_snap_m=40).iloc[0]
    assert route.distance_m == pytest.approx(200)
    assert route.start_snap_m == 30 and route.end_snap_m == 40
    assert list(route.geometry.coords) == [(400, 0), (600, 0)]
    with pytest.raises(ValueError, match='segment.*rattachement'):
        cm.shortest_path(roads, (400, 30), (600, -40), max_snap_m=39.9)


def test_projection_beyond_a_segment_reuses_its_endpoints():
    roads = network([(0, 0), (100, 0)])
    route = cm.shortest_path(roads, (-10, 0), (110, 0), max_snap_m=10).iloc[0]
    assert route.distance_m == 100
    assert route.start_snap_m == route.end_snap_m == 10
    assert route.nodes == 2
    assert list(route.geometry.coords) == [(0, 0), (100, 0)]


@pytest.mark.parametrize('reverse_duplicate', [False, True])
def test_different_edges_retain_vertices_and_remove_duplicate_segments(reverse_duplicate):
    coordinates = [(0, 0), (0, 0), (30, 0), (30, 40), (100, 40)]
    duplicate = coordinates[::-1] if reverse_duplicate else coordinates
    roads = network(coordinates, duplicate)
    before = roads.copy(deep=True)
    route = cm.shortest_path(roads, (10, 0), (80, 40), max_snap_m=0,
                             node_intersections=False).iloc[0]
    assert route.distance_m == pytest.approx(110)
    assert list(route.geometry.coords) == [(10, 0), (30, 0), (30, 40), (80, 40)]
    assert route.nodes == 4 and route.geometry.is_valid
    assert_geodataframe_equal(roads, before)


def test_multiline_network_and_shared_endpoint_remain_connected_without_noding():
    roads = gpd.GeoDataFrame(geometry=[MultiLineString([
        [(0, 0), (50, 0), (100, 0)], [(50, 0), (50, 50)]])], crs=32631)
    route = cm.shortest_path(roads, (20, 0), (50, 30), max_snap_m=0,
                             node_intersections=False).iloc[0]
    assert route.distance_m == pytest.approx(60)
    assert list(route.geometry.coords) == [(20, 0), (50, 0), (50, 30)]


@pytest.mark.parametrize('vertical', [[(50, -50), (50, 50)], [(50, 0), (50, 50)]])
def test_crossing_snap_does_not_create_an_implicit_connection(vertical):
    # The horizontal edge sorts first at the equal-distance crossing. In the
    # T case its interior must not reuse the vertical edge's endpoint node.
    roads = network([(0, 0), (100, 0)], vertical)
    with pytest.raises(ValueError, match='déconnectées'):
        cm.shortest_path(roads, (50, 0), (50, 30), max_snap_m=0,
                         node_intersections=False)
    route = cm.shortest_path(roads, (50, 0), (50, 30), max_snap_m=0,
                             node_intersections=True).iloc[0]
    assert route.distance_m == pytest.approx(30)
    assert route.route_status == 'ok'
    assert list(route.geometry.coords) == [(50, 0), (50, 30)]


def test_crossing_can_be_traversed_only_when_noded():
    roads = network([(0, 0), (100, 0)], [(50, -50), (50, 50)])
    with pytest.raises(ValueError, match='déconnectées'):
        cm.shortest_path(roads, (20, 0), (50, 30), max_snap_m=0,
                         node_intersections=False)
    route = cm.shortest_path(roads, (20, 0), (50, 30), max_snap_m=0).iloc[0]
    assert route.distance_m == pytest.approx(60)
    assert list(route.geometry.coords) == [(20, 0), (50, 0), (50, 30)]


def test_partial_collinear_overlap_does_not_connect_unnoded_edges():
    roads = network([(0, 0), (10, 0)], [(5, 0), (15, 0)])
    with pytest.raises(ValueError, match='déconnectées'):
        cm.shortest_path(roads, (2, 0), (12, 0), max_snap_m=0,
                         node_intersections=False)
    route = cm.shortest_path(roads, (2, 0), (12, 0), max_snap_m=0).iloc[0]
    assert route.distance_m == pytest.approx(10)
    assert list(route.geometry.coords) == [(2, 0), (5, 0), (10, 0), (12, 0)]


def test_separate_components_are_reported_without_switching_attachment():
    roads = network([(0, 0), (100, 0)], [(200, 0), (300, 0)])
    with pytest.raises(ValueError, match='déconnectées'):
        cm.shortest_path(roads, (50, 0), (250, 0), max_snap_m=0)


@pytest.mark.parametrize('reverse_order', [False, True])
@pytest.mark.parametrize('reverse_coordinates', [False, True])
def test_equidistant_segments_choose_a_deterministic_canonical_edge(reverse_order, reverse_coordinates):
    lines = [[(0, -1), (100, -1)], [(0, 1), (100, 1)]]
    if reverse_order:
        lines = lines[::-1]
    if reverse_coordinates:
        lines = [line[::-1] for line in lines]
    route = cm.shortest_path(network(*lines), (20, 0), (80, 0), max_snap_m=1).iloc[0]
    assert route.distance_m == pytest.approx(60)
    assert route.start_snap_m == route.end_snap_m == 1
    assert list(route.geometry.coords) == [(20, -1), (80, -1)]


@pytest.mark.parametrize('start,end,snap,expected,attachments', [
    ((400, 30), (400, -40), 'edge', (400, 0), (30, 40)),
    ((400, 0), (400, 0), 'edge', (400, 0), (0, 0)),
    ((-5, 0), (-10, 0), 'edge', (0, 0), (5, 10)),
    ((10, 0), (20, 0), 'node', (0, 0), (10, 20)),
])
def test_coincident_network_attachments_return_a_valid_point(start, end, snap, expected, attachments):
    route = cm.shortest_path(network([(0, 0), (1000, 0)]), start, end, snap=snap).iloc[0]
    assert route.distance_m == 0 and route.nodes == 1
    assert route.route_status == 'coincident' and route.snap_method == snap
    assert route.geometry.geom_type == 'Point' and route.geometry.is_valid
    assert route.geometry.equals(Point(expected))
    assert (route.start_snap_m, route.end_snap_m) == attachments


def test_distinct_nearby_attachments_are_not_rounded_into_a_zero_route():
    start, end = (50., 0.), (50. + 1e-9, 0.)
    route = cm.shortest_path(network([(0, 0), (100, 0)]), start, end, max_snap_m=0).iloc[0]
    assert route.route_status == 'ok' and route.distance_m > 0
    assert route.distance_m == pytest.approx(end[0] - start[0], abs=1e-14)
    assert route.geometry.geom_type == 'LineString' and route.geometry.is_valid


def test_projected_feet_use_metres_for_route_and_attachment_distances():
    roads = network([(1000000, 200000), (1001000, 200000)], crs=2263)
    factor = CRS.from_epsg(2263).axis_info[0].unit_conversion_factor
    route = cm.shortest_path(roads, (1000400, 200010), (1000600, 199980),
                             max_snap_m=20 * factor).iloc[0]
    assert route.distance_m == pytest.approx(200 * factor)
    assert route.start_snap_m == pytest.approx(10 * factor)
    assert route.end_snap_m == pytest.approx(20 * factor)
    assert list(route.geometry.coords) == [(1000400, 200000), (1000600, 200000)]
    with pytest.raises(ValueError, match='rattachement'):
        cm.shortest_path(roads, (1000400, 200010), (1000600, 199980),
                         max_snap_m=19 * factor)


@pytest.mark.parametrize('source_geographic', [False, True])
def test_coordinate_reprojection_and_output_source_crs(source_geographic):
    roads = network([(500000, 1000000), (501000, 1000000)])
    stops = gpd.GeoSeries([Point(500400, 1000000), Point(500600, 1000000)], crs=roads.crs).to_crs(4326)
    start, end = [(point.x, point.y) for point in stops]
    options = dict(points_crs=4326)
    if source_geographic:
        roads = roads.to_crs(4326)
        options = dict(metric_crs=32631)
    before = roads.copy(deep=True)
    route = cm.shortest_path(roads, start, end, max_snap_m=0.001, **options)
    assert route.distance_m.iloc[0] == pytest.approx(200, abs=1e-6)
    assert route.start_snap_m.iloc[0] < 1e-6 and route.end_snap_m.iloc[0] < 1e-6
    assert route.crs == roads.crs
    projected = route.to_crs(32631).geometry.iloc[0]
    np.testing.assert_allclose(projected.coords, [(500400, 1000000), (500600, 1000000)], atol=1e-6, rtol=0)
    assert_geodataframe_equal(roads, before)


def test_invalid_reprojected_coordinates_have_an_explicit_error():
    roads = network([(500000, 0), (501000, 0)])
    with pytest.raises(ValueError, match='transformation.*coordonnées.*non finies'):
        cm.shortest_path(roads, (3, 100), (3, 0), points_crs=4326)


@pytest.mark.parametrize('options,match', [
    ({'snap': 'nearest'}, 'snap'),
    ({'max_snap_m': -1}, 'rattachement'),
    ({'max_snap_m': np.inf}, 'rattachement'),
])
def test_invalid_attachment_options_are_rejected(options, match):
    with pytest.raises(ValueError, match=match):
        cm.shortest_path(network([(0, 0), (100, 0)]), (10, 0), (90, 0), **options)


def test_source_file_is_untouched_and_progress_reaches_completion(tmp_path):
    path = tmp_path / 'roads.gpkg'
    roads = network([(0, 0), (1000, 0)])
    roads.to_file(path, driver='GPKG', index=False)
    before = hashlib.sha256(path.read_bytes()).digest()
    calls = []
    route = cm.shortest_path(path, (400, 0), (600, 0), max_snap_m=0,
                             progress=lambda done, total: calls.append((done, total)))
    assert route.distance_m.iloc[0] == 200
    assert calls[-1] == (1, 1)
    assert hashlib.sha256(path.read_bytes()).digest() == before
    assert_geodataframe_equal(gpd.read_file(path), roads)


def test_cancellation_before_processing():
    event = threading.Event()
    event.set()
    with pytest.raises(cm.ProcessingCancelled):
        cm.shortest_path(network([(0, 0), (100, 0)]), (10, 0), (90, 0), cancel=event)


def test_cancellation_after_spatial_index_construction(monkeypatch):
    routing = importlib.import_module('cartomize.routing')
    real_tree = routing.STRtree
    event = threading.Event()

    def cancelled_tree(*args, **kwargs):
        tree = real_tree(*args, **kwargs)
        event.set()
        return tree

    monkeypatch.setattr(routing, 'STRtree', cancelled_tree)
    with pytest.raises(cm.ProcessingCancelled):
        cm.shortest_path(network([(0, 0), (100, 0)]), (10, 0), (90, 0), cancel=event)


def test_cancellation_before_returning_the_completed_route():
    event = threading.Event()
    with pytest.raises(cm.ProcessingCancelled):
        cm.shortest_path(network([(0, 0), (100, 0)]), (10, 0), (90, 0),
                         cancel=event, progress=lambda done, total: event.set())
