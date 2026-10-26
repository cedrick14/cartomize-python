"""Independent area, network and identity checks for expert procedure G02."""
import threading

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import shapely
from geopandas.testing import assert_geodataframe_equal
from shapely.geometry import LineString, MultiLineString, Point, Polygon, box

from cartomize.vector_topology import check_topology
from cartomize.algebra import ProcessingCancelled


def layer(geometries, ids=None, crs=32733):
    attributes = {} if ids is None else {"id": ids}
    return gpd.GeoDataFrame(attributes, geometry=geometries, crs=crs)


def test_polygon_duplicates_overlaps_and_boundary_contacts_have_distinct_rules():
    data = layer([box(0, 0, 2, 2), box(1, 0, 3, 2), box(3, 0, 4, 2),
                  Polygon([(0, 0), (0, 2), (2, 2), (2, 0), (0, 0)])],
                 [2**53 + 1, 2**53 + 2, 2**53 + 3, 2**53 + 4])
    data.index = [9, 9, 9, 9]
    original = data.copy()
    result = check_topology(data, id_field="id")
    assert result.summary["counts"] == {"duplicates": 1, "overlaps": 3}
    areas = sorted(result.report.loc[result.report.rule == "overlaps", "area_m2"])
    assert areas == [2, 2, 4]
    duplicate = result.report.loc[result.report.rule == "duplicates"].iloc[0]
    assert duplicate.feature_id == 2**53 + 1
    assert duplicate.feature_id_other == 2**53 + 4
    assert duplicate.source_row == 0 and duplicate.source_row_other == 3
    assert 2 not in result.report.source_row.tolist()
    assert 2 not in result.report.source_row_other.tolist()
    assert result.data.crs == data.crs
    assert_geodataframe_equal(data, original)


def test_reference_holes_allowed_gaps_outside_and_minimum_area_are_measurable():
    reference = layer([Polygon([(0, 0), (10, 0), (10, 10), (0, 10)],
                               holes=[[(4, 4), (6, 4), (6, 6), (4, 6)]])])
    # 96 m² of reference, 40 m² covered; 56 m² gap minus 20 m² allowed.
    data = layer([box(-1, 0, 4, 10)], ["west"])
    allowed = layer([box(8, 0, 10, 10)])
    result = check_topology(data, id_field="id", reference=reference, allowed_gaps=allowed)
    assert result.summary["reference_area_m2"] == 96
    assert result.summary["allowed_gap_area_m2"] == 20
    assert result.report.loc[result.report.rule == "gaps", "area_m2"].sum() == 36
    assert result.report.loc[result.report.rule == "outside", "area_m2"].sum() == 10
    # Gap has no invented source ID. The actual source has an exact text key.
    assert result.report.loc[result.report.rule == "gaps", "feature_id"].isna().all()
    assert result.report.loc[result.report.rule == "outside", "feature_id"].tolist() == ["west"]
    suppressed = check_topology(data, reference=reference, allowed_gaps=allowed,
                                min_area=36)
    assert suppressed.data.empty
    assert suppressed.summary["ignored_small_parts"]["gaps"] == 1
    assert suppressed.summary["ignored_small_parts"]["outside"] == 1


def test_no_reference_does_not_invent_gaps_and_explicit_gap_request_fails():
    data = layer([box(0, 0, 1, 1), box(2, 0, 3, 1)])
    assert check_topology(data).data.empty
    with pytest.raises(ValueError, match="reference"):
        check_topology(data, rules=["gaps"])
    with pytest.raises(ValueError, match="allowed_gaps"):
        check_topology(data, allowed_gaps=layer([box(1, 0, 2, 1)]))


def test_line_t_junction_is_connected_but_needs_vertex_to_be_noded():
    data = layer([LineString([(0, 0), (10, 0)]),
                  LineString([(5, 0), (5, 5)])], ["horizontal", "branch"])
    result = check_topology(data, id_field="id")
    assert result.summary["counts"] == {"duplicates": 0, "overlaps": 0,
                                        "dangles": 3, "crossings": 1}
    assert result.data.loc[result.data.rule == "crossings"].geometry.iloc[0].equals(Point(5, 0))
    dangles = result.data.loc[result.data.rule == "dangles"]
    assert not any(geom.equals(Point(5, 0)) for geom in dangles.geometry)
    noded = data.copy()
    noded.loc[0, "geometry"] = LineString([(0, 0), (5, 0), (10, 0)])
    assert check_topology(noded).summary["counts"]["crossings"] == 0


def test_line_crossing_vertex_and_endpoint_rules_are_explicit():
    crosses = layer([LineString([(-2, 0), (2, 0)]),
                     LineString([(0, -2), (0, 2)])])
    result = check_topology(crosses, rules=["crossings", "dangles"])
    assert result.summary["counts"] == {"crossings": 1, "dangles": 4}
    noded = layer([LineString([(-2, 0), (0, 0), (2, 0)]),
                   LineString([(0, -2), (0, 0), (0, 2)])])
    assert check_topology(noded, rules=["crossings"]).data.empty
    endpoint = layer([LineString([(0, 0), (1, 0)]), LineString([(1, 0), (2, 1)])])
    result = check_topology(endpoint)
    assert result.summary["counts"]["crossings"] == 0
    assert result.summary["counts"]["dangles"] == 2


def test_endpoint_tolerance_converts_metres_and_never_edits_sources():
    data = layer([LineString([(0, 0), (1, 0)]),
                  LineString([(1.125, 0), (2, 0)])])
    original = data.copy()
    exact = check_topology(data, rules=["dangles"])
    close = check_topology(data, rules=["dangles"], tolerance=.125)
    outside = check_topology(data, rules=["dangles"], tolerance=.124)
    assert exact.summary["counts"]["dangles"] == 4
    assert close.summary["counts"]["dangles"] == 2
    assert outside.summary["counts"]["dangles"] == 4
    assert_geodataframe_equal(data, original)
    assert set(close.report.tolerance_m) == {.125}


def test_multiline_parts_can_connect_to_each_other_and_closed_rings_do_not_dangle():
    data = layer([MultiLineString([[(0, 0), (2, 0)], [(2, 0), (3, 1)]]),
                  LineString([(10, 0), (12, 0), (11, 1), (10, 0)])])
    result = check_topology(data, rules=["dangles", "crossings"])
    assert result.summary["counts"] == {"dangles": 2, "crossings": 0}
    assert result.report.source_row.tolist() == [0, 0]
    assert result.report.part.tolist() == [0, 1]


def test_line_duplicates_use_topological_equality_and_overlap_length():
    data = layer([LineString([(0, 0), (4, 0)]),
                  LineString([(4, 0), (2, 0), (0, 0)]),
                  LineString([(2, 0), (5, 0)])])
    result = check_topology(data, rules=["duplicates", "overlaps"])
    assert result.summary["counts"] == {"duplicates": 1, "overlaps": 3}
    assert sorted(result.report.loc[result.report.rule == "overlaps", "length_m"]) == [2, 2, 4]


def test_self_crossing_and_retracing_lines_are_not_silently_ignored():
    bow = layer([LineString([(0, 0), (2, 2), (0, 2), (2, 0)])])
    result = check_topology(bow, rules=["crossings"])
    assert result.summary["counts"]["crossings"] == 1
    assert result.data.geometry.iloc[0].equals(Point(1, 1))
    assert result.report.source_row.tolist() == result.report.source_row_other.tolist() == [0]
    retrace = layer([LineString([(0, 0), (3, 0), (1, 0), (1, 2)])])
    result = check_topology(retrace, rules=["overlaps"])
    assert result.report.length_m.sum() == 2


def test_nonincident_self_contact_connects_endpoint():
    source = layer([LineString([(1, 0), (1, 2), (0, 0), (2, 0)])])
    result = check_topology(source, rules=["dangles"])
    assert result.summary["counts"]["dangles"] == 1
    assert result.data.geometry.iloc[0].equals(Point(2, 0))


def test_projected_feet_have_metre_tolerances_lengths_and_square_metre_areas():
    # EPSG:2263 uses US survey feet, 1200/3937 metres each.
    factor = 1200 / 3937
    polygons = layer([box(0, 0, 10, 10), box(5, 0, 15, 10)], crs=2263)
    result = check_topology(polygons, rules=["overlaps"])
    assert result.report.area_m2.iloc[0] == pytest.approx(50 * factor**2)
    lines = layer([LineString([(0, 0), (10, 0)]),
                   LineString([(11, 0), (20, 0)])], crs=2263)
    assert check_topology(lines, rules=["dangles"], tolerance=.30).summary["violations"] == 4
    assert check_topology(lines, rules=["dangles"], tolerance=.31).summary["violations"] == 2


def test_geographic_source_needs_explicit_measurement_projection_and_returns_source_crs():
    data = layer([box(15, -4, 15.001, -3.999), box(15.0005, -4, 15.0015, -3.999)], crs=4326)
    with pytest.raises(ValueError, match="projected"):
        check_topology(data)
    result = check_topology(data, metric_crs=32733)
    assert result.data.crs == data.crs
    expected = data.to_crs(32733).geometry.iloc[0].intersection(data.to_crs(32733).geometry.iloc[1]).area
    assert result.report.area_m2.iloc[0] == pytest.approx(expected)
    assert result.summary["measurement_crs"] == "EPSG:32733"


@pytest.mark.parametrize("geometries", [[None], [Point()],
    [Polygon([(0, 0), (1, 1), (0, 1), (1, 0), (0, 0)])],
    [LineString([(0, 0), (np.inf, 1)])]])
def test_invalid_input_requires_geometry_quality_first(geometries):
    with pytest.raises(ValueError, match="repair|non-finite"):
        check_topology(layer(geometries))


@pytest.mark.parametrize("ids", [["x", "x"], ["x", None]])
def test_business_identifiers_must_be_unambiguous(ids):
    with pytest.raises(ValueError, match="unique"):
        check_topology(layer([box(0, 0, 1, 1), box(1, 0, 2, 1)], ids), id_field="id")


@pytest.mark.parametrize("kwargs", [dict(rules="overlaps"), dict(rules=[]),
    dict(rules=["unknown"]), dict(tolerance=-1), dict(tolerance=float("nan")),
    dict(min_area=float("inf")), dict(tolerance=True), dict(min_area=True)])
def test_invalid_rule_or_threshold_configuration_is_rejected(kwargs):
    with pytest.raises(ValueError):
        check_topology(layer([box(0, 0, 1, 1)]), **kwargs)


def test_unused_thresholds_are_not_silently_accepted():
    with pytest.raises(ValueError, match="dangles"):
        check_topology(layer([box(0, 0, 1, 1)]), tolerance=.1)
    with pytest.raises(ValueError, match="min_area"):
        check_topology(layer([LineString([(0, 0), (1, 1)])]), min_area=1)


def test_empty_dataset_and_empty_errors_are_well_formed():
    empty = layer([])
    result = check_topology(empty)
    assert result.data.empty and result.report.empty
    assert result.data.crs == empty.crs
    assert result.summary["violations"] == 0
    reference = layer([box(0, 0, 10, 10)])
    result = check_topology(empty, reference=reference, rules=["gaps"])
    assert result.report.area_m2.tolist() == [100]


def test_reference_crs_is_aligned_and_large_ids_survive_null_gap_ids():
    source = layer([box(500000, 9500000, 500010, 9500010)], [2**63 - 2])
    reference = layer([box(500005, 9500000, 500015, 9500010)]).to_crs(4326)
    result = check_topology(source, id_field="id", reference=reference,
                            rules=["outside", "gaps"])
    value = result.report.loc[result.report.rule == "outside", "feature_id"].iloc[0]
    assert value == 2**63 - 2 and isinstance(value, int)
    assert result.report.loc[result.report.rule == "gaps", "feature_id"].isna().all()


def test_cancellation_before_and_during_work_produces_no_result():
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(ProcessingCancelled):
        check_topology(layer([box(0, 0, 1, 1)]), cancel=cancel)
    cancel.clear()
    calls = []
    def progress(done, total):
        calls.append((done, total))
        if done:
            cancel.set()
    with pytest.raises(ProcessingCancelled):
        check_topology(layer([box(0, 0, 1, 1), box(1, 0, 2, 1)]),
                       progress=progress, cancel=cancel)
    assert calls


def test_mixed_3d_exterior_2d_hole_is_valid_and_its_legitimate_gap_can_be_allowed():
    polygon = Polygon([(0, 0, 5), (10, 0, 5), (10, 10, 5), (0, 10, 5), (0, 0, 5)],
                      holes=[[(2, 2), (8, 2), (8, 8), (2, 8), (2, 2)]])
    assert polygon.is_valid and len(polygon.interiors[0].coords[0]) == 2
    source = layer([polygon])
    original_wkb = polygon.wkb
    reference = layer([box(0, 0, 10, 10)])
    result = check_topology(source, rules=["gaps"], reference=reference)
    assert result.report.area_m2.tolist() == [36]
    allowed = check_topology(source, rules=["gaps"], reference=reference,
                             allowed_gaps=layer([box(2, 2, 8, 8)]))
    assert allowed.data.empty
    assert source.geometry.iloc[0].wkb == original_wkb


def test_mixed_2d_and_3d_line_parts_keep_their_xy_connectivity():
    geometry = MultiLineString([[(0, 0), (2, 0)], [(2, 0, 5), (3, 1, 7)]])
    result = check_topology(layer([geometry]), rules=["dangles", "crossings"])
    assert result.summary["counts"] == {"dangles": 2, "crossings": 0}


@pytest.mark.skipif(not hasattr(shapely, "has_m"), reason="M coordinates require Shapely >= 2.1")
@pytest.mark.parametrize("wkt", ["LINESTRING M (0 0 1, 1 0 NaN)",
                                  "LINESTRING ZM (0 0 1 3, 1 0 2 NaN)"])
def test_nonfinite_supplied_m_ordinates_are_not_silently_ignored(wkt):
    with pytest.raises(ValueError, match="non-finite coordinates.*source_row 0"):
        check_topology(layer([shapely.from_wkt(wkt)]))


@pytest.mark.skipif(not hasattr(shapely, "has_m"), reason="M coordinates require Shapely >= 2.1")
def test_finite_m_coordinates_do_not_change_xy_topology_or_source():
    geometry = shapely.from_wkt("LINESTRING M (0 0 1, 1 0 2)")
    source = layer([geometry])
    result = check_topology(source, rules=["dangles"])
    assert result.summary["counts"] == {"dangles": 2}
    assert source.geometry.iloc[0].wkb == geometry.wkb
