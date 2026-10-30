"""Auditable polygon area tabulation by exact zone and category identities.

Repeated identities are dissolved before measurement. Class overlaps are never
silently assigned to one category: they are refused or explicitly reported.
Measurements and generated geometries use one caller-selected projected CRS.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
import math

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from shapely.geometry import GeometryCollection, Polygon
from shapely.strtree import STRtree

from ._validation import measurement_frame
from .imagery import _check_cancel
from .vector_io import is_missing
from .vector_quality import _quality_source
from .vector_selection import _finite_geometry


@dataclass
class AreaTabulationResult:
    """Area cells, polygon products, typed identities and numerical balances."""

    data: gpd.GeoDataFrame
    table: pd.DataFrame
    matrix: pd.DataFrame
    zones: gpd.GeoDataFrame
    categories: pd.DataFrame
    gaps: gpd.GeoDataFrame
    overlaps: gpd.GeoDataFrame
    summary: dict


_UNITS = {'m2': 1.0, 'ha': 10000.0, 'km2': 1000000.0}
_ABSOLUTE_M2 = 1e-6
_RELATIVE = 1e-8
_CELL_COLUMNS = ['zone_id', 'zone_type', 'zone_value', 'class_id', 'class_type',
                 'class_value', 'area', 'percentage']
_ZONE_COLUMNS = ['zone_id', 'zone_type', 'zone_value', 'source_count',
                 'source_area', 'zone_area', 'same_zone_excess_area',
                 'raw_same_zone_excess_area', 'covered_area', 'uncovered_area',
                 'unclassified_area', 'no_coverage_area', 'overlap_area',
                 'excess_area', 'raw_excess_area', 'summed_class_area',
                 'covered_percentage', 'uncovered_percentage',
                 'overlap_percentage', 'excess_percentage',
                 'summed_class_percentage', 'closure_error']
_CLASS_COLUMNS = ['class_id', 'class_type', 'class_value', 'source_count',
                  'source_area', 'dissolved_area', 'same_class_excess_area',
                  'raw_same_class_excess_area', 'covered_domain_area',
                  'outside_area']
_GAP_COLUMNS = ['gap_id', 'zone_id', 'zone_type', 'zone_value', 'kind',
                'area', 'percentage']
_OVERLAP_COLUMNS = ['overlap_id', 'kind', 'zone_id', 'zone_id_other',
                    'class_id', 'class_id_other', 'area']
_TEXT_COLUMNS = {'zone_id', 'zone_type', 'zone_value', 'class_id', 'class_type',
                 'class_value', 'gap_id', 'kind', 'overlap_id', 'zone_id_other',
                 'class_id_other'}
_BALANCE_COLUMNS = ['zone_area', 'covered_area', 'uncovered_area',
                    'unclassified_area', 'no_coverage_area', 'overlap_area',
                    'excess_area', 'raw_excess_area', 'summed_class_area',
                    'closure_error']


def _table(rows, columns):
    result = pd.DataFrame(rows, columns=columns)
    for name in columns:
        if name in _TEXT_COLUMNS:
            result[name] = result[name].astype('string')
        elif name == 'source_count':
            result[name] = result[name].astype('Int64')
        else:
            result[name] = result[name].astype('float64')
    return result


def _geotable(rows, columns, geometries, crs):
    return gpd.GeoDataFrame(_table(rows, columns),
                            geometry=gpd.GeoSeries(geometries, crs=crs), crs=crs)


def _identity(value, label):
    """An exact typed key and an exportable canonical textual value."""
    if is_missing(value):
        return None
    if isinstance(value, (bool, np.bool_)):
        kind, text = 'boolean', 'true' if value else 'false'
    elif isinstance(value, (int, np.integer)):
        kind, text = 'integer', str(int(value))
    elif isinstance(value, (float, np.floating)):
        if not np.isfinite(value):
            raise ValueError(label + ' must contain finite category values.')
        # Wider native floating types cannot be represented by a Python float.
        if isinstance(value, np.floating) and value.dtype.itemsize > 8:
            raise ValueError(label + ' does not support floating types wider than float64.')
        number = float(value)
        kind, text = 'float', repr(0.0 if number == 0 else number)
    elif isinstance(value, (datetime, pd.Timestamp, np.datetime64)):
        try:
            stamp = pd.Timestamp(value)
            kind = 'datetime_utc' if stamp.tzinfo is not None else 'datetime'
            # Aware identities represent instants; normalize their explicit offsets
            # to UTC, while never assigning a timezone to naive values.
            if stamp.tzinfo is not None:
                stamp = stamp.tz_convert('UTC')
            text = stamp.isoformat()
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(label + ' contains an unsupported timestamp.') from exc
    elif isinstance(value, date):
        kind, text = 'date', value.isoformat()
    elif isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError(label + ' must contain finite category values.')
        # Decimal equality is numerical, independently of trailing zero scale.
        if value:
            sign, digits, exponent = value.as_tuple()
            digits = list(digits)
            while len(digits) > 1 and digits[-1] == 0:
                digits.pop()
                exponent += 1
            text = str(Decimal((sign, tuple(digits), exponent)))
        else:
            text = '0'
        kind = 'decimal'
    elif isinstance(value, str):
        if '\x00' in value:
            raise ValueError(label + ' contains a NUL character that cannot be exported faithfully.')
        kind, text = 'string', value
    else:
        raise ValueError(label + ' must contain scalar strings, numbers, booleans or dates.')
    return kind, text


def _field(data, name, label):
    if (not isinstance(name, str) or not name or name not in data
            or isinstance(data[name].dtype, gpd.array.GeometryDtype)):
        raise ValueError(label + ' must name one existing attribute column.')
    return data[name]


def _validate_polygons(data, label, cancel):
    dimensions = {'z_features': 0, 'm_features': 0}
    if not data.columns.is_unique:
        raise ValueError(label + ' field names must be unique.')
    for row, geom in enumerate(data.geometry):
        _check_cancel(cancel)
        if geom is None or geom.is_empty:
            raise ValueError(f'{label}: missing or empty geometry at source_row {row}; audit/repair first.')
        if geom.geom_type not in {'Polygon', 'MultiPolygon'}:
            raise ValueError(f'{label}: source_row {row} is not a Polygon/MultiPolygon.')
        if not _finite_geometry(geom, cancel):
            raise ValueError(f'{label}: nonfinite coordinates at source_row {row}.')
        if not geom.is_valid:
            raise ValueError(f'{label}: invalid geometry at source_row {row}: '
                             + shapely.is_valid_reason(geom) + '; repair explicitly first.')
        if not math.isfinite(geom.area) or geom.area <= 0:
            raise ValueError(f'{label}: source_row {row} has no finite positive measurable area.')
        dimensions['z_features'] += int(bool(shapely.has_z(geom)))
        dimensions['m_features'] += int(bool(shapely.has_m(geom))) if hasattr(shapely, 'has_m') else 0
    return dimensions


def _polygonal(geometry):
    """Retain every area component, ignoring only boundary points and lines."""
    if geometry.is_empty:
        return Polygon()
    if geometry.geom_type in {'Polygon', 'MultiPolygon'}:
        return geometry
    parts = []
    if hasattr(geometry, 'geoms'):
        for part in geometry.geoms:
            value = _polygonal(part)
            if not value.is_empty:
                parts.append(value)
    return shapely.union_all(parts) if parts else Polygon()


def _union(geometries, cancel):
    _check_cancel(cancel)
    result = _polygonal(shapely.union_all(geometries))
    _check_cancel(cancel)
    return result


def _groups(values, geometries, prefix, label, cancel, allow_missing=False):
    groups, lookup, missing = [], {}, []
    for row, (value, geometry) in enumerate(zip(values, geometries)):
        _check_cancel(cancel)
        identity = _identity(value, label)
        if identity is None:
            if not allow_missing:
                raise ValueError(f'{label} has a missing value at source_row {row}.')
            missing.append(row)
            continue
        if identity not in lookup:
            lookup[identity] = len(groups)
            groups.append({'id': f'{prefix}{len(groups) + 1:06d}',
                           'type': identity[0], 'value': identity[1],
                           'rows': [], 'parts': []})
        item = groups[lookup[identity]]
        item['rows'].append(row)
        item['parts'].append(geometry)
    for item in groups:
        item['geometry'] = _union(item['parts'], cancel)
    return groups, missing


def _pair_overlaps(geometries, cancel):
    """Deterministic candidate pairs; sparse inputs do not become an N² scan."""
    tree = STRtree(geometries)
    for left, geometry in enumerate(geometries):
        _check_cancel(cancel)
        for right in sorted(map(int, tree.query(geometry))):
            _check_cancel(cancel)
            if right <= left:
                continue
            shared = _polygonal(geometry.intersection(geometries[right]))
            if not shared.is_empty and shared.area > 0:
                yield left, right, shared


def _within_overlap(parts, cancel):
    """Unique repeated footprint with indexed candidates and duplicate grouping.

    Normalized WKB groups exact duplicate point sets cheaply. Repeated copies
    already make their entire footprint ambiguous, so they must not produce a
    quadratic list of identical intersections. Remaining sparse candidates use
    the spatial index; growing a union over thousands of complex features would
    repeatedly rebuild topology and make real land-use layers needlessly slow.
    """
    unique, positions, counts = [], {}, []
    for geometry in parts:
        _check_cancel(cancel)
        key = shapely.normalize(geometry).wkb
        if key in positions:
            counts[positions[key]] += 1
        else:
            positions[key] = len(unique)
            unique.append(geometry)
            counts.append(1)
    repeated = [geometry for geometry, count in zip(unique, counts) if count > 1]
    repeated.extend(shared for _, _, shared in _pair_overlaps(unique, cancel))
    return _union(repeated, cancel)


def tabulate_area(zones, classes, *, zone_field, class_field, zones_layer=None,
                  classes_layer=None, metric_crs=None, area_unit='ha',
                  overlap_policy='error', zone_overlap_policy='independent',
                  null_classes='error', progress=None, cancel=None):
    """Cross polygon zones with categorical polygons and audit every area.

    Zone and category identities are type-aware, exact, and ordered by first
    source occurrence. Repeated identities are dissolved before intersections;
    same-category duplicate coverage is never counted twice. A complete long
    table and wide matrix include zero cells and categories outside all zones.
    IDs are stable positional keys; the typed canonical textual registries keep
    strings such as ``001`` distinct from numbers, booleans and native dates.
    Aware timestamps are canonicalized to UTC so equivalent explicit offsets
    identify the same instant; naive timestamps remain a separate type.

    Cross-category positive-area overlap **inside the union of zones** raises
    by default. ``overlap_policy='report'`` keeps all category areas and reports
    unique ambiguous area separately from additive excess; percentages may sum
    above 100. Distinct overlapping zones are measured independently, or refused
    with ``zone_overlap_policy='error'``. Global union-domain balances are kept
    separate from sums over zones, which can count shared territory repeatedly.

    Null zone values are refused. ``null_classes='unclassified'`` permits null
    category values: their footprint outside known category coverage is mapped
    as an unclassified gap, distinct from areas with no class-source coverage.
    Nulls never become an invented category. Empty layers with known CRSs and
    the requested fields are allowed; individual missing/empty/invalid or
    nonpolygon geometries are refused rather than repaired implicitly.

    A projected zone CRS or explicit projected ``metric_crs`` is required. Units
    in feet are converted through the CRS axis conversion factor. Areas are in
    ``m2``, ``ha`` or ``km2``; every output geometry uses the analysis CRS.
    Source Z/M coordinates are checked for finiteness before deliberate 2D
    analysis; neither input is modified. No coordinate snapping or positive-area
    sliver threshold is applied. Closure tolerance is fixed at 1e-6 m² plus
    1e-8 times the domain or zone area and is used only for arithmetic checks.
    Signed residuals are preserved; tiny negative numerical excess can be zeroed
    only within this tolerance, with its raw signed value retained.

    ``progress(done, total)`` uses total 10000. Event-like ``cancel`` is checked
    between computational steps and raises ProcessingCancelled without a result.
    """
    _check_cancel(cancel)
    if not isinstance(area_unit, str) or area_unit not in _UNITS:
        raise ValueError("area_unit must be 'm2', 'ha' or 'km2'.")
    if not isinstance(overlap_policy, str) or overlap_policy not in {'error', 'report'}:
        raise ValueError("overlap_policy must be 'error' or 'report'.")
    if not isinstance(zone_overlap_policy, str) or zone_overlap_policy not in {'independent', 'error'}:
        raise ValueError("zone_overlap_policy must be 'independent' or 'error'.")
    if not isinstance(null_classes, str) or null_classes not in {'error', 'unclassified'}:
        raise ValueError("null_classes must be 'error' or 'unclassified'.")
    if progress is not None and not callable(progress):
        raise ValueError('progress must be callable.')
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
    original_zones, actual_zones_layer = _quality_source(zones, zones_layer)
    _check_cancel(cancel)
    original_classes, actual_classes_layer = _quality_source(classes, classes_layer)
    zone_dimensions = _validate_polygons(original_zones, 'zones', cancel)
    class_dimensions = _validate_polygons(original_classes, 'classes', cancel)
    zone_values = _field(original_zones, zone_field, 'zone_field')
    class_values = _field(original_classes, class_field, 'class_field')
    advance(700)
    # Drop auxiliary ordinates only in independent working copies. Reprojection
    # must operate on XY so source Z is never mistaken for vertical datum data.
    zone_xy = original_zones.copy()
    class_xy = original_classes.copy()
    zone_xy.geometry = shapely.force_2d(zone_xy.geometry.to_numpy())
    class_xy.geometry = shapely.force_2d(class_xy.geometry.to_numpy())
    zone_work, linear_factor = measurement_frame(zone_xy, metric_crs)
    _check_cancel(cancel)
    class_work = class_xy.to_crs(zone_work.crs)
    _validate_polygons(zone_work, 'zones after reprojection', cancel)
    _validate_polygons(class_work, 'classes after reprojection', cancel)
    factor_m2 = linear_factor ** 2
    unit_m2 = _UNITS[area_unit]
    scale = factor_m2 / unit_m2
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError('The projected area conversion factor is not finite and positive.')

    def measure(geometry):
        _check_cancel(cancel)
        raw = float(geometry.area)
        value = raw * scale
        if not math.isfinite(value) or value < 0 or raw > 0 and value == 0:
            raise ValueError('A geometric area cannot be represented as a finite positive measurement.')
        return value

    def tolerance(reference):
        return _ABSOLUTE_M2 / unit_m2 + _RELATIVE * reference

    def excess(raw, reference, label):
        if not math.isfinite(raw) or raw < -tolerance(reference):
            raise ValueError(label + ' has inconsistent negative area beyond closure tolerance.')
        return max(raw, 0.0)

    def checked_sum(values):
        try:
            value = math.fsum(values)
        except OverflowError as exc:
            raise ValueError('Summed areas exceed finite numerical range.') from exc
        if not math.isfinite(value):
            raise ValueError('Summed areas exceed finite numerical range.')
        return value

    advance(1300)
    zone_groups, _ = _groups(zone_values, list(zone_work.geometry), 'z',
                             'zone_field', cancel)
    class_groups, null_rows = _groups(class_values, list(class_work.geometry), 'c',
                                      'class_field', cancel,
                                      allow_missing=null_classes == 'unclassified')
    zone_geometries = [group['geometry'] for group in zone_groups]
    domain = _union(zone_geometries, cancel)
    null_geometry = _union([class_work.geometry.iloc[row] for row in null_rows], cancel)
    class_domains = [_polygonal(domain.intersection(group['geometry'])) for group in class_groups]
    # Build coverage from the exact per-category geometries being measured.
    # Union-before-clip can differ measurably from clip-before-union on valid
    # complex data at large projected coordinates; mixing their areas would
    # manufacture an apparent negative class excess.
    known_domain = _union(class_domains, cancel)
    uncovered_domain = _polygonal(domain.difference(known_domain))
    unclassified_domain = _polygonal(uncovered_domain.intersection(null_geometry))
    no_coverage_domain = _polygonal(uncovered_domain.difference(null_geometry))
    advance(2500)

    overlap_rows, overlap_geometries = [], []

    def add_overlap(kind, geometry, *, zone=None, other_zone=None, category=None,
                    other_category=None):
        if geometry.is_empty or geometry.area <= 0:
            return
        overlap_rows.append({'overlap_id': f'o{len(overlap_rows) + 1:06d}',
                             'kind': kind, 'zone_id': zone,
                             'zone_id_other': other_zone, 'class_id': category,
                             'class_id_other': other_category, 'area': measure(geometry)})
        overlap_geometries.append(geometry)

    zone_shared = []
    for left, right, shared in _pair_overlaps(zone_geometries, cancel):
        if zone_overlap_policy == 'error':
            raise ValueError('Distinct zones overlap with positive area: '
                             + zone_groups[left]['id'] + ', ' + zone_groups[right]['id']
                             + "; use zone_overlap_policy='independent' to measure them independently.")
        zone_shared.append(shared)
        add_overlap('zone_overlap', shared, zone=zone_groups[left]['id'],
                    other_zone=zone_groups[right]['id'])
    class_shared = []
    for left, right, shared in _pair_overlaps(class_domains, cancel):
        if overlap_policy == 'error':
            raise ValueError('Distinct classes overlap with positive area inside the zones: '
                             + class_groups[left]['id'] + ', ' + class_groups[right]['id']
                             + "; use overlap_policy='report' to retain and audit both categories.")
        class_shared.append(shared)
        add_overlap('class_overlap', shared, category=class_groups[left]['id'],
                    other_category=class_groups[right]['id'])
    class_overlap_domain = _union(class_shared, cancel)
    zone_overlap_domain = _union(zone_shared, cancel)
    advance(3700)

    class_rows = []
    for number, (group, in_domain) in enumerate(zip(class_groups, class_domains)):
        _check_cancel(cancel)
        source_area = checked_sum(measure(part) for part in group['parts'])
        dissolved_area = measure(group['geometry'])
        raw_same = source_area - dissolved_area
        same = excess(raw_same, source_area, 'Same-class dissolution')
        group['source_area'] = source_area
        group['same_excess_area'] = same
        group['raw_same_excess_area'] = raw_same
        # Audit same-class overlap inside the analysis domain, including tiny
        # overlaps whose area is lost when subtracting two very large totals.
        if len(group['parts']) > 1:
            shared = _within_overlap(group['parts'], cancel)
            shared = _polygonal(shared.intersection(domain))
            add_overlap('same_class_overlap', shared, category=group['id'])
        class_rows.append({'class_id': group['id'], 'class_type': group['type'],
                           'class_value': group['value'], 'source_count': len(group['rows']),
                           'source_area': source_area, 'dissolved_area': dissolved_area,
                           'same_class_excess_area': same,
                           'raw_same_class_excess_area': raw_same,
                           'covered_domain_area': measure(in_domain),
                           'outside_area': measure(_polygonal(group['geometry'].difference(domain)))})
        advance(3700 + 1000 * (number + 1) / max(len(class_groups), 1))
    advance(4700)

    table_rows, data_rows, data_geometries = [], [], []
    zone_rows, gap_rows, gap_geometries, matrix_rows = [], [], [], []
    class_geometries = [group['geometry'] for group in class_groups]
    class_tree = STRtree(class_geometries)
    for number, group in enumerate(zone_groups):
        _check_cancel(cancel)
        geometry = group['geometry']
        zone_area = measure(geometry)
        source_area = checked_sum(measure(part) for part in group['parts'])
        raw_same = source_area - zone_area
        same = excess(raw_same, source_area, 'Same-zone dissolution')
        group['source_area'] = source_area
        group['same_excess_area'] = same
        group['raw_same_excess_area'] = raw_same
        if len(group['parts']) > 1:
            add_overlap('same_zone_overlap', _within_overlap(group['parts'], cancel), zone=group['id'])
        identity = {'zone_id': group['id'], 'zone_type': group['type'],
                    'zone_value': group['value']}
        matrix_row = dict(identity)
        candidates = set(map(int, class_tree.query(geometry)))
        cell_areas, cell_geometries = [], []
        for class_number, category in enumerate(class_groups):
            _check_cancel(cancel)
            intersection = (_polygonal(geometry.intersection(class_geometries[class_number]))
                            if class_number in candidates else Polygon())
            cell_area = measure(intersection)
            row = {**identity, 'class_id': category['id'], 'class_type': category['type'],
                   'class_value': category['value'], 'area': cell_area,
                   'percentage': 100.0 * (cell_area / zone_area)}
            table_rows.append(row)
            matrix_row[category['id']] = cell_area
            cell_areas.append(cell_area)
            cell_geometries.append(intersection)
            if not intersection.is_empty and intersection.area > 0:
                data_rows.append(row.copy())
                data_geometries.append(intersection)
        matrix_rows.append(matrix_row)
        covered = _union(cell_geometries, cancel)
        uncovered = _polygonal(geometry.difference(covered))
        unclassified = _polygonal(uncovered.intersection(null_geometry))
        no_coverage = _polygonal(uncovered.difference(null_geometry))
        ambiguous = _polygonal(geometry.intersection(class_overlap_domain))
        covered_area = measure(covered)
        uncovered_area = measure(uncovered)
        unclassified_area = measure(unclassified)
        no_coverage_area = measure(no_coverage)
        summed = checked_sum(cell_areas)
        raw_excess = summed - covered_area
        class_excess = excess(raw_excess, zone_area, 'Class area balance')
        closure = zone_area - covered_area - uncovered_area
        if (abs(closure) > tolerance(zone_area)
                or abs(uncovered_area - unclassified_area - no_coverage_area) > tolerance(zone_area)):
            raise ValueError('Zone area does not close within the documented numerical tolerance: ' + group['id'])
        overlap_area = measure(ambiguous)
        zone_rows.append({**identity, 'source_count': len(group['rows']),
                          'source_area': source_area, 'zone_area': zone_area,
                          'same_zone_excess_area': same, 'raw_same_zone_excess_area': raw_same,
                          'covered_area': covered_area, 'uncovered_area': uncovered_area,
                          'unclassified_area': unclassified_area, 'no_coverage_area': no_coverage_area,
                          'overlap_area': overlap_area, 'excess_area': class_excess,
                          'raw_excess_area': raw_excess, 'summed_class_area': summed,
                          'covered_percentage': 100.0 * (covered_area / zone_area),
                          'uncovered_percentage': 100.0 * (uncovered_area / zone_area),
                          'overlap_percentage': 100.0 * (overlap_area / zone_area),
                          'excess_percentage': 100.0 * (class_excess / zone_area),
                          'summed_class_percentage': 100.0 * (summed / zone_area),
                          'closure_error': closure})
        for kind, gap in [('unclassified', unclassified), ('no_coverage', no_coverage)]:
            if not gap.is_empty and gap.area > 0:
                area = measure(gap)
                gap_rows.append({'gap_id': f'g{len(gap_rows) + 1:06d}', **identity,
                                 'kind': kind, 'area': area, 'percentage': 100.0 * (area / zone_area)})
                gap_geometries.append(gap)
        advance(4700 + 4300 * (number + 1) / max(len(zone_groups), 1))
    advance(9000)

    domain_area = measure(domain)
    covered_area = measure(known_domain)
    uncovered_area = measure(uncovered_domain)
    domain_summed = checked_sum(measure(geometry) for geometry in class_domains)
    raw_domain_excess = domain_summed - covered_area
    domain_excess = excess(raw_domain_excess, domain_area, 'Global class area balance')
    domain_closure = domain_area - covered_area - uncovered_area
    if (abs(domain_closure) > tolerance(domain_area)
            or abs(uncovered_area - measure(unclassified_domain) - measure(no_coverage_domain))
            > tolerance(domain_area)):
        raise ValueError('Global area does not close within the documented numerical tolerance.')
    totals_domain = {'zone_area': domain_area, 'covered_area': covered_area,
                     'uncovered_area': uncovered_area,
                     'unclassified_area': measure(unclassified_domain),
                     'no_coverage_area': measure(no_coverage_domain),
                     'overlap_area': measure(class_overlap_domain),
                     'excess_area': domain_excess, 'raw_excess_area': raw_domain_excess,
                     'summed_class_area': domain_summed, 'closure_error': domain_closure,
                     'zone_overlap_area': measure(zone_overlap_domain)}
    sums = {name: checked_sum(row[name] for row in zone_rows) for name in _BALANCE_COLUMNS}
    raw_zone_excess = sums['zone_area'] - domain_area
    sums['raw_zone_excess_area'] = raw_zone_excess
    sums['zone_excess_area'] = excess(raw_zone_excess, sums['zone_area'], 'Global zone area balance')
    sums['source_area'] = checked_sum(row['source_area'] for row in zone_rows)
    sums['same_zone_excess_area'] = checked_sum(row['same_zone_excess_area'] for row in zone_rows)

    table = _table(table_rows, _CELL_COLUMNS)
    data = _geotable(data_rows, _CELL_COLUMNS, data_geometries, zone_work.crs)
    matrix = _table(matrix_rows, ['zone_id', 'zone_type', 'zone_value']
                    + [group['id'] for group in class_groups])
    zone_result = _geotable(zone_rows, _ZONE_COLUMNS, zone_geometries, zone_work.crs)
    categories = _table(class_rows, _CLASS_COLUMNS)
    gaps = _geotable(gap_rows, _GAP_COLUMNS, gap_geometries, zone_work.crs)
    overlaps = _geotable(overlap_rows, _OVERLAP_COLUMNS, overlap_geometries, zone_work.crs)
    advance(9700)

    def registry(groups, prefix):
        return [{prefix + '_id': group['id'], prefix + '_type': group['type'],
                 prefix + '_value': group['value'], 'source_rows': group['rows']}
                for group in groups]

    summary = {'schema': 'cartomize.vector.tabulation.v1',
               'input_zone_features': len(original_zones),
               'input_class_features': len(original_classes),
               'zone_count': len(zone_groups), 'class_count': len(class_groups),
               'intersection_features': len(data), 'table_cells': len(table),
               'gap_features': len(gaps), 'overlap_features': len(overlaps),
               'null_class_features': len(null_rows),
               'unclassified': {'source_features': len(null_rows),
                                'source_area': checked_sum(measure(class_work.geometry.iloc[row]) for row in null_rows),
                                'dissolved_area': measure(null_geometry),
                                'covered_domain_area': measure(_polygonal(null_geometry.intersection(domain))),
                                'outside_area': measure(_polygonal(null_geometry.difference(domain))),
                                'already_classified_area': measure(_polygonal(null_geometry.intersection(known_domain))),
                                'unclassified_area': measure(unclassified_domain)},
               'area_unit': area_unit, 'measurement_crs': str(zone_work.crs),
               'metres_per_coordinate_unit': linear_factor,
               'source_crs': {'zones': str(original_zones.crs), 'classes': str(original_classes.crs)},
               'parameters': {'zone_field': zone_field, 'class_field': class_field,
                              'zones_layer': actual_zones_layer, 'classes_layer': actual_classes_layer,
                              'metric_crs': str(zone_work.crs), 'area_unit': area_unit,
                              'overlap_policy': overlap_policy,
                              'zone_overlap_policy': zone_overlap_policy,
                              'null_classes': null_classes},
               'dimensionality': {'policy': 'finite_source_ordinates_then_explicit_2d_analysis',
                                  'zones': zone_dimensions, 'classes': class_dimensions,
                                  'output_dimensions': 2},
               'registries': {'zones': registry(zone_groups, 'zone'),
                              'classes': registry(class_groups, 'class'),
                              'unclassified_source_rows': null_rows},
               'totals': {'domain': totals_domain, 'zone_sums': sums},
               'closure_tolerance': {'absolute_m2': _ABSOLUTE_M2, 'relative': _RELATIVE,
                                     'rule': 'absolute_m2 + relative * zone_or_domain_area_m2',
                                     'purpose': 'arithmetic_balance_only_no_geometric_filter'},
               'policies': {'class_overlap_scope': 'union_of_zones',
                            'same_identity': 'dissolve_before_measurement',
                            'zone_overlap': zone_overlap_policy,
                            'category_overlap': overlap_policy,
                            'positive_area_slivers': 'all_retained',
                            'boundary_contacts': 'zero_area_not_a_polygon_cell',
                            'percentage_denominator': 'dissolved_zone_area',
                            'identity_order': 'first_source_occurrence',
                            'identity_encoding': 'type_and_exact_canonical_text',
                            'null_classes': null_classes,
                            'geometry_repair': 'none', 'coordinate_precision_grid': None,
                            'overlap_diagnostics': 'pairwise_between_groups_unique_within_one_group'}}
    for result in (data, table, matrix, zone_result, categories, gaps, overlaps):
        result.attrs['area_unit'] = area_unit
        result.attrs['measurement_crs'] = str(zone_work.crs)
    advance(10000)
    return AreaTabulationResult(data, table, matrix, zone_result, categories, gaps, overlaps, summary)
