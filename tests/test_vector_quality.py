"""Row-level geometry diagnosis and explicit, non-destructive repair decisions."""
import inspect
from threading import Event

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import shapely
from geopandas.testing import assert_geodataframe_equal
from shapely.geometry import GeometryCollection, LineString, Point, Polygon, box

from cartomize.algebra import ProcessingCancelled
from cartomize.vector_quality import audit_geometries, repair_geometries


def bowtie():
    return Polygon([(0, 0), (2, 2), (0, 2), (2, 0), (0, 0)])


def collapse():
    return Polygon([(0, 0), (1, 1), (1, 2), (1, 1), (0, 0)])


def frame(geometries, crs=32733, **columns):
    return gpd.GeoDataFrame(columns, geometry=geometries, crs=crs)


def test_audit_has_exact_identifiers_all_error_reasons_and_does_not_modify_source():
    source = frame([box(0, 0, 2, 2), bowtie(), None, Point(), box(0, 0, 2, 2)],
                   business_id=[2**60 + i for i in range(5)], value=[1, 2, 3, 4, 5])
    source.index = [8, 8, 9, 9, 8]
    before = source.copy(deep=True)
    result = audit_geometries(source, id_field="business_id")
    assert_geodataframe_equal(source, before)
    assert_geodataframe_equal(result.data, before)
    assert result.report.feature_id.tolist() == source.business_id.tolist()
    assert result.report.source_row.tolist() == list(range(5))
    assert result.report.status.tolist() == ["valid", "invalid", "missing", "empty", "duplicate"]
    assert "Self-intersection" in result.report.loc[1, "reason"]
    assert result.report.loc[4, "duplicate_of_row"] == 0
    assert result.report.loc[0, "area_m2"] == 4
    assert result.issues.source_row.tolist() == [1, 2, 3, 4]
    assert result.summary["invalid_geometries"] == 1
    assert result.summary["duplicate_geometries"] == 1
    assert result.rejected.empty


def test_repair_bowtie_expected_area_keeps_attributes_custom_geometry_and_duplicate_labels():
    source = frame([bowtie(), box(3, 0, 5, 2)], label=["001", "002"], source_row=[30, 31])
    source = source.rename_geometry("shape")
    source.index = [7, 7]
    original_wkb = source.geometry.to_wkb().tolist()
    result = repair_geometries(source, id_field="label")
    assert source.geometry.to_wkb().tolist() == original_wkb
    assert result.data.geometry.name == "shape"
    assert result.data.index.tolist() == [7, 7]
    assert result.data.source_row.tolist() == [30, 31]
    assert result.data.label.tolist() == ["001", "002"]
    assert result.data.geometry.is_valid.all()
    np.testing.assert_allclose(result.data.area, [2, 4])
    assert result.report.loc[0, "before_area_m2"] == 0
    assert result.report.loc[0, "after_area_m2"] == 2
    assert result.report.loc[0, "area_delta_m2"] == 2
    assert result.report.loc[0, "before_geometry_type"] == "Polygon"
    assert result.report.loc[0, "after_geometry_type"] == "MultiPolygon"
    assert result.report.decision.tolist() == ["repaired", "unchanged"]
    assert result.summary["repaired_features"] == 1
    assert result.summary["retained_unusable_features"] == 0


@pytest.mark.parametrize("policy,expected_count,decision", [("keep", 2, "kept"), ("drop", 1, "dropped")])
@pytest.mark.parametrize("condition", ["missing", "empty"])
def test_missing_and_empty_policies_keep_or_reject_original_features(policy, expected_count, decision, condition):
    geometry = None if condition == "missing" else Polygon()
    source = frame([geometry, Point(1, 1)], code=["bad", "good"])
    result = repair_geometries(source, **{condition: policy})
    assert len(result.data) == expected_count
    assert result.report.loc[0, "decision"] == decision + "_" + condition
    assert len(result.rejected) == 2 - expected_count
    if policy == "drop":
        assert result.rejected.code.tolist() == ["bad"]
        assert result.data.code.tolist() == ["good"]
    else:
        assert result.summary["retained_unusable_features"] == 1


@pytest.mark.parametrize("condition,geometry", [("missing", None), ("empty", Polygon())])
def test_explicit_missing_empty_errors_do_not_mutate_source(condition, geometry):
    source = frame([geometry, bowtie()])
    before = source.geometry.to_wkb().tolist()
    with pytest.raises(ValueError, match="source_row 0"):
        repair_geometries(source, **{condition: "error"})
    assert source.geometry.to_wkb().tolist() == before


def test_exact_geometry_type_change_can_be_rejected_or_refused():
    source = frame([bowtie(), Point(4, 4)], code=[10, 20])
    result = repair_geometries(source, type_changes="drop")
    assert result.data.code.tolist() == [20]
    assert result.rejected.code.tolist() == [10]
    assert result.rejected.geometry.iloc[0].equals_exact(source.geometry.iloc[0], 0)
    assert result.report.loc[0, "decision"] == "dropped_type_change"
    assert result.report.loc[0, "after_area_m2"] == 2
    with pytest.raises(ValueError, match="Polygon -> MultiPolygon"):
        repair_geometries(source, type_changes="error")


def test_collapsed_lines_and_collections_are_preserved_and_reported():
    spike = Polygon([(0, 0), (2, 0), (2, 2), (1, 1), (2, 2), (0, 2), (0, 0)])
    source = frame([collapse(), spike])
    result = repair_geometries(source)
    assert result.data.geom_type.tolist() == ["MultiLineString", "GeometryCollection"]
    assert result.report.collapsed.tolist() == [True, True]
    assert result.report.after_collection.tolist() == [False, True]
    assert result.data.geometry.iloc[1].area == 4
    assert result.summary["collapsed_features"] == 2


@pytest.mark.skipif("method" not in inspect.signature(shapely.make_valid).parameters,
                    reason="structure is explicitly optional on Shapely 2.0")
def test_valid_mixed_collection_is_not_reported_as_a_new_collapse():
    geometry = GeometryCollection([box(0, 0, 2, 2), LineString([(4, 0), (5, 0)])])
    result = repair_geometries(frame([geometry]), method="structure")
    assert result.data.geometry.iloc[0].wkb == geometry.wkb
    assert not result.report.loc[0, "collapsed"]
    assert result.report.loc[0, "after_collection"]
    assert result.report.loc[0, "decision"] == "unchanged"


@pytest.mark.skipif("method" not in inspect.signature(shapely.make_valid).parameters,
                    reason="structure is explicitly optional on Shapely 2.0")
def test_empty_policy_applies_to_structure_collapses_too():
    source = frame([collapse(), Point(3, 3)])
    retained = repair_geometries(source, method="structure", keep_collapsed=False)
    assert retained.report.loc[0, "decision"] == "kept_empty_repair"
    assert retained.data.geometry.iloc[0].is_empty
    rejected = repair_geometries(source, method="structure", keep_collapsed=False, empty="drop")
    assert len(rejected.data) == len(rejected.rejected) == 1
    assert rejected.report.loc[0, "decision"] == "dropped_empty_repair"
    with pytest.raises(ValueError, match="produced an empty"):
        repair_geometries(source, method="structure", keep_collapsed=False, empty="error")


@pytest.mark.parametrize("function", [audit_geometries, repair_geometries])
def test_projected_feet_are_converted_to_physical_units(function):
    source = frame([box(0, 0, 10, 20)], crs=2263)
    result = function(source)
    area_column = "area_m2" if function is audit_geometries else "after_area_m2"
    length_column = "length_m" if function is audit_geometries else "after_length_m"
    factor = 1200 / 3937
    assert result.report.loc[0, area_column] == pytest.approx(200 * factor**2)
    assert result.report.loc[0, length_column] == pytest.approx(60 * factor)
    assert result.summary["metres_per_coordinate_unit"] == pytest.approx(factor)


def test_geographic_measures_are_missing_until_projected_crs_is_explicit():
    source = frame([box(15, -4.01, 15.01, -4)], crs=4326)
    result = audit_geometries(source)
    assert result.report.area_m2.isna().all()
    assert result.report.length_m.isna().all()
    assert not result.summary["measurements_available"]
    measured = repair_geometries(source, metric_crs=32733)
    expected = source.to_crs(32733)
    assert measured.report.loc[0, "after_area_m2"] == pytest.approx(expected.area.iloc[0])
    assert measured.data.crs == source.crs
    assert measured.data.geometry.iloc[0].wkb == source.geometry.iloc[0].wkb
    with pytest.raises(ValueError, match="projected"):
        audit_geometries(source, metric_crs=4326)


@pytest.mark.parametrize("ids", [["001", None], [2**60, 2**60]])
@pytest.mark.parametrize("function", [audit_geometries, repair_geometries])
def test_explicit_identifiers_must_be_unique_and_present(function, ids):
    with pytest.raises(ValueError, match="identifiers"):
        function(frame([Point(0, 0), Point(1, 1)], code=ids), id_field="code")


def test_exact_duplicates_do_not_claim_topological_equivalence():
    forward = LineString([(0, 0), (1, 1)])
    reverse = LineString([(1, 1), (0, 0)])
    result = audit_geometries(frame([forward, reverse, forward]))
    assert result.report.status.tolist() == ["valid", "valid", "duplicate"]
    assert result.summary["duplicate_geometries"] == 1


def test_nonfinite_coordinates_are_diagnosed_and_never_silently_repaired():
    source = frame([LineString([(0, 0), (np.inf, 1)])])
    result = audit_geometries(source)
    assert result.report.loc[0, "status"] == "nonfinite"
    assert pd.isna(result.report.loc[0, "area_m2"])
    assert result.summary["nonfinite_geometries"] == 1
    with pytest.raises(ValueError, match="Non-finite.*source_row 0"):
        repair_geometries(source)


def test_mixed_2d_3d_collection_does_not_invent_nan_z_errors():
    source = frame([GeometryCollection([Point(0, 0), Point(1, 1, 2)])])
    result = audit_geometries(source)
    assert not result.report.loc[0, "nonfinite"]


def test_empty_layer_returns_typed_reports_and_layers():
    source = frame([], identifier=pd.Series(dtype="int64"))
    for function in (audit_geometries, repair_geometries):
        result = function(source, id_field="identifier")
        assert result.data.empty and result.report.empty and result.issues.empty and result.rejected.empty
        assert result.data.crs == result.issues.crs == source.crs
        assert "source_row" in result.report and "feature_id" in result.report
        assert result.summary["input_features"] == result.summary["output_features"] == 0


@pytest.mark.parametrize("function", [audit_geometries, repair_geometries])
def test_cancellation_before_and_during_work(function):
    event = Event()
    event.set()
    with pytest.raises(ProcessingCancelled):
        function(frame([bowtie()]), cancel=event)
    event.clear()
    progress = []
    def update(done, total):
        progress.append((done, total))
        if done == 1:
            event.set()
    with pytest.raises(ProcessingCancelled):
        function(frame([bowtie(), bowtie()]), cancel=event, progress=update)
    assert progress == [(0, 2), (1, 2)]


def test_structure_has_explicit_version_guard_and_linework_still_works(monkeypatch):
    make_valid = shapely.make_valid
    monkeypatch.setattr(shapely, "make_valid", lambda geometry: make_valid(geometry))
    with pytest.raises(ValueError, match="Shapely >= 2.1 and GEOS >= 3.10"):
        repair_geometries(frame([bowtie()]), method="structure")
    assert repair_geometries(frame([bowtie()])).data.geometry.is_valid.all()


@pytest.mark.parametrize("kwargs", [{"method": "buffer0"}, {"missing": "discard"}, {"empty": "discard"},
                                    {"type_changes": "keep"}, {"keep_collapsed": False}, {"keep_collapsed": "yes"}])
def test_invalid_policy_is_refused_before_processing(kwargs):
    with pytest.raises(ValueError):
        repair_geometries(frame([bowtie()]), **kwargs)


@pytest.mark.parametrize("replacement", [None, bowtie()])
def test_failed_geos_repair_never_returns_a_false_success(monkeypatch, replacement):
    monkeypatch.setattr(shapely, "make_valid", lambda geometry: replacement)
    with pytest.raises(ValueError, match="did not produce a finite valid geometry"):
        repair_geometries(frame([bowtie()]))


def test_unknown_crs_is_refused_and_file_input_is_supported(tmp_path):
    source = frame([bowtie(), box(4, 0, 6, 2)], identifier=["001", "002"])
    with pytest.raises(ValueError, match="no CRS"):
        audit_geometries(source.set_crs(None, allow_override=True))
    path = tmp_path / "source.gpkg"
    source.to_file(path)
    original_bytes = path.read_bytes()
    result = repair_geometries(path, id_field="identifier")
    assert result.data.identifier.tolist() == ["001", "002"]
    assert result.data.geometry.is_valid.all()
    assert path.read_bytes() == original_bytes
