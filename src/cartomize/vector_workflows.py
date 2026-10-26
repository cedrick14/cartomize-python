"""Vector workflow primitives with explicit predicates, units and output fields."""
from __future__ import annotations

import operator
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR
import numpy as np
import pandas as pd
import geopandas as gpd

from ._validation import aligned, frame, measurement_frame


def _finite_decimal(value):
    """Parse a numeric filter without rounding an integer identifier to float."""
    try:
        number = Decimal(int(value)) if isinstance(value, (int, np.integer)) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError('A numeric filter requires a finite value.') from exc
    if not number.is_finite():
        raise ValueError('A numeric filter requires a finite value.')
    return number


def _integer_comparison(series, comparison, value):
    """Compare integer/nullable integer fields with exact decimal thresholds."""
    number = _finite_decimal(value)
    present = series.notna()
    if not present.any():
        return present
    # Check the actual range before converting potentially enormous exponents
    # to Python integers, and before pandas can coerce signed/unsigned types.
    minimum, maximum = int(series.min()), int(series.max())
    if number < minimum:
        return present if comparison in {'ne', 'gt', 'ge'} else present & False
    if number > maximum:
        return present if comparison in {'ne', 'lt', 'le'} else present & False
    integral = number == number.to_integral_value()
    if comparison in {'eq', 'ne'}:
        if not integral:
            return present if comparison == 'ne' else present & False
        return getattr(series, comparison)(int(number)) & present
    rounding = ROUND_CEILING if comparison in {'lt', 'ge'} else ROUND_FLOOR
    threshold = int(number.to_integral_value(rounding=rounding))
    return getattr(series, comparison)(threshold) & present


def _integer_membership(series, values):
    present = series.notna()
    minimum = int(series.min()) if present.any() else None
    maximum = int(series.max()) if present.any() else None
    normalized = []
    for value in values:
        if value is None or value is pd.NA or isinstance(value, (float, np.floating)) and np.isnan(value):
            # Preserve pandas' explicit missing-value membership convention.
            normalized.append(value)
            continue
        number = _finite_decimal(value)
        if minimum is not None and minimum <= number <= maximum and number == number.to_integral_value():
            normalized.append(int(number))
    return series.isin(normalized)


def select_attributes(data, field, comparison, value=None):
    """Select whole records without evaluating Python, SQL or query expressions.

    Integer identifiers and numeric text are compared exactly, including signed
    and unsigned nullable 64-bit fields. Decimal thresholds are not rounded to
    a neighbouring integer before deciding the comparison.
    """
    result = frame(data)
    if field not in result.columns or field == result.geometry.name:
        raise ValueError('Select an existing attribute field.')
    series = result[field]
    comparisons = {'eq': operator.eq, 'ne': operator.ne, 'lt': operator.lt,
                   'le': operator.le, 'gt': operator.gt, 'ge': operator.ge}
    if comparison == 'is_null':
        mask = series.isna()
    elif comparison == 'not_null':
        mask = series.notna()
    elif comparison in {'contains', 'starts_with'}:
        if not isinstance(value, str):
            raise ValueError('Text selection requires a string value.')
        text = series.astype('string')
        mask = text.str.contains(value, regex=False, na=False) if comparison == 'contains' else text.str.startswith(value, na=False)
    elif comparison in {'in', 'not_in'}:
        if not isinstance(value, (list, tuple, set)):
            raise ValueError('Membership selection requires a list of values.')
        try:
            mask = _integer_membership(series, value) if pd.api.types.is_integer_dtype(series.dtype) else series.isin(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f'Invalid filter value for {field}: {exc}') from exc
        if comparison == 'not_in':
            mask = ~mask & series.notna()
    elif comparison in comparisons:
        if value is None:
            raise ValueError('Use is_null or not_null for missing values.')
        try:
            if pd.api.types.is_bool_dtype(series.dtype):
                if not isinstance(value, (bool, np.bool_)):
                    raise ValueError('A Boolean field requires true or false.')
            elif pd.api.types.is_integer_dtype(series.dtype):
                mask = _integer_comparison(series, comparison, value)
                return result.loc[mask.fillna(False)].copy()
            elif pd.api.types.is_numeric_dtype(series.dtype):
                value = float(value)
                if not np.isfinite(value):
                    raise ValueError('A numeric filter requires a finite value.')
            elif pd.api.types.is_datetime64_any_dtype(series.dtype):
                value = pd.Timestamp(value)
            mask = comparisons[comparison](series, value) & series.notna()
        except (TypeError, ValueError) as exc:
            raise ValueError(f'Invalid filter value for {field}: {exc}') from exc
    else:
        raise ValueError('Unsupported attribute comparison.')
    return result.loc[mask.fillna(False)].copy()


def select_location(data, mask, *, predicate='intersects'):
    """Select features against the union of mask geometries, retaining attributes.

    The predicate is evaluated as source.predicate(mask_union). Overlapping
    masks never duplicate a selected source record.
    """
    allowed = {'intersects', 'within', 'contains', 'covers', 'covered_by',
               'touches', 'overlaps', 'crosses', 'disjoint'}
    if predicate not in allowed:
        raise ValueError('Unsupported spatial predicate.')
    source, mask = aligned(data, mask)
    valid_mask = mask.geometry.notna() & ~mask.geometry.is_empty
    union = mask.loc[valid_mask].geometry.union_all()
    selected = getattr(source.geometry, predicate)(union)
    selected &= source.geometry.notna() & ~source.geometry.is_empty
    return source.loc[selected].copy()


def geometry_operation(data, operation, *, metric_crs=None, tolerance=0):
    """Derive geometry without changing attributes or the stored input CRS.

    Centroids and simplification require projected units. Simplification
    tolerance is expressed in metres; feet-based projections are converted.
    """
    original = frame(data)
    if operation == 'explode':
        return original.explode(index_parts=False, ignore_index=True)
    allowed = {'centroid', 'representative_point', 'boundary', 'convex_hull', 'simplify'}
    if operation not in allowed:
        raise ValueError('Unsupported geometry operation.')
    work = original.copy()
    if operation in {'centroid', 'simplify'}:
        work, factor = measurement_frame(work, metric_crs)
    if operation == 'simplify':
        tolerance = float(tolerance)
        if not np.isfinite(tolerance) or tolerance < 0:
            raise ValueError('Simplification tolerance must be nonnegative metres.')
        geometry = work.geometry.simplify(tolerance / factor, preserve_topology=True)
    elif operation == 'representative_point':
        geometry = work.geometry.representative_point()
    else:
        geometry = getattr(work.geometry, operation)
    work = work.set_geometry(geometry)
    return work.to_crs(original.crs)


def spatial_summary(zones, observations, *, field=None, statistic='count',
                    predicate='within', output_field=None):
    """Summarize observations per zone, preserving every zone and its index.

    Predicates apply to observations relative to zones. Overlapping zones are
    evaluated independently; a boundary point is excluded with 'within'.
    Count counts records, not distinct sites; callers deduplicate beforehand.
    A sum is zero for a zone without observations, but remains missing when
    observations exist and every value is missing. Missing values do not become
    measured zeros.
    """
    if statistic not in {'count', 'sum', 'mean', 'min', 'max'}:
        raise ValueError('Unsupported summary statistic.')
    if predicate not in {'within', 'intersects', 'covered_by'}:
        raise ValueError('Unsupported summary predicate.')
    zones, observations = aligned(zones, observations)
    output_field = output_field or ('feature_count' if statistic == 'count' else f'{statistic}_{field}')
    if not output_field or output_field in zones.columns:
        raise ValueError('Choose a new, nonempty output field.')
    if statistic != 'count':
        if field not in observations or not pd.api.types.is_numeric_dtype(observations[field].dtype):
            raise ValueError('The summary field must be numeric.')
    right = gpd.GeoDataFrame({'_cm_zone': np.arange(len(zones))}, geometry=zones.geometry.to_numpy(), crs=zones.crs)
    left = gpd.GeoDataFrame(geometry=observations.geometry.to_numpy(), crs=zones.crs)
    if statistic != 'count':
        left['_cm_value'] = observations[field].to_numpy()
    joined = gpd.sjoin(left, right, how='inner', predicate=predicate)
    if statistic == 'count':
        values = joined.groupby('_cm_zone').size().reindex(range(len(zones)), fill_value=0).astype('int64')
    else:
        grouped = joined.groupby('_cm_zone')['_cm_value']
        if statistic == 'sum':
            values = grouped.sum(min_count=1).reindex(range(len(zones)), fill_value=0)
        else:
            values = grouped.agg(statistic).reindex(range(len(zones)))
    zones[output_field] = values.to_numpy()
    return zones


def join_attributes(data, table, *, left_on, right_on=None, how='left', validate='many_to_one',
                    null_keys='unmatched'):
    """Attach attributes with explicit cardinality and missing-key semantics.

    ``unmatched`` (default) never joins missing identifiers; a left join keeps
    their source records without table attributes. Cardinality is checked on
    nonmissing keys found on both sides. ``match`` explicitly requests pandas'
    missing-to-missing joins and full-key cardinality checks. ``error`` rejects
    any missing key. Output follows source order and then table order, retaining
    all permitted matches rather than selecting an implicit first record.
    """
    source = frame(data)
    table = pd.DataFrame(table).copy()
    right_on = right_on or left_on
    if how not in {'left', 'inner'}:
        raise ValueError('Attribute joins support left or inner joins.')
    if validate not in {'one_to_one', 'one_to_many', 'many_to_one', 'many_to_many'}:
        raise ValueError('Unsupported join cardinality.')
    if null_keys not in {'unmatched', 'match', 'error'}:
        raise ValueError('null_keys must be unmatched, match or error.')
    if left_on not in source or right_on not in table:
        raise ValueError('Join fields do not exist.')
    if source.geometry.name in table:
        raise ValueError('The joined table must not contain a geometry column.')
    if null_keys == 'match':
        return source.merge(table, left_on=left_on, right_on=right_on, how=how, validate=validate, sort=False)
    left_missing, right_missing = source[left_on].isna(), table[right_on].isna()
    if null_keys == 'error' and (left_missing.any() or right_missing.any()):
        raise ValueError('Join keys contain missing values; choose null_keys=unmatched or match explicitly.')
    table = table.loc[~right_missing].copy()
    left_keys = source.loc[~left_missing, left_on]
    right_keys = table[right_on]
    matched_left = left_keys.loc[left_keys.isin(right_keys)]
    matched_right = right_keys.loc[right_keys.isin(left_keys)]
    if validate in {'one_to_one', 'one_to_many'} and matched_left.duplicated().any():
        raise pd.errors.MergeError(f'Matching keys are not unique in the left dataset for {validate}.')
    if validate in {'one_to_one', 'many_to_one'} and matched_right.duplicated().any():
        raise pd.errors.MergeError(f'Matching keys are not unique in the right dataset for {validate}.')
    return source.merge(table, left_on=left_on, right_on=right_on, how=how, sort=False)


def latest_records(data, *, group_by, order_by):
    """Keep a complete latest record per identifier rather than mixing columns.

    Dates are parsed as UTC; missing identifiers or invalid dates are rejected.
    Equal dates preserve input order and the final record wins deterministically.
    """
    source = frame(data)
    if group_by not in source or order_by not in source:
        raise ValueError('Group and date fields must exist.')
    if source[group_by].isna().any():
        raise ValueError('The identifier field contains missing values.')
    dates = pd.to_datetime(source[order_by], errors='raise', utc=True)
    if dates.isna().any():
        raise ValueError('The date field contains missing values.')
    order = np.argsort(dates.to_numpy(), kind='stable')
    return source.iloc[order].drop_duplicates(subset=[group_by], keep='last').copy()
