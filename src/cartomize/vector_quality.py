"""Geometry diagnosis and explicit GEOS repair with a row-level audit.

All predicates and repairs are planar. No snapping, buffering, coordinate
rounding or feature merging is performed. WKB duplicates are exact, including
vertex order, and are diagnosed rather than deleted by these procedures.
"""
from __future__ import annotations

import inspect
from collections import Counter

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from pyproj import CRS, Transformer

from ._validation import frame, linear_factor
from .imagery import _check_cancel
from .vector_quality_result import VectorQualityResult


def _identified_frame(data, id_field):
    """Keep business identifiers exact and independent of dataframe labels."""
    result = frame(data)
    if id_field is None:
        identifiers = list(range(len(result)))
    else:
        if id_field == result.geometry.name or id_field not in result.columns:
            raise ValueError("id_field must name an existing attribute column.")
        values = result[id_field]
        if not isinstance(values, pd.Series):
            raise ValueError("id_field must name exactly one attribute column.")
        if values.isna().any():
            raise ValueError("id_field contains missing identifiers.")
        try:
            repeated = values.duplicated().any()
        except TypeError as exc:
            raise ValueError("id_field must contain scalar identifiers.") from exc
        if repeated:
            raise ValueError("id_field must contain unique identifiers.")
        identifiers = values.tolist()
        if any(not pd.api.types.is_scalar(value) for value in identifiers):
            raise ValueError("id_field must contain scalar identifiers.")
    return result, identifiers


def _finite_geometry(geometry):
    """Check every supplied ordinate, without treating absent Z as NaN Z."""
    if geometry is None or geometry.is_empty:
        return True
    kind = geometry.geom_type
    if kind == "Polygon":
        return (_finite_geometry(geometry.exterior)
                and all(_finite_geometry(ring) for ring in geometry.interiors))
    if hasattr(geometry, "geoms"):
        return all(_finite_geometry(part) for part in geometry.geoms)
    coordinates = np.asarray(geometry.coords, dtype=float)
    return bool(np.isfinite(coordinates).all())


def _state(geometry):
    missing = geometry is None
    empty = bool(not missing and geometry.is_empty)
    finite = _finite_geometry(geometry)
    valid = bool(not missing and finite and geometry.is_valid)
    reason = ("Missing geometry" if missing else
              "Empty geometry" if empty else
              "Non-finite coordinates" if not finite else
              str(shapely.is_valid_reason(geometry)))
    return dict(geometry_type=None if missing else geometry.geom_type,
                missing=missing, empty=empty, nonfinite=not finite,
                valid=valid, reason=reason)


def _measurement_context(source_crs, metric_crs):
    target = CRS.from_user_input(metric_crs) if metric_crs is not None else CRS.from_user_input(source_crs)
    if metric_crs is None and not target.is_projected:
        return None, None, dict(
            measurement_crs=None, measurements_available=False,
            measurement_note="Physical area and length are unavailable without an explicit projected CRS.")
    factor = linear_factor(target)
    source = CRS.from_user_input(source_crs)
    transformer = None if source == target else Transformer.from_crs(source, target, always_xy=True)
    return transformer, factor, dict(
        measurement_crs=target.to_string(), measurements_available=True,
        area_unit="m2", length_unit="m", metres_per_coordinate_unit=factor,
        measurement_note=("Planar measures in the stated projected CRS. Measures before repair "
                          "describe the supplied geometry; an invalid polygon's area is not a validated surface."))


def _measures(geometry, transformer, factor):
    if factor is None or geometry is None or not _finite_geometry(geometry):
        return np.nan, np.nan
    measured = (shapely.transform(geometry, lambda xy: np.column_stack(
                    transformer.transform(xy[:, 0], xy[:, 1])))
                if transformer is not None else geometry)
    if not _finite_geometry(measured):
        raise ValueError("The chosen metric_crs produces non-finite geometry coordinates.")
    area = float(measured.area * factor**2)
    length = float(measured.length * factor)
    if not np.isfinite([area, length]).all():
        raise ValueError("Geometry measures overflow in the chosen projected CRS.")
    return area, length


def _diagnostic_rows(data, identifiers, transformer, factor, progress, cancel):
    rows, first_wkb = [], {}
    total = len(data)
    if progress:
        progress(0, total)
    for position, geometry in enumerate(data.geometry):
        _check_cancel(cancel)
        state = _state(geometry)
        area, length = _measures(geometry, transformer, factor)
        duplicate = None
        if not state["missing"] and not state["empty"] and not state["nonfinite"]:
            token = geometry.wkb
            if token in first_wkb:
                duplicate = first_wkb[token]
            else:
                first_wkb[token] = position
        status = ("missing" if state["missing"] else "empty" if state["empty"] else
                  "nonfinite" if state["nonfinite"] else "invalid" if not state["valid"] else
                  "duplicate" if duplicate is not None else "valid")
        rows.append(dict(source_row=position, feature_id=identifiers[position], status=status,
                         **state, duplicate_of_row=duplicate, area_m2=area, length_m=length))
        if progress:
            progress(position + 1, total)
    _check_cancel(cancel)
    return rows


_AUDIT_COLUMNS = ["source_row", "feature_id", "status", "geometry_type", "missing", "empty",
                  "nonfinite", "valid", "reason", "duplicate_of_row", "area_m2", "length_m"]


def _report(rows, columns):
    result = pd.DataFrame(rows, columns=columns)
    # Inferred float dtype would round large integer identifiers when a table
    # mixes numeric types. Identifiers are labels and must never be coerced.
    result["feature_id"] = pd.Series([row["feature_id"] for row in rows], dtype=object)
    result["source_row"] = result["source_row"].astype("int64")
    if "duplicate_of_row" in result:
        result["duplicate_of_row"] = pd.array([row["duplicate_of_row"] for row in rows], dtype="Int64")
    return result


def _issues(report, geometries, selected, crs):
    positions = [i for i, keep in enumerate(selected) if keep]
    table = report.iloc[positions].copy().reset_index(drop=True)
    return gpd.GeoDataFrame(table, geometry=[geometries[i] for i in positions], crs=crs)


def _summary(data, rows, id_field, measure_info, operation):
    return dict(
        schema="cartomize.vector_quality.v1", operation=operation, input_features=len(data),
        crs=data.crs.to_string(), id_field=id_field,
        identifier_source="source_row" if id_field is None else "attribute",
        source_row_base=0, missing_geometries=sum(row["missing"] for row in rows),
        empty_geometries=sum(row["empty"] for row in rows),
        nonfinite_geometries=sum(row["nonfinite"] for row in rows),
        invalid_geometries=sum(not row["missing"] and not row["empty"] and not row["valid"] for row in rows),
        duplicate_geometries=sum(row["duplicate_of_row"] is not None for row in rows),
        geometry_types=dict(Counter(row["geometry_type"] for row in rows if row["geometry_type"] is not None)),
        duplicate_rule="Exact WKB including coordinate and component order; missing and empty geometries excluded.",
        coordinate_policy="No snapping or tolerance; GEOS planar validity rules.",
        shapely_version=shapely.__version__, geos_version=shapely.geos_version_string,
        **measure_info)


def audit_geometries(data, *, id_field=None, metric_crs=None, progress=None, cancel=None):
    """Diagnose every feature while preserving the original layer.

    An explicit ``id_field`` must contain unique, nonmissing scalar labels. If
    omitted, ``feature_id`` is the zero-based source row number, which is only
    stable for this input ordering. ``report`` contains every row and ``issues``
    contains its original geometry when missing, empty, invalid, nonfinite or
    exactly duplicated. This procedure never repairs or removes features.
    """
    _check_cancel(cancel)
    source, identifiers = _identified_frame(data, id_field)
    transformer, factor, measure_info = _measurement_context(source.crs, metric_crs)
    geometries = source.geometry.tolist()
    rows = _diagnostic_rows(source, identifiers, transformer, factor, progress, cancel)
    report = _report(rows, _AUDIT_COLUMNS)
    selected = [row["status"] != "valid" for row in rows]
    summary = _summary(source, rows, id_field, measure_info, "audit_geometries")
    summary.update(output_features=len(source), issue_features=sum(selected))
    return VectorQualityResult(source, report, summary,
                               issues=_issues(report, geometries, selected, source.crs),
                               rejected=source.iloc[0:0].copy())


def _repair_function(method, keep_collapsed):
    if method not in {"linework", "structure"}:
        raise ValueError("method must be 'linework' or 'structure'.")
    if not isinstance(keep_collapsed, (bool, np.bool_)):
        raise ValueError("keep_collapsed must be a boolean.")
    if method == "linework":
        if not keep_collapsed:
            raise ValueError("linework requires keep_collapsed=True; choose structure to discard collapsed parts.")
        # Shapely 2.0 has no method keyword; its sole algorithm is linework.
        return shapely.make_valid
    if "method" not in inspect.signature(shapely.make_valid).parameters or tuple(shapely.geos_version) < (3, 10, 0):
        raise ValueError("method='structure' requires Shapely >= 2.1 and GEOS >= 3.10.")
    return lambda geometry: shapely.make_valid(geometry, method="structure", keep_collapsed=bool(keep_collapsed))


def repair_geometries(data, *, id_field=None, method="linework", missing="keep", empty="keep",
                      type_changes="allow", keep_collapsed=True, metric_crs=None,
                      progress=None, cancel=None):
    """Repair invalid finite geometries with explicit retention policies.

    ``missing`` and ``empty`` accept ``keep``, ``drop`` or ``error``. The empty
    policy also applies when repair collapses a geometry to an empty result.
    ``type_changes`` accepts ``allow``, ``drop`` or ``error`` and compares exact
    geometry types, including Polygon to MultiPolygon. A dropped feature is
    stored unchanged in ``rejected``. Collections and lower-dimensional parts
    are preserved when allowed, without implicit polygon extraction.

    Already valid geometries are passed through unchanged, even with structure.
    Nonfinite coordinates or a still-invalid nonempty repair cause an error;
    there is no implicit coordinate removal. ``report`` covers every source
    row, including rejected features, with before/after measurements and reasons.
    GEOS may change topology: invalid pre-repair areas are not reliable surfaces.
    """
    _check_cancel(cancel)
    for name, policy in (("missing", missing), ("empty", empty)):
        if policy not in {"keep", "drop", "error"}:
            raise ValueError(f"{name} must be 'keep', 'drop' or 'error'.")
    if type_changes not in {"allow", "drop", "error"}:
        raise ValueError("type_changes must be 'allow', 'drop' or 'error'.")
    repair = _repair_function(method, keep_collapsed)
    source, identifiers = _identified_frame(data, id_field)
    transformer, factor, measure_info = _measurement_context(source.crs, metric_crs)
    originals = source.geometry.tolist()
    # Audit callbacks are omitted here so progress is monotonic over the public
    # repair pass. Cancellation is still checked during diagnosis.
    before = _diagnostic_rows(source, identifiers, transformer, factor, None, cancel)
    rows, results, accepted = [], [], []
    if progress:
        progress(0, len(source))
    for position, (geometry, state) in enumerate(zip(originals, before)):
        _check_cancel(cancel)
        after_geometry = geometry
        decision = "unchanged"
        keep = True
        if state["nonfinite"]:
            raise ValueError(f"Non-finite geometry coordinates at source_row {position}; repair was not applied.")
        if state["missing"]:
            if missing == "error":
                raise ValueError(f"Missing geometry at source_row {position}.")
            keep = missing != "drop"
            decision = "kept_missing" if keep else "dropped_missing"
        elif state["empty"]:
            if empty == "error":
                raise ValueError(f"Empty geometry at source_row {position}.")
            keep = empty != "drop"
            decision = "kept_empty" if keep else "dropped_empty"
        elif not state["valid"]:
            try:
                after_geometry = repair(geometry)
            except shapely.errors.GEOSException as exc:
                raise ValueError(f"GEOS repair failed at source_row {position}: {exc}") from exc
            decision = "repaired"
        after = _state(after_geometry)
        changed_type = state["geometry_type"] != after["geometry_type"]
        changed = ((geometry is None) != (after_geometry is None)
                   or geometry is not None and after_geometry is not None and geometry.wkb != after_geometry.wkb)
        if ((after["missing"] and not state["missing"]) or after["nonfinite"]
                or (not after["missing"] and not after["empty"] and not after["valid"])):
            raise ValueError(f"Repair did not produce a finite valid geometry at source_row {position}: {after['reason']}")
        if decision == "repaired" and after["empty"]:
            if empty == "error":
                raise ValueError(f"Repair produced an empty geometry at source_row {position}.")
            keep = empty != "drop"
            decision = "kept_empty_repair" if keep else "dropped_empty_repair"
        if changed_type:
            if type_changes == "error":
                raise ValueError(f"Geometry type changed at source_row {position}: {state['geometry_type']} -> {after['geometry_type']}.")
            if type_changes == "drop":
                keep = False
                decision = "dropped_type_change"
        area_after, length_after = _measures(after_geometry, transformer, factor)
        row = dict(source_row=position, feature_id=identifiers[position], decision=decision,
                   retained=keep, geometry_changed=bool(changed), type_changed=changed_type,
                   duplicate_of_row=state["duplicate_of_row"])
        for name in ("geometry_type", "missing", "empty", "nonfinite", "valid", "reason"):
            row["before_" + name] = state[name]
            row["after_" + name] = after[name]
        row.update(before_area_m2=state["area_m2"], after_area_m2=area_after,
                   area_delta_m2=area_after - state["area_m2"],
                   before_length_m=state["length_m"], after_length_m=length_after,
                   length_delta_m=length_after - state["length_m"])
        # Collapsed components inside a collection are recorded as well as a
        # wholly collapsed feature. Dimensions of empty results are undefined.
        original_dimension = int(shapely.get_dimensions(geometry)) if geometry is not None else -1
        def lower_dimension(part):
            if part is None or part.is_empty:
                return False
            if hasattr(part, "geoms"):
                return any(lower_dimension(component) for component in part.geoms)
            return int(shapely.get_dimensions(part)) < original_dimension
        row["collapsed"] = bool(changed and not state["missing"] and not state["empty"] and
                                (after["empty"] or lower_dimension(after_geometry)))
        row["after_collection"] = after["geometry_type"] == "GeometryCollection"
        rows.append(row)
        results.append(after_geometry)
        accepted.append(keep)
        if progress:
            progress(position + 1, len(source))
    _check_cancel(cancel)
    columns = ["source_row", "feature_id", "decision", "retained", "geometry_changed", "type_changed",
               "duplicate_of_row"]
    for name in ("geometry_type", "missing", "empty", "nonfinite", "valid", "reason"):
        columns += ["before_" + name, "after_" + name]
    columns += ["before_area_m2", "after_area_m2", "area_delta_m2", "before_length_m",
                "after_length_m", "length_delta_m", "collapsed", "after_collection"]
    report = _report(rows, columns)
    selected = [not keep or row["status"] != "valid" for keep, row in zip(accepted, before)]
    kept_positions = [i for i, keep in enumerate(accepted) if keep]
    rejected_positions = [i for i, keep in enumerate(accepted) if not keep]
    repaired = source.iloc[kept_positions].copy()
    # Assign positionally: source dataframe labels may legitimately be repeated.
    repaired.geometry = gpd.array.from_shapely([results[i] for i in kept_positions], crs=source.crs)
    summary = _summary(source, before, id_field, measure_info, "repair_geometries")
    summary.update(
        output_features=len(repaired), rejected_features=len(rejected_positions),
        method=method, missing_policy=missing, empty_policy=empty,
        type_change_policy=type_changes, keep_collapsed=bool(keep_collapsed),
        repaired_features=sum(row["geometry_changed"] for row in rows),
        retained_repaired_features=sum(row["geometry_changed"] and row["retained"] for row in rows),
        type_changed_features=sum(row["type_changed"] for row in rows),
        collapsed_features=sum(row["collapsed"] for row in rows),
        retained_unusable_features=sum(row["retained"] and (row["after_missing"] or row["after_empty"])
                                      for row in rows),
        output_missing_geometries=sum(row["retained"] and row["after_missing"] for row in rows),
        output_empty_geometries=sum(row["retained"] and row["after_empty"] for row in rows),
        output_invalid_geometries=sum(row["retained"] and not row["after_missing"]
                                      and not row["after_empty"] and not row["after_valid"] for row in rows),
        issue_features=sum(selected), output_geometry_types=dict(Counter(repaired.geom_type.dropna())))
    return VectorQualityResult(repaired, report, summary,
                               issues=_issues(report, originals, selected, source.crs),
                               rejected=source.iloc[rejected_positions].copy())
