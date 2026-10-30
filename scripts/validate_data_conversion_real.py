"""Validate G06 against pinned real polygons and Sentinel-2 pixels, offline.

Example, from the repository root::

    python scripts/validate_data_conversion_real.py \
        --data ../g06-validation-data --work ../g06-real-validation \
        --output docs/VALIDATION_G06_REAL.json

The Paris GeoJSON must already be present: this script downloads nothing.
The JSON source is the vector oracle. SQLite/WKB and DBF/SHP are decoded here
without Cartomize or GDAL; FlatGeobuf uses GDAL only to decode the output.
Raster validation compares complete source/output arrays and metadata through
Rasterio; it is not an independent certification of the GDAL TIFF decoder.
The separate analytic fixture exercises custom band metadata and portable PAM
companions. It is never presented as a real satellite observation.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
from importlib import metadata
import json
import math
import os
from pathlib import Path
import platform
import sqlite3
import struct
import subprocess
import sys
import tempfile
import time
import traceback
from xml.etree import ElementTree as ET

import geopandas as gpd
import numpy as np
from pyproj import CRS
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import from_origin


REPO = Path(__file__).resolve().parents[1]
PARIS_URL = ('https://raw.githubusercontent.com/jorisvandenbossche/geopandas-tutorial/'
             '72c7f3168e1e4e257caf84eb7b3fcaa47ade09c0/data/paris_districts.geojson')
PARIS_SHA256 = 'db65faf397e8876e9a62cdb722bc8c0897e9f9e4db4daa5c01a7e7d7883d626b'
MODULES = ('__init__', '_validation', 'imagery', 'raster_conversion', 'session',
           'storage', 'vector_conversion', 'vector_io', 'vector_reprojection')
DERIVED_TAGS = {'IMAGE_STRUCTURE', 'DERIVED_SUBDATASETS', 'SUBDATASETS'}


def digest(path):
    result = sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            result.update(chunk)
    return result.hexdigest()


def module_hashes():
    return {f'src/cartomize/{name}.py': digest(REPO / 'src/cartomize' / (name + '.py'))
            for name in MODULES}


def atomic_report(path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix='.g06-report-', suffix='.json', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as handle:
            json.dump(record, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write('\n')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def sql_name(name):
    return '"' + name.replace('"', '""') + '"'


def tuple_tree(value):
    return tuple(tuple_tree(item) for item in value) if isinstance(value, (list, tuple)) else value


def read_wkb(blob, offset=0):
    """Decode the 2-D Polygon/MultiPolygon WKB used by this pinned source."""
    assert blob[offset] in (0, 1)
    endian = '<' if blob[offset] == 1 else '>'
    kind, = struct.unpack_from(endian + 'I', blob, offset + 1)
    offset += 5
    if kind == 3:
        rings = []
        count, = struct.unpack_from(endian + 'I', blob, offset)
        offset += 4
        for _ in range(count):
            points, = struct.unpack_from(endian + 'I', blob, offset)
            offset += 4
            ring = [struct.unpack_from(endian + 'dd', blob, offset + index * 16)
                    for index in range(points)]
            offset += points * 16
            rings.append(ring)
        return {'type': 'Polygon', 'coordinates': rings}, offset
    if kind == 6:
        count, = struct.unpack_from(endian + 'I', blob, offset)
        offset += 4
        polygons = []
        for _ in range(count):
            polygon, offset = read_wkb(blob, offset)
            assert polygon['type'] == 'Polygon'
            polygons.append(polygon['coordinates'])
        return {'type': 'MultiPolygon', 'coordinates': polygons}, offset
    raise AssertionError(f'Unexpected WKB geometry type {kind}; the oracle is strictly 2-D.')


def gpkg_geometry(blob):
    assert blob[:3] == b'GP\x00'
    flags = blob[3]
    assert flags & 0b11000000 == 0
    envelope = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}[(flags >> 1) & 7]
    geometry, end = read_wkb(blob, 8 + envelope)
    assert end == len(blob), 'Unexamined GeoPackage geometry bytes.'
    return geometry


def normalized_ring(points):
    """Ignore only ring start and direction, without rounding coordinates."""
    points = tuple_tree(points)
    assert len(points) >= 4 and points[0] == points[-1]
    points = points[:-1]
    candidates = []
    for sequence in (points, tuple(reversed(points))):
        first = min(sequence)
        for index, point in enumerate(sequence):
            if point == first:
                candidates.append(sequence[index:] + sequence[:index])
    return min(candidates)


def same_polygon(expected, observed, *, ring_direction=False):
    assert expected['type'] == observed['type'] == 'Polygon'
    before, after = expected['coordinates'], observed['coordinates']
    assert len(before) == len(after)
    if ring_direction:
        assert normalized_ring(before[0]) == normalized_ring(after[0])
        assert sorted(normalized_ring(ring) for ring in before[1:]) == sorted(
            normalized_ring(ring) for ring in after[1:])
    else:
        assert tuple_tree(before) == tuple_tree(after), 'A coordinate, ring or vertex order changed.'


def same_properties(expected, observed, field_map=None):
    field_map = field_map or {}
    expected = {field_map.get(key, key): value for key, value in expected.items()}
    assert set(expected) == set(observed), (set(expected), set(observed))
    for name, value in expected.items():
        actual = observed[name]
        if isinstance(actual, np.generic):
            actual = actual.item()
        assert type(actual) is type(value), (name, type(value).__name__, type(actual).__name__)
        assert actual == value, (name, value, actual)


def vector_counts(features):
    return dict(features=len(features), attributes_checked=sum(len(item['properties']) for item in features),
                coordinates_checked=sum(len(ring) for item in features for ring in item['geometry']['coordinates']))


def check_gpkg(path, reference, expected_crs):
    with sqlite3.connect(path) as connection:
        records = connection.execute('SELECT table_name,column_name,srs_id FROM gpkg_geometry_columns').fetchall()
        assert len(records) == 1
        table, geometry_column, srs_id = records[0]
        schema = connection.execute(f'PRAGMA table_info({sql_name(table)})').fetchall()
        primary = [item[1] for item in schema if item[5]]
        assert len(primary) == 1 and primary[0] not in reference[0]['properties']
        attributes = [item[1] for item in schema if item[1] not in {*primary, geometry_column}]
        assert set(attributes) == set(reference[0]['properties']), (
            'GeoPackage fields changed', list(reference[0]['properties']), attributes)
        types = {item[1]: item[2] for item in schema if item[1] in attributes}
        assert 'INT' in types['id'].upper() and 'INT' in types['population'].upper()
        assert types['district_name'].upper().startswith('TEXT')
        definition, = connection.execute('SELECT definition FROM gpkg_spatial_ref_sys WHERE srs_id=?', (srs_id,)).fetchone()
        assert expected_crs.equals(CRS.from_wkt(definition), ignore_axis_order=True)
        connection.row_factory = sqlite3.Row
        rows = connection.execute(f'SELECT * FROM {sql_name(table)} ORDER BY rowid').fetchall()
    assert len(rows) == len(reference)
    for expected, actual in zip(reference, rows):
        same_properties(expected['properties'], {name: actual[name] for name in attributes})
        same_polygon(expected['geometry'], gpkg_geometry(actual[geometry_column]))
    return dict(**vector_counts(reference), oracle='Original JSON + SQLite + independent GeoPackage/WKB decoder',
                declared_attribute_types=types, all_coordinates_exact=True, row_order_preserved=True, crs_preserved=True)


def check_geojson(path, reference, expected_crs):
    document = json.loads(Path(path).read_text(encoding='utf-8'))
    crs = document.get('crs', {}).get('properties', {}).get('name', 'OGC:CRS84')
    assert expected_crs.equals(CRS.from_user_input(crs), ignore_axis_order=True)
    observed = document['features']
    assert len(observed) == len(reference)
    for before, after in zip(reference, observed):
        same_properties(before['properties'], after['properties'])
        same_polygon(before['geometry'], after['geometry'])
    return dict(**vector_counts(reference), oracle='Python JSON decoder on both files',
                all_scalar_types_exact=True, all_coordinates_exact=True, row_order_preserved=True, crs_preserved=True)


def check_fgb(path, reference, expected_crs):
    frame = gpd.read_file(path)
    assert expected_crs.equals(frame.crs, ignore_axis_order=True)
    assert len(frame) == len(reference)
    fields = [name for name in frame if name != frame.geometry.name]
    assert set(fields) == set(reference[0]['properties']), (
        'FlatGeobuf fields changed', list(reference[0]['properties']), fields)
    assert frame['id'].dtype.kind in 'iu' and frame['population'].dtype.kind in 'iu'
    for index, expected in enumerate(reference):
        same_properties(expected['properties'], {name: frame[name].iloc[index] for name in fields})
        same_polygon(expected['geometry'], frame.geometry.iloc[index].__geo_interface__)
    return dict(**vector_counts(reference), oracle='Original JSON; GDAL decodes only the FlatGeobuf output',
                output_dtypes={name: str(frame[name].dtype) for name in fields},
                all_coordinates_exact=True, row_order_preserved=True, crs_preserved=True)


def read_dbf(path):
    raw = Path(path).read_bytes()
    count, header_size, record_size = struct.unpack_from('<IHH', raw, 4)
    fields = []
    for offset in range(32, header_size - 1, 32):
        descriptor = raw[offset:offset + 32]
        name = descriptor[:11].split(b'\x00', 1)[0].decode('ascii')
        fields.append((name, chr(descriptor[11]), descriptor[16], descriptor[17]))
    assert raw[header_size - 1] == 0x0d
    assert record_size == 1 + sum(field[2] for field in fields)
    records = []
    for index in range(count):
        start = header_size + index * record_size
        assert raw[start:start + 1] == b' ', 'A DBF record is marked as deleted.'
        offset, record = start + 1, {}
        for name, kind, width, decimals in fields:
            value = raw[offset:offset + width]
            offset += width
            if kind == 'C':
                record[name] = value.decode('utf-8').rstrip(' ')
            elif kind in {'N', 'F'}:
                record[name] = int(value) if decimals == 0 else float(value)
            else:
                raise AssertionError(f'Unexpected DBF field type {kind}.')
        records.append(record)
    return records, fields


def read_shp(path):
    raw = Path(path).read_bytes()
    assert struct.unpack_from('>i', raw)[0] == 9994
    assert struct.unpack_from('>i', raw, 24)[0] * 2 == len(raw)
    assert struct.unpack_from('<i', raw, 32)[0] == 5
    offset, records = 100, []
    while offset < len(raw):
        number, words = struct.unpack_from('>ii', raw, offset)
        assert number == len(records) + 1
        offset += 8
        stop = offset + words * 2
        assert struct.unpack_from('<i', raw, offset)[0] == 5
        parts, points = struct.unpack_from('<ii', raw, offset + 36)
        indices = list(struct.unpack_from('<' + 'i' * parts, raw, offset + 44)) + [points]
        start = offset + 44 + 4 * parts
        xy = [struct.unpack_from('<dd', raw, start + index * 16) for index in range(points)]
        assert start + 16 * points == stop
        records.append(dict(type='Polygon', coordinates=[xy[a:b] for a, b in zip(indices, indices[1:])]))
        offset = stop
    return records


def check_shapefile(path, reference, expected_crs, mapping):
    properties, schema = read_dbf(Path(path).with_suffix('.dbf'))
    geometries = read_shp(path)
    assert len(properties) == len(geometries) == len(reference)
    assert [(name, kind, decimals) for name, kind, _, decimals in schema] == [
        ('id', 'N', 0), ('district', 'C', 0), ('population', 'N', 0)], ('DBF schema changed', schema)
    crs = CRS.from_wkt(Path(path).with_suffix('.prj').read_text())
    assert expected_crs.equals(crs, ignore_axis_order=True)
    assert Path(path).with_suffix('.cpg').read_text().strip().casefold() == 'utf-8'
    changed_rings = 0
    for expected, attributes, geometry in zip(reference, properties, geometries):
        same_properties(expected['properties'], attributes, mapping)
        same_polygon(expected['geometry'], geometry, ring_direction=True)
        changed_rings += int(tuple_tree(expected['geometry']['coordinates']) != tuple_tree(geometry['coordinates']))
    return dict(**vector_counts(reference), oracle='Original JSON + independent DBF/SHP binary decoders',
                field_map=mapping, encoding='UTF-8', all_attribute_types_and_values_exact=True,
                all_coordinate_values_exact=True, allowed_change='Polygon ring direction/start only',
                polygons_with_ring_representation_changed=changed_rings, row_order_preserved=True, crs_preserved=True)


def raster_snapshot(path):
    with rasterio.open(path) as source:
        tags = []
        for band in (0, *source.indexes):
            for namespace in (None, *source.tag_namespaces(band)):
                if namespace in DERIVED_TAGS:
                    continue
                values = source.tags(band, ns=namespace)
                if values:
                    tags.append((band, namespace, values))
        return dict(values=source.read(), masks=source.read_masks(), crs=source.crs,
                    transform=source.transform, width=source.width, height=source.height,
                    count=source.count, dtypes=source.dtypes, nodata=source.nodata,
                    descriptions=source.descriptions, scales=source.scales, offsets=source.offsets,
                    units=source.units, colors=source.colorinterp, tags=tags,
                    overviews=[source.overviews(band) for band in source.indexes])


def check_raster(expected, path, *, driver, dtype=None, nodata='preserve', compression='lzw'):
    wanted_nodata = expected['nodata'] if nodata == 'preserve' else nodata
    if wanted_nodata == 'nan':
        wanted_nodata = math.nan
    with rasterio.open(path) as actual:
        assert (actual.width, actual.height, actual.count) == (expected['width'], expected['height'], expected['count'])
        assert actual.crs == expected['crs'] and actual.transform == expected['transform']
        assert actual.dtypes == ((dtype,) * actual.count if dtype else expected['dtypes'])
        if isinstance(wanted_nodata, float) and math.isnan(wanted_nodata):
            assert math.isnan(actual.nodata)
        else:
            assert actual.nodata == wanted_nodata
        values, masks = actual.read(), actual.read_masks()
        np.testing.assert_array_equal(masks, expected['masks'])
        valid = expected['masks'] != 0
        np.testing.assert_array_equal(values[valid], expected['values'][valid])
        if nodata == 'preserve':
            np.testing.assert_array_equal(values, expected['values'])
        elif wanted_nodata is not None and np.any(~valid):
            assert np.isnan(values[~valid]).all() if math.isnan(wanted_nodata) else np.all(values[~valid] == wanted_nodata)
        for attribute, key in [('descriptions', 'descriptions'), ('scales', 'scales'),
                               ('offsets', 'offsets'), ('units', 'units'), ('colorinterp', 'colors')]:
            assert getattr(actual, attribute) == expected[key], attribute
        for band, namespace, tags in expected['tags']:
            observed = actual.tags(band, ns=namespace)
            assert all(observed.get(key) == value for key, value in tags.items()), (band, namespace, tags, observed)
        assert [actual.overviews(band) for band in actual.indexes] == expected['overviews']
        observed_compression = actual.compression.name.lower() if actual.compression else 'none'
        assert observed_compression == compression
        if driver == 'COG':
            assert actual.tags(ns='IMAGE_STRUCTURE').get('LAYOUT') == 'COG'
        details = dict(pixel_values_checked=int(values.size), valid_values_checked=int(valid.sum()),
            masks_checked=int(masks.size), all_valid_values_exact=True, masks_exact=True,
            grid_exact=True, metadata_preserved=True, output_dtype=list(actual.dtypes),
            output_nodata='nan' if isinstance(actual.nodata, float) and math.isnan(actual.nodata) else actual.nodata,
            compression=observed_compression, driver=driver,
            oracle='Full source arrays and metadata; independent NumPy comparisons; shared GDAL TIFF decoder')
    return details


def validate(data, work, output):
    if not __debug__:
        raise RuntimeError('Run without Python -O; validation assertions must remain enabled.')
    source = data / 'paris_districts.geojson' if data.is_dir() else data
    fixtures = REPO / 'tests/data/sentinel2_mvouti'
    if output == source or output.is_relative_to(fixtures):
        raise ValueError('The report must not overwrite input data.')
    work.mkdir(parents=True, exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix='run-', dir=work))
    os.environ.setdefault('MPLCONFIGDIR', str(work / 'matplotlib-cache'))
    sys.path.insert(0, str(REPO / 'src'))
    import cartomize as cm
    from cartomize.session import load_session, save_session

    started = time.perf_counter()
    code_before = module_hashes()
    files = [source, fixtures / 'README.md', fixtures / 'provenance.json',
             *(fixtures / (name + '.tif') for name in ('red', 'nir', 'scl'))]
    before = {str(path): digest(path) for path in files}
    provenance = json.loads((fixtures / 'provenance.json').read_text())
    document = json.loads(source.read_text(encoding='utf-8'))
    reference = document['features']
    expected_crs = CRS.from_user_input(document['crs']['properties']['name'])
    try:
        head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        head = None
    report = dict(schema='cartomize.validation_g06_real.v1', generated_at_utc=datetime.now(timezone.utc).isoformat(),
        cartomize_version=cm.__version__, repository_head_at_validation=head,
        code_state='Module hashes identify the tested working sources; HEAD may precede uncommitted implementation.',
        validation_script_sha256=digest(Path(__file__)), tested_source_sha256=code_before,
        runtime=dict(python=platform.python_version(), platform=platform.platform(), gdal=rasterio.__gdal_version__,
            packages={name: metadata.version(name) for name in ('geopandas', 'pyogrio', 'shapely', 'numpy', 'pyproj', 'rasterio')}),
        sources=[dict(name='Paris districts', url=PARIS_URL, expected_sha256=PARIS_SHA256,
                      local_file=str(source), scope='Pinned historical teaching snapshot; 80 real district polygons.'),
                 dict(name='Sentinel-2 Mayombe', item_url=provenance['source_item'],
                      attribution=provenance['attribution'], license=provenance['license'],
                      provenance_file='tests/data/sentinel2_mvouti/provenance.json',
                      assets={name: {key: provenance['assets'][name][key] for key in ('href', 'source_window', 'sha256')}
                              for name in ('red', 'nir', 'scl')},
                      scope='Unresampled native integer cutouts. No recalibration or land-cover accuracy claim.')],
        source_sha256_before=before, output_directory=str(run), downloaded_files=0,
        method='Original JSON properties/coordinates, independent SQLite/WKB and DBF/SHP decoding, full raster-array comparison; no pass relies solely on a Cartomize summary.',
        analytic_fixture='Separate deterministic 64x64 raster with one NoData sample, custom dataset/band metadata and two overview levels.',
        checks=[], passed=0, failed=0)

    def check(name, function):
        try:
            details = function()
            report['checks'].append(dict(name=name, status='passed', **details))
            report['passed'] += 1
        except Exception as exc:
            report['checks'].append(dict(name=name, status='failed', error_type=type(exc).__name__,
                                         message=str(exc), traceback=traceback.format_exc()))
            report['failed'] += 1

    def inputs():
        assert before[str(source)] == PARIS_SHA256
        assert len(reference) == 80 and [item['properties']['id'] for item in reference] == list(range(1, 81))
        assert all(item['geometry']['type'] == 'Polygon' for item in reference)
        assert expected_crs.equals(CRS.from_epsg(4326), ignore_axis_order=True)
        for name in ('red', 'nir', 'scl'):
            assert before[str(fixtures / (name + '.tif'))] == provenance['assets'][name]['sha256']
        with rasterio.open(fixtures / 'scl.tif') as src:
            counts = Counter(map(int, src.read(1).ravel()))
            assert {str(key): value for key, value in sorted(counts.items())} == provenance['scl_counts']
        return dict(**vector_counts(reference), pinned_files_verified=4, source_crs='OGC:CRS84',
                    scl_class_counts={str(key): value for key, value in sorted(counts.items())})

    check('Pinned source hashes, original IDs and Sentinel provenance', inputs)

    def vector(driver, label, verify, **options):
        result = cm.convert_vector(source, run / label, driver=driver, **options)
        details = verify(result.data)
        details['driver'] = driver
        details['output'] = str(result.data)
        details['output_sha256'] = digest(result.data)
        return details

    check('Paris -> GeoPackage: SQLite fields, scalar types and WKB coordinates',
          lambda: vector('GPKG', 'paris_gpkg', lambda path: check_gpkg(path, reference, expected_crs)))
    check('Paris -> GeoJSON: every JSON scalar, coordinate and row',
          lambda: vector('GeoJSON', 'paris_geojson', lambda path: check_geojson(path, reference, expected_crs)))
    check('Paris -> FlatGeobuf: all records against the original JSON oracle',
          lambda: vector('FlatGeobuf', 'paris_fgb', lambda path: check_fgb(path, reference, expected_crs)))
    field_map = {'district_name': 'district'}
    check('Paris -> adapted Shapefile: independent DBF/SHP and explicit ring representation policy',
          lambda: vector('ESRI Shapefile', 'paris_shapefile',
                         lambda path: check_shapefile(path, reference, expected_crs, field_map),
                         field_map=field_map, encoding='UTF-8', loss_policy='report'))

    def raster(name, label, **parameters):
        path = fixtures / (name + '.tif')
        expected = raster_snapshot(path)
        result = cm.convert_raster(path, run / label, **parameters)
        details = check_raster(expected, result.data, **parameters)
        details.update(source_band=name, output=str(result.data), output_sha256=digest(result.data))
        return details

    check('Real Sentinel red -> GeoTIFF: every pixel, mask and grid element',
          lambda: raster('red', 'sentinel_red_gtiff', driver='GTiff', compression='deflate'))
    check('Real Sentinel NIR -> COG: every pixel, mask and metadata value',
          lambda: raster('nir', 'sentinel_nir_cog', driver='COG', compression='lzw'))
    check('Real Sentinel SCL -> uint16 COG with NoData=65535: exact class conservation',
          lambda: raster('scl', 'sentinel_scl_cog', driver='COG', dtype='uint16', nodata=65535, compression='deflate'))
    check('Real Sentinel red -> float32 GeoTIFF with NaN NoData: exact valid values',
          lambda: raster('red', 'sentinel_red_float', driver='GTiff', dtype='float32', nodata='nan', compression='lzw'))

    analytic = {}

    def pam():
        case = run / 'analytic_pam'
        case.mkdir()
        path = case / 'source.tif'
        values = np.arange(4096, dtype='int16').reshape(64, 64)
        values[0, 0] = -9999
        with rasterio.open(path, 'w', driver='GTiff', width=64, height=64, count=1,
                           dtype='int16', nodata=-9999, crs='EPSG:32733',
                           transform=from_origin(500000, 9500000, 10, 10)) as dataset:
            dataset.write(values, 1)
            dataset.set_band_description(1, 'Analytic G06 metadata fixture')
            dataset.set_band_unit(1, 'm')
            dataset.scales, dataset.offsets = (.25,), (-10.,)
            dataset.update_tags(validation='analytic; not satellite observations')
            dataset.update_tags(1, sensor='G06 analytic sensor')
            dataset.update_tags(1, ns='VALIDATION_BAND', verification_anchor='PAM-survives-portable-session', label='Métadonnées préservées')
            dataset.update_tags(ns='VALIDATION_GLOBAL', source='deterministic NumPy arange')
            dataset.build_overviews([2, 4], Resampling.nearest)
        expected = raster_snapshot(path)
        result = cm.convert_raster(path, case / 'delivery', driver='COG')
        details = check_raster(expected, result.data, driver='COG')
        sidecar = Path(str(result.data) + '.aux.xml')
        assert sidecar.is_file(), 'This run did not exercise a PAM companion; no PAM claim is allowed.'
        tree = ET.parse(sidecar).getroot()
        tags = {(node.get('domain'), item.get('key')): item.text
                for node in tree.findall("./PAMRasterBand[@band='1']/Metadata") for item in node.findall('MDI')}
        # Current GDAL keeps the named band domain inside the TIFF but omits
        # this ordinary band tag during the COG copy. Check the tag that the
        # actual sidecar supplies, as well as every source tag above.
        assert tags.get((None, 'sensor')) == 'G06 analytic sensor'
        manifest = json.loads(result.manifest.read_text())
        assert str(sidecar) in manifest['files']
        analytic.update(case=case, source=path, result=result, snapshot=expected,
                        source_sha256=digest(path), sidecar_sha256=digest(sidecar))
        return dict(**details, fixture_type='analytic', pam_companion=str(sidecar),
                    pam_band_metadata_parsed_independently=True, pam_band_tag={'sensor': 'G06 analytic sensor'},
                    sidecar_declared_in_manifest=True,
                    original_analytic_sha256=analytic['source_sha256'])

    check('Analytic COG: custom band metadata requires and survives a declared PAM companion', pam)

    def portable():
        assert analytic, 'The analytic COG/PAM prerequisite failed.'
        result = analytic['result']
        archive = save_session(dict(data=str(result.data), manifest=str(result.manifest), report=str(result.report)),
                               run / 'portable_cog.cmz', portable=True)
        retired = run / 'analytic_original_retired'
        analytic['case'].rename(retired)
        assert not result.data.exists() and not analytic['source'].exists()
        loaded = load_session(archive, directory=run / 'portable_restored')
        assert not loaded.missing, loaded.missing
        restored = Path(loaded.state['data'])
        assert restored.is_relative_to(loaded.directory) and restored != result.data
        sidecar = Path(str(restored) + '.aux.xml')
        assert sidecar.is_file() and digest(sidecar) == analytic['sidecar_sha256']
        details = check_raster(analytic['snapshot'], restored, driver='COG')
        manifest = json.loads(Path(loaded.state['manifest']).read_text())
        assert all(Path(path).is_file() for path in manifest['files'])
        assert digest(retired / 'source.tif') == analytic['source_sha256']
        return dict(**details, fixture_type='analytic', original_paths_unavailable=True,
                    portable_archive=str(archive), restored_data=str(restored),
                    colocated_pam_exact=True, all_manifest_files_present=True, missing_dependencies=[])

    check('Portable COG/PAM: reopen after the original source and delivery paths are retired', portable)

    def immutable():
        after = {str(path): digest(path) for path in files}
        report['source_sha256_after'] = after
        assert after == before, 'An original input changed.'
        current = module_hashes()
        report['tested_source_sha256_after'] = current
        assert current == code_before, 'A tested module changed during validation.'
        return dict(input_files=len(before), input_bytes_unchanged=True, tested_modules=len(code_before),
                    tested_modules_unchanged=True, network_downloads=0)

    check('All original inputs and tested application modules remain byte-identical', immutable)
    report['status'] = 'passed' if report['failed'] == 0 else 'failed'
    report['duration_seconds'] = round(time.perf_counter() - started, 3)
    atomic_report(output, report)
    print(json.dumps({key: report[key] for key in ('status', 'passed', 'failed', 'duration_seconds')}, ensure_ascii=False))
    for item in report['checks']:
        if item['status'] == 'failed':
            print(json.dumps(item, ensure_ascii=False))
    return 0 if report['failed'] == 0 else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True, help='Existing Paris GeoJSON or its containing directory.')
    parser.add_argument('--work', type=Path, default=REPO.parent / 'g06-real-validation',
                        help='Directory outside the repository for retained validation products.')
    parser.add_argument('--output', type=Path, required=True, help='JSON validation report.')
    args = parser.parse_args()
    return validate(args.data.expanduser().resolve(), args.work.expanduser().resolve(), args.output.expanduser().resolve())


if __name__ == '__main__':
    raise SystemExit(main())
