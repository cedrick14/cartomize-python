"""Reproduce M08 checks on three pinned, real GeoPandas teaching datasets.

Usage from the repository root::

    python scripts/validate_vector_quality_real.py --data CACHE --output REPORT.json

Correct cached files are reused without a network request or rewrite. An
incorrect cache file is refused; remove that specific file before retrying.
Only the three URLs below are downloaded, and only data are read. GeoPandas,
Shapely and Cartomize share GEOS: the comparison validates integration and
consistency, not independent certification of the geometry engine.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import platform
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile

import geopandas as gpd
from geopandas.testing import assert_geodataframe_equal
import numpy as np
import pandas as pd
import shapely

REPO = Path(__file__).resolve().parents[1]
TUTORIAL_REF = "72c7f3168e1e4e257caf84eb7b3fcaa47ade09c0"
SOURCES = (
    {
        "file_name": "paris_districts.geojson",
        "url": "https://raw.githubusercontent.com/jorisvandenbossche/geopandas-tutorial/72c7f3168e1e4e257caf84eb7b3fcaa47ade09c0/data/paris_districts.geojson",
        "bytes": 370905,
        "sha256": "db65faf397e8876e9a62cdb722bc8c0897e9f9e4db4daa5c01a7e7d7883d626b",
    },
    {
        "file_name": "cod_mines_curated_all_opendata_p_ipis.geojson",
        "url": "https://raw.githubusercontent.com/jorisvandenbossche/geopandas-tutorial/72c7f3168e1e4e257caf84eb7b3fcaa47ade09c0/data/cod_mines_curated_all_opendata_p_ipis.geojson",
        "bytes": 6544746,
        "sha256": "1fccfe863bdbe6d7ebc6808bd7484c09a832c35a0e4816611004dd05223cd842",
    },
    {
        "file_name": "cod_conservation.zip",
        "url": "https://raw.githubusercontent.com/jorisvandenbossche/geopandas-tutorial/72c7f3168e1e4e257caf84eb7b3fcaa47ade09c0/data/cod_conservation.zip",
        "bytes": 1511770,
        "sha256": "af5f5300833296390930106fef971e7442da663d67e499538681908958a914b4",
    },
)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def verify_cache(path, expected):
    if path.is_symlink():
        raise ValueError(f"Cache symlinks are not accepted: {path}")
    if not path.is_file() or path.stat().st_size != expected["bytes"] or sha(path) != expected["sha256"]:
        raise ValueError(f"Cached file does not match the pinned SHA-256: {path}. Remove this file before retrying.")


def safe_destination(root, relative):
    root = root.resolve()
    target = root / relative
    if not target.resolve().is_relative_to(root):
        raise ValueError("Cache target escapes its authorized directory.")
    current = target
    while current != root:
        if current.is_symlink():
            raise ValueError(f"Cache symlinks are not accepted: {current}")
        current = current.parent
    return target


def download_source(root, source):
    target = safe_destination(root, Path("data") / source["file_name"])
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        verify_cache(target, source)
        return target
    descriptor, temporary_name = tempfile.mkstemp(prefix=".m08-", suffix=".part", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        request = urllib.request.Request(source["url"], headers={"User-Agent": "Cartomize-M08-validation/1.0"})
        with os.fdopen(descriptor, "wb") as destination:
            with urllib.request.urlopen(request, timeout=30) as response:
                received = 0
                while chunk := response.read(1024 * 1024):
                    received += len(chunk)
                    if received > source["bytes"]:
                        raise ValueError("Downloaded data exceed the pinned file size.")
                    destination.write(chunk)
        verify_cache(temporary, source)
        # Check again before publication, in case another process populated
        # the same cache while the request was in flight.
        if target.exists():
            verify_cache(target, source)
        else:
            temporary.replace(target)
        return target
    finally:
        temporary.unlink(missing_ok=True)


def extract_verified_zip(archive_path, root):
    target_root = safe_destination(root, Path("data/cod_conservation"))
    target_root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        infos = archive.infolist()
        if len(infos) > 1000 or sum(member.file_size for member in infos) > 64 * 1024**2:
            raise ValueError("Archive expansion exceeds the validation dataset limits.")
        seen = set()
        destinations = []
        for member in infos:
            name = member.filename.replace("\\", "/")
            relative = PurePosixPath(name)
            if (relative.is_absolute() or PureWindowsPath(name).drive
                    or ".." in relative.parts or "\x00" in name
                    or stat.S_ISLNK(member.external_attr >> 16)):
                raise ValueError(f"Unsafe archive member: {member.filename!r}")
            target = safe_destination(target_root, Path(*relative.parts))
            key = str(target).casefold()
            if key in seen:
                raise ValueError("Duplicate archive member paths are not accepted.")
            seen.add(key)
            destinations.append((member, target))
        for member, target in destinations:
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            # This archive is pinned and bounded above. Comparing each member
            # protects the reusable extracted cache as well as the ZIP itself.
            content = archive.read(member)
            expected_hash = hashlib.sha256(content).hexdigest()
            if target.exists():
                if not target.is_file() or target.stat().st_size != len(content) or sha(target) != expected_hash:
                    raise ValueError(f"Extracted cache file is altered: {target}. Remove it before retrying.")
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as destination:
                destination.write(content)
    return target_root


def prepare_inputs(root):
    root.mkdir(parents=True, exist_ok=True)
    records = []
    for source in SOURCES:
        target = download_source(root, source)
        records.append({**source, "path": str(target), "matches_prior_validation_sha256": True})
        if source["file_name"].endswith(".zip"):
            extract_verified_zip(target, root)
    return {"tutorial_commit": TUTORIAL_REF, "sources": records}


def repository_head():
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def write_report(destination, text):
    descriptor, name = tempfile.mkstemp(prefix=".m08-report-", suffix=".json", dir=destination.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def serial(value):
    if isinstance(value, dict):
        return {str(k): serial(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [serial(v) for v in value]
    if isinstance(value, np.generic):
        return serial(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.isoformat()
    return value


def polygons(geometry):
    if geometry.geom_type == "Polygon" and not geometry.is_empty:
        yield geometry
    elif hasattr(geometry, "geoms"):
        for component in geometry.geoms:
            yield from polygons(component)


def validate(root, output_path):
    if not __debug__:
        raise RuntimeError("Run validation without Python -O; assertions must remain enabled.")
    if output_path.is_relative_to(root / "data"):
        raise ValueError("The validation report must be outside the input data subdirectory.")
    ROOT = root
    started = time.perf_counter()
    # Always validate the sources adjacent to this script, even if an older
    # Cartomize checkout is installed editable in the selected interpreter.
    sys.path.insert(0, str(REPO / "src"))
    os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "matplotlib-cache"))
    import cartomize as cm
    modules = ['src/cartomize/vector_quality.py', 'src/cartomize/vector_topology.py',
               'src/cartomize/vector_duplicates.py', 'src/cartomize/vector_quality_result.py']
    code_hashes = {name: sha(REPO / name) for name in modules}
    provenance = prepare_inputs(ROOT)
    sources = [{k: v for k, v in entry.items() if k != 'path'} |
               {'file_name': Path(entry['path']).name} for entry in provenance['sources']]
    source_hashes = {entry['path']: sha(entry['path']) for entry in provenance['sources']}

    parks_path = ROOT / 'data/cod_conservation/Conservation/RDC_aire_protegee_2013.shp'
    parks = gpd.read_file(parks_path)
    mines = gpd.read_file(ROOT / 'data/cod_mines_curated_all_opendata_p_ipis.geojson')
    paris_raw = gpd.read_file(ROOT / 'data/paris_districts.geojson')
    originals = {name: data.copy(deep=True) for name, data in
                 [('parks', parks), ('mines', mines), ('paris_raw', paris_raw)]}
    checks = []


    def passed(name, **metrics):
        checks.append({'name': name, 'status': 'passed', **serial(metrics)})
        print(json.dumps(checks[-1], ensure_ascii=False), flush=True)


    assert len(parks) == 50 and len(mines) == 3687 and len(paris_raw) == 80
    assert all(entry['sha256'] == source_hashes[entry['path']] for entry in provenance['sources'])
    passed('Pinned input hashes and expected feature counts', parks=50, mine_visits=3687, paris_districts=80)

    audit = cm.audit_geometries(parks)
    assert_geodataframe_equal(audit.data, parks)
    assert audit.summary['invalid_geometries'] == 1
    np.testing.assert_array_equal(audit.report['valid'], parks.is_valid.to_numpy())
    np.testing.assert_allclose(audit.report.area_m2, parks.area.to_numpy(), rtol=1e-12)
    np.testing.assert_allclose(audit.report.length_m, parks.length.to_numpy(), rtol=1e-12)
    invalid_rows = np.flatnonzero(~parks.is_valid.to_numpy())
    passed('G01 audit of RDC protected areas', invalid_rows=invalid_rows.tolist(),
           source_geometry_types=parks.geom_type.value_counts().to_dict(),
           missing=int(parks.geometry.isna().sum()), empty=int(parks.is_empty.sum()),
           reference='Direct GeoPandas validity, area and length; shared GEOS engine',
           summary=audit.summary)

    repair = cm.repair_geometries(parks, method='linework')
    expected = parks.copy()
    expected.geometry = gpd.array.from_shapely([
        geom if geom.is_valid else shapely.make_valid(geom) for geom in parks.geometry
    ], crs=parks.crs)
    assert_geodataframe_equal(repair.data, expected)
    pd.testing.assert_frame_equal(repair.data.drop(columns=repair.data.geometry.name),
                                  parks.drop(columns=parks.geometry.name))
    assert len(repair.data) == 50 and repair.data.is_valid.all()
    assert repair.rejected.empty
    np.testing.assert_allclose(repair.report.before_area_m2, parks.area.to_numpy(), rtol=1e-12)
    np.testing.assert_allclose(repair.report.after_area_m2, repair.data.area.to_numpy(), rtol=1e-12)
    np.testing.assert_allclose(repair.report.area_delta_m2,
                               repair.data.area.to_numpy() - parks.area.to_numpy(), rtol=1e-12, atol=1e-6)
    np.testing.assert_array_equal(repair.report.geometry_changed, ~parks.is_valid.to_numpy())
    for i in np.flatnonzero(parks.is_valid.to_numpy()):
        assert parks.geometry.iloc[i].wkb == repair.data.geometry.iloc[i].wkb
    assert cm.audit_geometries(repair.data).summary['invalid_geometries'] == 0
    changed = repair.report[repair.report.geometry_changed].to_dict('records')
    for item in changed:
        item['protected_area_name'] = parks.iloc[item['source_row']]['NOM']
    passed('G01 repair, full-record preservation and before/after measurements',
           input_features=50, retained_features=50, valid_before=49, valid_after=50,
           unchanged_valid_geometry_wkb=49, changed_features=changed,
           area_before_m2=float(parks.area.sum()), area_after_m2=float(repair.data.area.sum()),
           reference='Direct shapely.make_valid only on invalid geometries; shared GEOS engine',
           measurement_note='Planar measures in the source RDC Mercator projection, metres; an invalid pre-repair area is not a validated surface.')

    assert mines.vid.is_unique and mines.vid.notna().all()
    assert mines[['pcode', 'visit_date']].notna().all().all()
    for geometry in ['none', 'exact', 'topological']:
        result = cm.deduplicate(mines, keys=['pcode', 'visit_date'], geometry=geometry, id_field='vid')
        expected = mines.loc[~mines.duplicated(['pcode', 'visit_date'], keep='first')]
        assert_geodataframe_equal(result.data, expected)
        assert len(result.report) == len(mines)
        np.testing.assert_array_equal(result.report.retained_row, np.arange(len(mines)))
        pd.testing.assert_series_equal(result.report.source_id, mines.vid, check_names=False)
        assert result.rejected.empty
        passed('G03 distinct mine visits by site and date: ' + geometry,
               input_features=len(mines), output_features=len(result.data),
               removed_features=len(result.rejected), repeated_site_records=int(mines.duplicated('pcode').sum()),
               criteria={'keys': ['pcode', 'visit_date'], 'geometry': geometry},
               reference='pandas.duplicated on site code and visit date; every distinct dated visit remains')

    wkb = mines.geometry.to_wkb()
    geometry_cases = []
    for geometry in ['exact', 'topological']:
        for keep in ['first', 'last', 'none']:
            result = cm.deduplicate(mines, geometry=geometry, keep=keep, id_field='vid')
            mask = ~wkb.duplicated(keep=False if keep == 'none' else keep)
            assert_geodataframe_equal(result.data, mines.loc[mask])
            assert_geodataframe_equal(result.rejected, mines.loc[~mask])
            assert result.report.retained.tolist() == mask.tolist()
            assert pd.api.types.is_integer_dtype(result.report.source_id.dtype)
            assert pd.api.types.is_integer_dtype(result.report.retained_id.dtype)
            geometry_cases.append({'geometry': geometry, 'keep': keep,
                                   'output_features': len(result.data), 'removed_features': len(result.rejected),
                                   'duplicate_groups': result.summary['duplicate_groups'],
                                   'duplicate_features': result.summary['duplicate_features']})
    passed('G03 geometry-only rules and complete deletion journal', cases=geometry_cases,
           reference='pandas.duplicated on point WKB; exact WKB equality and XY equality coincide for these finite 2D points',
           interpretation='Coincident sites or repeated visits may be legitimate; geometry-only removal is an explicit rule, not a recommended survey cleaning policy.')

    last = cm.deduplicate(mines, keys=['pcode'], order_by='visit_date', keep='last', id_field='vid')
    selected = mines.sort_values('visit_date', kind='stable').drop_duplicates('pcode', keep='last').index
    expected = mines.loc[mines.index.isin(selected)]
    assert_geodataframe_equal(last.data, expected)
    assert len(last.data) == mines.pcode.nunique() == 2403
    assert len(last.rejected) == 1284
    kept = last.report.loc[last.report.retained, 'source_row'].tolist()
    assert kept == expected.index.tolist()
    for record in last.report.itertuples(index=False):
        chosen = mines.iloc[record.retained_row]
        assert record.retained_id == chosen.vid
        assert mines.iloc[record.source_row].pcode == chosen.pcode
    passed('G03 most recent complete visit per site', retained_sites=len(last.data), removed_prior_visits=len(last.rejected),
           missing_worker_counts_retained=int(last.data.workers_numb.isna().sum()),
           reference='pandas stable date sort, drop_duplicates(pcode, keep=last), then source order',
           semantics='Whole original rows retained, including unknown measurements; no cross-date aggregation.')

    paris = paris_raw.to_crs(2154)
    paris_before = paris.copy(deep=True)
    topology = cm.check_topology(paris, id_field='id', rules=['overlaps'], min_area=0.0)
    reference_parts = []
    for i, left in enumerate(paris.geometry):
        for j in range(i + 1, len(paris)):
            right = paris.geometry.iloc[j]
            if left.intersects(right):
                for part in polygons(left.intersection(right)):
                    if part.area > 0:
                        reference_parts.append((i, j, part))
    assert len(topology.report) == len(reference_parts)
    actual_pairs, expected_pairs = defaultdict(list), defaultdict(list)
    for row in topology.report.itertuples(index=False):
        actual_pairs[(int(row.source_row), int(row.source_row_other))].append(row.area_m2)
        assert row.feature_id == paris.id.iloc[row.source_row]
        assert row.feature_id_other == paris.id.iloc[row.source_row_other]
    for i, j, part in reference_parts:
        expected_pairs[(i, j)].append(part.area)
    assert set(actual_pairs) == set(expected_pairs)
    for pair in expected_pairs:
        np.testing.assert_allclose(sorted(actual_pairs[pair]), sorted(expected_pairs[pair]), rtol=1e-12, atol=1e-8)
    assert topology.issues.crs == paris.crs
    np.testing.assert_allclose(topology.issues.area, topology.report.area_m2, rtol=1e-12, atol=1e-8)
    assert_geodataframe_equal(paris, paris_before)
    areas = topology.report.area_m2.to_numpy()
    passed('G02 Paris pairwise overlap audit in EPSG:2154', features=80,
           pairs_checked_by_reference=80*79//2, overlap_pairs=len(actual_pairs), overlap_parts=len(areas),
           pairwise_area_m2=float(areas.sum()),
           minimum_part_area_m2=float(areas.min()) if len(areas) else None,
           maximum_part_area_m2=float(areas.max()) if len(areas) else None,
           reference='Exhaustive loop on all 3160 feature pairs with direct Shapely intersections; same GEOS engine, different candidate enumeration',
           interpretation='Positive shared areas are observations under the exact chosen rule. Tiny slivers and other overlaps require source-resolution and domain review; the report does not declare every overlap a data error.',
           overlap_sum_note='Sum of pairwise overlaps, not unique covered area.',
           summary=topology.summary)

    threshold = cm.check_topology(paris, id_field='id', rules=['overlaps'], min_area=1.0)
    expected_large = [(i, j, part) for i, j, part in reference_parts if part.area > 1.0]
    assert len(threshold.report) == len(expected_large)
    assert (threshold.report.area_m2 > 1.0).all()
    passed('G02 explicit one-square-metre overlap threshold',
           min_area_m2=1.0, overlap_parts=len(threshold.report),
           ignored_small_parts=threshold.summary['ignored_small_parts'],
           threshold_comparison='strictly greater than 1 square metre; does not modify geometries')

    for name, data in [('parks', parks), ('mines', mines), ('paris_raw', paris_raw)]:
        assert_geodataframe_equal(data, originals[name])
    assert all(sha(path) == digest for path, digest in source_hashes.items())
    assert {name: sha(REPO / name) for name in modules} == code_hashes
    passed('Source tables, source file bytes and tested code unchanged throughout validation',
           inputs_checked=3, sha256_source_files_checked=len(source_hashes), tested_modules=len(code_hashes))

    report = {
        'schema': 'cartomize.validation_m08_real.v1',
        'generated_at_utc': datetime.now(timezone.utc).isoformat(),
        'cartomize_version': cm.__version__,
        'repository_head_at_validation': repository_head(),
        'validation_script_sha256': sha(Path(__file__)),
        'code_state': 'Validation of the working implementation; module SHA-256 values identify the exact tested source bytes.',
        'tested_source_sha256': code_hashes,
        'runtime': {'python': platform.python_version(), 'platform': platform.platform(),
                    'packages': {name: metadata.version(name) for name in ['geopandas', 'shapely', 'pandas', 'numpy', 'pyproj', 'pyogrio']},
                    'geos': shapely.geos_version_string},
        'source_repository': 'https://github.com/jorisvandenbossche/geopandas-tutorial',
        'source_commit': provenance['tutorial_commit'],
        'sources': sources,
        'input_dataset_scope': 'Historical external teaching snapshots already used in the project. No current protected-area or mining inventory is claimed. Original data are not committed.',
        'method': 'Independent validation script written for this run; downloaded code was not executed. Geometry comparisons share GeoPandas/GEOS with Cartomize and are integration/consistency checks, not an independent certification of GEOS.',
        'passed': len(checks), 'failed': 0,
        'duration_seconds': round(time.perf_counter() - started, 3),
        'checks': checks,
    }
    destination = output_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    write_report(destination, json.dumps(serial(report), ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    print(json.dumps({'report': str(destination), 'passed': len(checks), 'failed': 0,
                      'seconds': report['duration_seconds']}, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", type=Path, default=Path(".real-project-data/m08"),
                        help="Reusable verified dataset cache (default: .real-project-data/m08)")
    parser.add_argument("--output", type=Path, default=Path("docs/VALIDATION_M08_REAL.json"),
                        help="JSON validation report (default: docs/VALIDATION_M08_REAL.json)")
    args = parser.parse_args()
    root = args.data.expanduser().resolve()
    output = args.output.expanduser().resolve()
    validate(root, output)


if __name__ == "__main__":
    main()
