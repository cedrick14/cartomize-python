"""Auditable, planar distance bands around points, lines and polygons.

Cumulative round buffers are differenced in increasing distance order. The
default dissolved mode measures distance to the complete source set; the
independent mode keeps one group per original feature without conflating its
possibly repeated business label with its positional identity.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Integral, Real

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from shapely.geometry import Polygon

from ._validation import measurement_frame
from .imagery import _check_cancel
from .vector_quality import _dimension_flags, _quality_source
from .vector_selection import _finite_geometry
from .vector_tabulation import _field, _identity, _polygonal, _within_overlap


@dataclass
class BufferRingsResult:
    """Polygon rings, dense intervals, source provenance and area balances."""

    data: gpd.GeoDataFrame
    table: pd.DataFrame
    sources: gpd.GeoDataFrame
    balances: pd.DataFrame
    summary: dict


_UNITS = {'m2': 1.0, 'ha': 10000.0, 'km2': 1000000.0}
_ABSOLUTE_M2 = 1e-6
_RELATIVE = 1e-8
_GEOMETRIES = {'Point', 'MultiPoint', 'LineString', 'MultiLineString',
               'Polygon', 'MultiPolygon'}
_RING_COLUMNS = ['ring_id', 'group_id', 'band_index', 'lower_m', 'upper_m', 'area']
_SOURCE_COLUMNS = ['source_id', 'source_row', 'id_type', 'id_value',
                   'geometry_type', 'source_area']
_BALANCE_COLUMNS = ['group_id', 'source_count', 'base_area', 'outer_area',
                    'expected_area', 'sum_ring_area', 'union_ring_area',
                    'overlap_area', 'excess_area', 'raw_excess_area',
                    'uncovered_area', 'outside_area', 'closure_error',
                    'max_step_closure_error', 'non_nested_area']
_TEXT_COLUMNS = {'ring_id', 'group_id', 'source_id', 'id_type', 'id_value',
                 'geometry_type'}
_INTEGER_COLUMNS = {'band_index', 'source_row', 'source_count'}


def _table(rows, columns):
    result = pd.DataFrame(rows, columns=columns)
    for column in columns:
        dtype = ('string' if column in _TEXT_COLUMNS else
                 'Int64' if column in _INTEGER_COLUMNS else 'float64')
        result[column] = result[column].astype(dtype)
    return result


def _geotable(rows, columns, geometries, crs):
    return gpd.GeoDataFrame(_table(rows, columns),
                            geometry=gpd.GeoSeries(geometries, crs=crs), crs=crs)


def _distances(values):
    """Accept an ordered numeric sequence without sorting or coercing text."""
    if isinstance(values, (str, bytes, dict, set, frozenset)):
        raise ValueError('distances must be an ordered sequence of positive metre distances.')
    try:
        result = list(values)
    except TypeError as exc:
        raise ValueError('distances must be an ordered sequence of positive metre distances.') from exc
    if not result:
        raise ValueError('distances must contain at least one positive upper bound in metres.')
    converted = []
    previous = 0.0
    for value in result:
        if not isinstance(value, Real) or isinstance(value, (bool, np.bool_)):
            raise ValueError('Every distance must be a finite positive real number in metres, not a boolean or text.')
        try:
            number = float(value)
        except (OverflowError, ValueError) as exc:
            raise ValueError('Distances must be representable as finite positive float64 metres.') from exc
        if not math.isfinite(number) or number <= 0:
            raise ValueError('Every distance must be a finite positive real number in metres.')
        if number <= previous:
            raise ValueError('distances must be strictly increasing positive upper bounds; duplicates are refused.')
        converted.append(number)
        previous = number
    return converted


def _validate_source(data, label, cancel):
    if not data.columns.is_unique:
        raise ValueError(label + ' field names must be unique.')
    dimensions = {'z_features': 0, 'm_features': 0}
    for row, geometry in enumerate(data.geometry):
        _check_cancel(cancel)
        if geometry is None or geometry.is_empty:
            raise ValueError(f'{label}: missing or empty geometry at source_row {row}; prepare the source explicitly first.')
        if geometry.geom_type not in _GEOMETRIES:
            raise ValueError(f'{label}: unsupported {geometry.geom_type} at source_row {row}; '
                             'expected Point/MultiPoint, LineString/MultiLineString or Polygon/MultiPolygon.')
        if not _finite_geometry(geometry, cancel):
            raise ValueError(f'{label}: nonfinite coordinates at source_row {row}.')
        if not geometry.is_valid:
            raise ValueError(f'{label}: invalid geometry at source_row {row}: '
                             + shapely.is_valid_reason(geometry) + '; repair explicitly first.')
        if (not math.isfinite(geometry.area)
                or geometry.geom_type in {'Polygon', 'MultiPolygon'} and geometry.area <= 0):
            raise ValueError(f'{label}: no finite positive polygon area at source_row {row}.')
        has_z, has_m = _dimension_flags(geometry)
        dimensions['z_features'] += int(has_z)
        dimensions['m_features'] += int(has_m)
    return dimensions


def buffer_rings(data, distances, *, layer=None, metric_crs=None,
                 mode='dissolved', id_field=None, include_input=False,
                 quad_segs=16, area_unit='ha', progress=None, cancel=None):
    """Create nonoverlapping distance bands and verify their area partition.

    ``distances`` gives strictly increasing, finite, positive upper bounds in
    metres. The implicit first lower bound is zero; subsequent bounds are the
    preceding upper distances. Values are never sorted, deduplicated or taken
    as absolute values. ``quad_segs`` is an integer from 1 through 1024, giving
    the number of straight segments per quarter circle. Caps and joins are
    round. These are polygonal approximations to planar Euclidean buffers,
    not ellipsoidal/geodesic distances or exact circles.

    ``mode='dissolved'`` unions the buffers of every source feature **at each
    distance**, then removes the previously occupied footprint. Its bands
    describe distance to the nearest source geometry with disjoint interiors.
    ``mode='independent'`` repeats this construction for each original row.
    Bands of different independent groups may overlap; the summary reports
    their unique repeated footprint separately from additive excess area.
    ``id_field`` supplies exact typed descriptive labels, never grouping keys.
    Missing selected labels are refused; duplicates retain separate source IDs.

    Polygon interiors are excluded by default. ``include_input=True`` includes
    them in the first interval. This affects polygonal parts only; a point or
    line has zero area. Polygon holes receive outward buffers along their own
    boundary too. In dissolved mode the excluded base is the union of all
    original polygons; in independent mode it is the current source polygon.
    Rings may share their zero-area boundary: polygon files do not encode the
    open/closed endpoint convention of a numeric interval.

    Inputs require a known CRS and valid, finite, nonempty standard point,
    line or polygon geometries. An empty layer with a known CRS is allowed.
    Multilayer files require explicit ``layer`` selection. A projected input
    CRS or projected ``metric_crs`` is required; projected feet are converted
    to metres. Every output geometry uses that analysis CRS. Source Z/M are
    validated before deliberate 2D analysis, and the input remains unchanged.

    ``data`` contains positive-area rings, while ``table`` keeps every group ×
    interval row including zero-area intervals. ``sources`` is a separate
    positional registry with typed labels and the source geometry in analysis
    CRS; original arbitrary attributes are not copied or aggregated. Summary
    group mappings link every result to its original zero-based source rows.
    ``balances`` verifies union coverage, interior disjointness and arithmetic
    closure per group. Every positive geometric component is retained without
    a sliver threshold, snapping, automatic repair or feature reassignment.
    Arithmetic/geometric residual checks use 1e-6 m² + 1e-8 × reference area;
    actual residuals are reported, never filtered out of the generated rings.

    ``progress(done, total)`` uses total 10000. Event-compatible ``cancel`` is
    checked between computational stages and raises ProcessingCancelled.
    """
    _check_cancel(cancel)
    bounds = _distances(distances)
    if not isinstance(mode, str) or mode not in {'dissolved', 'independent'}:
        raise ValueError("mode must be 'dissolved' or 'independent'.")
    if not isinstance(include_input, (bool, np.bool_)):
        raise ValueError('include_input must be a boolean.')
    if (not isinstance(quad_segs, Integral) or isinstance(quad_segs, (bool, np.bool_))
            or not 1 <= quad_segs <= 1024):
        raise ValueError('quad_segs must be an integer from 1 through 1024, not a boolean.')
    if not isinstance(area_unit, str) or area_unit not in _UNITS:
        raise ValueError("area_unit must be 'm2', 'ha' or 'km2'.")
    if progress is not None and not callable(progress):
        raise ValueError('progress must be callable.')
    quad_segs = int(quad_segs)
    include_input = bool(include_input)
    last_progress = -1

    def advance(value):
        nonlocal last_progress
        _check_cancel(cancel)
        value = max(last_progress, min(10000, int(value)))
        if progress is not None and value != last_progress:
            progress(value, 10000)
        last_progress = value
        _check_cancel(cancel)

    advance(0)
    original, actual_layer = _quality_source(data, layer)
    dimensions = _validate_source(original, 'source', cancel)
    values = (_field(original, id_field, 'id_field') if id_field is not None
              else range(len(original)))
    identities = []
    for row, value in enumerate(values):
        _check_cancel(cancel)
        identity = _identity(value, 'id_field')
        if identity is None:
            raise ValueError(f'id_field contains a missing label at source_row {row}.')
        identities.append(identity)
    advance(600)
    xy = original.copy()
    xy.geometry = shapely.force_2d(xy.geometry.to_numpy())
    work, metres_per_unit = measurement_frame(xy, metric_crs)
    _validate_source(work, 'source after reprojection', cancel)
    unit_m2 = _UNITS[area_unit]
    try:
        scale = metres_per_unit ** 2 / unit_m2
    except OverflowError as exc:
        raise ValueError('The projected area conversion factor exceeds the finite numerical range.') from exc
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError('The projected area conversion factor is not finite and positive.')
    coordinate_bounds = [distance / metres_per_unit for distance in bounds]
    if any(not math.isfinite(distance) or distance <= 0 for distance in coordinate_bounds):
        raise ValueError('A distance cannot be represented as finite positive projected coordinate units.')
    if any(left >= right for left, right in zip(coordinate_bounds, coordinate_bounds[1:])):
        raise ValueError('Distinct distances collapse to one projected coordinate distance.')

    def measure(geometry):
        _check_cancel(cancel)
        raw = float(geometry.area)
        value = raw * scale
        if not math.isfinite(value) or value < 0 or raw > 0 and value == 0:
            raise ValueError('A geometric area cannot be represented as a finite positive measurement.')
        return value

    def checked(geometry, label):
        _check_cancel(cancel)
        geometry = _polygonal(geometry)
        if not _finite_geometry(geometry, cancel) or not geometry.is_valid:
            raise ValueError(label + ' produced an invalid or nonfinite polygon; no repair was applied.')
        measure(geometry)
        _check_cancel(cancel)
        return geometry

    def union(geometries):
        _check_cancel(cancel)
        result = checked(shapely.union_all(geometries), 'Union')
        _check_cancel(cancel)
        return result

    def difference(left, right, label):
        _check_cancel(cancel)
        return checked(left.difference(right), label)

    def total(values):
        try:
            result = math.fsum(values)
        except OverflowError as exc:
            raise ValueError('Summed areas exceed the finite numerical range.') from exc
        if not math.isfinite(result):
            raise ValueError('Summed areas exceed the finite numerical range.')
        return result

    def tolerance(reference):
        return _ABSOLUTE_M2 / unit_m2 + _RELATIVE * reference

    def excess(raw, reference):
        if raw < -tolerance(reference) or not math.isfinite(raw):
            raise ValueError('Area balance has negative excess beyond the documented numerical tolerance.')
        return max(0.0, raw)

    source_geometries = list(work.geometry)
    source_rows = [{'source_id': f's{row + 1:06d}', 'source_row': row,
                    'id_type': identity[0], 'id_value': identity[1],
                    'geometry_type': geometry.geom_type, 'source_area': measure(geometry)}
                   for row, (identity, geometry) in enumerate(zip(identities, source_geometries))]
    groups = ([list(range(len(work)))] if mode == 'dissolved' and len(work)
              else [[row] for row in range(len(work))])
    group_registry = [{'group_id': f'g{position + 1:06d}',
                       'source_ids': [source_rows[row]['source_id'] for row in rows],
                       'source_rows': rows} for position, rows in enumerate(groups)]
    table_rows, data_rows, ring_geometries, balance_rows = [], [], [], []
    advance(1200)
    intervals = len(groups) * len(bounds)
    processed = 0
    for rows, registry in zip(groups, group_registry):
        _check_cancel(cancel)
        geometries = [source_geometries[row] for row in rows]
        base = (Polygon() if include_input else
                union([geometry for geometry in geometries
                       if geometry.geom_type in {'Polygon', 'MultiPolygon'}]))
        occupied = base
        previous_outer = base
        group_rings, group_areas = [], []
        non_nested_areas, step_errors = [], []
        lower_m = 0.0
        for band_index, (upper_m, coordinate_distance) in enumerate(zip(bounds, coordinate_bounds), 1):
            buffers = []
            for geometry in geometries:
                _check_cancel(cancel)
                value = checked(shapely.buffer(geometry, coordinate_distance,
                    quad_segs=quad_segs, cap_style='round', join_style='round'), 'Buffer')
                if value.is_empty:
                    raise ValueError('A positive buffer collapsed to an empty polygon; choose representable distances/coordinates.')
                buffers.append(value)
            outer = union(buffers)
            outer_area = measure(outer)
            missing_previous = difference(previous_outer, outer, 'Nested buffer check')
            non_nested = measure(missing_previous)
            non_nested_areas.append(non_nested)
            if non_nested > tolerance(outer_area):
                raise ValueError('Cumulative buffers are not nested within the documented numerical tolerance.')
            ring = difference(outer, occupied, 'Ring difference')
            area = measure(ring)
            row = {'ring_id': f'r{len(table_rows) + 1:06d}',
                   'group_id': registry['group_id'], 'band_index': band_index,
                   'lower_m': lower_m, 'upper_m': upper_m, 'area': area}
            table_rows.append(row)
            if area > 0:
                data_rows.append(row)
                ring_geometries.append(ring)
                group_rings.append(ring)
                group_areas.append(area)
            occupied = union([occupied, ring])
            step_error = outer_area - measure(occupied)
            step_errors.append(step_error)
            if abs(step_error) > tolerance(outer_area):
                raise ValueError('A cumulative ring step does not close within the documented numerical tolerance.')
            previous_outer = outer
            lower_m = upper_m
            processed += 1
            advance(1200 + 6300 * processed / max(intervals, 1))

        expected = difference(outer, base, 'Expected footprint')
        united = union(group_rings)
        shared = checked(_within_overlap(group_rings, cancel), 'Ring interior overlap check')
        uncovered = difference(expected, united, 'Ring coverage check')
        outside = difference(united, expected, 'Ring extent check')
        expected_area = measure(expected)
        summed_area = total(group_areas)
        union_area = measure(united)
        raw_excess = summed_area - union_area
        closure = expected_area - summed_area
        overlap_area = measure(shared)
        uncovered_area = measure(uncovered)
        outside_area = measure(outside)
        allowed = tolerance(expected_area)
        if (abs(closure) > allowed or abs(raw_excess) > allowed
                or overlap_area > allowed or uncovered_area > allowed or outside_area > allowed):
            raise ValueError('Ring coverage/interior disjointness does not close within the documented numerical tolerance: '
                             + registry['group_id'])
        balance_rows.append({'group_id': registry['group_id'], 'source_count': len(rows),
            'base_area': measure(base), 'outer_area': measure(outer),
            'expected_area': expected_area, 'sum_ring_area': summed_area,
            'union_ring_area': union_area, 'overlap_area': overlap_area,
            'excess_area': excess(raw_excess, expected_area), 'raw_excess_area': raw_excess,
            'uncovered_area': uncovered_area, 'outside_area': outside_area,
            'closure_error': closure,
            'max_step_closure_error': max(map(abs, step_errors), default=0.0),
            'non_nested_area': total(non_nested_areas)})
    advance(7900)
    # Independent groups can count shared territory repeatedly. Use a unique
    # overlap footprint, not the sum of pairwise areas (which overcounts triples).
    all_union = union(ring_geometries)
    advance(8400)
    all_overlap = checked(_within_overlap(ring_geometries, cancel), 'Global overlap audit')
    summed_area = total(row['area'] for row in table_rows)
    union_area = measure(all_union)
    raw_excess = summed_area - union_area
    totals = {'sum_ring_area': summed_area, 'union_ring_area': union_area,
              'overlap_area': measure(all_overlap),
              'excess_area': excess(raw_excess, summed_area), 'raw_excess_area': raw_excess}
    advance(9400)
    table = _table(table_rows, _RING_COLUMNS)
    data_result = _geotable(data_rows, _RING_COLUMNS, ring_geometries, work.crs)
    sources = _geotable(source_rows, _SOURCE_COLUMNS, source_geometries, work.crs)
    balances = _table(balance_rows, _BALANCE_COLUMNS)
    summary = {'schema': 'cartomize.vector.rings.v1',
        'input_features': len(original), 'group_count': len(groups), 'band_count': len(bounds),
        'ring_features': len(data_result), 'table_rows': len(table),
        'empty_intervals': len(table) - len(data_result),
        'area_unit': area_unit, 'measurement_crs': str(work.crs),
        'source_crs': str(original.crs), 'metres_per_coordinate_unit': metres_per_unit,
        'parameters': {'distances': bounds, 'layer': actual_layer, 'metric_crs': str(work.crs),
                       'mode': mode, 'id_field': id_field, 'include_input': include_input,
                       'quad_segs': quad_segs, 'area_unit': area_unit},
        'groups': group_registry, 'totals': totals,
        'dimensionality': {'policy': 'finite_source_ordinates_then_explicit_2d_analysis',
                           **dimensions, 'output_dimensions': 2},
        'closure_tolerance': {'absolute_m2': _ABSOLUTE_M2, 'relative': _RELATIVE,
                              'rule': 'absolute_m2 + relative * reference_area_m2',
                              'purpose': 'residual_checks_only_no_geometric_filter'},
        'policies': {'distance_model': 'planar_in_explicit_projected_crs',
                     'distance_unit': 'm', 'cap_style': 'round', 'join_style': 'round',
                     'circle_model': 'inscribed_linear_arcs_quad_segs_per_quadrant',
                     'dissolve_order': 'union_source_buffers_at_each_distance_before_differences',
                     'ring_construction': 'subtract_previously_occupied_footprint',
                     'polygon_interiors': 'include_in_first_band' if include_input else 'exclude',
                     'source_identity': 'one_original_row_one_source_id_labels_never_aggregate',
                     'source_attributes': 'typed_selected_label_and_positional_registry_only',
                     'intergroup_overlap': 'permitted_and_audited' if mode == 'independent' else 'one_dissolved_group',
                     'overlap_area': 'unique_footprint_shared_by_at_least_two_output_rings',
                     'excess_area': 'sum_ring_area_minus_union_ring_area',
                     'interval_boundaries': 'polygon_boundaries_may_touch_zero_area',
                     'positive_area_slivers': 'all_retained', 'geometry_repair': 'none',
                     'coordinate_precision_grid': None, 'quad_segs_range': [1, 1024]}}
    for result in (data_result, table, sources, balances):
        result.attrs['area_unit'] = area_unit
        result.attrs['measurement_crs'] = str(work.crs)
    advance(10000)
    return BufferRingsResult(data_result, table, sources, balances, summary)
