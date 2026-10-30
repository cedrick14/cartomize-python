"""Validate G12 distance rings with pinned real sources and arithmetic oracles.

The two unchanged input files are the historical GeoPandas tutorial snapshots
of IPIS mine locations and Paris quartiers. A geographic selection of the mine
points stays inside UTM 35S; Paris is measured in Lambert-93. Line tests use
boundaries derived explicitly from the real Paris polygons, not invented road
observations. Separate point, segment and rectangular fixtures are synthetic.

Regular-polygon, capsule and rectangle areas below are computed with Python
arithmetic and trigonometry, independently of GEOS. References for irregular
real polygon/line buffers share GEOS; their purpose is to check integration,
ring construction, publication and accounting, not certify the geometry engine.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from importlib import metadata
import inspect
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time
import traceback

import numpy as np
import pandas as pd

from validate_vector_quality_real import (
    SOURCES, TUTORIAL_REF, download_source, sha, verify_cache,
)


REPO = Path(__file__).resolve().parents[1]
AREA_FACTORS = {"m2": 1.0, "ha": 10000.0, "km2": 1e6}
POINT_DISTANCES = [100.0, 250.0, 500.0, 1000.0]
PARIS_DISTANCES = [50.0, 100.0, 250.0, 500.0]
MINES_BOUNDS = (28.0, -3.0, 29.0, -2.0)


def finite_nonnegative(value, label):
    """Validate an arithmetic-oracle length without accepting booleans."""
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a finite nonnegative number.")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{label} must be a finite nonnegative number.")
    return number


def regular_disk_area(radius, quad_segs=16):
    """Area of a regular 4q-gon inscribed in a radius-r circle.

    A round point buffer has this area, not exactly pi*r*r: each of its 4q
    triangles has area r*r*sin(2*pi/(4q))/2. No geometry engine is used.
    """
    radius = finite_nonnegative(radius, "radius")
    if isinstance(quad_segs, bool) or not isinstance(quad_segs, int) or quad_segs < 1:
        raise ValueError("quad_segs must be a positive integer.")
    return 2.0 * quad_segs * math.sin(math.pi / (2.0 * quad_segs)) * radius**2


def segment_buffer_area(length, radius, quad_segs=16):
    """A straight segment's round buffer: rectangle plus two semicircles."""
    length = finite_nonnegative(length, "length")
    radius = finite_nonnegative(radius, "radius")
    return 2.0 * length * radius + regular_disk_area(radius, quad_segs)


def rectangle_buffer_area(width, height, radius, quad_segs=16):
    """Full round buffer of an axis-aligned rectangle, including its interior."""
    width = finite_nonnegative(width, "width")
    height = finite_nonnegative(height, "height")
    radius = finite_nonnegative(radius, "radius")
    if width == 0 or height == 0:
        raise ValueError("Rectangle width and height must be positive.")
    return width * height + 2.0 * (width + height) * radius + regular_disk_area(radius, quad_segs)


def perforated_rectangle_buffer_area(width, height, hole_width, hole_height, radius, quad_segs=16):
    """A centered rectangular hole shrinks to zero during outward buffering.

    The exterior has rounded convex corners. The rectangular hole's edges move
    inward and meet at sharp corners, until its smaller dimension closes.
    """
    hole_width = finite_nonnegative(hole_width, "hole_width")
    hole_height = finite_nonnegative(hole_height, "hole_height")
    if not 0 < hole_width < width or not 0 < hole_height < height:
        raise ValueError("The positive rectangular hole must lie inside its rectangle.")
    radius = finite_nonnegative(radius, "radius")
    outer = rectangle_buffer_area(width, height, radius, quad_segs)
    return outer - max(0.0, hole_width - 2.0 * radius) * max(0.0, hole_height - 2.0 * radius)


def arithmetic_bands(cumulative_area, distances, *, include_input=False):
    """Successive cumulative-area differences with an implicit lower bound 0."""
    previous_distance = 0.0
    previous_area = 0.0 if include_input else cumulative_area(0.0)
    result = []
    for value in distances:
        distance = finite_nonnegative(value, "distance")
        if distance <= previous_distance:
            raise ValueError("Distances must be positive and strictly increasing.")
        area = cumulative_area(distance)
        result.append(area - previous_area)
        previous_distance, previous_area = distance, area
    if not result:
        raise ValueError("At least one distance is required.")
    return result


def serial(value):
    if isinstance(value, dict):
        return {str(key): serial(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [serial(item) for item in value]
    if isinstance(value, np.generic):
        return serial(value.item())
    if isinstance(value, Path):
        return str(value)
    if value is pd.NA or value is pd.NaT:
        return None
    return value


def atomic_report(path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".g12-report-", suffix=".json", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(serial(document), handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def prepare(root):
    paths, provenance = {}, []
    root.mkdir(parents=True, exist_ok=True)
    for source in SOURCES[:2]:
        candidates = [root / folder / source["file_name"] for folder in ("geopandas", "data", "")]
        target = next((path for path in candidates if path.exists()), None)
        if target is None:
            target = download_source(root, source)
        else:
            verify_cache(target, source)
        paths[source["file_name"]] = target
        provenance.append({**source, "path": str(target), "sha256_verified": True})
    return paths, provenance, {str(path): sha(path) for path in paths.values()}


def close(actual, expected, *, independent=False):
    """Arithmetic precision and shared-GEOS integration precision are distinct."""
    np.testing.assert_allclose(actual, expected, rtol=1e-10 if independent else 1e-8,
                               atol=1e-6 if independent else 0.001)


def polygon_union(geometries):
    import shapely
    return shapely.union_all(list(geometries))


def check_structure(result, distances, *, source_count, groups, unit="m2"):
    """Recalculate every count, interval, group balance and output union."""
    assert result.summary["schema"] == "cartomize.vector.rings.v1"
    assert result.summary["input_features"] == source_count == len(result.sources)
    assert result.summary["group_count"] == groups == len(result.balances)
    assert result.summary["band_count"] == len(distances)
    assert result.summary["area_unit"] == unit
    assert result.summary["table_rows"] == len(result.table) == groups * len(distances)
    assert result.summary["ring_features"] == len(result.data)
    assert result.summary["empty_intervals"] == int((result.table["area"] == 0).sum())
    assert not result.table["ring_id"].duplicated().any()
    assert result.sources["source_row"].tolist() == list(range(source_count))
    assert not result.sources["source_id"].duplicated().any()
    assert result.data.crs == result.sources.crs
    assert result.data.crs.is_projected
    assert result.data.geometry.is_valid.all() and not result.data.geometry.is_empty.any()
    assert set(result.data.geom_type) <= {"Polygon", "MultiPolygon"}
    assert result.sources.geometry.is_valid.all()
    expected_columns = ["ring_id", "group_id", "band_index", "lower_m", "upper_m", "area"]
    assert list(result.table.columns) == expected_columns
    positives = result.table.loc[result.table["area"] > 0].reset_index(drop=True)
    pd.testing.assert_frame_equal(result.data.drop(columns="geometry").reset_index(drop=True),
                                  positives, check_exact=True)
    scale = result.summary["metres_per_coordinate_unit"] ** 2 / AREA_FACTORS[unit]
    close(result.data.geometry.area * scale, result.data["area"])
    lower = [0.0, *distances[:-1]]
    maximum_intersection = 0.0
    for group_id, rows in result.table.groupby("group_id", sort=False):
        assert rows["band_index"].tolist() == list(range(1, len(distances) + 1))
        assert rows["lower_m"].tolist() == lower
        assert rows["upper_m"].tolist() == distances
        geometries = result.data.loc[result.data["group_id"] == group_id, "geometry"].tolist()
        union_area = polygon_union(geometries).area * scale
        summed = math.fsum(rows["area"])
        balance = result.balances.loc[result.balances["group_id"] == group_id].iloc[0]
        close(balance["sum_ring_area"], summed)
        close(balance["union_ring_area"], union_area)
        close(balance["expected_area"], union_area)
        close(balance["raw_excess_area"], summed - union_area)
        closure_budget = (1e-6 + 1e-8 * balance["expected_area"] * AREA_FACTORS[unit]) / AREA_FACTORS[unit]
        for name in ("uncovered_area", "outside_area", "overlap_area", "excess_area", "non_nested_area"):
            assert abs(balance[name]) <= closure_budget, (group_id, name, balance[name], closure_budget)
        assert abs(balance["closure_error"]) <= closure_budget
        for index, left in enumerate(geometries):
            for right in geometries[index + 1:]:
                intersection = left.intersection(right).area * scale
                maximum_intersection = max(maximum_intersection, intersection)
                assert intersection <= closure_budget
    totals = result.summary["totals"]
    global_union_area = polygon_union(result.data.geometry).area * scale
    close(totals["sum_ring_area"], math.fsum(result.table["area"]))
    close(totals["union_ring_area"], global_union_area)
    close(totals["raw_excess_area"], totals["sum_ring_area"] - global_union_area)
    assert np.isfinite(result.table["area"]).all() and (result.table["area"] >= 0).all()
    return {"sources": source_count, "groups": groups, "intervals": len(distances),
            "table_rows": len(result.table), "positive_ring_features": len(result.data),
            "maximum_within_group_intersection_area": maximum_intersection,
            "area_unit": unit, "bounds_and_balances_recalculated": True}


def compare_arithmetic(result, expected):
    expected = list(expected)
    close(result.table["area"], expected, independent=True)
    return {"arithmetic_cells_checked": len(expected),
            "maximum_arithmetic_area_difference_m2": float(np.max(np.abs(result.table["area"].to_numpy() - expected), initial=0))}


def compare_real_reference(result, projected, distances, *, mode, include_input=False, quad_segs=16):
    """Construct raw cumulative buffers with GeoPandas, then subtract neighbours.

    Geometry calculations share GEOS. This deliberately bypasses Cartomize's
    progressive occupied-footprint construction and summary calculations.
    """
    import shapely
    # GeoPandas 1.2 renamed resolution to quad_segs; retain the supported 1.0+
    # range without emitting a deprecation warning on the newer versions.
    keyword = "quad_segs" if "quad_segs" in inspect.signature(projected.geometry.buffer).parameters else "resolution"
    raw = {distance: projected.geometry.buffer(distance, **{keyword: quad_segs}) for distance in distances}
    groups = [list(range(len(projected)))] if mode == "dissolved" else [[row] for row in range(len(projected))]
    differences = []
    reference_outer = []
    for group_index, positions in enumerate(groups, 1):
        group_id = f"g{group_index:06d}"
        polygons = [projected.geometry.iloc[row] for row in positions
                    if projected.geometry.iloc[row].geom_type in {"Polygon", "MultiPolygon"}]
        base = polygon_union(polygons)
        previous = shapely.GeometryCollection() if include_input else base
        expected = []
        for distance in distances:
            cumulative = polygon_union(raw[distance].iloc[positions])
            expected.append(cumulative.difference(previous))
            previous = cumulative
        reference_outer.append(previous if include_input else previous.difference(base))
        rows = result.table.loc[result.table["group_id"] == group_id]
        actual = result.data.set_index("ring_id")
        for row, geometry in zip(rows.itertuples(index=False), expected):
            close(row.area, geometry.area)
            calculated = actual.loc[row.ring_id].geometry if row.area > 0 else shapely.GeometryCollection()
            mismatch = calculated.symmetric_difference(geometry).area
            assert mismatch <= 0.001 + 1e-8 * max(geometry.area, calculated.area)
            differences.append(mismatch)
    reference_union = polygon_union(reference_outer)
    close(result.summary["totals"]["union_ring_area"], reference_union.area)
    close(result.summary["totals"]["excess_area"],
          max(0.0, math.fsum(item.area for item in reference_outer) - reference_union.area))
    return {"reference": "GeoPandas cumulative buffers, adjacent-buffer differences; shared GEOS, separate construction order",
            "reference_cells_checked": len(result.table),
            "maximum_symmetric_difference_m2": max(differences, default=0.0),
            "comparison_tolerance": {"absolute_m2": 0.001, "relative": 1e-8}}


def check_publication(record, expected):
    import cartomize as cm
    from cartomize.tableio import read_table
    products = record["products"]
    assert set(products) == {"primary", "data", "sources", "table", "balances", "audit", "summary"}
    assert products["primary"] == products["data"] == record["primary"]
    for name in ("data", "sources"):
        actual = cm.read_file(products[name], layer="features")
        reference = getattr(expected, name)
        assert actual.crs == reference.crs
        assert actual.geometry.to_wkb().tolist() == reference.geometry.to_wkb().tolist()
        pd.testing.assert_frame_equal(actual.drop(columns="geometry").reset_index(drop=True),
                                      reference.drop(columns="geometry").reset_index(drop=True),
                                      check_dtype=False, check_exact=True)
    for name in ("table", "balances"):
        schema = json.loads(Path(str(products[name]) + ".schema.json").read_text(encoding="utf-8"))
        actual = read_table(products[name], dtype=schema["types"])
        pd.testing.assert_frame_equal(actual, getattr(expected, name), check_dtype=False, check_exact=True)
    summary = json.loads(Path(products["summary"]).read_text(encoding="utf-8"))
    assert summary == serial(expected.summary)
    audit = json.loads(Path(products["audit"]).read_text(encoding="utf-8"))
    assert audit["schema"] == "cartomize.vector_rings.audit.v1"
    assert audit["area_unit"] == expected.summary["area_unit"]
    for name, table in audit["tables"].items():
        reference = getattr(expected, name)
        if "geometry" in reference.columns:
            reference = reference.drop(columns="geometry")
        assert list(table["columns"]) == list(reference.columns)
        assert table["records"] == serial(reference.to_dict("records"))
    assert set(audit["verified_files"]) == {Path(products[name]).name for name in ("data", "sources", "table", "balances")}
    for name, verification in audit["verified_files"].items():
        path = Path(record["primary"]).parent / name
        assert sha(path) == verification["sha256"]
        assert verification["rows"] == len(getattr(expected, path.stem))
    for path in Path(record["primary"]).parent.rglob("*.json"):
        assert ".cartomize-" not in path.read_text(encoding="utf-8"), "A temporary path leaked into a published product."
    return {"products": products, "vector_wkb_and_attributes_exact": True,
            "tables_reopened_exactly": True, "audit_and_summary_verified": True}


def validate(data_root, work, output):
    if not __debug__:
        raise RuntimeError("Run validation without Python -O; assertions must remain enabled.")
    sys.path.insert(0, str(REPO / "src"))
    import geopandas as gpd
    from shapely.geometry import LineString, Point, Polygon, box
    import shapely
    from cartomize.vector_rings import buffer_rings
    import cartomize as cm

    paths, provenance, originals = prepare(data_root)
    if work == data_root or output in [Path(path) for path in originals]:
        raise ValueError("Validation output must not overwrite input sources.")
    work.mkdir(parents=True, exist_ok=True)
    if any(work.iterdir()):
        raise ValueError("The validation work directory must be empty; existing products are never overwritten.")
    code_hashes = {str(path.relative_to(REPO)): sha(path) for path in sorted((REPO / "src/cartomize").rglob("*.py"))}
    steps = []

    def check(name, function):
        started = time.perf_counter()
        record = {"name": name}
        try:
            record.update(function() or {})
            record["status"] = "passed"
        except Exception as exc:
            record.update(status="failed", error=str(exc), traceback=traceback.format_exc())
        record["seconds"] = round(time.perf_counter() - started, 3)
        steps.append(record)
        print(json.dumps({key: value for key, value in record.items() if key not in {"traceback", "products"}},
                         ensure_ascii=False), flush=True)

    mines = cm.read_file(paths[SOURCES[1]["file_name"]])
    paris = cm.read_file(paths[SOURCES[0]["file_name"]])
    source_tables = [frame.drop(columns="geometry").copy(deep=True) for frame in (mines, paris)]
    source_wkb = [frame.geometry.to_wkb().tolist() for frame in (mines, paris)]
    xmin, ymin, xmax, ymax = MINES_BOUNDS
    mine_mask = mines.geometry.x.between(xmin, xmax) & mines.geometry.y.between(ymin, ymax)
    selected = mines.loc[mine_mask].copy().reset_index(drop=True)
    projected_mines = selected.to_crs(32735)
    projected_paris = paris.to_crs(2154)
    common = {"area_unit": "m2", "quad_segs": 16}
    real_results = {}

    def original_inputs():
        assert len(mines) == 3687 and len(paris) == 80 and len(selected) == 240
        assert set(mines.geom_type) == {"Point"} and set(paris.geom_type) == {"Polygon"}
        assert mines.geometry.is_valid.all() and paris.geometry.is_valid.all()
        assert projected_mines.geometry.is_valid.all() and projected_paris.geometry.is_valid.all()
        for data, source in ((mines, SOURCES[1]), (paris, SOURCES[0])):
            original = json.loads(paths[source["file_name"]].read_text(encoding="utf-8"))["features"]
            assert data["id"].tolist() == [feature["properties"].get("id", feature.get("id")) for feature in original]
            assert data.geometry.to_wkb().tolist() == [shapely.geometry.shape(feature["geometry"]).wkb for feature in original]
        return {"original_mine_records": len(mines), "selected_mine_records": len(selected),
                "selection_bounds_wgs84": list(MINES_BOUNDS), "selection_rule": "Inclusive longitude and latitude ranges, original row order",
                "paris_quartiers": len(paris), "mine_analysis_crs": "EPSG:32735", "paris_analysis_crs": "EPSG:2154",
                "original_identifiers_and_wkb_verified": True}

    check("Pinned original points and polygons, with explicit geographic selection", original_inputs)

    def arithmetic_points():
        data = gpd.GeoDataFrame({"name": ["001"]}, geometry=[Point(500000, 9500000)], crs=32733)
        errors = []
        for segments in (1, 4, 16, 64):
            result = buffer_rings(data, POINT_DISTANCES, mode="independent", id_field="name", area_unit="m2", quad_segs=segments)
            check_structure(result, POINT_DISTANCES, source_count=1, groups=1)
            expected = arithmetic_bands(lambda radius: regular_disk_area(radius, segments), POINT_DISTANCES)
            errors.append(compare_arithmetic(result, expected)["maximum_arithmetic_area_difference_m2"])
            assert result.sources["id_value"].tolist() == ["001"]
        return {"quad_segs_checked": [1, 4, 16, 64], "arithmetic_cells_checked": 16,
                "maximum_arithmetic_area_difference_m2": max(errors),
                "reference": "Regular 4q-gon triangle formula; geometric fixtures explicitly synthetic"}

    check("Synthetic point rings agree with the regular-polygon area formula", arithmetic_points)

    def arithmetic_lines():
        lengths = [50.0, 125.0, 250.0]
        geometries = [LineString([(500000, 9500000), (500050, 9500000)]),
                      LineString([(503000, 9500000), (503000, 9500125)]),
                      LineString([(506000, 9500000), (506150, 9500200)])]
        data = gpd.GeoDataFrame(geometry=geometries, crs=32733)
        result = buffer_rings(data, POINT_DISTANCES, mode="independent", **common)
        details = check_structure(result, POINT_DISTANCES, source_count=3, groups=3)
        expected = [area for length in lengths for area in arithmetic_bands(
            lambda radius: segment_buffer_area(length, radius), POINT_DISTANCES)]
        return {**details, **compare_arithmetic(result, expected), "reference": "Straight capsule: 2*length*radius plus regular disk area"}

    check("Synthetic horizontal, vertical and diagonal line rings match capsule areas", arithmetic_lines)

    def arithmetic_polygons():
        rectangle = box(500000, 9500000, 500020, 9500014)
        hole = box(500006, 9500004, 500014, 9500010)
        perforated = Polygon(rectangle.exterior.coords, [hole.exterior.coords])
        data = gpd.GeoDataFrame(geometry=[rectangle, perforated], crs=32733)
        distances = [1.0, 2.0, 3.0, 5.0, 15.0]
        errors = []
        for include in (False, True):
            result = buffer_rings(data, distances, mode="independent", include_input=include, **common)
            check_structure(result, distances, source_count=2, groups=2)
            functions = [lambda radius: rectangle_buffer_area(20, 14, radius),
                         lambda radius: perforated_rectangle_buffer_area(20, 14, 8, 6, radius)]
            expected = [area for function in functions for area in arithmetic_bands(function, distances, include_input=include)]
            errors.append(compare_arithmetic(result, expected)["maximum_arithmetic_area_difference_m2"])
        return {"arithmetic_cells_checked": 20, "hole_closure_checked": True,
                "include_input_values": [False, True], "maximum_arithmetic_area_difference_m2": max(errors),
                "reference": "Rectangle perimeter expansion plus regular disk; rectangular hole contraction to zero"}

    check("Synthetic polygon rings preserve outside-only semantics and close holes correctly", arithmetic_polygons)

    def independent_overlap():
        data = gpd.GeoDataFrame({"label": ["001", "NA", ""]}, geometry=[Point(0, 0)] * 3, crs=32733)
        distances = [10.0, 20.0]
        independent = buffer_rings(data, distances, mode="independent", id_field="label", area_unit="m2", quad_segs=1)
        check_structure(independent, distances, source_count=3, groups=3)
        close(independent.summary["totals"]["sum_ring_area"], 2400, independent=True)
        close(independent.summary["totals"]["union_ring_area"], 800, independent=True)
        close(independent.summary["totals"]["overlap_area"], 800, independent=True)
        close(independent.summary["totals"]["excess_area"], 1600, independent=True)
        assert independent.sources["id_value"].tolist() == ["001", "NA", ""]
        dissolved = buffer_rings(data, distances, id_field="label", area_unit="m2", quad_segs=1)
        check_structure(dissolved, distances, source_count=3, groups=1)
        close(dissolved.summary["totals"]["sum_ring_area"], 800, independent=True)
        close(dissolved.summary["totals"]["overlap_area"], 0, independent=True)
        close(dissolved.summary["totals"]["excess_area"], 0, independent=True)
        return {"independent_sum_m2": 2400, "unique_domain_m2": 800, "unique_overlap_m2": 800,
                "additive_excess_m2": 1600, "dissolved_domain_m2": 800,
                "duplicate_positions_not_merged_in_independent_mode": True, "exact_string_labels_preserved": True}

    check("Coincident synthetic sources distinguish unique overlap from additive excess", independent_overlap)

    def projected_feet():
        from pyproj import CRS
        data = gpd.GeoDataFrame(geometry=[Point(1000000, 200000)], crs=2263)
        unit_factor = CRS.from_epsg(2263).axis_info[0].unit_conversion_factor
        expected_m2 = arithmetic_bands(regular_disk_area, POINT_DISTANCES)
        errors = []
        for unit in AREA_FACTORS:
            result = buffer_rings(data, POINT_DISTANCES, area_unit=unit)
            check_structure(result, POINT_DISTANCES, source_count=1, groups=1, unit=unit)
            close(result.summary["metres_per_coordinate_unit"], unit_factor, independent=True)
            close(result.table["area"].to_numpy() * AREA_FACTORS[unit], expected_m2, independent=True)
            errors.append(float(np.max(np.abs(result.table["area"].to_numpy() * AREA_FACTORS[unit] - expected_m2))))
            outer = polygon_union(result.data.geometry)
            close(outer.bounds, [1000000 - 1000 / unit_factor, 200000 - 1000 / unit_factor,
                                 1000000 + 1000 / unit_factor, 200000 + 1000 / unit_factor], independent=True)
        return {"source_crs": "EPSG:2263", "metres_per_coordinate_unit": unit_factor,
                "area_units_checked": list(AREA_FACTORS), "maximum_arithmetic_area_difference_m2": max(errors),
                "metre_bounds_preserved_in_foot_coordinates": True}

    check("US survey foot coordinates and m2/ha/km2 outputs preserve physical distances", projected_feet)

    def real_mines_independent():
        result = buffer_rings(selected, POINT_DISTANCES, metric_crs=32735, mode="independent", id_field="pcode", **common)
        details = check_structure(result, POINT_DISTANCES, source_count=240, groups=240)
        expected = arithmetic_bands(regular_disk_area, POINT_DISTANCES) * 240
        real_results["mines_independent"] = result
        assert result.sources["id_value"].tolist() == selected["pcode"].tolist()
        return {**details, **compare_arithmetic(result, expected),
                "analysis_crs": "EPSG:32735", "original_mine_labels_preserved": True,
                "reference": "Exact regular-polygon area applies to each original projected mine point; PROJ shared"}

    check("240 real mine sites: every independent distance band has its arithmetic area", real_mines_independent)

    def real_mines_dissolved():
        result = buffer_rings(selected, POINT_DISTANCES, metric_crs=32735, id_field="pcode", **common)
        details = check_structure(result, POINT_DISTANCES, source_count=240, groups=1)
        comparison = compare_real_reference(result, projected_mines, POINT_DISTANCES, mode="dissolved")
        real_results["mines_dissolved"] = result
        independent = real_results["mines_independent"]
        close(result.summary["totals"]["union_ring_area"], independent.summary["totals"]["union_ring_area"])
        assert independent.summary["totals"]["excess_area"] > 0
        close(result.summary["totals"]["overlap_area"], 0)
        return {**details, **comparison, "independent_source_excess_m2": independent.summary["totals"]["excess_area"],
                "global_distance_bands_have_disjoint_interiors": True}

    check("Real mine buffers dissolve into global distance bands without double counting", real_mines_dissolved)

    def real_polygons_independent():
        result = buffer_rings(paris, PARIS_DISTANCES, metric_crs=2154, mode="independent", id_field="district_name", **common)
        details = check_structure(result, PARIS_DISTANCES, source_count=80, groups=80)
        comparison = compare_real_reference(result, projected_paris, PARIS_DISTANCES, mode="independent")
        real_results["paris_independent"] = result
        assert result.sources["id_value"].tolist() == paris["district_name"].tolist()
        return {**details, **comparison, "polygon_interiors_excluded": True, "original_quartier_names_preserved": True}

    check("80 original Paris quartier polygons: outside-only independent rings", real_polygons_independent)

    def real_polygons_dissolved():
        results = []
        errors = []
        for include in (False, True):
            result = buffer_rings(paris, PARIS_DISTANCES, metric_crs=2154, id_field="id", include_input=include, **common)
            check_structure(result, PARIS_DISTANCES, source_count=80, groups=1)
            comparison = compare_real_reference(result, projected_paris, PARIS_DISTANCES, mode="dissolved", include_input=include)
            errors.append(comparison["maximum_symmetric_difference_m2"])
            results.append(result)
        base_area = polygon_union(projected_paris.geometry).area
        close(results[1].table["area"].iloc[0] - results[0].table["area"].iloc[0], base_area)
        close(results[1].table["area"].iloc[1:], results[0].table["area"].iloc[1:])
        real_results["paris_dissolved"] = results[0]
        return {"original_polygons": 80, "include_input_values": [False, True], "unique_source_area_m2": base_area,
                "only_first_band_changes_when_input_included": True,
                "maximum_symmetric_difference_m2": max(errors), "shared_engine_reference": "GEOS"}

    check("Dissolved Paris rings include the original polygon domain only when requested", real_polygons_dissolved)

    def real_boundary_lines():
        lines = paris.copy()
        lines.geometry = lines.geometry.boundary
        distances = [50.0, 100.0, 250.0, 500.0, 1000.0]
        result = buffer_rings(lines, distances, metric_crs=2154, id_field="id", **common)
        details = check_structure(result, distances, source_count=80, groups=1)
        comparison = compare_real_reference(result, lines.to_crs(2154), distances, mode="dissolved")
        assert set(result.sources["geometry_type"]) == {"LineString"}
        close(result.balances["base_area"], 0)
        return {**details, **comparison,
                "derivation": "Boundary of each of the 80 original Paris quartier polygons, retaining original vertices and attributes",
                "source_type": "Derived real polygon boundaries, not observed roads or synthetic lines"}

    check("Derived real Paris boundary lines: five dissolved distance bands", real_boundary_lines)

    def publish_mines():
        from cartomize.vector_io import write_geopackage
        path = work / "selected_original_mines.gpkg"
        write_geopackage(selected, path, layer="sites")
        parameters = {"data": str(path), "layer": "sites", "distances": POINT_DISTANCES,
                      "metric_crs": 32735, "mode": "independent", "id_field": "pcode", **common}
        expected = buffer_rings(**parameters)
        record = cm.execute_operation("vector.buffer_rings", parameters, work / "mine_rings")
        details = check_publication(record, expected)
        assert len(expected.table) == 960
        return {**details, "derived_selection_file": str(path), "published_ring_rows": len(expected.table)}

    check("Real mine rings publish and reopen with exact geometry, bounds, labels and balances", publish_mines)

    def publish_paris():
        parameters = {"data": str(paths[SOURCES[0]["file_name"]]), "distances": PARIS_DISTANCES,
                      "metric_crs": 2154, "id_field": "district_name", **common}
        expected = buffer_rings(**parameters)
        record = cm.execute_operation("vector.buffer_rings", parameters, work / "paris_rings")
        return check_publication(record, expected)

    check("Original geographic Paris file publishes verified projected ring products", publish_paris)

    def cancellation():
        from threading import Event
        from cartomize.algebra import ProcessingCancelled
        cancelled = Event()
        progress_values = []

        def progress(done, total):
            progress_values.append(done)
            assert total == 10000
            if done >= 2500:
                cancelled.set()

        try:
            buffer_rings(selected, POINT_DISTANCES, metric_crs=32735, mode="independent",
                         progress=progress, cancel=cancelled, **common)
        except ProcessingCancelled:
            pass
        else:
            raise AssertionError("Cancellation returned partial rings instead of stopping.")
        assert progress_values and progress_values == sorted(progress_values)
        destination = work / "cancelled_publication"
        try:
            cm.execute_operation("vector.buffer_rings", {"data": selected, "distances": POINT_DISTANCES,
                                 "metric_crs": 32735, **common}, destination, cancel=cancelled)
        except ProcessingCancelled:
            pass
        else:
            raise AssertionError("Cancelled ring publication unexpectedly succeeded.")
        assert not destination.exists()
        return {"monotonic_progress": True, "cancellation_stopped_computation": True, "no_partial_publication": True}

    check("Cancellation stops real-source processing without partial publication", cancellation)

    def source_preservation():
        assert all(sha(path) == digest for path, digest in originals.items())
        for index, frame in enumerate((mines, paris)):
            assert frame.geometry.to_wkb().tolist() == source_wkb[index]
            pd.testing.assert_frame_equal(frame.drop(columns="geometry"), source_tables[index], check_exact=True)
        return {"original_files_checked": len(originals), "all_original_sha256_unchanged": True,
                "in_memory_source_values_and_wkb_unchanged": True}

    check("All original files and in-memory source records remain unchanged", source_preservation)
    try:
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        head = None
    report = {"schema": "cartomize.g12_real_validation.v1", "version": cm.__version__,
              "generated_at_utc": datetime.now(timezone.utc).isoformat(), "commit": head,
              "source_sha256": code_hashes, "validation_script_sha256": sha(Path(__file__)),
              "source_hashes_unchanged_during_validation": all(sha(REPO / name) == digest for name, digest in code_hashes.items()),
              "python": platform.python_version(), "platform": platform.platform(),
              "packages": {name: metadata.version(name) for name in ["geopandas", "shapely", "pandas", "pyogrio", "pyproj"]},
              "tutorial_commit": TUTORIAL_REF, "sources": provenance, "original_sha256": originals,
              "temporal_scope": "Historical published teaching snapshots, not current mine activity or Paris statistics.",
              "independent_checks": "Python arithmetic/trigonometry for regular polygons, straight capsules, rectangles and rectangular holes; literal oracle tests; source SHA-256.",
              "shared_engines": "Real irregular buffers/differences/unions share GEOS. Reprojection and file decoding share PROJ/GDAL.",
              "line_source": "Paris polygon boundaries explicitly derived from the original 80 geometries; no road observations are claimed.",
              "synthetic_cases": "Point, straight-line and rectangular fixtures are explicitly simulated validation geometries.",
              "passed": sum(step["status"] == "passed" for step in steps),
              "failed": sum(step["status"] == "failed" for step in steps), "steps": steps}
    atomic_report(output, report)
    print(json.dumps({key: report[key] for key in ("version", "passed", "failed")}), flush=True)
    return report["failed"] == 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path(".real-project-data"))
    parser.add_argument("--work", type=Path, default=Path("reports/g12-real/products"))
    parser.add_argument("--output", "--report", type=Path, default=Path("reports/g12-real/validation.json"))
    arguments = parser.parse_args()
    raise SystemExit(0 if validate(arguments.data.resolve(), arguments.work.resolve(), arguments.output.resolve()) else 1)
