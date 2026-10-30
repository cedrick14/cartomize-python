"""Validate G09 area tables against pinned Paris polygons and geometric oracles.

Original land-use labels and quartier boundaries come from the pinned public
GeoPandas tutorial snapshot. A separate analytical partition of those real
boundaries into rectangular strips is explicitly synthetic: its areas are
computed by Python clipping and the shoelace formula, without GEOS. The real
land-use comparison uses a different overlay/aggregation order but shares GEOS;
projection and file decoding also share PROJ/GDAL with Cartomize.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from importlib import metadata
import json
import math
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import platform
import stat
import subprocess
import tempfile
import time
import traceback
import zipfile

import numpy as np
import pandas as pd

from validate_vector_quality_real import (
    SOURCES, TUTORIAL_REF, download_source, safe_destination, sha, verify_cache,
)


REPO = Path(__file__).resolve().parents[1]
LAND_USE_SOURCE = {
    'file_name': 'paris_land_use.zip',
    'url': f'https://raw.githubusercontent.com/jorisvandenbossche/geopandas-tutorial/{TUTORIAL_REF}/data/paris_land_use.zip',
    'bytes': 781246,
    'sha256': '35f7eb93515cd94a26d9a626e0febd77b08ffb0a45a29bb2e41166838f408d35',
}


def clip_ring(ring, bounds):
    """Clip a polygon-ring walk to a rectangle using only Python arithmetic.

    The walk can be concave. Disconnected pieces may be linked by zero-area
    boundary segments; their signed shoelace sum still gives the intersection
    area. The caller supplies a valid polygon ring; no geometry repair is done.
    """
    points = [tuple(float(value) for value in coordinate[:2]) for coordinate in ring]
    if any(len(point) != 2 or not all(math.isfinite(value) for value in point) for point in points):
        raise ValueError('Oracle ring coordinates must contain finite x and y values.')
    if points and points[0] == points[-1]:
        points.pop()
    if bounds is None:
        return points
    if len(bounds) != 4 or not all(math.isfinite(value) for value in bounds):
        raise ValueError('Oracle bounds must contain four finite values.')
    xmin, ymin, xmax, ymax = map(float, bounds)
    if xmin > xmax or ymin > ymax:
        raise ValueError('Oracle bounds must be ordered xmin, ymin, xmax, ymax.')
    for axis, boundary, lower in [(0, xmin, True), (0, xmax, False),
                                   (1, ymin, True), (1, ymax, False)]:
        if not points:
            break
        output = []
        previous = points[-1]
        previous_inside = previous[axis] >= boundary if lower else previous[axis] <= boundary
        for current in points:
            current_inside = current[axis] >= boundary if lower else current[axis] <= boundary
            if current_inside != previous_inside:
                fraction = (boundary - previous[axis]) / (current[axis] - previous[axis])
                intersection = [previous[index] + fraction * (current[index] - previous[index])
                                for index in range(2)]
                intersection[axis] = boundary
                output.append(tuple(intersection))
            if current_inside:
                output.append(current)
            previous, previous_inside = current, current_inside
        points = output
    return points


def ring_area(ring, bounds=None):
    """Unsigned shoelace area after optional rectangular clipping.

    Translate to the first vertex before multiplication to prevent catastrophic
    cancellation at large projected eastings/northings; use compensated sums.
    """
    points = clip_ring(ring, bounds)
    if len(points) < 3:
        return 0.0
    ox, oy = points[0]
    translated = [(x - ox, y - oy) for x, y in points]
    terms = [ax * by - bx * ay for (ax, ay), (bx, by)
             in zip(translated, translated[1:] + translated[:1])]
    return abs(math.fsum(terms)) / 2.0


def polygon_area(geometry, bounds=None):
    """Area of valid Polygon/MultiPolygon coordinates, including holes."""
    if geometry['type'] == 'MultiPolygon':
        return math.fsum(polygon_area({'type': 'Polygon', 'coordinates': polygon}, bounds)
                         for polygon in geometry['coordinates'])
    if geometry['type'] != 'Polygon':
        raise ValueError('The area oracle accepts Polygon and MultiPolygon only.')
    rings = geometry['coordinates']
    if not rings:
        return 0.0
    return ring_area(rings[0], bounds) - math.fsum(ring_area(ring, bounds) for ring in rings[1:])


def extract_land_use(archive_path, root):
    """Extract/verify each member of the pinned ZIP without rewriting sources."""
    with zipfile.ZipFile(archive_path) as archive:
        infos = archive.infolist()
        if len(infos) > 100 or sum(member.file_size for member in infos) > 32 * 1024**2:
            raise ValueError('Land-use archive exceeds the validation limits.')
        # Reuse the general acceptance cache if present, otherwise isolate ours.
        folder = 'geopandas/paris_land_use' if (root / 'geopandas/paris_land_use').is_dir() else 'data/paris_land_use'
        target_root = safe_destination(root, Path(folder))
        target_root.mkdir(parents=True, exist_ok=True)
        seen = set()
        for member in infos:
            relative = PurePosixPath(member.filename.replace('\\', '/'))
            if (relative.is_absolute() or PureWindowsPath(str(relative)).drive
                    or '..' in relative.parts or '\x00' in str(relative)
                    or stat.S_ISLNK(member.external_attr >> 16)):
                raise ValueError('Unsafe land-use archive member.')
            target = safe_destination(target_root, Path(*relative.parts))
            key = str(target).casefold()
            if key in seen:
                raise ValueError('Duplicate land-use archive member.')
            seen.add(key)
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            content = archive.read(member)
            if target.exists():
                if not target.is_file() or target.read_bytes() != content:
                    raise ValueError(f'Altered extracted land-use source: {target}')
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open('xb') as handle:
                    handle.write(content)
    return target_root


def prepare(root):
    paths, provenance = {}, []
    for source in (SOURCES[0], LAND_USE_SOURCE):
        candidates = [root / folder / source['file_name'] for folder in ('geopandas', 'data', '')]
        target = next((path for path in candidates if path.exists()), None)
        if target is None:
            target = download_source(root, source)
        else:
            verify_cache(target, source)
        paths[source['file_name']] = target
        provenance.append({**source, 'path': str(target), 'sha256_verified': True})
    extracted = extract_land_use(paths['paris_land_use.zip'], root)
    paths['land'] = extracted / 'paris_land_use.shp'
    originals = {*paths.values(), *(path for path in extracted.rglob('*') if path.is_file())}
    return paths, provenance, {str(path): sha(path) for path in sorted(originals)}


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
    descriptor, name = tempfile.mkstemp(prefix='.g09-report-', suffix='.json', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as handle:
            json.dump(serial(document), handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write('\n')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def close(actual, expected, *, independent=False):
    """Separate arithmetic-oracle precision from overlay-order precision."""
    np.testing.assert_allclose(actual, expected,
                               rtol=1e-10 if independent else 2e-7,
                               atol=1e-6 if independent else 0.002)


def polygon_parts(geometry):
    """Area-only pieces for the GEOS comparison; boundary contacts have no area."""
    if geometry.is_empty:
        return []
    if geometry.geom_type == 'Polygon':
        return [geometry]
    if geometry.geom_type in {'MultiPolygon', 'GeometryCollection'}:
        return [polygon for part in geometry.geoms for polygon in polygon_parts(part)]
    return []


def check_tables(result, expected, zone_areas, *, independent=False):
    """Verify every cell, including zero cells, and every matrix correspondence."""
    classes = result.categories.set_index('class_id')['class_value'].to_dict()
    zones = result.zones.set_index('zone_id')['zone_value'].to_dict()
    assert result.summary['schema'] == 'cartomize.vector.tabulation.v1'
    assert result.summary['area_unit'] == 'm2'
    assert len(result.table) == len(zones) * len(classes)
    assert len(result.matrix) == len(zones)
    assert result.summary['zone_count'] == len(zones)
    assert result.summary['class_count'] == len(classes)
    assert result.summary['table_cells'] == len(result.table)
    assert set(expected) == {(value, category) for value in zones.values() for category in classes.values()}
    assert list(result.matrix.columns) == ['zone_id', 'zone_type', 'zone_value', *classes]
    assert not result.table[['zone_id', 'class_id']].duplicated().any()
    matrix = result.matrix.set_index('zone_id')
    errors = []
    for row in result.table.itertuples(index=False):
        reference = expected[(row.zone_value, row.class_value)]
        close(row.area, reference, independent=independent)
        close(row.percentage, 100.0 * reference / zone_areas[row.zone_value], independent=independent)
        assert matrix.loc[row.zone_id, row.class_id] == row.area
        assert row.zone_type == 'integer' and row.class_type == 'string'
        if independent and reference == 0:
            assert row.area == 0, 'A zero-area analytical cell acquired positive area.'
        errors.append(abs(row.area - reference))
    positives = result.table.loc[result.table['area'] > 0].reset_index(drop=True)
    pd.testing.assert_frame_equal(result.data.drop(columns='geometry').reset_index(drop=True), positives,
                                  check_exact=True)
    for row in result.zones.itertuples(index=False):
        close(row.zone_area, zone_areas[row.zone_value], independent=True)
        # The complex land-use coverage uses GEOS unions. Check the fixed
        # published arithmetic-closure contract, independently of the tighter
        # shoelace tolerances used for each simple analytical cell.
        assert abs(row.covered_area + row.uncovered_area - row.zone_area) <= 1e-6 + 1e-8 * row.zone_area
        assert abs(row.unclassified_area + row.no_coverage_area - row.uncovered_area) <= 1e-6 + 1e-8 * row.zone_area
        assert row.closure_error == row.zone_area - row.covered_area - row.uncovered_area
    assert result.summary['closure_tolerance']['absolute_m2'] == 1e-6
    assert result.summary['closure_tolerance']['relative'] == 1e-8
    for frame in (result.data, result.zones, result.gaps, result.overlaps):
        assert frame.crs.is_projected
        assert frame.crs == result.data.crs
        assert frame.geometry.is_valid.all()
        assert not frame.geometry.is_empty.any()
        assert frame.geom_type.isin(['Polygon', 'MultiPolygon']).all()
    return dict(zone_count=len(zones), class_count=len(classes), table_cells=len(expected),
                zero_cells=int((result.table['area'] == 0).sum()),
                maximum_cell_area_difference_m2=max(errors, default=0.0),
                all_cells_and_matrix_verified=True)


def check_published(record, expected, *, expected_layers=None):
    """Reopen every advertised product and verify audit hashes and source text."""
    import cartomize as cm
    from cartomize.tableio import read_table

    products = record['products']
    assert set(products) == {'primary', 'data', 'table', 'matrix', 'zones', 'categories',
                             'gaps', 'overlaps', 'audit', 'summary'}
    assert products['primary'] == products['data'] == record['primary']
    for name in ('data', 'zones', 'gaps', 'overlaps'):
        actual = cm.read_file(products[name], layer='features')
        reference = getattr(expected, name)
        assert actual.crs == reference.crs
        assert actual.geometry.to_wkb().tolist() == reference.geometry.to_wkb().tolist()
        pd.testing.assert_frame_equal(actual.drop(columns='geometry').reset_index(drop=True),
                                      reference.drop(columns='geometry').reset_index(drop=True),
                                      check_dtype=False, check_exact=True)
    for name in ('table', 'matrix', 'categories'):
        schema = json.loads(Path(str(products[name]) + '.schema.json').read_text(encoding='utf-8'))
        actual = read_table(products[name], dtype=schema['types'])
        pd.testing.assert_frame_equal(actual, getattr(expected, name), check_dtype=False, check_exact=True)
    expected_summary = serial(expected.summary)
    if expected_layers:
        expected_summary['parameters'].update(expected_layers)
    assert json.loads(Path(products['summary']).read_text(encoding='utf-8')) == expected_summary
    audit = json.loads(Path(products['audit']).read_text(encoding='utf-8'))
    assert audit['schema'] == 'cartomize.vector_tabulation.audit.v1'
    assert audit['area_unit'] == expected.summary['area_unit']
    for name, table in audit['tables'].items():
        reference = getattr(expected, name)
        if 'geometry' in reference.columns:
            reference = reference.drop(columns='geometry')
        assert list(table['columns']) == list(reference.columns)
        assert len(table['records']) == len(reference)
        assert table['records'] == serial(reference.to_dict('records'))
    assert set(audit['verified_files']) == {Path(products[name]).name for name in
                                           ('data', 'zones', 'gaps', 'overlaps', 'table', 'matrix', 'categories')}
    for name, verification in audit['verified_files'].items():
        path = Path(record['primary']).parent / name
        assert sha(path) == verification['sha256']
        assert verification['rows'] == len(getattr(expected, path.stem))
    for path in Path(record['primary']).parent.rglob('*.json'):
        assert '.cartomize-' not in path.read_text(encoding='utf-8'), 'A temporary path leaked into a published product.'
    return dict(products={name: str(path) for name, path in products.items()},
                vector_wkb_and_attributes_exact=True, tables_reopened_exactly=True,
                audit_and_summary_verified=True)


def validate(data_root, work, output):
    import geopandas as gpd
    from shapely.geometry import box
    import shapely
    from cartomize.vector_tabulation import tabulate_area
    import cartomize as cm

    paths, provenance, originals = prepare(data_root)
    work.mkdir(parents=True, exist_ok=True)
    if any(work.iterdir()):
        raise ValueError('The validation work directory must be empty; existing products are never overwritten.')
    steps = []

    def check(name, function):
        started = time.perf_counter()
        record = {'name': name}
        try:
            record.update(function() or {})
            record['status'] = 'passed'
        except Exception as exc:
            record.update(status='failed', error=str(exc), traceback=traceback.format_exc())
        record['seconds'] = round(time.perf_counter() - started, 3)
        steps.append(record)
        print(json.dumps({key: value for key, value in record.items() if key not in {'traceback', 'products'}},
                         ensure_ascii=False), flush=True)

    zones = cm.read_file(paths['paris_districts.geojson'])
    classes = cm.read_file(paths['land'])
    projected = zones.to_crs(2154)
    projected_classes = classes.to_crs(2154)
    source_wkb = (zones.geometry.to_wkb().tolist(), classes.geometry.to_wkb().tolist())
    source_tables = (zones.drop(columns='geometry').copy(deep=True), classes.drop(columns='geometry').copy(deep=True))
    zone_areas = {str(identifier): polygon_area(geometry.__geo_interface__)
                  for identifier, geometry in zip(projected['id'], projected.geometry)}
    base_parameters = dict(zone_field='id', class_field='class', metric_crs=2154, area_unit='m2')
    raw_json = json.loads(paths['paris_districts.geojson'].read_text(encoding='utf-8'))['features']

    def original_data():
        assert len(zones) == len(raw_json) == 80 and len(classes) == 3243
        assert zones['id'].tolist() == [feature['properties']['id'] for feature in raw_json]
        assert zones['district_name'].tolist() == [feature['properties']['district_name'] for feature in raw_json]
        assert classes['class'].nunique() == 8 and not classes['class'].isna().any()
        close(projected.geometry.area.to_numpy(), list(zone_areas.values()), independent=True)
        return dict(quartiers=80, land_use_features=3243, original_land_use_classes=8,
                    zone_area_reference='Python translated shoelace on the projected original boundary coordinates',
                    land_use_labels=classes['class'].drop_duplicates().tolist())

    check('Pinned original Paris boundaries and land-use categories', original_data)

    xmin, ymin, xmax, ymax = projected.total_bounds
    edges = np.linspace(xmin - 1, xmax + 1, 4)
    strip_bounds = [(float(left), float(ymin - 1), float(right), float(ymax + 1))
                    for left, right in zip(edges[:-1], edges[1:])]
    strip_bounds.append((float(xmax + 10), float(ymin - 1), float(xmax + 20), float(ymax + 1)))
    strip_names = ['analytical_left', 'analytical_middle', 'analytical_right', 'outside_domain']
    strips = gpd.GeoDataFrame({'class': strip_names}, geometry=[box(*bounds) for bounds in strip_bounds], crs=2154)
    expected_strips = {(str(identifier), name): polygon_area(geometry.__geo_interface__, bounds)
                       for identifier, geometry in zip(projected['id'], projected.geometry)
                       for name, bounds in zip(strip_names, strip_bounds)}
    def analytical_partition():
        result = tabulate_area(zones, strips, **base_parameters)
        details = check_tables(result, expected_strips, zone_areas, independent=True)
        close(result.zones['covered_area'], list(zone_areas.values()), independent=True)
        close(result.zones['uncovered_area'], 0, independent=True)
        close(result.zones['overlap_area'], 0, independent=True)
        # Overlay arithmetic can leave minute positive slivers. The engine
        # intentionally retains them; verify their measured extent explicitly.
        assert result.gaps['area'].sum() <= 1e-6
        return {**details, 'numerical_gap_area_m2': float(result.gaps['area'].sum()),
                'reference': 'Independent Python rectangle clipping and translated shoelace; real boundaries, explicitly analytical classes'}

    check('Independent areas for real quartiers cut by analytical strips', analytical_partition)

    def uncovered_partition():
        partial = strips.iloc[[0, 2, 3]].copy()
        result = tabulate_area(zones, partial, **base_parameters)
        expected = {key: value for key, value in expected_strips.items() if key[1] != strip_names[1]}
        details = check_tables(result, expected, zone_areas, independent=True)
        missing = [expected_strips[(str(identifier), strip_names[1])] for identifier in projected['id']]
        close(result.zones['uncovered_area'], missing, independent=True)
        close(result.zones['no_coverage_area'], missing, independent=True)
        close(result.zones['unclassified_area'], 0, independent=True)
        assert set(result.gaps['kind']) == {'no_coverage'}
        return {**details, 'uncovered_area_m2': float(math.fsum(missing)), 'gap_kind_verified': 'no_coverage'}

    check('Independent uncovered-area balances and explicit zero cells', uncovered_partition)

    def null_class_partition():
        nullable = strips.copy()
        nullable.loc[1, 'class'] = None
        try:
            tabulate_area(zones, nullable, **base_parameters)
        except ValueError:
            pass
        else:
            raise AssertionError('Missing class labels were silently accepted by the strict policy.')
        result = tabulate_area(zones, nullable, **base_parameters, null_classes='unclassified')
        expected = {key: value for key, value in expected_strips.items() if key[1] != strip_names[1]}
        details = check_tables(result, expected, zone_areas, independent=True)
        missing = [expected_strips[(str(identifier), strip_names[1])] for identifier in projected['id']]
        close(result.zones['unclassified_area'], missing, independent=True)
        close(result.zones['no_coverage_area'], 0, independent=True)
        assert set(result.gaps['kind']) == {'unclassified'}
        assert result.summary['null_class_features'] == 1
        return {**details, 'strict_missing_class_rejected': True, 'unclassified_area_m2': float(math.fsum(missing))}

    check('Missing class labels require an explicit unclassified policy', null_class_partition)

    def overlapping_classes():
        bounds = [(strip_bounds[0][0], strip_bounds[0][1], strip_bounds[1][2], strip_bounds[0][3]),
                  (strip_bounds[1][0], strip_bounds[1][1], strip_bounds[2][2], strip_bounds[1][3]),
                  strip_bounds[1]]
        names = ['wide_left', 'wide_right', 'middle_again']
        categories = gpd.GeoDataFrame({'class': names}, geometry=[box(*item) for item in bounds], crs=2154)
        expected = {(str(identifier), name): polygon_area(geometry.__geo_interface__, rectangle)
                    for identifier, geometry in zip(projected['id'], projected.geometry)
                    for name, rectangle in zip(names, bounds)}
        try:
            tabulate_area(zones, categories, **base_parameters)
        except ValueError as exc:
            assert 'overlap' in str(exc).lower()
        else:
            raise AssertionError('Positive class overlaps were not refused by the default policy.')
        result = tabulate_area(zones, categories, **base_parameters, overlap_policy='report')
        details = check_tables(result, expected, zone_areas, independent=True)
        middle = [expected_strips[(str(identifier), strip_names[1])] for identifier in projected['id']]
        close(result.zones['overlap_area'], middle, independent=True)
        # Excess subtracts two large area totals. Compare its rounding residual
        # with the zone-area scale even where the exact excess is zero.
        residual = np.abs(result.zones['excess_area'].to_numpy() - np.asarray(middle) * 2)
        assert (residual <= 1e-6 + 1e-10 * np.asarray(list(zone_areas.values()))).all()
        close(result.zones['uncovered_area'], 0, independent=True)
        assert 'class_overlap' in set(result.overlaps['kind'])
        return {**details, 'default_overlap_refused': True,
                'unique_overlap_footprint_m2': float(math.fsum(middle)),
                'excess_area_m2': float(math.fsum(middle) * 2),
                'maximum_excess_rounding_difference_m2': float(residual.max()),
                'triple_counting_distinguished': True}

    check('Triple category overlaps: unique footprint and additive excess', overlapping_classes)

    def repeated_categories_and_zones():
        doubled_zones = pd.concat([zones, zones.iloc[[0, 0]]], ignore_index=True)
        doubled_classes = pd.concat([strips, strips.iloc[[0, 0]]], ignore_index=True)
        doubled_zones.index = pd.Index([number // 2 for number in range(len(doubled_zones))])
        result = tabulate_area(doubled_zones, doubled_classes, **base_parameters)
        details = check_tables(result, expected_strips, zone_areas, independent=True)
        assert result.zones['source_count'].iloc[0] == 3
        assert result.categories['source_count'].iloc[0] == 3
        close(result.zones['same_zone_excess_area'].iloc[0], zone_areas[str(zones['id'].iloc[0])] * 2, independent=True)
        assert {'same_zone_overlap', 'same_class_overlap'} <= set(result.overlaps['kind'])
        return {**details, 'same_identity_duplicates_dissolved': True, 'duplicate_source_index_supported': True}

    check('Repeated source identities and categories dissolve without double counting', repeated_categories_and_zones)

    def separate_overlapping_zones():
        duplicate = zones.iloc[[0]].copy()
        duplicate['id'] = 999
        overlapping = pd.concat([zones, duplicate], ignore_index=True)
        try:
            tabulate_area(overlapping, strips, **base_parameters, zone_overlap_policy='error')
        except ValueError as exc:
            assert 'zones overlap' in str(exc).lower()
        else:
            raise AssertionError('Overlapping distinct zones were silently accepted in strict mode.')
        result = tabulate_area(overlapping, strips, **base_parameters)
        expected = {**expected_strips, **{('999', name): expected_strips[(str(zones['id'].iloc[0]), name)] for name in strip_names}}
        areas = {**zone_areas, '999': zone_areas[str(zones['id'].iloc[0])]}
        details = check_tables(result, expected, areas, independent=True)
        assert result.summary['totals']['zone_sums']['zone_excess_area'] >= areas['999'] - 0.01
        assert 'zone_overlap' in set(result.overlaps['kind'])
        return {**details, 'strict_zone_overlap_refused': True,
                'independent_zone_sums_and_unique_domain_distinguished': True}

    check('Overlapping distinct zones retain independent balances and a unique domain', separate_overlapping_zones)

    def projected_geometry_quality():
        invalid_count = int((~projected_classes.geometry.is_valid).sum())
        if invalid_count:
            try:
                tabulate_area(zones, classes, **base_parameters, overlap_policy='report')
            except ValueError as exc:
                assert 'after reprojection' in str(exc) and 'invalid geometry' in str(exc)
            else:
                raise AssertionError('Invalid reprojected polygons were silently accepted.')
        else:
            # Projection-library versions can improve numerical robustness.
            # If all transformed inputs are valid, no refusal is required.
            result = tabulate_area(zones, classes, **base_parameters, overlap_policy='report')
            assert result.data.geometry.is_valid.all()
        return dict(original_invalid_features=int((~classes.geometry.is_valid).sum()),
                    transformed_invalid_features=invalid_count,
                    post_projection_geometry_quality_enforced=True,
                    real_land_use_analysis='Native projected CRS retained; no geometry repair or coordinate snapping')

    check('Geometry validity after reprojection is enforced explicitly', projected_geometry_quality)

    real_results = {}

    def original_land_use():
        # Native LAEA polygons are valid. Reprojecting their tiny boundaries can
        # introduce invalidities; that refusal is checked separately above.
        native_zones = zones.to_crs(classes.crs)
        native_zone_areas = {str(identifier): polygon_area(geometry.__geo_interface__)
                             for identifier, geometry in zip(native_zones['id'], native_zones.geometry)}
        names = classes['class'].drop_duplicates().tolist()
        expected = {(str(identifier), name): 0.0 for identifier in zones['id'] for name in names}
        covered, overlap = {}, {}
        index = classes.sindex
        for identifier, geometry in zip(native_zones['id'], native_zones.geometry):
            candidates = index.query(geometry, predicate='intersects')
            by_class = {name: [] for name in names}
            for row in candidates:
                source = classes.iloc[int(row)]
                clipped = source.geometry.intersection(geometry)
                by_class[source['class']].extend(polygon_parts(clipped))
            unions = []
            for name in names:
                union = shapely.union_all(by_class[name])
                expected[(str(identifier), name)] = union.area
                unions.append(union)
            covered[str(identifier)] = shapely.union_all(unions).area
            parts = [left.intersection(right) for i, left in enumerate(unions) for right in unions[i + 1:]
                     if not left.is_empty and not right.is_empty]
            overlap[str(identifier)] = shapely.union_all(parts).area
        result = tabulate_area(zones, classes, **{**base_parameters, 'metric_crs': classes.crs}, overlap_policy='report')
        details = check_tables(result, expected, native_zone_areas)
        for row in result.zones.itertuples(index=False):
            close(row.covered_area, covered[row.zone_value])
            close(row.overlap_area, overlap[row.zone_value])
        assert result.categories['same_class_excess_area'].sum() > 20000
        real_results['result'] = result
        return {**details, 'same_class_excess_m2': float(result.categories['same_class_excess_area'].sum()),
                'unique_covered_domain_m2': result.summary['totals']['domain']['covered_area'],
                'class_overlap_area_m2': result.summary['totals']['domain']['overlap_area'],
                'measurement_crs': str(classes.crs),
                'reference': 'Intersect original source polygons first, then union each category per zone; GEOS shared, operation order independent',
                'comparison_tolerance': {'absolute_m2': 0.002, 'relative': 2e-7}}

    check('Original Paris land-use classes: complete real area crosstab', original_land_use)

    def land_use_publication():
        parameters = dict(zones=str(paths['paris_districts.geojson']), classes=str(paths['land']),
                          classes_layer='paris_land_use', **{**base_parameters, 'metric_crs': str(classes.crs)},
                          overlap_policy='report')
        record = cm.execute_operation('vector.tabulate_area', parameters, work / 'paris_land_use_tabulation')
        # File inputs record the explicit/discovered layer names; the in-memory
        # reference has no file layer metadata. All other summary values match.
        return check_published(record, real_results['result'], expected_layers={
            'classes_layer': 'paris_land_use', 'zones_layer': 'paris_districts'})

    check('Real land-use geometries, tables, balances and audit reopen exactly', land_use_publication)

    def publication():
        from cartomize.vector_io import write_geopackage
        path = work / 'analytical_strips.gpkg'
        write_geopackage(strips, path, layer='classes')
        parameters = dict(zones=str(paths['paris_districts.geojson']), classes=str(path),
                          classes_layer='classes', **base_parameters)
        result = tabulate_area(**parameters)
        check_tables(result, expected_strips, zone_areas, independent=True)
        record = cm.execute_operation('vector.tabulate_area', parameters, work / 'published_tabulation')
        return check_published(record, result)

    check('Publication from geographic zones and projected class layer reopens exactly', publication)

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
            tabulate_area(zones, strips, **base_parameters, progress=progress, cancel=cancelled)
        except ProcessingCancelled:
            pass
        else:
            raise AssertionError('Cancellation returned a partial result instead of stopping.')
        assert progress_values == sorted(progress_values)
        destination = work / 'cancelled_publication'
        try:
            cm.execute_operation('vector.tabulate_area', dict(zones=zones, classes=strips, **base_parameters),
                                 destination, cancel=cancelled)
        except ProcessingCancelled:
            pass
        else:
            raise AssertionError('Cancelled publication unexpectedly succeeded.')
        assert not destination.exists()
        return dict(monotonic_progress=True, cancellation_stopped_computation=True, no_partial_publication=True)

    check('Cancellation preserves sources and does not publish partial products', cancellation)

    def sources_unchanged():
        assert all(sha(path) == digest for path, digest in originals.items())
        assert source_wkb == (zones.geometry.to_wkb().tolist(), classes.geometry.to_wkb().tolist())
        pd.testing.assert_frame_equal(source_tables[0], zones.drop(columns='geometry'), check_exact=True)
        pd.testing.assert_frame_equal(source_tables[1], classes.drop(columns='geometry'), check_exact=True)
        return dict(files_checked=len(originals), all_original_sha256_unchanged=True,
                    in_memory_source_values_and_wkb_unchanged=True)

    check('Original files and in-memory sources remain unchanged', sources_unchanged)
    try:
        head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        head = None
    report = dict(schema='cartomize.g09_real_validation.v1', version=cm.__version__,
                  generated_at_utc=datetime.now(timezone.utc).isoformat(), commit=head,
                  source_sha256={str(path.relative_to(REPO)): sha(path) for path in sorted((REPO / 'src/cartomize').rglob('*.py'))},
                  validation_script_sha256=sha(Path(__file__)), python=platform.python_version(), platform=platform.platform(),
                  packages={name: metadata.version(name) for name in ['geopandas', 'shapely', 'pandas', 'pyogrio']},
                  tutorial_commit=TUTORIAL_REF, sources=provenance, original_sha256=originals,
                  temporal_scope='Historical published teaching snapshots, not current Paris land-use statistics.',
                  independent_checks='Python rectangle clipping and translated shoelace on real zone boundaries; literal oracle tests; source SHA-256.',
                  shared_engines='Real land-use intersection/union reference shares GEOS, with a different operation order. Projection and decoding share PROJ/GDAL.',
                  analytical_classes='Explicit synthetic rectangular partitions used only to validate area calculations on real boundary geometries.',
                  passed=sum(step['status'] == 'passed' for step in steps),
                  failed=sum(step['status'] == 'failed' for step in steps), steps=steps)
    atomic_report(output, report)
    print(json.dumps({key: report[key] for key in ('version', 'passed', 'failed')}), flush=True)
    return report['failed'] == 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=Path('.real-project-data'))
    parser.add_argument('--work', type=Path, default=Path('reports/g09-real/products'))
    parser.add_argument('--output', '--report', type=Path, default=Path('reports/g09-real/validation.json'))
    arguments = parser.parse_args()
    raise SystemExit(0 if validate(arguments.data.resolve(), arguments.work.resolve(), arguments.output.resolve()) else 1)
