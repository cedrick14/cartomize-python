"""Validate the G01 completion on pinned real data and analytic geometries.

Run from the repository root::

    python scripts/validate_g01_real.py --data CACHE --output REPORT.json

The unchanged M08 cache supplies the RDC protected areas and Paris districts.
The RDC identifier is explicitly constructed from the pinned archive hash,
member name and original row. Paris retains its original id. Grid sizes are
experimental scenarios, not recommendations about either dataset's accuracy.
Independent checks use a shoelace formula, literal expected coordinates and
SQLite/GeoPackage bytes. GEOS validity itself is not independently certified.
"""
from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, timezone
from hashlib import sha256
from importlib import metadata
import json
import math
import os
from pathlib import Path
import platform
import sqlite3
import subprocess
import sys
import tempfile
import time

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from shapely.geometry import Point, Polygon

from validate_vector_quality_real import (
    SOURCES, TUTORIAL_REF, download_source, extract_verified_zip, sha, serial,
)


REPO = Path(__file__).resolve().parents[1]
PARK_MEMBER = "Conservation/RDC_aire_protegee_2013.shp"
REFERENCES = [
    "https://docs.qgis.org/3.44/en/docs/user_manual/processing_algs/qgis/vectorgeometry.html",
    "https://docs.qgis.org/3.44/en/docs/user_manual/processing_algs/qgis/checkgeometry.html",
    "https://doc.esri.com/en/arcgis-pro/latest/tool-reference/data-management/check-geometry.html",
    "https://shapely.readthedocs.io/en/stable/reference/shapely.make_valid.html",
    "https://shapely.readthedocs.io/en/stable/reference/shapely.set_precision.html",
    "https://www.geopackage.org/spec140/#gpb_format",
]
STATE_FIELDS = (
    "has_z", "has_m", "coordinate_dimension", "topological_dimension",
    "coordinate_count", "part_count", "wkb_sha256",
)


def atomic_report(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".g01-report-", suffix=".json", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(serial(report), handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def source_identity():
    try:
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO,
                                       text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        head = None
    modules = {str(path.relative_to(REPO)): sha(path)
               for path in sorted((REPO / "src/cartomize").rglob("*.py"))}
    return head, modules


def wkb_hash(geometry):
    return None if geometry is None else sha256(geometry.wkb).hexdigest()


def same_frame(expected, observed):
    assert len(observed) == len(expected)
    assert observed.crs == expected.crs
    pd.testing.assert_frame_equal(
        expected.drop(columns=expected.geometry.name).reset_index(drop=True),
        observed.drop(columns=observed.geometry.name).reset_index(drop=True),
        check_dtype=False, check_exact=True,
    )
    assert observed.geometry.to_wkb().tolist() == expected.geometry.to_wkb().tolist()


def correspondence(source, result):
    """Check every retained/rejected row against the complete original layer."""
    same_frame(source, result.before)
    report = result.report
    assert report.source_row.tolist() == list(range(len(source)))
    assert report.output_row.dtype == pd.Int64Dtype()
    assert report.rejected_row.dtype == pd.Int64Dtype()
    for prefix in ("before_", "after_"):
        assert set(prefix + field for field in STATE_FIELDS) <= set(report.columns)
    for row in report.itertuples(index=False):
        original = source.iloc[[row.source_row]]
        original_hash = wkb_hash(original.geometry.iloc[0])
        assert (pd.isna(row.before_wkb_sha256) if original_hash is None
                else row.before_wkb_sha256 == original_hash)
        if row.retained:
            assert pd.isna(row.rejected_row) and not pd.isna(row.output_row)
            selected = result.data.iloc[[int(row.output_row)]]
            selected_hash = wkb_hash(selected.geometry.iloc[0])
            assert (pd.isna(row.after_wkb_sha256) if selected_hash is None
                    else row.after_wkb_sha256 == selected_hash)
        else:
            assert pd.isna(row.output_row) and not pd.isna(row.rejected_row)
            selected = result.rejected.iloc[[int(row.rejected_row)]]
            assert selected.geometry.iloc[0] is None or (
                selected.geometry.iloc[0].wkb == original.geometry.iloc[0].wkb)
        pd.testing.assert_frame_equal(
            original.drop(columns=original.geometry.name).reset_index(drop=True),
            selected.drop(columns=selected.geometry.name).reset_index(drop=True),
            check_dtype=False, check_exact=True,
        )
    assert report.output_row.dropna().tolist() == list(range(len(result.data)))
    assert report.rejected_row.dropna().tolist() == list(range(len(result.rejected)))


def ring_area(coordinates):
    """Translated shoelace calculation; no Shapely area call in the reference."""
    if len(coordinates) < 4:
        return 0.0
    x0, y0 = coordinates[0][:2]
    terms = []
    for left, right in zip(coordinates, coordinates[1:]):
        ax, ay = left[0] - x0, left[1] - y0
        bx, by = right[0] - x0, right[1] - y0
        terms.append(ax * by - bx * ay)
    return abs(math.fsum(terms)) / 2


def independent_area(geometry):
    if geometry is None:
        return math.nan
    if geometry.is_empty:
        return 0.0
    interface = geometry.__geo_interface__
    kind = interface["type"]
    if kind == "Polygon":
        rings = interface["coordinates"]
        return ring_area(rings[0]) - math.fsum(ring_area(ring) for ring in rings[1:])
    if kind == "MultiPolygon":
        return math.fsum(ring_area(rings[0]) - math.fsum(ring_area(ring) for ring in rings[1:])
                         for rings in interface["coordinates"])
    if kind == "GeometryCollection":
        return math.fsum(independent_area(part) for part in geometry.geoms)
    return 0.0


def grid_check(geometries, spacing):
    xy = shapely.get_coordinates(geometries)
    scaled = xy / spacing
    residual = np.abs(scaled - np.rint(scaled))
    arithmetic_bound = max(1e-7, float(np.max(np.abs(scaled))) * np.finfo(float).eps * 4)
    assert np.isfinite(xy).all() and float(residual.max()) <= arithmetic_bound
    return {"coordinates_checked": len(xy), "maximum_grid_multiple_residual": float(residual.max()),
            "floating_point_comparison_bound": arithmetic_bound}


def quoted(name):
    return '"' + name.replace('"', '""') + '"'


def gpkg_wkb(blob):
    """Strip the standard GeoPackage header without invoking a GIS reader."""
    if blob is None:
        return None
    assert isinstance(blob, bytes) and blob[:2] == b"GP" and blob[2] == 0
    flags = blob[3]
    assert flags & 0b11000000 == 0
    envelope_bytes = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}[(flags >> 1) & 7]
    payload = blob[8 + envelope_bytes:]
    assert payload[0] in (0, 1) and len(payload) >= 5
    return payload


def scalar_equal(actual, expected):
    if pd.isna(expected):
        return actual is None
    if isinstance(expected, (datetime, date, pd.Timestamp)):
        return pd.Timestamp(actual) == pd.Timestamp(expected)
    if isinstance(expected, np.generic):
        expected = expected.item()
    if isinstance(expected, int) and not isinstance(expected, bool):
        return type(actual) is int and actual == expected
    return actual == expected


def sqlite_roundtrip(path, expected):
    """Check all attributes and WKB using SQLite, including business fid."""
    with sqlite3.connect(path) as connection:
        layers = connection.execute("SELECT table_name, column_name FROM gpkg_geometry_columns").fetchall()
        assert len(layers) == 1
        table, geometry_column = layers[0]
        fields = connection.execute(f"PRAGMA table_info({quoted(table)})").fetchall()
        primary_keys = [field[1] for field in fields if field[5]]
        assert len(primary_keys) == 1
        expected_attributes = {name for name in expected.columns if name != expected.geometry.name}
        assert primary_keys[0] not in expected_attributes, "A business field became the storage FID."
        assert {field[1] for field in fields} - {geometry_column, primary_keys[0]} == expected_attributes
        connection.row_factory = sqlite3.Row
        rows = connection.execute(f"SELECT * FROM {quoted(table)} ORDER BY rowid").fetchall()
    assert len(rows) == len(expected)
    attributes = [name for name in expected.columns if name != expected.geometry.name]
    for position, actual in enumerate(rows):
        original = expected.iloc[position]
        for name in attributes:
            assert scalar_equal(actual[name], original[name]), (position, name, actual[name], original[name])
        geometry = original.geometry
        want = None if geometry is None else shapely.to_wkb(geometry, flavor="iso", byte_order=1)
        assert gpkg_wkb(actual[geometry_column]) == want, (position, "WKB differs")
    return {"features": len(rows), "attributes_per_feature": len(attributes),
            "all_wkb_equal": True, "all_attribute_values_equal": True}


def expect_refusal(function, destination=None):
    try:
        function()
    except ValueError as exc:
        if destination is not None:
            assert not destination.exists(), "A refused operation published its destination."
        return str(exc)
    raise AssertionError("The intentionally unsupported operation was not refused.")


def validate(cache, output):
    if not __debug__:
        raise RuntimeError("Run validation without Python -O; assertions must remain enabled.")
    if output.is_relative_to(cache / "data"):
        raise ValueError("The validation report must be outside the input data directory.")
    sys.path.insert(0, str(REPO / "src"))
    os.environ.setdefault("MPLCONFIGDIR", str(cache / "matplotlib-cache"))
    import cartomize as cm

    started = time.perf_counter()
    head, code_hashes = source_identity()
    pinned = [item for item in SOURCES if item["file_name"] in
              {"paris_districts.geojson", "cod_conservation.zip"}]
    paths = {item["file_name"]: download_source(cache, item) for item in pinned}
    extract_verified_zip(paths["cod_conservation.zip"], cache)
    parks_path = cache / "data/cod_conservation" / PARK_MEMBER
    input_files = [*paths.values(), *sorted(parks_path.parent.glob("RDC_aire_protegee_2013.*"))]
    input_hashes = {str(path): sha(path) for path in input_files if path.is_file()}
    archive_hash = sha(paths["cod_conservation.zip"])
    parks_original = cm.read_file(parks_path)
    parks = parks_original.copy()
    provenance_prefix = f"sha256:{archive_hash}:{PARK_MEMBER}:row:"
    parks["validation_id"] = [provenance_prefix + str(i) for i in range(len(parks))]
    paris = cm.read_file(paths["paris_districts.geojson"])
    parks_wkb = parks.geometry.to_wkb().tolist()
    paris_wkb = paris.geometry.to_wkb().tolist()
    report = {
        "schema": "cartomize.validation_g01_real.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "cartomize_version": cm.__version__, "repository_head_at_validation": head,
        "validation_script_sha256": sha(Path(__file__)), "tested_source_sha256": code_hashes,
        "code_state": "Module hashes identify the tested working sources; HEAD may precede uncommitted implementation.",
        "runtime": {"python": platform.python_version(), "platform": platform.platform(),
                    "geos": shapely.geos_version_string,
                    "packages": {name: metadata.version(name) for name in
                                 ("geopandas", "shapely", "pandas", "numpy", "pyproj", "pyogrio", "pyarrow")}},
        "source_repository": "https://github.com/jorisvandenbossche/geopandas-tutorial",
        "source_commit": TUTORIAL_REF, "sources": pinned, "source_file_sha256": input_hashes,
        "identifier_policy": {"rdc": "Explicitly constructed validation_id; not an original business identifier.",
                              "rdc_prefix": provenance_prefix, "rdc_suffix": "zero-based original archive-member row",
                              "paris": "Original id attribute; preserved through an input permutation."},
        "input_dataset_scope": "Pinned historical teaching snapshots, not current protected-area inventories. Only a provenance attribute is added to the RDC in-memory validation copy.",
        "method": "Real geometry integration plus independent translated shoelace arithmetic, literal analytic expectations, grid-multiple arithmetic and SQLite/GeoPackage WKB and attribute rereads. GEOS validity and repair are shared-engine checks, not independent certification.",
        "grid_scenarios": {"values": [0.0, 0.01, 1.0], "unit": "source projected metre",
                           "meaning": "Experimental verification scenarios; no source-accuracy recommendation."},
        "references": REFERENCES, "checks": [], "passed": 0, "failed": 0,
    }

    def passed(name, **details):
        report["checks"].append({"name": name, "status": "passed", **details})
        report["passed"] += 1

    active_check = "Pinned datasets and explicit provenance identifiers"
    try:
        assert len(parks) == 50 and len(paris) == 80
        assert parks.validation_id.is_unique and parks.validation_id.notna().all()
        assert set(paris.id) == set(range(1, 81)) and paris.id.is_unique
        assert parks.crs.is_projected and parks.crs.axis_info[0].unit_conversion_factor == 1
        passed(active_check, rdc_features=50, paris_features=80, rdc_business_attributes_unchanged=True,
               original_archive_sha256=archive_hash, rdc_identifier_example=parks.validation_id.iloc[1])

        active_check = "Original RDC diagnosis, dimensions and immutable source"
        audit = cm.audit_geometries(parks, id_field="validation_id")
        assert audit.summary["invalid_geometries"] == 1
        assert audit.report.loc[~audit.report.valid, "source_row"].tolist() == [1]
        assert "Self-intersection" in audit.report.loc[1, "reason"]
        assert audit.report.output_row.tolist() == list(range(50))
        assert set(STATE_FIELDS) <= set(audit.report.columns)
        assert audit.report.wkb_sha256.tolist() == [wkb_hash(g) for g in parks.geometry]
        same_frame(parks, audit.data)
        same_frame(parks, audit.before)
        passed(active_check, invalid_source_rows=[1], invalid_name=parks.NOM.iloc[1],
               reason=audit.report.loc[1, "reason"], coordinate_count=int(audit.report.coordinate_count.sum()),
               source_types=parks.geom_type.value_counts().to_dict(), source_unchanged=True)

        baseline = None
        for spacing in (0.0, 0.01, 1.0):
            active_check = f"RDC repair and explicit XY grid scenario {spacing:g} metre"
            result = cm.repair_geometries(parks, id_field="validation_id", method="linework",
                                         tolerance=spacing, empty="error", missing="error")
            correspondence(parks, result)
            assert len(result.data) == 50 and result.data.is_valid.all() and result.rejected.empty
            assert result.report.feature_id.tolist() == parks.validation_id.tolist()
            assert int(result.report.repair_changed.sum()) == 1
            assert result.summary["tolerance"] == spacing
            assert result.summary["tolerance_unit"] == "metre"
            expected_steps = ["diagnose_original", "repair_invalid"]
            if spacing:
                expected_steps.append("xy_precision_grid")
            expected_steps.append("validate_final")
            assert result.summary["processing_steps"] == expected_steps
            independently_measured = np.array([independent_area(g) for g in result.data.geometry])
            np.testing.assert_allclose(result.report.after_area_m2, independently_measured,
                                       rtol=2e-11, atol=2e-5)
            before_measured = np.array([independent_area(g) for g in parks.geometry])
            np.testing.assert_allclose(result.report.before_area_m2, before_measured, rtol=2e-11, atol=2e-5)
            np.testing.assert_allclose(result.report.area_delta_m2,
                                       result.report.after_area_m2 - result.report.before_area_m2, rtol=0, atol=0)
            details = {"input_features": 50, "retained_features": 50, "valid_after": 50,
                       "repair_changed_features": int(result.report.repair_changed.sum()),
                       "precision_changed_features": int(result.report.precision_changed.sum()),
                       "total_geometry_changed_features": int(result.report.geometry_changed.sum()),
                       "output_types": result.data.geom_type.value_counts().to_dict(),
                       "area_before_m2": float(result.report.before_area_m2.sum()),
                       "area_after_m2": float(result.report.after_area_m2.sum()),
                       "area_delta_sum_m2": float(result.report.area_delta_m2.sum()),
                       "absolute_area_delta_sum_m2": float(result.report.area_delta_m2.abs().sum()),
                       "coordinate_count_before": int(result.report.before_coordinate_count.sum()),
                       "coordinate_count_after": int(result.report.after_coordinate_count.sum()),
                       "maximum_shoelace_area_difference_m2": float(np.max(np.abs(result.report.after_area_m2 - independently_measured))),
                       "measurement_note": "Planar areas in source RDC Mercator; invalid pre-repair areas do not establish territorial surfaces."}
            if spacing == 0:
                baseline = result
                assert not result.report.precision_changed.any()
                assert result.summary["precision_mode"] is None
                assert sum(a == b for a, b in zip(parks_wkb, result.data.geometry.to_wkb())) == 49
                details["unchanged_original_valid_wkb"] = 49
            else:
                assert baseline is not None
                assert result.summary["precision_mode"] == "valid_output"
                assert result.summary["tolerance_metres_per_unit"] == 1.0
                expected_changes = [a != b for a, b in zip(baseline.data.geometry.to_wkb(), result.data.geometry.to_wkb())]
                assert result.report.precision_changed.tolist() == expected_changes
                details.update(grid_check(result.data.geometry.to_numpy(), spacing))
            passed(active_check, **details)

        active_check = "Paris original business IDs survive an input permutation"
        reordered = paris.sample(frac=1, random_state=1701).copy()
        paris_result = cm.repair_geometries(reordered, id_field="id", tolerance=0.0)
        correspondence(reordered, paris_result)
        same_frame(reordered, paris_result.data)
        assert paris_result.report.feature_id.tolist() == reordered.id.tolist()
        expected_by_id = dict(zip(paris.id, paris.geometry.to_wkb()))
        assert dict(zip(paris_result.data.id, paris_result.data.geometry.to_wkb())) == expected_by_id
        assert not paris_result.report.geometry_changed.any()
        passed(active_check, features=80, original_id_range=[1, 80], random_state=1701,
               complete_source_preserved=True, all_original_wkb_and_attributes_unchanged=True)

        active_check = "Positive geographic grid is refused even with metric_crs"
        message = expect_refusal(lambda: cm.repair_geometries(paris, id_field="id", tolerance=0.01,
                                                              metric_crs="EPSG:2154"))
        passed(active_check, source_crs="EPSG:4326", requested_measurement_crs="EPSG:2154",
               requested_grid=0.01, message=message)

        active_check = "Independent analytic surfaces, collapse and correspondence"
        bowtie = Polygon([(0, 0), (2, 2), (0, 2), (2, 0), (0, 0)])
        square = Polygon([(3.1, .1), (3.9, .1), (3.9, .9), (3.1, .9), (3.1, .1)])
        thin = Polygon([(5.1, .1), (5.4, .1), (5.4, 2.1), (5.1, 2.1), (5.1, .1)])
        analytic = gpd.GeoDataFrame({"id": ["001", "002", "003", "004", "005"],
                                    "fid": pd.array([2**60 + 1, None, 2**60 + 3, 0, 7], dtype="Int64")},
                                   geometry=[bowtie, square, thin, Polygon(), None], crs="EPSG:32733")
        analytic_result = cm.repair_geometries(analytic, id_field="id", tolerance=1,
                                              empty="drop", missing="drop")
        correspondence(analytic, analytic_result)
        assert analytic_result.data.id.tolist() == ["001", "002"]
        assert analytic_result.rejected.id.tolist() == ["003", "004", "005"]
        np.testing.assert_allclose(analytic_result.report.after_area_m2.iloc[:3], [2, 1, 0], rtol=0, atol=1e-12)
        assert analytic_result.report.loc[2, "after_empty"]
        assert analytic_result.report.output_row.tolist()[:2] == [0, 1]
        assert analytic_result.report.rejected_row.dropna().tolist() == [0, 1, 2]
        assert set(map(tuple, shapely.get_coordinates(analytic_result.data.geometry.iloc[1]))) == {
            (3.0, 0.0), (4.0, 0.0), (4.0, 1.0), (3.0, 1.0)}
        collapsed_error = expect_refusal(lambda: cm.repair_geometries(analytic.iloc[[2]], tolerance=1, empty="error"))
        passed(active_check, fixture="Entirely synthetic geometry with literal expectations",
               expected_retained_ids=["001", "002"], expected_rejected_ids=["003", "004", "005"],
               expected_after_areas_m2=[2, 1, 0], collapse_error=collapsed_error,
               source_count=5, output_count=2, rejected_count=3)

        active_check = "Grid dimensions, Z preservation and projected feet"
        point_z = gpd.GeoDataFrame({"id": ["Z"]}, geometry=[Point(.9, .9, 12.345)], crs="EPSG:32733")
        changed_z = cm.repair_geometries(point_z, id_field="id", tolerance=1)
        assert tuple(changed_z.data.geometry.iloc[0].coords[0]) == (1., 1., 12.345)
        assert changed_z.report.loc[0, "before_has_z"] and changed_z.report.loc[0, "after_has_z"]
        assert changed_z.report.loc[0, "before_coordinate_dimension"] == 3
        feet = gpd.GeoDataFrame({"id": ["ft"]}, geometry=[square], crs="EPSG:2263")
        feet_result = cm.repair_geometries(feet, id_field="id", tolerance=1)
        metres_per_foot = 1200 / 3937
        assert math.isclose(feet_result.summary["tolerance_metres_per_unit"], metres_per_foot, rel_tol=1e-14)
        assert math.isclose(feet_result.report.after_area_m2.iloc[0], metres_per_foot**2, rel_tol=1e-14)
        passed(active_check, expected_xyz=[1., 1., 12.345], feet_unit=feet_result.summary["tolerance_unit"],
               metres_per_source_foot=metres_per_foot, expected_square_metre_area=metres_per_foot**2,
               scope="Controlled synthetic fixtures; Z validity is not certified.")

        with tempfile.TemporaryDirectory(prefix="cartomize-g01-real-") as temporary:
            work = Path(temporary)
            active_check = "Multilayer file requires an explicit source layer"
            bundle = work / "two_layers.gpkg"
            paris.head(3).to_file(bundle, layer="paris", driver="GPKG", index=False)
            parks.head(2).to_file(bundle, layer="rdc", driver="GPKG", index=False)
            messages = [expect_refusal(lambda function=function: function(bundle))
                        for function in (cm.audit_geometries, cm.repair_geometries)]
            selected = cm.audit_geometries(bundle, layer="paris", id_field="id")
            assert len(selected.data) == 3 and selected.summary["source_layer"] == "paris"
            assert selected.report.feature_id.tolist() == paris.id.iloc[:3].tolist()
            passed(active_check, layers=["paris", "rdc"], selected_layer="paris", selected_features=3,
                   ambiguous_input_messages=messages)

            active_check = "Published RDC before/data/rejected products and every saved attribute/WKB"
            parameters = {"data": parks, "id_field": "validation_id", "tolerance": 0.01,
                          "method": "linework", "empty": "error", "missing": "error"}
            expected = cm.repair_geometries(**parameters)
            record = cm.execute_operation("vector.repair_geometries", parameters, work / "published_rdc")
            products = record["products"]
            assert {"before", "data", "issues", "rejected", "report", "summary"} <= set(products)
            product_checks = {}
            for key in ("before", "data", "rejected"):
                original = getattr(expected, key)
                same_frame(original, cm.read_file(products[key]))
                product_checks[key] = sqlite_roundtrip(products[key], original)
            with Path(products["report"]).open(encoding="utf-8-sig", newline="") as handle:
                saved_rows = list(csv.DictReader(handle))
            assert [row["feature_id"] for row in saved_rows] == parks.validation_id.tolist()
            assert [int(row["output_row"]) for row in saved_rows] == list(range(50))
            assert all(row["rejected_row"] == "" for row in saved_rows)
            sidecar = Path(products["report"] + ".schema.json")
            schema = json.loads(sidecar.read_text(encoding="utf-8"))
            assert "feature_id" in schema["label_columns"] and schema["types"]["feature_id"] == "string"
            saved_summary = json.loads(Path(products["summary"]).read_text(encoding="utf-8"))
            assert saved_summary["tolerance"] == 0.01
            passed(active_check, published_product_names=sorted(products), product_checks=product_checks,
                   saved_report_rows=len(saved_rows), report_labels_preserved=True,
                   complete_source_and_correspondence_persisted=True)

            active_check = "Saved rejection correspondence preserves business fid and leading zeros"
            rejected_fixture = analytic.iloc[:2].copy()
            rejection_parameters = {"data": rejected_fixture, "id_field": "id", "type_changes": "drop"}
            expected = cm.repair_geometries(**rejection_parameters)
            assert expected.data.id.tolist() == ["002"] and expected.rejected.id.tolist() == ["001"]
            record = cm.execute_operation("vector.repair_geometries", rejection_parameters, work / "published_rejections")
            product_checks = {key: sqlite_roundtrip(record["products"][key], getattr(expected, key))
                              for key in ("before", "data", "rejected")}
            with Path(record["products"]["report"]).open(encoding="utf-8-sig", newline="") as handle:
                saved = list(csv.DictReader(handle))
            assert [(r["feature_id"], r["source_row"], r["output_row"], r["rejected_row"]) for r in saved] == [
                ("001", "0", "", "0"), ("002", "1", "0", "")]
            passed(active_check, source_features=2, output_features=1, rejected_features=1,
                   large_business_fid=2**60 + 1, missing_business_fid_preserved=True,
                   leading_zero_ids=["001", "002"], product_checks=product_checks)

            active_check = "Measured coordinates are refused before mutation or atomic publication"
            measured = gpd.GeoDataFrame({"id": ["M"]}, geometry=[shapely.from_wkt("POINT M (0.9 0.9 7)")],
                                       crs="EPSG:32733")
            same_frame(measured, cm.repair_geometries(measured, tolerance=0).data)
            mutation_message = expect_refusal(lambda: cm.repair_geometries(measured, tolerance=1))
            destination = work / "measured_refused"
            export_message = expect_refusal(
                lambda: cm.execute_operation("vector.repair_geometries", {"data": measured}, destination), destination)
            passed(active_check, valid_m_retained_in_memory_at_zero=True, mutation_refused=True,
                   destination_published=False, mutation_message=mutation_message, export_message=export_message)

        active_check = "Source records, pinned file bytes and tested modules remain unchanged"
        assert parks.geometry.to_wkb().tolist() == parks_wkb and paris.geometry.to_wkb().tolist() == paris_wkb
        pd.testing.assert_frame_equal(parks.drop(columns="validation_id"), parks_original, check_exact=True)
        assert input_hashes == {path: sha(Path(path)) for path in input_hashes}
        assert code_hashes == source_identity()[1], "The application sources changed during validation."
        passed(active_check, source_files=len(input_hashes), tested_modules=len(code_hashes),
               historical_validation_reports_rewritten=False)
    except Exception as exc:
        report["checks"].append({"name": active_check, "status": "failed",
                                 "error_type": type(exc).__name__, "message": str(exc)})
        report["failed"] += 1
    report["status"] = "passed" if not report["failed"] else "failed"
    report["duration_seconds"] = round(time.perf_counter() - started, 3)
    atomic_report(output, report)
    print(json.dumps({key: report[key] for key in ("status", "passed", "failed", "duration_seconds")}), flush=True)
    if report["failed"]:
        print(json.dumps(report["checks"][-1], ensure_ascii=False), flush=True)
    return 0 if not report["failed"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    return validate(args.data.expanduser().resolve(), args.output.expanduser().resolve())


if __name__ == "__main__":
    raise SystemExit(main())
