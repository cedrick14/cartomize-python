"""Validate G07 partitions and published outputs against pinned real datasets.

Run from the repository root::

    python scripts/validate_vector_selection_real.py --data .real-project-data \
        --work reports/g07-real/products --output reports/g07-real/validation.json

The three historical GeoPandas teaching datasets retain the M08 SHA-256 pins.
Existing real-project caches are reused. Only missing public files are fetched;
downloaded notebooks or other code are never executed. Attribute decisions use
the original JSON scalars. The RDC point-in-polygon oracle uses Python ray
casting, without invoking GEOS predicates. Paris polygon intersections share
GEOS with Cartomize and validate integration, not the geometric engine itself.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import sqlite3
import subprocess
import tempfile
import time
import traceback

import numpy as np
import pandas as pd

from validate_vector_quality_real import (
    SOURCES, TUTORIAL_REF, download_source, extract_verified_zip, sha, verify_cache,
)


REPO = Path(__file__).resolve().parents[1]
PARK_MEMBER = 'Conservation/RDC_aire_protegee_2013.shp'


def serial(value):
    if isinstance(value, dict):
        return {str(key): serial(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [serial(item) for item in value]
    if isinstance(value, np.generic):
        return serial(value.item())
    if isinstance(value, (date, datetime, Path)):
        return value.isoformat() if isinstance(value, (date, datetime)) else str(value)
    if value is pd.NA or value is pd.NaT:
        return None
    return value


def atomic_report(path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix='.g07-report-', suffix='.json', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as handle:
            json.dump(serial(document), handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write('\n')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def prepare(root):
    """Reuse either the general acceptance cache or a module validation cache."""
    paths, provenance = {}, []
    for source in SOURCES:
        candidates = [root / folder / source['file_name'] for folder in ('geopandas', 'data', '')]
        target = next((path for path in candidates if path.exists()), None)
        if target is None:
            target = download_source(root, source)
        else:
            verify_cache(target, source)
        paths[source['file_name']] = target
        provenance.append({**source, 'path': str(target), 'sha256_verified': True})
    # The helper verifies each extracted member against the pinned ZIP bytes,
    # including existing files, and refuses altered caches instead of repairing them.
    extracted = extract_verified_zip(paths['cod_conservation.zip'], root)
    paths['parks'] = extracted / PARK_MEMBER
    originals = {*paths.values(), *(p for p in extracted.rglob('*') if p.is_file())}
    return paths, provenance, {str(path): sha(path) for path in sorted(originals)}


def ring_relation(point, ring):
    """Return 0 outside, 1 strictly inside, 2 on an edge; no GIS predicate."""
    x, y = point[:2]
    inside = False
    for first, second in zip(ring, ring[1:] + ring[:1]):
        ax, ay = first[:2]
        bx, by = second[:2]
        cross = (x - ax) * (by - ay) - (y - ay) * (bx - ax)
        if cross == 0 and min(ax, bx) <= x <= max(ax, bx) and min(ay, by) <= y <= max(ay, by):
            return 2
        if (ay > y) != (by > y) and x < (bx - ax) * (y - ay) / (by - ay) + ax:
            inside = not inside
    return int(inside)


def point_within(point, geometry):
    """Strict point membership in a valid Polygon/MultiPolygon, including holes."""
    if geometry['type'] == 'MultiPolygon':
        return any(point_within(point, {'type': 'Polygon', 'coordinates': polygon})
                   for polygon in geometry['coordinates'])
    if geometry['type'] != 'Polygon':
        raise ValueError('The independent oracle accepts polygon masks only.')
    rings = geometry['coordinates']
    return bool(rings and ring_relation(point, rings[0]) == 1
                and all(ring_relation(point, ring) == 0 for ring in rings[1:]))


def same_rows(expected, actual, *, published=False):
    assert list(actual.columns) == list(expected.columns), 'The source schema changed.'
    assert actual.crs == expected.crs
    assert actual.geometry.to_wkb().tolist() == expected.geometry.to_wkb().tolist()
    if not published:
        assert actual.index.equals(expected.index)
    pd.testing.assert_frame_equal(
        expected.drop(columns=expected.geometry.name).reset_index(drop=True),
        actual.drop(columns=actual.geometry.name).reset_index(drop=True),
        check_dtype=not published, check_exact=True,
    )


def check_partition(source, result, *, attributes=None, spatial=None,
                    combination='and', invert=False, criteria=None, id_field=None):
    """Account for every original position and every published decision."""
    a = None if attributes is None else np.asarray(attributes, dtype=bool)
    s = None if spatial is None else np.asarray(spatial, dtype=bool)
    combined = s if a is None else a if s is None else (a & s if combination == 'and' else a | s)
    selected = ~combined if invert else combined
    retained, rejected = np.flatnonzero(selected), np.flatnonzero(~selected)
    same_rows(source.iloc[retained], result.data)
    same_rows(source.iloc[rejected], result.rejected)
    report, summary = result.report, result.summary
    assert report.source_row.tolist() == list(range(len(source)))
    assert report.source_index.tolist() == source.index.tolist()
    assert report.source_id.tolist() == (source[id_field].tolist() if id_field else list(range(len(source))))
    assert report.combined_match.tolist() == combined.tolist()
    assert report.selected.tolist() == selected.tolist()
    for column, expected in [('attribute_match', a), ('spatial_match', s)]:
        assert report[column].isna().all() if expected is None else report[column].tolist() == expected.tolist()
    for index, expected in enumerate(criteria or (), 1):
        assert report[f'attribute_{index}_match'].tolist() == list(expected)
        assert summary['criteria'][index - 1]['matched'] == sum(expected)
    assert report.output_row.dtype == report.rejected_row.dtype == pd.Int64Dtype()
    assert report.output_row.notna().tolist() == selected.tolist()
    assert report.rejected_row.notna().tolist() == (~selected).tolist()
    assert report.output_row.dropna().tolist() == list(range(len(retained)))
    assert report.rejected_row.dropna().tolist() == list(range(len(rejected)))
    reasons = []
    for row, chosen in enumerate(selected):
        if chosen:
            reason = 'selected_by_inversion' if invert else 'selected'
        elif invert:
            reason = 'excluded_by_inversion'
        elif a is not None and not a[row]:
            reason = 'attribute_and_spatial_no_match' if s is not None and not s[row] else 'attribute_no_match'
        else:
            reason = 'spatial_no_match'
        reasons.append(reason)
    assert report.reason.tolist() == reasons
    assert summary['input_features'] == len(source)
    assert summary['output_features'] == len(retained)
    assert summary['rejected_features'] == len(rejected)
    combinations = None if a is None or s is None else dict(
        both=int((a & s).sum()), attributes_only=int((a & ~s).sum()),
        spatial_only=int((~a & s).sum()), neither=int((~a & ~s).sum()))
    assert summary['combinations'] == combinations
    for name, expected in [('attributes', a), ('spatial', s)]:
        block = summary['blocks'][name]
        assert block['enabled'] == (expected is not None)
        if expected is not None:
            assert block['matched'] == int(expected.sum())
            assert block['unmatched'] == len(source) - int(expected.sum())
    return dict(input_features=len(source), retained=len(retained), rejected=len(rejected),
                all_rows_accounted_for=True, attributes_exact=True, geometry_wkb_exact=True,
                source_order_preserved=True, decisions_and_reasons_verified=True,
                combinations=combinations)


def check_published(record, result, *, date_column=None):
    import cartomize as cm

    products = record['products']
    assert {'data', 'rejected', 'report', 'audit', 'summary'} <= set(products)
    assert all(Path(path).is_file() for path in products.values())
    assert record['primary'] == products['data']
    for name, expected in [('data', result.data), ('rejected', result.rejected)]:
        observed = cm.read_file(products[name], layer='features')
        same_rows(expected, observed, published=True)
        if date_column:
            with sqlite3.connect(products[name]) as connection:
                types = {row[1]: row[2].upper() for row in connection.execute('PRAGMA table_info(features)')}
                assert types[date_column] == 'DATE'
                rows = connection.execute(f'SELECT "{date_column}" FROM features ORDER BY rowid').fetchall()
            assert [row[0] for row in rows] == [None if value is None or pd.isna(value) else value.isoformat()
                                              for value in expected[date_column]]
    csv_report = pd.read_csv(products['report'], keep_default_na=False)
    assert csv_report.source_row.tolist() == result.report.source_row.tolist()
    assert csv_report.reason.tolist() == result.report.reason.tolist()
    assert csv_report.selected.tolist() == result.report.selected.tolist()
    audit = json.loads(Path(products['audit']).read_text(encoding='utf-8'))
    assert audit['schema'] == 'cartomize.vector_selection.audit.v1'
    assert audit['row_numbering'] == 'zero_based_source_order'
    assert len(audit['records']) == len(result.report)
    for expected, observed in zip(result.report.to_dict('records'), audit['records']):
        assert set(expected) == set(observed)
        for name, value in expected.items():
            if name in {'source_index', 'source_id'}:
                # Both real datasets use integral source identities. JSON
                # carries their digits as text to avoid JavaScript rounding.
                assert observed[name] == {'type': 'integer', 'value': str(value)}
            else:
                assert observed[name] == serial(value)
    report_schema = json.loads(Path(str(products['report']) + '.schema.json').read_text(encoding='utf-8'))
    assert report_schema['types']['source_id'] == report_schema['types']['source_index'] == 'string'
    assert json.loads(Path(products['summary']).read_text(encoding='utf-8')) == serial(result.summary)
    for path in Path(record['primary']).parent.rglob('*.json'):
        assert '.cartomize-' not in path.read_text(encoding='utf-8'), 'A temporary path leaked into a delivered product.'
    return dict(products={name: str(path) for name, path in products.items()},
                retained_and_excluded_reopened_exactly=True, native_date_verified=date_column)


def validate(data_root, work, output):
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

    paris_path = paths['paris_districts.geojson']
    mines_path = paths['cod_mines_curated_all_opendata_p_ipis.geojson']
    paris_json = json.loads(paris_path.read_text(encoding='utf-8'))['features']
    mines_json = json.loads(mines_path.read_text(encoding='utf-8'))['features']
    paris = cm.read_file(paris_path)
    mines = cm.read_file(mines_path)
    parks = cm.read_file(paths['parks'])
    kahuzi = parks[parks.NOM.astype(str).str.contains('Kahuzi', case=False, na=False)].copy()
    assert len(kahuzi) == 1 and kahuzi.geometry.is_valid.all()
    # Conservation uses a custom Mercator CRS. Align the oracle coordinates
    # explicitly; the selection call itself receives the original mask CRS.
    kahuzi_interface = kahuzi.to_crs(mines.crs).geometry.iloc[0].__geo_interface__

    def originals_match_json():
        assert len(paris) == len(paris_json) == 80
        assert len(mines) == len(mines_json) == 3687
        assert paris['id'].tolist() == [item['properties']['id'] for item in paris_json]
        assert mines['vid'].tolist() == [item['properties']['vid'] for item in mines_json]
        for value, feature in zip(mines['visit_date'], mines_json):
            raw = feature['properties']['visit_date']
            assert value is None or pd.isna(value) if raw is None else (
                type(value) is date and value == date.fromisoformat(raw.rstrip('Z')))
        return dict(paris_features=len(paris), mine_visits=len(mines), protected_areas=len(parks),
                    reference='Original JSON feature order, ids and ISO calendar dates; Python standard library')

    check('Original JSON identifiers and native calendar dates', originals_match_json)

    paris_attributes = [item['properties']['population'] >= 30000 for item in paris_json]
    paris_filters = [{'field': 'population', 'comparison': 'ge', 'value': 30000}]
    # Repeated mask records exercise union semantics without duplicating source rows.
    paris_mask = paris.iloc[[0, 59, 0]].copy()
    paris_spatial = paris.geometry.intersects(paris_mask.geometry.union_all()).tolist()
    paris_mask_path = work / 'paris_mask.gpkg'
    from cartomize.vector_io import write_geopackage
    write_geopackage(paris_mask, paris_mask_path, layer='mask')
    for combination, invert in [('and', False), ('or', False), ('or', True)]:
        def paris_case(combination=combination, invert=invert):
            source = paris.copy()
            source.index = pd.Index([number // 2 for number in range(len(source))], name='repeated_index')
            result = cm.extract_features(source, filters=paris_filters, mask=paris_mask,
                                         combination=combination, invert=invert, id_field='id')
            return {**check_partition(source, result, attributes=paris_attributes, spatial=paris_spatial,
                                     combination=combination, invert=invert, criteria=[paris_attributes], id_field='id'),
                    'reference': 'JSON population comparisons; GEOS polygon intersections (shared engine)',
                    'duplicate_index_and_mask_records': True}
        check(f'Paris combined {combination}, inversion={invert}', paris_case)

    def paris_publication():
        parameters = dict(data=str(paris_path), filters=paris_filters, mask=str(paris_mask_path),
                          mask_layer='mask', combination='and', id_field='id')
        result = cm.extract_features(**parameters)
        check_partition(paris, result, attributes=paris_attributes, spatial=paris_spatial,
                        criteria=[paris_attributes], id_field='id')
        record = cm.execute_operation('vector.extract_features', parameters, work / 'paris_partition')
        return check_published(record, result)

    check('Paris published selected/excluded GeoPackages and reports', paris_publication)

    mine_criteria = [
        ['IPIS' in (item['properties']['project'] or '') for item in mines_json],
        [item['properties']['workers_numb'] is not None and item['properties']['workers_numb'] > 0
         for item in mines_json],
        [item['properties']['visit_date'] is not None
         and date.fromisoformat(item['properties']['visit_date'].rstrip('Z')) >= date(2010, 1, 1)
         for item in mines_json],
    ]
    mine_attributes = np.logical_and.reduce(mine_criteria)
    mine_filters = [dict(field='project', comparison='contains', value='IPIS'),
                    dict(field='workers_numb', comparison='gt', value=0),
                    dict(field='visit_date', comparison='ge', value='2010-01-01')]
    mine_spatial = [point_within(item['geometry']['coordinates'], kahuzi_interface) for item in mines_json]
    for combination in ['and', 'or']:
        def mines_case(combination=combination):
            result = cm.extract_features(mines, filters=mine_filters, mask=kahuzi,
                                         predicate='within', combination=combination, id_field='vid')
            return {**check_partition(mines, result, attributes=mine_attributes, spatial=mine_spatial,
                                     combination=combination, criteria=mine_criteria, id_field='vid'),
                    'reference': 'Original JSON scalar conditions and Python point-in-polygon ray casting',
                    'mask': str(kahuzi.NOM.iloc[0])}
        check(f'RDC combined {combination}: dates, workforce and Kahuzi-Biega', mines_case)

    def mines_publication():
        mask_path = work / 'kahuzi_mask.gpkg'
        write_geopackage(kahuzi, mask_path, layer='mask')
        parameters = dict(data=str(mines_path), filters=mine_filters, mask=str(mask_path), mask_layer='mask',
                          predicate='within', combination='or', id_field='vid')
        result = cm.extract_features(**parameters)
        check_partition(mines, result, attributes=mine_attributes, spatial=mine_spatial,
                        combination='or', criteria=mine_criteria, id_field='vid')
        record = cm.execute_operation('vector.extract_features', parameters, work / 'rdc_partition')
        return check_published(record, result, date_column='visit_date')

    check('RDC publication preserves native DATE in selected and excluded records', mines_publication)

    def sources_unchanged():
        assert all(sha(path) == digest for path, digest in originals.items())
        return dict(files_checked=len(originals), all_original_sha256_unchanged=True)

    check('Original files remain unchanged', sources_unchanged)
    try:
        head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        head = None
    modules = {str(path.relative_to(REPO)): sha(path)
               for path in sorted((REPO / 'src/cartomize').rglob('*.py'))}
    report = dict(schema='cartomize.g07_real_validation.v1', version=cm.__version__,
                  generated_at_utc=datetime.now(timezone.utc).isoformat(), commit=head,
                  source_sha256=modules, validation_script_sha256=sha(Path(__file__)),
                  python=platform.python_version(), platform=platform.platform(),
                  packages={name: metadata.version(name) for name in ['geopandas', 'shapely', 'pandas', 'pyogrio']},
                  tutorial_commit=TUTORIAL_REF, sources=provenance, original_sha256=originals,
                  temporal_scope='Historical training snapshots, not a current inventory of sites or protected areas.',
                  independent_checks='JSON attribute decisions, Python point-in-polygon predicates, SQLite DATE storage.',
                  shared_engines='Paris polygon intersection and geometry decoding use GEOS/GDAL shared with Cartomize. '
                                 'Kahuzi coordinates are aligned with PROJ; its point membership predicate is independent.',
                  passed=sum(step['status'] == 'passed' for step in steps),
                  failed=sum(step['status'] == 'failed' for step in steps), steps=steps)
    atomic_report(output, report)
    print(json.dumps({key: report[key] for key in ('version', 'passed', 'failed')}), flush=True)
    return report['failed'] == 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=Path('.real-project-data'))
    parser.add_argument('--work', type=Path, default=Path('reports/g07-real/products'))
    parser.add_argument('--output', '--report', type=Path, default=Path('reports/g07-real/validation.json'))
    arguments = parser.parse_args()
    raise SystemExit(0 if validate(arguments.data.resolve(), arguments.work.resolve(), arguments.output.resolve()) else 1)
