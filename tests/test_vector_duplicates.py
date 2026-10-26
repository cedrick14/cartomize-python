"""Scientific duplicate cases: provenance, survey dates, geometry and identifiers."""

import json
import threading

import geopandas as gpd
from geopandas.testing import assert_geodataframe_equal
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import (GeometryCollection, LineString, MultiLineString,
                              Point, Polygon, box)

from cartomize.algebra import ProcessingCancelled
from cartomize.vector_duplicates import deduplicate


def points(values, *, dtype=None, geometry=None):
    count = len(values)
    return gpd.GeoDataFrame(
        {"key": pd.Series(values, dtype=dtype), "record": np.arange(count)},
        geometry=geometry if geometry is not None else [Point(i, 0) for i in range(count)],
        crs=32631,
    )


def test_repeated_survey_position_does_not_erase_different_dates():
    data = points(["site A"] * 4, geometry=[Point(1, 1)] * 4)
    data["date"] = pd.to_datetime(["2025-01-01", "2026-01-01", "2026-01-01", "2026-02-01"])
    result = deduplicate(data, keys=["key", "date"], geometry="exact")
    assert result.data.record.tolist() == [0, 1, 3]
    assert result.rejected.record.tolist() == [2]
    assert result.report.retained_row.tolist() == [0, 1, 1, 3]
    assert result.report.group_size.tolist() == [1, 2, 2, 1]
    assert result.summary["duplicate_groups"] == 1
    assert result.summary["duplicate_features"] == 2


def test_attribute_and_geometry_criteria_are_conjunctive():
    data = points(["A", "A", "B", "A"],
                  geometry=[Point(0, 0), Point(1, 0), Point(0, 0), Point(0, 0)])
    assert deduplicate(data, keys="key").data.record.tolist() == [0, 2]
    assert deduplicate(data, geometry="exact").data.record.tolist() == [0, 1]
    assert deduplicate(data, keys="key", geometry="exact").data.record.tolist() == [0, 1, 2]


def test_boolean_numeric_and_text_keys_have_distinct_category_identities():
    data = points([True, 1, 1.0, "1", False, 0], dtype=object)
    result = deduplicate(data, keys="key")
    assert result.data.record.tolist() == [0, 1, 3, 4, 5]
    assert result.report.group_id.tolist() == [1, 2, 2, 3, 4, 5]
    assert result.report.retained_row.tolist() == [0, 1, 1, 3, 4, 5]
    assert result.rejected.record.tolist() == [2]
    assert result.data.key.dtype == object
    assert isinstance(result.data.key.iloc[0], bool)
    assert isinstance(result.data.key.iloc[1], int)
    assert isinstance(result.data.key.iloc[2], str)
    assert "booleans are distinct" in result.summary["attribute_equivalence"]


def test_topological_polygon_equality_ignores_orientation_and_redundant_vertices():
    ordinary = Polygon([(0, 0), (2, 0), (2, 2), (0, 2), (0, 0)])
    reversed_ring = Polygon(list(ordinary.exterior.coords)[::-1])
    extra_vertex = Polygon([(0, 0), (1, 0), (2, 0), (2, 2), (0, 2), (0, 0)])
    different = Polygon([(0, 0), (2, 0), (1, 2), (0, 0)])
    data = points([1, 1, 1, 1], geometry=[ordinary, reversed_ring, extra_vertex, different])
    assert deduplicate(data, geometry="exact").data.record.tolist() == [0, 1, 2, 3]
    result = deduplicate(data, geometry="topological")
    assert result.data.record.tolist() == [0, 3]
    assert result.report.retained_row.tolist() == [0, 0, 0, 3]
    assert result.report.group_id.tolist() == [1, 1, 1, 2]


def test_topological_equivalence_allows_line_segmentation_and_geometry_collections():
    line = LineString([(0, 0), (2, 0)])
    split = MultiLineString([[(0, 0), (1, 0)], [(1, 0), (2, 0)]])
    collection = GeometryCollection([line, Point(1, 0)])
    data = points([1, 1, 1], geometry=[line, split, collection])
    assert deduplicate(data, geometry="topological").data.record.tolist() == [0]
    assert len(deduplicate(data, geometry="exact").data) == 3


def test_topology_is_explicitly_xy_while_exact_preserves_z():
    data = points([1, 1], geometry=[Point(1, 2, 3), Point(1, 2, 4)])
    assert len(deduplicate(data, geometry="exact").data) == 2
    result = deduplicate(data, geometry="topological")
    assert len(result.data) == 1
    assert result.data.geometry.iloc[0].z == 3
    assert "Z/M ignored" in result.summary["geometry_equivalence"]


@pytest.mark.parametrize("dtype,base", [("int64", 2**53), ("Int64", 2**53),
                                       ("uint64", 2**64 - 3), ("UInt64", 2**64 - 3)])
def test_large_integer_keys_are_never_rounded(dtype, base):
    data = points([base, base + 1, base + 2, base + 1], dtype=dtype)
    result = deduplicate(data, keys="key")
    assert result.data.record.tolist() == [0, 1, 2]
    assert result.data.key.tolist() == [base, base + 1, base + 2]
    assert result.data.key.dtype == data.key.dtype
    assert result.rejected.key.dtype == data.key.dtype


def test_string_identifiers_keep_leading_zeroes_and_dtypes():
    data = points(["0001", "1", "0001", "001"], dtype="string")
    data["id"] = pd.Series([2**64 - 4, 2**64 - 3, 2**64 - 2, 2**64 - 1], dtype="UInt64")
    result = deduplicate(data, keys="key", id_field="id", keep="last")
    assert result.data.record.tolist() == [1, 2, 3]
    assert result.data.key.tolist() == ["1", "0001", "001"]
    assert result.report.source_id.dtype == data.id.dtype
    assert result.report.retained_id.tolist() == [2**64 - 2, 2**64 - 3, 2**64 - 2, 2**64 - 1]
    assert result.report.retained_id.dtype == data.id.dtype


@pytest.mark.parametrize("dtype,values", [("Int64", [1, None, 1, None]),
                                         ("string", ["A", None, "A", None]),
                                         ("datetime64[ns]", [pd.Timestamp("2026-01-01"), pd.NaT,
                                                              pd.Timestamp("2026-01-01"), pd.NaT])])
def test_null_key_policy_is_explicit(dtype, values):
    data = points(values, dtype=dtype)
    distinct = deduplicate(data, keys="key")
    assert distinct.data.record.tolist() == [0, 1, 3]
    assert distinct.report.reason.tolist() == ["duplicate_group_keep_first", "null_key_distinct",
                                               "duplicate_removed", "null_key_distinct"]
    assert deduplicate(data, keys="key", null_keys="match").data.record.tolist() == [0, 1]
    with pytest.raises(ValueError, match="missing values.*row 1"):
        deduplicate(data, keys="key", null_keys="error")


def test_matching_null_patterns_does_not_ignore_other_key_fields():
    data = points([None, None, None, None], dtype="Int64")
    data["date"] = pd.Series(["A", "B", "A", None], dtype="string")
    result = deduplicate(data, keys=["key", "date"], null_keys="match")
    assert result.data.record.tolist() == [0, 1, 3]


@pytest.mark.parametrize("geometry", ["exact", "topological"])
def test_missing_and_empty_geometries_are_never_removed_as_geometry_duplicates(geometry):
    data = points(["A"] * 6, geometry=[None, None, Point(), GeometryCollection(), Point(0, 0), Point(0, 0)])
    result = deduplicate(data, keys="key", geometry=geometry, null_keys="match")
    assert result.data.record.tolist() == [0, 1, 2, 3, 4]
    assert result.summary["missing_geometries"] == 2
    assert result.summary["empty_geometries"] == 2
    assert result.report.reason.iloc[:4].tolist() == ["missing_geometry_distinct"] * 2 + ["empty_geometry_distinct"] * 2
    # Attribute-only selection explicitly does not use the geometry state.
    assert deduplicate(data, keys="key").data.record.tolist() == [0]


@pytest.mark.parametrize("keep,expected", [("first", [0, 2]), ("last", [2, 3]), ("none", [2])])
def test_keep_rules_have_a_complete_group_journal(keep, expected):
    data = points(["A", "A", "B", "A"])
    result = deduplicate(data, keys="key", keep=keep)
    assert result.data.record.tolist() == expected
    assert sorted(result.data.record.tolist() + result.rejected.record.tolist()) == [0, 1, 2, 3]
    assert result.report.source_row.tolist() == [0, 1, 2, 3]
    assert result.report.group_id.tolist() == [1, 1, 2, 1]
    assert result.report.group_size.tolist() == [3, 3, 1, 3]
    if keep == "none":
        assert result.report.retained_row.iloc[[0, 1, 3]].isna().all()
        assert result.report.retained_id.iloc[[0, 1, 3]].isna().all()
        assert result.report.reason.iloc[[0, 1, 3]].eq("duplicate_group_removed").all()
    assert str(result.report.retained_row.dtype) == "Int64"


@pytest.mark.parametrize("dtype,base", [("int64", 2**53), ("uint64", 2**64 - 4)])
def test_keep_none_retained_identifiers_stay_nullable_integers(dtype, base):
    data = points(["A", "A", "B"])
    data["id"] = pd.Series([base, base + 1, base + 2], dtype=dtype)
    report = deduplicate(data, keys="key", keep="none", id_field="id").report
    assert report.retained_id.iloc[:2].isna().all()
    assert report.retained_id.iloc[2] == base + 2
    assert str(report.retained_id.dtype) == ("UInt64" if dtype == "uint64" else "Int64")


@pytest.mark.parametrize("keep,ascending,expected", [("first", True, [1, 2]),
                                                    ("last", True, [2, 3]),
                                                    ("first", False, [0, 2]),
                                                    ("last", False, [2, 3])])
def test_ordering_uses_source_position_for_ties_and_keeps_source_output_order(keep, ascending, expected):
    data = points(["A", "A", "B", "A"])
    data["priority"] = [2, 1, 0, None]
    result = deduplicate(data, keys="key", keep=keep, order_by="priority", ascending=ascending)
    assert result.data.record.tolist() == expected
    assert result.summary["order_nulls"] == "last"
    data["priority"] = [1, 1, 1, 1]
    assert deduplicate(data, keys="key", order_by="priority", ascending=False).data.record.tolist() == [0, 2]
    assert deduplicate(data, keys="key", order_by="priority", keep="last").data.record.tolist() == [2, 3]


def test_multifield_ordering_retains_the_complete_record_including_missing_measurements():
    data = points(["A", "A", "B", "A"])
    data["date"] = pd.to_datetime(["2026-01-01", "2026-02-01", "2026-01-01", "2026-02-01"])
    data["priority"] = [1, 1, 1, 2]
    data["measurement"] = pd.Series([42, 10, 12, None], dtype="Int64")
    result = deduplicate(data, keys="key", order_by=["date", "priority"], keep="last")
    assert result.data.record.tolist() == [2, 3]
    assert pd.isna(result.data.measurement.iloc[1])
    assert result.data.geometry.iloc[1] == data.geometry.iloc[3]
    assert result.summary["aggregation"].startswith("none")


@pytest.mark.parametrize("index", [[2**53 + 1, 2**53 + 1, 2**53 + 3],
                                   pd.MultiIndex.from_tuples([("A", 1), ("A", 1), ("B", 2)])])
def test_duplicate_index_custom_geometry_and_metadata_are_preserved(index):
    data = points(["A", "A", "B"])
    data.index = index
    data = data.rename_geometry("shape")
    data["category"] = pd.Categorical(["a", "a", "b"])
    data.attrs = {"study": "Mvouti", "parameters": {"year": 2026}}
    before = data.copy(deep=True)
    result = deduplicate(data, keys="key", keep="last")
    assert_geodataframe_equal(result.data, data.iloc[[1, 2]])
    assert_geodataframe_equal(result.rejected, data.iloc[[0]])
    assert_geodataframe_equal(data, before)
    assert result.data.attrs == data.attrs
    assert result.data.geometry.name == "shape"
    assert result.report.source_index.tolist() == list(index)
    assert result.report.retained_index.tolist() == [index[1], index[1], index[2]]
    assert result.report.retained_row.tolist() == [1, 1, 2]
    json.dumps(result.summary, allow_nan=False)


def test_empty_input_has_typed_outputs_and_complete_summary():
    data = points([], dtype="Int64")
    result = deduplicate(data, keys="key")
    assert_geodataframe_equal(result.data, data)
    assert_geodataframe_equal(result.rejected, data)
    assert result.report.empty
    assert str(result.report.source_row.dtype) == "int64"
    assert str(result.report.retained_row.dtype) == "Int64"
    assert result.summary["groups"] == result.summary["input_features"] == 0


@pytest.mark.parametrize("kwargs,match", [({}, "criteria"), ({"keys": []}, "criteria"),
    ({"keys": "absent"}, "Unknown"), ({"keys": ["key", "key"]}, "repeated"),
    ({"keys": "geometry"}, "geometry field"), ({"keys": 1}, "field name"),
    ({"keys": "key", "order_by": "geometry"}, "geometry field"),
    ({"keys": "key", "order_by": "absent"}, "Unknown"),
    ({"keys": "key", "geometry": "near"}, "geometry must"),
    ({"keys": "key", "geometry": []}, "geometry must"),
    ({"keys": "key", "keep": "all"}, "keep must"),
    ({"keys": "key", "keep": []}, "keep must"),
    ({"keys": "key", "null_keys": "ignore"}, "null_keys must"),
    ({"keys": "key", "null_keys": []}, "null_keys must"),
    ({"keys": "key", "ascending": "True"}, "ascending"),
    ({"keys": "key", "id_field": ["record"]}, "id_field"),
    ({"keys": "key", "id_field": "absent"}, "Unknown"),
    ({"keys": "key", "id_field": "geometry"}, "geometry field"),
    ({"keys": "key", "progress": 1}, "progress")])
def test_invalid_parameters_are_rejected(kwargs, match):
    with pytest.raises(ValueError, match=match):
        deduplicate(points(["A", "A"]), **kwargs)


def test_geometry_attributes_are_rejected_even_when_not_active():
    data = points(["A", "A"])
    data["second_geometry"] = data.geometry.copy()
    with pytest.raises(ValueError, match="geometry field"):
        deduplicate(data, keys="second_geometry")


def test_bad_identifiers_unhashable_keys_duplicate_fields_and_missing_crs():
    data = points(["A", "A"])
    with pytest.raises(ValueError, match="unique"):
        deduplicate(data, keys="key", id_field="key")
    data["id"] = pd.Series([1, None], dtype="Int64")
    with pytest.raises(ValueError, match="missing values"):
        deduplicate(data, keys="key", id_field="id")
    data["bad"] = [[1], [1]]
    with pytest.raises(ValueError, match="scalar, hashable"):
        deduplicate(data, keys="bad")
    with pytest.raises(ValueError, match="CRS"):
        deduplicate(data.set_crs(None, allow_override=True), keys="key")
    repeated = pd.concat([data, data["key"]], axis=1)
    with pytest.raises(ValueError, match="field names must be unique"):
        deduplicate(repeated, keys="key")


@pytest.mark.parametrize("bad_geometry,match", [
    (Polygon([(0, 0), (2, 2), (0, 2), (2, 0), (0, 0)]), "Invalid geometry"),
    (Point(float("inf"), 0), "Nonfinite"),
    (LineString([(0, 0, 0), (1, 1, float("nan"))]), "Nonfinite"),
])
def test_topological_mode_refuses_invalid_and_nonfinite_geometries(bad_geometry, match):
    data = points([1, 2], geometry=[Point(0, 0), bad_geometry])
    with pytest.raises(ValueError, match=match + ".*row 1"):
        deduplicate(data, geometry="topological")
    # Exact serialization can audit a malformed duplicate without repairing it.
    assert len(deduplicate(data, geometry="exact").data) == 2


def test_cancel_before_and_during_processing_never_modifies_source():
    data = points(["A"] * 500, geometry=[box(i, 0, i + 1, 1) for i in range(500)])
    before = data.copy(deep=True)
    event = threading.Event()
    event.set()
    with pytest.raises(ProcessingCancelled):
        deduplicate(data, keys="key", cancel=event)
    event.clear()
    progress = []
    def stop(done, total):
        progress.append((done, total))
        if done >= 3000:
            event.set()
    with pytest.raises(ProcessingCancelled):
        deduplicate(data, geometry="topological", progress=stop, cancel=event)
    assert progress[-1] == (3000, 10000)
    assert_geodataframe_equal(data, before)


def test_progress_is_monotonic_and_ends_after_a_complete_report():
    calls = []
    result = deduplicate(points([1, 1, 2]), keys="key", progress=lambda done, total: calls.append((done, total)))
    assert calls[0] == (0, 10000)
    assert calls[-1] == (10000, 10000)
    assert [done for done, _ in calls] == sorted(done for done, _ in calls)
    assert len(result.report) == 3


def test_large_distinct_topological_points_use_spatial_candidates():
    # A disjoint survey should perform no pairwise topological equality calls.
    from unittest.mock import patch
    from shapely.geometry.base import BaseGeometry
    data = points([1] * 2000)
    original_equals = BaseGeometry.equals
    calls = []
    def counted(left, right):
        calls.append(1)
        return original_equals(left, right)
    with patch.object(BaseGeometry, "equals", counted):
        result = deduplicate(data, geometry="topological")
    assert len(result.data) == 2000
    assert calls == []
