"""Geometry diagnosis and explicit GEOS repair with a row-level audit.

All predicates and repairs are planar. An optional, explicitly requested XY
precision grid follows repair; its effects are recorded separately. Features
are never merged. WKB duplicates are exact, including vertex order, and are
diagnosed rather than deleted by these procedures.
"""
from __future__ import annotations

import inspect
from collections import Counter
from hashlib import sha256
from numbers import Real
import warnings

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from pyproj import CRS, Transformer

from ._validation import frame, linear_factor
from .imagery import _check_cancel
from .vector_quality_result import VectorQualityResult


def _quality_source(data, layer):
    """Select a file layer deliberately, without changing other procedures."""
    if isinstance(data, (gpd.GeoDataFrame, gpd.GeoSeries)):
        if layer is not None:
            raise ValueError("layer is only supported for a file input, not an in-memory layer.")
        return frame(data), None
    # pyogrio's metadata can already erase the M suffix and signal it only as
    # a warning. Older GEOS must be stopped before that file reaches Shapely.
    supports_m = hasattr(shapely, 'has_m') and tuple(shapely.geos_version) >= (3, 12, 0)
    with warnings.catch_warnings():
        if not supports_m:
            warnings.filterwarnings('error', message=r'.*[Mm]easured.*geometry types.*')
        try:
            return _quality_file(data, layer)
        except UserWarning as exc:
            if 'measured' not in str(exc).lower():
                raise
            raise ValueError("Measured (M) input requires Shapely >= 2.1 and GEOS >= 3.12; refusing a read that could lose M.") from exc


def _quality_file(data, layer):
    import pyogrio
    from .vector_io import read_vector
    if layer is not None and (not isinstance(layer, str) or not layer.strip()):
        raise ValueError("layer must be a nonempty layer name.")
    layers = [str(name) for name, kind in pyogrio.list_layers(data) if kind is not None]
    if not layers:
        raise ValueError("The input contains no vector geometry layer.")
    if layer is None:
        if len(layers) != 1:
            raise ValueError("The input contains multiple layers; choose layer explicitly: " + ", ".join(layers))
        layer = layers[0]
    elif layer not in layers:
        raise ValueError(f"Unknown vector layer {layer!r}; available layers: " + ", ".join(layers))
    return frame(read_vector(data, layer=layer)), layer


def _precision_context(tolerance, crs):
    if (not isinstance(tolerance, Real) or isinstance(tolerance, (bool, np.bool_))
            or not np.isfinite(tolerance) or tolerance < 0):
        raise ValueError("tolerance must be a finite nonnegative number, not a boolean.")
    source = CRS.from_user_input(crs)
    factor = linear_factor(source) if tolerance > 0 else None
    return dict(tolerance=float(tolerance),
                tolerance_unit=source.axis_info[0].unit_name if source.axis_info else None,
                tolerance_metres_per_unit=factor,
                precision_mode='valid_output' if tolerance > 0 else None)


def _parts(geometry):
    if geometry is None or geometry.is_empty:
        return 0
    return sum(_parts(part) for part in geometry.geoms) if hasattr(geometry, 'geoms') else 1


def _dimension_flags(geometry):
    if geometry is None:
        return False, False
    # Read the dimension declaration, including an explicitly supplied NaN Z.
    # GEOS versions before 3.12 can report has_z=False for that coordinate.
    wkb = geometry.wkb
    code = int.from_bytes(wkb[1:5], 'little' if wkb[0] else 'big')
    iso = (code & 0x0fffffff) // 1000
    return bool(code & 0x80000000 or iso in (1, 3)), bool(code & 0x40000000 or iso in (2, 3))


def _changed(before, after):
    return ((before is None) != (after is None)
            or before is not None and after is not None and before.wkb != after.wkb)


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
    has_z, has_m = _dimension_flags(geometry)
    return dict(geometry_type=None if missing else geometry.geom_type,
                missing=missing, empty=empty, nonfinite=not finite,
                valid=valid, reason=reason, has_z=has_z, has_m=has_m,
                coordinate_dimension=0 if missing else 2 + int(has_z) + int(has_m),
                topological_dimension=int(shapely.get_dimensions(geometry)),
                coordinate_count=int(shapely.get_num_coordinates(geometry)),
                part_count=_parts(geometry),
                wkb_sha256=None if missing else sha256(geometry.wkb).hexdigest())


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


_STATE_COLUMNS = ["geometry_type", "missing", "empty", "nonfinite", "valid", "reason",
                  "has_z", "has_m", "coordinate_dimension", "topological_dimension",
                  "coordinate_count", "part_count", "wkb_sha256"]
_AUDIT_COLUMNS = ["source_row", "feature_id", "output_row", "rejected_row", "status", *_STATE_COLUMNS,
                  "duplicate_of_row", "area_m2", "length_m"]


def _report(rows, columns):
    result = pd.DataFrame(rows, columns=columns)
    # Inferred float dtype would round large integer identifiers when a table
    # mixes numeric types. Identifiers are labels and must never be coerced.
    result["feature_id"] = pd.Series([row["feature_id"] for row in rows], dtype=object)
    result["source_row"] = result["source_row"].astype("int64")
    for name in ("duplicate_of_row", "output_row", "rejected_row"):
        if name in result:
            result[name] = pd.array([row[name] for row in rows], dtype="Int64")
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
        coordinate_policy="Original coordinates; GEOS planar validity rules.",
        shapely_version=shapely.__version__, geos_version=shapely.geos_version_string,
        **measure_info)


def audit_geometries(data, *, layer=None, id_field=None, metric_crs=None, progress=None, cancel=None):
    """Diagnose every feature while preserving the original layer.

    An explicit ``id_field`` must contain unique, nonmissing scalar labels. If
    omitted, ``feature_id`` is the zero-based source row number, which is only
    stable for this input ordering. ``report`` contains every row and ``issues``
    contains its original geometry when missing, empty, invalid, nonfinite or
    exactly duplicated. ``before`` is the complete original layer. File inputs
    with several layers require an explicit ``layer`` name. This procedure
    never repairs or removes features, or changes their coordinate precision.
    """
    _check_cancel(cancel)
    source, source_layer = _quality_source(data, layer)
    source, identifiers = _identified_frame(source, id_field)
    transformer, factor, measure_info = _measurement_context(source.crs, metric_crs)
    geometries = source.geometry.tolist()
    rows = _diagnostic_rows(source, identifiers, transformer, factor, progress, cancel)
    for row in rows:
        row['output_row'] = row['source_row']
        row['rejected_row'] = None
    report = _report(rows, _AUDIT_COLUMNS)
    selected = [row["status"] != "valid" for row in rows]
    summary = _summary(source, rows, id_field, measure_info, "audit_geometries")
    summary.update(output_features=len(source), rejected_features=0, issue_features=sum(selected), source_layer=source_layer,
                   row_mapping="source_row identifies before; output_row identifies data, both zero-based.",
                   report_label_columns=['feature_id'],
                   processing_steps=['diagnose_original'])
    return VectorQualityResult(source, report, summary,
                               issues=_issues(report, geometries, selected, source.crs),
                               rejected=source.iloc[0:0].copy(), before=source.copy())


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


def repair_geometries(data, *, layer=None, id_field=None, method="linework", missing="keep", empty="keep",
                      type_changes="allow", keep_collapsed=True, tolerance=0.0, metric_crs=None,
                      progress=None, cancel=None):
    """Repair invalid finite geometries with explicit retention policies.

    ``missing`` and ``empty`` accept ``keep``, ``drop`` or ``error``. The empty
    policy also applies when repair collapses a geometry to an empty result.
    ``type_changes`` accepts ``allow``, ``drop`` or ``error`` and compares exact
    geometry types, including Polygon to MultiPolygon. A dropped feature is
    stored unchanged in ``rejected``. Collections and lower-dimensional parts
    are preserved when allowed, without implicit polygon extraction.

    ``tolerance`` is an optional XY precision-grid spacing in the units of the
    SOURCE projected CRS. Zero disables it and already valid geometries pass
    through unchanged. A positive grid is applied AFTER GEOS repair, using
    ``valid_output``; it can remove vertices/parts or produce empty results.
    The empty and type-change policies apply to that final result too.
    ``keep_collapsed`` controls GEOS repair only, not the grid. ``metric_crs``
    affects measurements only. Repair and precision changes are distinguished
    in the report. M geometries cannot be modified without losing measures and
    are refused before either operation. Z is carried by the planar engine,
    which may interpolate new Z vertices; this is not a validation of Z values.

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
    source, source_layer = _quality_source(data, layer)
    source, identifiers = _identified_frame(source, id_field)
    precision_info = _precision_context(tolerance, source.crs)
    tolerance = precision_info['tolerance']
    transformer, factor, measure_info = _measurement_context(source.crs, metric_crs)
    originals = source.geometry.tolist()
    # Audit callbacks are omitted here so progress is monotonic over the public
    # repair pass. Cancellation is still checked during diagnosis.
    before = _diagnostic_rows(source, identifiers, transformer, factor, None, cancel)
    for position, state in enumerate(before):
        if (state['has_m'] and not state['missing'] and not state['empty']
                and (not state['valid'] or tolerance > 0)):
            raise ValueError(f"Measured (M) geometry at source_row {position}; repair or precision modification cannot preserve M.")
    rows, results, accepted = [], [], []
    output_row = rejected_row = 0
    if progress:
        progress(0, len(source))
    for position, (geometry, state) in enumerate(zip(originals, before)):
        _check_cancel(cancel)
        after_geometry = geometry
        decision = "unchanged"
        keep = True
        repair_changed = precision_changed = False
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
            repair_changed = bool(_changed(geometry, after_geometry))
        intermediate = _state(after_geometry)
        if (intermediate['nonfinite'] or not intermediate['missing'] and not intermediate['empty']
                and not intermediate['valid']):
            raise ValueError(f"Repair did not produce a finite valid geometry at source_row {position}: {intermediate['reason']}")
        if tolerance > 0 and after_geometry is not None and not after_geometry.is_empty:
            try:
                precise = shapely.set_precision(after_geometry, tolerance, mode='valid_output')
            except shapely.errors.GEOSException as exc:
                raise ValueError(f"Precision grid failed at source_row {position}: {exc}") from exc
            precision_changed = bool(_changed(after_geometry, precise))
            after_geometry = precise
            if precision_changed:
                decision = 'repaired_and_precision' if repair_changed else 'precision_changed'
        after = _state(after_geometry)
        changed_type = state["geometry_type"] != after["geometry_type"]
        changed = _changed(geometry, after_geometry)
        if ((after["missing"] and not state["missing"]) or after["nonfinite"]
                or (not after["missing"] and not after["empty"] and not after["valid"])):
            raise ValueError(f"Repair did not produce a finite valid geometry at source_row {position}: {after['reason']}")
        if not state['missing'] and not state['empty'] and after["empty"]:
            stage = 'precision' if precision_changed else 'repair'
            if empty == "error":
                raise ValueError(f"{stage.capitalize()} produced an empty geometry at source_row {position}.")
            keep = empty != "drop"
            decision = ('kept_empty_' if keep else 'dropped_empty_') + stage
        if changed_type:
            if type_changes == "error":
                raise ValueError(f"Geometry type changed at source_row {position}: {state['geometry_type']} -> {after['geometry_type']}.")
            if type_changes == "drop":
                keep = False
                decision = "dropped_type_change"
        area_after, length_after = _measures(after_geometry, transformer, factor)
        row = dict(source_row=position, feature_id=identifiers[position], decision=decision,
                   retained=keep, geometry_changed=bool(changed), type_changed=changed_type,
                   repair_changed=repair_changed, precision_changed=precision_changed,
                   output_row=output_row if keep else None, rejected_row=None if keep else rejected_row,
                   duplicate_of_row=state["duplicate_of_row"])
        output_row += int(keep)
        rejected_row += int(not keep)
        for name in _STATE_COLUMNS:
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
    columns = ["source_row", "feature_id", "output_row", "rejected_row", "decision", "retained",
               "geometry_changed", "type_changed", "repair_changed", "precision_changed", "duplicate_of_row"]
    for name in _STATE_COLUMNS:
        columns += ["before_" + name, "after_" + name]
    columns += ["before_area_m2", "after_area_m2", "area_delta_m2", "before_length_m",
                "after_length_m", "length_delta_m", "collapsed", "after_collection"]
    report = _report(rows, columns)
    selected = [not keep or original["status"] != "valid" for keep, original in zip(accepted, before)]
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
        source_layer=source_layer, **precision_info,
        coordinate_policy=("GEOS planar repair, then XY grid in source projected CRS units; valid_output removes collapsed parts."
                           if tolerance > 0 else "GEOS planar repair; no precision grid; valid geometries unchanged."),
        processing_steps=['diagnose_original', 'repair_invalid'] + (['xy_precision_grid'] if tolerance > 0 else []) + ['validate_final'],
        dimensional_policy="Planar operations may interpolate Z at new vertices; M modification is refused.",
        row_mapping="source_row identifies before; output_row identifies data; rejected_row identifies rejected, all zero-based.",
        report_label_columns=['feature_id'],
        repair_changed_features=sum(row['repair_changed'] for row in rows),
        precision_changed_features=sum(row['precision_changed'] for row in rows),
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
                               rejected=source.iloc[rejected_positions].copy(), before=source.copy())
