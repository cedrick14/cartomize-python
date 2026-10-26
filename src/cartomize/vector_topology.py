"""Explicit polygon-coverage and line-network topology diagnostics.

The checks do not alter, snap, repair or dissolve the source. Topology is
evaluated in XY. All measurements and the endpoint tolerance use an explicitly
projected coordinate system; returned error geometries use the input CRS.
"""
from collections import Counter
from math import isfinite

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from shapely.geometry import LineString, Point, box
from shapely.ops import linemerge, unary_union
from shapely.strtree import STRtree

from ._validation import frame, measurement_frame
from .imagery import _check_cancel
from .vector_quality_result import VectorQualityResult


_POLYGON_RULES = {"duplicates", "overlaps", "gaps", "outside"}
_LINE_RULES = {"duplicates", "overlaps", "dangles", "crossings"}
_FIELDS = ["violation_id", "rule", "source_row", "source_row_other",
           "feature_id", "feature_id_other", "part", "part_other", "endpoint",
           "detail", "area_m2", "length_m", "tolerance_m"]


def _finite_coordinates(geometry, cancel):
    """Check supplied XY/Z/M ordinates without inventing absent dimensions.

    A Polygon may have a 3D exterior and 2D holes. Padding all rings through
    get_coordinates(include_z=True) would manufacture NaN Z values for those
    valid 2D holes, while ignoring M would miss genuinely nonfinite ordinates.
    """
    _check_cancel(cancel)
    if geometry.is_empty:
        return True
    if geometry.geom_type == "Polygon":
        return (_finite_coordinates(geometry.exterior, cancel)
                and all(_finite_coordinates(ring, cancel) for ring in geometry.interiors))
    if hasattr(geometry, "geoms"):
        return all(_finite_coordinates(part, cancel) for part in geometry.geoms)
    return bool(np.isfinite(np.asarray(geometry.coords, dtype=float)).all())


def _validate_geometry(data, label, cancel=None):
    """Reject unusable geometries before any GEOS overlay is attempted."""
    for row, geom in enumerate(data.geometry):
        _check_cancel(cancel)
        if geom is None or geom.is_empty:
            raise ValueError(f"{label}: missing or empty geometry at source_row {row}; "
                             "audit/repair geometries first.")
        if not _finite_coordinates(geom, cancel):
            raise ValueError(f"{label}: non-finite coordinates at source_row {row}; "
                             "audit/repair geometries first.")
        if not geom.is_valid:
            raise ValueError(f"{label}: invalid geometry at source_row {row}: "
                             f"{shapely.is_valid_reason(geom)}; repair geometries first.")


def _identifiers(data, id_field):
    if id_field is None:
        return list(range(len(data)))
    if not isinstance(id_field, str) or not id_field or id_field not in data:
        raise ValueError("id_field must name an existing attribute column.")
    if id_field == data.geometry.name:
        raise ValueError("id_field must be an attribute, not the geometry column.")
    values = data[id_field]
    if values.isna().any() or values.duplicated().any():
        raise ValueError("id_field must contain unique, non-missing identifiers.")
    return values.tolist()


def _components(geometry, names):
    if geometry.is_empty:
        return
    if geometry.geom_type in names:
        yield geometry
    elif hasattr(geometry, "geoms"):
        for part in geometry.geoms:
            yield from _components(part, names)


def _polygon_mask(value, crs, label, cancel=None):
    data = frame(value)
    _validate_geometry(data, label, cancel)
    if not set(data.geom_type).issubset({"Polygon", "MultiPolygon"}):
        raise ValueError(label + " must contain only Polygon/MultiPolygon geometries.")
    data = data.to_crs(crs)
    _validate_geometry(data, label + " after reprojection", cancel)
    return unary_union(list(data.geometry))


def _xy(point):
    return (float(point.x), float(point.y))


def _vertices(line):
    return {(float(c[0]), float(c[1])) for c in line.coords}


def _linear_parts(geometry):
    """Report connected overlap lines, independent of redundant vertices."""
    components = list(_components(geometry, {"LineString", "LinearRing"}))
    if not components:
        return []
    merged = unary_union(components)
    if merged.geom_type == "MultiLineString":
        merged = linemerge(merged)
    return list(_components(merged, {"LineString", "LinearRing"}))


def _number(value, name):
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(name + " must be a finite non-negative number.")
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError):
        raise ValueError(name + " must be a finite non-negative number.") from None
    if not isfinite(result) or result < 0:
        raise ValueError(name + " must be a finite non-negative number.")
    return result


def check_topology(data, *, id_field=None, rules=None, reference=None,
                   allowed_gaps=None, tolerance=0.0, min_area=0.0,
                   metric_crs=None, progress=None, cancel=None):
    """Return mapped, attributable topology violations without editing input.

    Polygon rules are ``duplicates`` (topological equality), ``overlaps``
    (positive area shared by each pair), ``gaps`` (reference minus coverage and
    explicit allowed gaps), and ``outside`` (each feature outside reference).
    Without a reference the defaults are duplicates/overlaps. With one, all
    four rules are selected. Holes in the reference are outside its domain.

    Line defaults select duplicates, overlaps, dangles and crossings. A
    dangle is an open part endpoint not touching another part within
    ``tolerance`` metres; an endpoint exactly meeting a nonincident segment of
    its own part is also connected. Closed parts have no dangles. A crossing
    is a point intersection that lacks a coordinate vertex on at least one
    participating part; a T-junction is connected for dangle detection but
    remains unnoded if the through-line has no vertex there. Self crossings
    and overlaps in non-simple lines are inspected by segment. Shared
    endpoints and intersections with a vertex on both lines are already
    noded. A reported dangle may be a legitimate dead end.

    ``tolerance`` applies only to dangles and never snaps coordinates. All
    other comparisons are exact GEOS predicates. ``min_area`` is a strict
    lower threshold in square metres for polygon overlaps, gaps and outside
    parts; it never suppresses duplicate detection. Overlaps are pairwise,
    so their summed areas/lengths are not a unique covered area/length.

    The source must have a projected CRS, or ``metric_crs`` must supply one.
    Errors are reprojected back to the source CRS. A supplied ``id_field``
    must be non-null and unique; otherwise feature IDs are zero-based source
    row positions. Neither DataFrame index labels nor FIDs are used as keys.
    """
    _check_cancel(cancel)
    original = frame(data)
    ids = _identifiers(original, id_field)
    tolerance = _number(tolerance, "tolerance")
    min_area = _number(min_area, "min_area")
    requested = None
    if rules is not None:
        if isinstance(rules, (str, bytes)):
            raise ValueError("rules must be a non-empty list of rule names.")
        try:
            requested = list(rules)
        except TypeError:
            raise ValueError("rules must be a non-empty list of rule names.") from None
        if not requested or any(not isinstance(rule, str) for rule in requested):
            raise ValueError("rules must be a non-empty list of rule names.")
        requested = list(dict.fromkeys(requested))
    _validate_geometry(original, "data", cancel)
    kinds = set(original.geom_type)
    if kinds and kinds.issubset({"Polygon", "MultiPolygon"}):
        family = "polygon"
    elif kinds and kinds.issubset({"LineString", "MultiLineString", "LinearRing"}):
        family = "line"
    elif not kinds:
        family = "line" if set(requested or []) & {"dangles", "crossings"} else "polygon"
    else:
        raise ValueError("Use one polygon or line family at a time; points and "
                         "mixed geometry families are not supported by these rules.")
    if requested is None:
        selected = (["duplicates", "overlaps", "gaps", "outside"]
                    if family == "polygon" and reference is not None else
                    ["duplicates", "overlaps"] if family == "polygon" else
                    ["duplicates", "overlaps", "dangles", "crossings"])
    else:
        selected = requested
    accepted = _POLYGON_RULES if family == "polygon" else _LINE_RULES
    unknown = set(selected) - accepted
    if unknown:
        raise ValueError(f"Unsupported {family} topology rules: {sorted(unknown)}.")
    if set(selected) & {"gaps", "outside"} and reference is None:
        raise ValueError("A polygon reference is required for gaps/outside checks.")
    if allowed_gaps is not None and "gaps" not in selected:
        raise ValueError("allowed_gaps requires the gaps rule and a reference.")
    if reference is not None and family != "polygon":
        raise ValueError("reference is supported only for polygon coverage rules.")
    if tolerance and "dangles" not in selected:
        raise ValueError("tolerance is used only by the line dangles rule.")
    if min_area and not (family == "polygon" and
                         set(selected) & {"overlaps", "gaps", "outside"}):
        raise ValueError("min_area is used only by polygon overlaps/gaps/outside.")
    work, factor = measurement_frame(original, metric_crs)
    _validate_geometry(work, "data after reprojection", cancel)
    geometries = list(work.geometry)
    rows, errors = [], []
    ignored_small_parts = Counter()
    tree = STRtree(geometries)
    total = max(len(geometries), 1)
    if progress:
        progress(0, total)

    def add(rule, geometry, row=None, other=None, *, part=None, other_part=None,
            endpoint=None, detail=""):
        rows.append(dict(violation_id=len(rows) + 1, rule=rule,
                         source_row=row, source_row_other=other,
                         feature_id=ids[row] if row is not None else None,
                         feature_id_other=ids[other] if other is not None else None,
                         part=part, part_other=other_part, endpoint=endpoint,
                         detail=detail, area_m2=float(geometry.area) * factor**2,
                         length_m=float(geometry.length) * factor,
                         tolerance_m=tolerance if rule == "dangles" else 0.0))
        errors.append(geometry)

    def add_polygons(rule, geometry, row=None, other=None, detail=""):
        for polygon in _components(geometry, {"Polygon"}):
            if polygon.area * factor**2 > min_area:
                add(rule, polygon, row, other, detail=detail)
            else:
                ignored_small_parts[rule] += 1

    # Feature duplicates and polygon overlaps use only index-selected pairs.
    for i, geometry in enumerate(geometries):
        _check_cancel(cancel)
        if "duplicates" in selected or family == "polygon" and "overlaps" in selected:
            for j in sorted(int(j) for j in tree.query(geometry)):
                _check_cancel(cancel)
                if j <= i:
                    continue
                other = geometries[j]
                if "duplicates" in selected and geometry.equals(other):
                    add("duplicates", geometry, i, j,
                        detail="Topologically equal XY point sets; attributes are not compared.")
                if family == "polygon" and "overlaps" in selected and geometry.intersects(other):
                    add_polygons("overlaps", geometry.intersection(other), i, j,
                                 "Pairwise shared area; boundary-only contact is allowed.")
        if progress:
            progress(i + 1, total)

    reference_area = allowed_area = None
    if family == "polygon" and (set(selected) & {"gaps", "outside"}):
        _check_cancel(cancel)
        domain = _polygon_mask(reference, work.crs, "reference", cancel)
        reference_area = float(domain.area) * factor**2
        if domain.is_empty:
            raise ValueError("reference must define a non-empty polygon domain.")
        if "gaps" in selected:
            _check_cancel(cancel)
            coverage = unary_union(geometries)
            gaps = domain.difference(coverage)
            if allowed_gaps is not None:
                allowed = _polygon_mask(allowed_gaps, work.crs, "allowed_gaps", cancel)
                allowed_area = float(domain.intersection(allowed).area) * factor**2
                gaps = gaps.difference(allowed)
            add_polygons("gaps", gaps,
                         detail="Reference area with no source coverage, excluding allowed gaps.")
        if "outside" in selected:
            for i, geometry in enumerate(geometries):
                _check_cancel(cancel)
                add_polygons("outside", geometry.difference(domain), i,
                             detail="Feature area outside the reference polygon domain.")

    if family == "line":
        parts = [(i, k, part) for i, geometry in enumerate(geometries)
                 for k, part in enumerate(_components(geometry, {"LineString", "LinearRing"}))]
        lines = [p[2] for p in parts]
        part_tree = STRtree(lines)
        vertices = [_vertices(line) for line in lines]
        for pi, (row, part, line) in enumerate(parts):
            _check_cancel(cancel)
            if set(selected) & {"overlaps", "crossings"}:
                for pj in sorted(int(j) for j in part_tree.query(line)):
                    _check_cancel(cancel)
                    if pj <= pi:
                        continue
                    other_row, other_part, other_line = parts[pj]
                    intersection = line.intersection(other_line)
                    if "overlaps" in selected:
                        for overlap in _linear_parts(intersection):
                            if overlap.length > 0:
                                add("overlaps", overlap, row, other_row, part=part,
                                    other_part=other_part,
                                    detail="Pairwise shared line length; point-only contact is allowed.")
                    if "crossings" in selected:
                        for point in _components(intersection, {"Point"}):
                            if _xy(point) not in vertices[pi] or _xy(point) not in vertices[pj]:
                                add("crossings", point, row, other_row, part=part,
                                    other_part=other_part,
                                    detail="Intersection lacks a coordinate vertex on at least one line part.")

            coordinates = list(line.coords)
            # Non-simple lines can cross/overlap themselves without another
            # feature. A segment index limits these checks to possible contacts.
            segments = None
            if not line.is_simple and set(selected) & {"overlaps", "crossings", "dangles"}:
                segments = [LineString([a[:2], b[:2]]) for a, b in
                            zip(coordinates[:-1], coordinates[1:]) if a[:2] != b[:2]]
                segment_tree = STRtree(segments)
                self_points, self_overlaps = {}, []
                for si, segment in enumerate(segments):
                    _check_cancel(cancel)
                    for sj in sorted(int(j) for j in segment_tree.query(segment)):
                        if sj <= si:
                            continue
                        intersection = segment.intersection(segments[sj])
                        if "overlaps" in selected:
                            self_overlaps.extend(_components(intersection, {"LineString"}))
                        if "crossings" in selected:
                            ends_a, ends_b = _vertices(segment), _vertices(segments[sj])
                            for point in _components(intersection, {"Point"}):
                                if _xy(point) not in ends_a or _xy(point) not in ends_b:
                                    self_points[point.wkb] = point
                for overlap in _linear_parts(unary_union(self_overlaps)):
                    if overlap.length > 0:
                        add("overlaps", overlap, row, row, part=part, other_part=part,
                            detail="Self-overlap between nonidentical segments of one line part.")
                for point in self_points.values():
                    add("crossings", point, row, row, part=part, other_part=part,
                        detail="Unnoded self-intersection inside at least one original segment.")

            if "dangles" in selected and not line.is_closed:
                distance_units = tolerance / factor
                for endpoint, coords in ((0, coordinates[0]), (1, coordinates[-1])):
                    _check_cancel(cancel)
                    point = Point(coords[:2])
                    search = (point if not distance_units else
                              box(point.x - distance_units, point.y - distance_units,
                                  point.x + distance_units, point.y + distance_units))
                    connected = any(
                        j != pi and point.distance(lines[j]) <= distance_units
                        for j in map(int, part_tree.query(search)))
                    if not connected and not line.is_simple:
                        # Do not treat the endpoint's own continuation as a
                        # nearby connection. Only exact self-contacts count.
                        coordinates_xy = [c[:2] for c in coordinates]
                        rest = (coordinates_xy[1:] if endpoint == 0 else coordinates_xy[:-1])
                        connected = len(rest) >= 2 and Point(coords[:2]).intersects(LineString(rest))
                    if not connected:
                        add("dangles", point, row, part=part, endpoint=endpoint,
                            detail="Open endpoint has no other line part within tolerance; a dead end may be legitimate.")

    _check_cancel(cancel)
    report = pd.DataFrame(rows, columns=_FIELDS)
    # Object IDs avoid float conversion when large integer keys share a column
    # with gap records, whose identifiers are absent.
    for field in ("feature_id", "feature_id_other"):
        report[field] = pd.Series([row[field] for row in rows], dtype=object)
    for field in ("violation_id", "source_row", "source_row_other", "part", "part_other", "endpoint"):
        report[field] = pd.array(report[field], dtype="Int64")
    for field in ("area_m2", "length_m", "tolerance_m"):
        report[field] = pd.to_numeric(report[field], errors="raise").astype(float)
    issues = gpd.GeoDataFrame(report.copy(), geometry=errors, crs=work.crs).to_crs(original.crs)
    counts = {rule: int(sum(row["rule"] == rule for row in rows)) for rule in selected}
    summary = dict(schema="cartomize.vector_topology.v1", operation="check_topology",
                   input_features=len(original), geometry_family=family,
                   empty_input=not len(original), id_field=id_field,
                   identifier_policy="attribute" if id_field is not None else "zero_based_source_row",
                   source_crs=str(original.crs), measurement_crs=str(work.crs),
                   coordinate_unit_to_metre=factor, dimensions="XY", rules=selected,
                   tolerance_m=tolerance, tolerance_applies_to="dangles only; no snapping",
                   min_area_m2=min_area, area_comparison="strictly greater than min_area",
                   violations=len(rows), counts=counts,
                   ignored_small_parts={rule: int(ignored_small_parts[rule]) for rule in selected},
                   reference_area_m2=reference_area, allowed_gap_area_m2=allowed_area,
                   geometry_modified=False,
                   overlap_measurement="pairwise; summing can count the same area or length more than once",
                   dangle_interpretation="candidate connectivity issue; legitimate dead ends require expert interpretation",
                   crossing_convention="point intersection lacking a coordinate vertex on at least one original line part")
    if progress:
        progress(total, total)
    return VectorQualityResult(data=issues, report=report, summary=summary, issues=issues)
