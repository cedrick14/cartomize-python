"""Explicit vector duplicate rules with complete source-row provenance.

Duplicate detection never aggregates measurements or silently chooses all
attributes. A retained row is an unchanged source record, including its index,
attribute dtypes and active geometry column.
"""

from collections import defaultdict

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely import STRtree

from ._validation import frame
from .algebra import ProcessingCancelled
from .vector_quality_result import VectorQualityResult


def _check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise ProcessingCancelled("Traitement interrompu.")


def _fields(data, value, parameter):
    if value is None:
        return []
    fields = [value] if isinstance(value, str) else value
    if not isinstance(fields, (list, tuple)) or any(
        not isinstance(field, str) or not field for field in fields
    ):
        raise ValueError(f"{parameter} must be a field name or a list of field names.")
    if len(set(fields)) != len(fields):
        raise ValueError(f"{parameter} contains repeated fields.")
    for field in fields:
        if field not in data.columns:
            raise ValueError(f"Unknown {parameter} field: {field!r}.")
        if isinstance(data[field].dtype, gpd.array.GeometryDtype):
            raise ValueError(f"{parameter} cannot use geometry field {field!r} as an attribute.")
    return list(fields)


def _missing(value, field):
    """Inspect scalars without coercing integers or accepting array-valued keys."""
    missing = pd.isna(value)
    if not isinstance(missing, (bool, np.bool_)):
        raise ValueError(f"Field {field!r} must contain scalar, hashable values.")
    if not missing:
        try:
            hash(value)
        except TypeError as exc:
            raise ValueError(f"Field {field!r} must contain scalar, hashable values.") from exc
    return bool(missing)


def _finite_geometry(geom, cancel):
    """Check present ordinates, without manufacturing NaN Z values for 2D parts."""
    _check_cancel(cancel)
    if geom.is_empty:
        return True
    if geom.geom_type == "Polygon":
        return _finite_geometry(geom.exterior, cancel) and all(
            _finite_geometry(ring, cancel) for ring in geom.interiors
        )
    if hasattr(geom, "geoms"):
        return all(_finite_geometry(part, cancel) for part in geom.geoms)
    return bool(np.isfinite(np.asarray(geom.coords, dtype=float)).all())


def _retained_ids(source_ids, representatives):
    """Build nullable identifiers without converting large integers to floats."""
    values = [pd.NA if row < 0 else source_ids.array[row] for row in representatives]
    dtype = source_ids.dtype
    if any(row < 0 for row in representatives):
        if pd.api.types.is_integer_dtype(dtype):
            # Nullable integer dtypes preserve the full signed/unsigned domain.
            prefix = "UInt" if pd.api.types.is_unsigned_integer_dtype(dtype) else "Int"
            dtype = prefix + str(dtype.itemsize * 8)
        elif pd.api.types.is_bool_dtype(dtype):
            dtype = "boolean"
    try:
        return pd.Series(values, dtype=dtype)
    except (TypeError, ValueError):
        # Exotic scalar extension types can still be reported losslessly.
        return pd.Series(values, dtype=object)


def deduplicate(data, *, keys=None, geometry="none", keep="first",
                order_by=None, ascending=True, null_keys="distinct",
                id_field=None, progress=None, cancel=None):
    """Remove explicitly defined duplicates and return an auditable result.

    ``keys`` selects attribute fields. ``geometry`` is ``none`` (attributes
    only), ``exact`` (identical WKB, including coordinate/part order and Z/M),
    or ``topological`` (the same XY point set, irrespective of vertex ordering,
    ring direction or redundant vertices). When both are selected, attributes
    **and** geometry must match. At least one criterion is required.
    Numeric keys such as 1 and 1.0 compare equal, while boolean keys are a
    distinct category: True is not the number 1, and False is not 0. Text keys
    are never converted to numbers.

    Null attribute keys are distinct by default; ``null_keys='match'`` matches
    equal null patterns and ``'error'`` refuses them. Missing and empty
    geometries always remain distinct when geometry is a comparison criterion;
    with ``geometry='none'`` they have no effect. Topological comparison refuses
    invalid geometries and nonfinite coordinates, including present Z/M values.
    Topology is planar: finite Z/M differences do not prevent XY equality.

    ``keep`` selects the first or last complete source record per group, or
    ``'none'`` removes all members of a duplicated group. ``order_by`` optionally
    determines first/last selection; ties follow source position and missing
    order values are always last. ``ascending`` applies to every ordering field.
    No attribute aggregation is performed. Both data and rejected layers retain
    source order, indices (even duplicates), attribute dtypes and CRS.

    The report contains every source row, a one-based group identifier, group
    size, retained status, the selected source row and its identifier, plus a
    decision reason. Source row positions are zero-based and unambiguous even
    for duplicate or MultiIndex labels. ``id_field`` must be unique and nonnull;
    otherwise row position serves as the identifier. A group removed by
    ``keep='none'`` has no retained row or identifier.

    ``progress(done, total)`` uses a total of 10000. ``cancel`` accepts a
    threading.Event-compatible object; cancellation raises ProcessingCancelled
    before returning any result. Source data is never modified.
    """
    _check_cancel(cancel)
    if not isinstance(geometry, str) or geometry not in {"none", "exact", "topological"}:
        raise ValueError("geometry must be 'none', 'exact' or 'topological'.")
    if not isinstance(keep, str) or keep not in {"first", "last", "none"}:
        raise ValueError("keep must be 'first', 'last' or 'none'.")
    if not isinstance(null_keys, str) or null_keys not in {"distinct", "match", "error"}:
        raise ValueError("null_keys must be 'distinct', 'match' or 'error'.")
    if not isinstance(ascending, (bool, np.bool_)):
        raise ValueError("ascending must be a boolean.")
    if progress is not None and not callable(progress):
        raise ValueError("progress must be callable.")

    source = frame(data)
    if not source.columns.is_unique:
        raise ValueError("Input field names must be unique.")
    keys = _fields(source, keys, "keys")
    order_by = _fields(source, order_by, "order_by")
    if not keys and geometry == "none":
        raise ValueError("Specify keys or a geometry comparison; no duplicate criteria were supplied.")
    if id_field is not None:
        if not isinstance(id_field, str) or not id_field:
            raise ValueError("id_field must name one attribute field.")
        _fields(source, id_field, "id_field")
        seen_ids = set()
        for row, value in enumerate(source[id_field].array):
            _check_cancel(cancel)
            if _missing(value, id_field):
                raise ValueError(f"id_field {id_field!r} has missing values at source row {row}.")
            if value in seen_ids:
                raise ValueError(f"id_field {id_field!r} must contain unique values.")
            seen_ids.add(value)

    def advance(done):
        _check_cancel(cancel)
        if progress is not None:
            progress(int(done), 10000)
        _check_cancel(cancel)

    advance(0)
    count = len(source)
    geometries = source.geometry.array
    attribute_arrays = [source[field].array for field in keys]
    # A dedicated object distinguishes missing scalars from every user value.
    missing_token = object()
    boolean_token = object()
    row_keys = []
    distinct_reason = [None] * count
    null_rows = 0
    missing_geometries = 0
    empty_geometries = 0
    for row in range(count):
        _check_cancel(cancel)
        key, has_null = [], False
        for field, values in zip(keys, attribute_arrays):
            value = values[row]
            if _missing(value, field):
                has_null = True
                key.append(missing_token)
            elif isinstance(value, (bool, np.bool_)):
                # Python dictionaries equate True/1 and False/0. Those values
                # are distinct attribute categories in a mixed object column.
                # A private tag keeps booleans separate without changing the
                # exact equality of integral and floating numeric values.
                key.append((boolean_token, bool(value)))
            else:
                key.append(value)
        null_rows += int(has_null)
        if has_null and null_keys == "error":
            raise ValueError(f"keys contain missing values at source row {row}.")
        if has_null and null_keys == "distinct":
            distinct_reason[row] = "null_key_distinct"
        geom = geometries[row]
        if geom is None:
            missing_geometries += 1
            if geometry != "none":
                distinct_reason[row] = "missing_geometry_distinct"
        elif geom.is_empty:
            empty_geometries += 1
            if geometry != "none":
                distinct_reason[row] = "empty_geometry_distinct"
        elif geometry == "topological":
            if not _finite_geometry(geom, cancel):
                raise ValueError(f"Nonfinite coordinates at source row {row}; topological comparison refused.")
            if not geom.is_valid:
                raise ValueError(f"Invalid geometry at source row {row}; topological comparison refused.")
        row_keys.append(tuple(key))
        if row % 128 == 0 or row + 1 == count:
            advance(3000 * (row + 1) // max(1, count))
    advance(3000)

    roots = np.full(count, -1, dtype=np.int64)
    groups = {}
    partitions = defaultdict(list)
    for row, key in enumerate(row_keys):
        _check_cancel(cancel)
        if distinct_reason[row] is not None:
            roots[row] = row
            groups[row] = [row]
        elif geometry == "exact":
            partitions[(key, geometries[row].wkb)].append(row)
        else:
            partitions[key].append(row)

    grouped_count = int(np.count_nonzero(roots >= 0))
    for members in partitions.values():
        _check_cancel(cancel)
        if geometry != "topological" or len(members) == 1:
            first = members[0]
            groups[first] = members
            roots[members] = first
            grouped_count += len(members)
            advance(3000 + 5000 * grouped_count // max(1, count))
            continue
        # Query once per new equivalence class. A duplicate block is assigned
        # together, rather than re-comparing each row to all earlier rows.
        tree = STRtree([geometries[row] for row in members])
        bounds = [geometries[row].bounds for row in members]
        for local_row, row in enumerate(members):
            _check_cancel(cancel)
            if roots[row] >= 0:
                continue
            geom = geometries[row]
            equivalents = [row]
            roots[row] = row
            for candidate_position in tree.query(geom):
                _check_cancel(cancel)
                candidate_position = int(candidate_position)
                candidate = members[candidate_position]
                if roots[candidate] >= 0 or bounds[candidate_position] != bounds[local_row]:
                    continue
                if geom.equals(geometries[candidate]):
                    equivalents.append(candidate)
                    roots[candidate] = row
            groups[row] = sorted(equivalents)
            grouped_count += len(equivalents)
            advance(3000 + 5000 * grouped_count // max(1, count))
    advance(8000)

    ranks = np.arange(count, dtype=np.int64)
    if order_by and count:
        ordering = source[order_by].reset_index(drop=True).copy()
        row_column = object()
        ordering[row_column] = ranks
        try:
            sorted_rows = ordering.sort_values(
                by=[*order_by, row_column],
                ascending=[bool(ascending)] * len(order_by) + [True],
                na_position="last", kind="stable",
            )[row_column].to_numpy(dtype=np.int64)
        except (TypeError, ValueError) as exc:
            raise ValueError("order_by fields must contain mutually sortable values.") from exc
        ranks[sorted_rows] = np.arange(count, dtype=np.int64)
    _check_cancel(cancel)

    group_ids = np.empty(count, dtype=np.int64)
    group_sizes = np.empty(count, dtype=np.int64)
    representatives = np.full(count, -1, dtype=np.int64)
    retained = np.zeros(count, dtype=bool)
    reasons = [None] * count
    duplicate_groups = 0
    duplicate_features = 0
    for group_id, root in enumerate(sorted(groups), start=1):
        _check_cancel(cancel)
        members = groups[root]
        group_ids[members] = group_id
        group_sizes[members] = len(members)
        if len(members) > 1:
            duplicate_groups += 1
            duplicate_features += len(members)
        if keep == "none" and len(members) > 1:
            for row in members:
                reasons[row] = "duplicate_group_removed"
            continue
        chooser = max if keep == "last" else min
        representative = chooser(members, key=lambda row: ranks[row])
        representatives[members] = representative
        retained[representative] = True
        for row in members:
            if len(members) == 1:
                reasons[row] = distinct_reason[row] or "unique"
            elif row == representative:
                reasons[row] = f"duplicate_group_keep_{keep}"
            else:
                reasons[row] = "duplicate_removed"

    source_ids = (source[id_field].reset_index(drop=True).copy() if id_field
                  else pd.Series(np.arange(count, dtype=np.int64)))
    source_index = list(source.index)
    report = pd.DataFrame({
        "source_row": np.arange(count, dtype=np.int64),
        "source_index": pd.Series(source_index, dtype=object),
        "source_id": source_ids,
        "group_id": group_ids,
        "group_size": group_sizes,
        "retained": retained,
        "retained_row": pd.array(
            [pd.NA if row < 0 else int(row) for row in representatives], dtype="Int64"
        ),
        "retained_index": pd.Series(
            [None if row < 0 else source_index[row] for row in representatives], dtype=object
        ),
        "retained_id": _retained_ids(source_ids, representatives),
        "reason": pd.Series(reasons, dtype="string"),
    })
    output = source.iloc[np.flatnonzero(retained)].copy()
    rejected = source.iloc[np.flatnonzero(~retained)].copy()
    summary = {
        "procedure": "deduplicate",
        "crs": str(source.crs),
        "input_features": count,
        "output_features": len(output),
        "removed_features": len(rejected),
        "groups": len(groups),
        "duplicate_groups": duplicate_groups,
        "duplicate_features": duplicate_features,
        "null_key_features": null_rows,
        "missing_geometries": missing_geometries,
        "empty_geometries": empty_geometries,
        "parameters": {
            "keys": keys, "geometry": geometry, "keep": keep,
            "order_by": order_by, "ascending": bool(ascending),
            "null_keys": null_keys, "id_field": id_field,
        },
        "source_row_base": 0,
        "group_id_base": 1,
        "output_order": "source",
        "order_nulls": "last",
        "aggregation": "none; selected complete source record",
        "attribute_equivalence": "equal numeric values match; booleans are distinct from numbers; text is not coerced",
        "geometry_equivalence": {
            "none": "geometry ignored",
            "exact": "identical WKB including coordinate order and Z/M",
            "topological": "identical XY point set; Z/M ignored",
        }[geometry],
        "null_geometry_policy": "distinct when geometry is compared; ignored otherwise",
    }
    advance(10000)
    return VectorQualityResult(data=output, report=report, summary=summary,
                               rejected=rejected)
