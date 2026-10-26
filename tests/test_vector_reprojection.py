"""Independent coordinates and transactional guarantees for G04 batch reprojection.

The numeric references below are analytic or published PROJ examples, rather
than values obtained by calling the implementation a second time.
"""
import json
import math
from pathlib import Path
import sqlite3
import struct
from threading import Event

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import CRS
import pytest
import shapely
from shapely.geometry import GeometryCollection, LinearRing, LineString, MultiPolygon, Point, Polygon, box

from cartomize.algebra import ProcessingCancelled
import cartomize.vector_reprojection as reprojection


def frame(geometries, crs=4326, **attributes):
    return gpd.GeoDataFrame(attributes, geometry=geometries, crs=crs)


def only_output(result):
    assert Path(result.manifest).is_file()
    assert Path(result.report).is_file()
    assert len(result.layers) == 1
    return gpd.read_file(next(iter(result.layers.values())))


def mercator(lon, lat):
    """EPSG:3857 spherical formula, PROJ webmerc documentation."""
    radius = 6378137.0
    return (radius * math.radians(lon),
            radius * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)))


def assert_nothing_published(destination):
    assert not destination.exists()
    assert not list(destination.parent.glob('.cartomize-*'))


def test_mercator_matches_independent_formula_and_preserves_source_and_attributes(tmp_path):
    coordinates = [(0, 0), (15, -4), (33, 45), (-73.9857, 40.7484)]
    source = frame([Point(*xy) for xy in coordinates],
                   fid=[8, 8, 8, 8], identifier=[2**60 + i for i in range(4)],
                   code=['001', '002', '003', '004'])
    original = source.copy(deep=True)
    result = reprojection.reproject_batch(source, tmp_path / 'mercator', 3857)
    output = only_output(result)
    expected = np.asarray([mercator(*xy) for xy in coordinates])
    np.testing.assert_allclose(np.column_stack([output.geometry.x, output.geometry.y]),
                               expected, rtol=0, atol=1e-6)
    assert CRS(output.crs).equals(CRS(3857))
    assert output.identifier.tolist() == original.identifier.tolist()
    assert output.fid.tolist() == original.fid.tolist()
    assert output.code.tolist() == original.code.tolist()
    assert source.geometry.to_wkb().tolist() == original.geometry.to_wkb().tolist()
    assert source.crs == original.crs
    pd.testing.assert_frame_equal(pd.DataFrame(source.drop(columns='geometry')),
                                  pd.DataFrame(original.drop(columns='geometry')))
    report = json.loads(Path(result.manifest).read_text(encoding='utf-8'))['layers'][0]
    np.testing.assert_allclose(report['target_bounds'],
                               [expected[:, 0].min(), expected[:, 1].min(),
                                expected[:, 0].max(), expected[:, 1].max()], rtol=0, atol=1e-6)
    assert report['source_crs_wkt'] and report['operation']['definition']
    assert report['features'] == len(source)


@pytest.mark.parametrize('target,coordinates,expected', [
    (32633, (15, 0), (500000.0, 0.0)),
    (32733, (15, 0), (500000.0, 10000000.0)),
    # https://proj.org/en/stable/operations/projections/utm.html
    (32632, (12, 56), (687071.44, 6210141.33)),
    (32759, (174, -44), (740526.32, 5123750.87)),
])
def test_utm_axis_order_hemisphere_and_official_reference_points(tmp_path, target, coordinates, expected):
    output = only_output(reprojection.reproject_batch(
        frame([Point(*coordinates)]), tmp_path / f'utm_{target}', target))
    np.testing.assert_allclose(output.geometry.iloc[0].coords[0], expected, rtol=0, atol=0.01)


def test_geographic_grades_and_paris_prime_meridian_are_not_assumed_to_be_degrees(tmp_path):
    # NTF (Paris), in grads, to the same NTF datum relative to Greenwich.
    source = frame([Point(0, 50), Point(3, 52)], crs=4807)
    output = only_output(reprojection.reproject_batch(source, tmp_path / 'paris', 4275))
    expected = np.asarray([(2.337229166666667, 45), (5.037229166666667, 46.8)])
    np.testing.assert_allclose(np.column_stack([output.geometry.x, output.geometry.y]),
                               expected, rtol=0, atol=1e-8)
    entry = reprojection.inspect_reprojection(source, 4275)['layers'][0]
    np.testing.assert_allclose(entry['bounds'], [0, 50, 3, 52], rtol=0, atol=0)
    # AOI is in Greenwich degrees. A datum conversion to WGS 84 may move its
    # outline by hundreds of metres; it must not retain grad/Paris coordinates.
    np.testing.assert_allclose(entry['geographic_bounds'],
                               [2.337229166666667, 45, 5.037229166666667, 46.8],
                               rtol=0, atol=0.01)


def test_accuracy_filter_keeps_a_pure_conversion_without_misreporting_accuracy(tmp_path):
    result = reprojection.reproject_batch(frame([Point(15, -4)]), tmp_path / 'accuracy',
                                          3857, accuracy=0.01)
    np.testing.assert_allclose(only_output(result).geometry.iloc[0].coords[0], mercator(15, -4),
                               rtol=0, atol=1e-6)
    operation = result.summary['layers'][0]['operation']
    assert operation['accuracy'] is None or operation['accuracy'] >= 0
    assert not operation['ballpark']


def test_directory_discovers_all_spatial_layers_and_recursion_is_explicit(tmp_path):
    inputs = tmp_path / 'inputs'; inputs.mkdir()
    package = inputs / 'mixed.gpkg'
    frame([Point(15, -4)], code=['geographic']).to_file(package, layer='geographic', index=False)
    frame([Point(*mercator(15, -4))], crs=3857, code=['projected']).to_file(
        package, layer='projected', index=False)
    frame([Point(15.5, -4.5)], code=['other']).to_file(inputs / 'other.geojson', index=False)
    (inputs / 'notes.txt').write_text('Not a spatial layer.', encoding='utf-8')
    child = inputs / 'nested'; child.mkdir()
    frame([Point(16, -5)], code=['nested']).to_file(child / 'deep.gpkg', index=False)

    shallow = reprojection.discover_vector_layers(inputs)
    recursive = reprojection.discover_vector_layers(inputs, recursive=True)
    assert len(shallow) == 3
    assert len(recursive) == 4
    assert len({layer['id'] for layer in recursive}) == 4
    assert [layer['id'] for layer in recursive] == [
        layer['id'] for layer in reprojection.discover_vector_layers(inputs, recursive=True)]
    selected = reprojection.discover_vector_layers({'path': str(package), 'layer': 'projected'})
    assert len(selected) == 1
    assert selected[0]['layer'] == 'projected'

    before = {p: p.read_bytes() for p in inputs.rglob('*') if p.is_file()}
    result = reprojection.reproject_batch(inputs, tmp_path / 'batch', 4326)
    assert len(result.layers) == 3
    records = {gpd.read_file(path).code.iloc[0]: gpd.read_file(path)
               for path in result.layers.values()}
    for name in ('geographic', 'projected'):
        np.testing.assert_allclose(records[name].geometry.iloc[0].coords[0], [15, -4],
                                   rtol=0, atol=1e-8)
    for path, content in before.items():
        assert path.read_bytes() == content


def test_catalogue_identifies_exact_operation_and_explicit_choice_matches_auto(tmp_path):
    source = frame([Point(15, -4)])
    catalogue = reprojection.inspect_reprojection(source, 3857)
    assert len(catalogue['layers']) == 1
    layer = catalogue['layers'][0]
    operations = layer['catalogue']['operations']
    assert operations and layer['catalogue']['best_available']
    selected = operations[0]
    assert selected['id'] and selected['description'] and selected['definition']
    assert selected['ballpark'] is False
    assert selected['accuracy'] is None or selected['accuracy'] >= 0
    automatic = only_output(reprojection.reproject_batch(source, tmp_path / 'automatic', 3857))
    explicit = only_output(reprojection.reproject_batch(
        source, tmp_path / 'explicit', 3857, operations={layer['id']: selected['id']}))
    np.testing.assert_allclose(shapely.get_coordinates(automatic.geometry),
                               shapely.get_coordinates(explicit.geometry), rtol=0, atol=0)
    with pytest.raises(ValueError):
        reprojection.reproject_batch(source, tmp_path / 'unknown', 3857,
                                     operations={layer['id']: 'operation-that-does-not-exist'})
    assert_nothing_published(tmp_path / 'unknown')


def test_equal_filenames_in_different_directories_do_not_overwrite_each_other(tmp_path):
    sources = []
    for position, directory in enumerate(['first', 'second']):
        parent = tmp_path / directory; parent.mkdir()
        source = parent / 'points.gpkg'
        frame([Point(15 + position, -4)], code=[directory]).to_file(source, layer='points', index=False)
        sources.append(source)
    discovered = reprojection.discover_vector_layers(sources)
    assert len({layer['id'] for layer in discovered}) == 2
    result = reprojection.reproject_batch(sources, tmp_path / 'same_names', 3857)
    assert len(result.layers) == len(set(result.layers.values())) == 2
    assert {gpd.read_file(path).code.iloc[0] for path in result.layers.values()} == {'first', 'second'}


def test_missing_empty_and_z_are_preserved_without_inventing_a_vertical_transformation(tmp_path):
    source = frame([Point(15, -4, 127.25), None, Point(), Point(16, -5)],
                   code=['elevation', 'missing', 'empty', 'plain'])
    output = only_output(reprojection.reproject_batch(source, tmp_path / 'z', 3857))
    assert output.code.tolist() == source.code.tolist()
    assert output.geometry.iloc[0].z == 127.25
    assert output.geometry.iloc[1] is None
    assert output.geometry.iloc[2].is_empty
    np.testing.assert_allclose(output.geometry.iloc[0].coords[0][:2], mercator(15, -4),
                               rtol=0, atol=1e-6)
    assert source.geometry.iloc[0].z == 127.25


def test_polygon_rings_are_transformed_without_changing_attributes(tmp_path):
    polygon = Polygon([(14, -5), (16, -5), (16, -3), (14, -3)],
                      holes=[[(14.5, -4.5), (15, -4.5), (15, -4), (14.5, -4)]])
    source = frame([polygon], code=['with_hole'])
    output = only_output(reprojection.reproject_batch(source, tmp_path / 'polygon', 3857))
    transformed = output.geometry.iloc[0]
    assert transformed.is_valid
    assert len(transformed.interiors) == 1
    np.testing.assert_allclose(transformed.exterior.coords,
                               [mercator(*xy) for xy in polygon.exterior.coords], rtol=0, atol=1e-6)
    np.testing.assert_allclose(transformed.interiors[0].coords,
                               [mercator(*xy) for xy in polygon.interiors[0].coords], rtol=0, atol=1e-6)


def test_polygon_and_multipolygon_remain_their_original_types_in_one_output_layer(tmp_path):
    single = box(14, -5, 15, -4)
    multiple = MultiPolygon([box(16, -5, 17, -4), box(16, -3, 17, -2)])
    source = frame([single, multiple], code=['single', 'multiple'])
    output = only_output(reprojection.reproject_batch(source, tmp_path / 'mixed_polygon_types', 3857))
    assert output.geom_type.tolist() == ['Polygon', 'MultiPolygon']
    assert output.code.tolist() == source.code.tolist()
    assert len(output.geometry.iloc[1].geoms) == 2
    np.testing.assert_allclose(shapely.get_coordinates(output.geometry),
                               [mercator(*xy) for xy in shapely.get_coordinates(source.geometry)],
                               rtol=0, atol=1e-6)


def test_geometry_collection_with_mixed_dimensions_cannot_acquire_fabricated_z(tmp_path):
    collection = GeometryCollection([Point(15, -4), Point(16, -5, 123.25)])
    source = frame([collection], code=['mixed_dimensions'])
    before = collection.wkb
    with pytest.raises(ValueError):
        reprojection.reproject_batch(source, tmp_path / 'mixed_dimensions', 3857)
    assert source.geometry.iloc[0].wkb == before
    assert_nothing_published(tmp_path / 'mixed_dimensions')


@pytest.mark.parametrize('in_collection', [False, True])
def test_standalone_linear_ring_is_rejected_before_reaching_gdal(tmp_path, monkeypatch, in_collection):
    ring = LinearRing([(14, -5), (15, -5), (15, -4), (14, -5)])
    geometry = GeometryCollection([ring]) if in_collection else ring
    source = frame([geometry])
    def forbidden_writer(*args, **kwargs):
        pytest.fail('Unsupported standalone LinearRing reached the native GDAL writer.')
    # Some GDAL builds can crash on a standalone LinearRing; prevent that path
    # even if a future regression removes the preflight validation.
    monkeypatch.setattr(gpd.GeoDataFrame, 'to_file', forbidden_writer)
    with pytest.raises(ValueError):
        reprojection.reproject_batch(source, tmp_path / 'linear_ring', 3857)
    assert source.geometry.iloc[0].wkb == geometry.wkb
    assert_nothing_published(tmp_path / 'linear_ring')


@pytest.mark.parametrize('coordinate', [(math.nan, 0), (math.inf, 0), (0, 91)])
def test_nonfinite_and_invalid_geographic_coordinates_fail_atomically(tmp_path, coordinate):
    with pytest.raises(ValueError):
        reprojection.reproject_batch(frame([Point(*coordinate)]), tmp_path / 'invalid', 3857)
    assert_nothing_published(tmp_path / 'invalid')


def test_target_area_of_use_is_checked_even_when_projection_returns_finite_coordinates(tmp_path):
    # PROJ can return a very large but finite northing at the Mercator pole.
    source = frame([Point(0, 90)])
    with pytest.raises(ValueError):
        reprojection.reproject_batch(source, tmp_path / 'pole', 3857)
    assert_nothing_published(tmp_path / 'pole')


def test_line_ending_at_antimeridian_is_continuous_and_not_mistaken_for_a_crossing(tmp_path):
    source = frame([LineString([(179, 0), (180, 0)])])
    output = only_output(reprojection.reproject_batch(source, tmp_path / 'dateline_endpoint', 3857))
    np.testing.assert_allclose(output.geometry.iloc[0].coords,
                               [mercator(179, 0), mercator(180, 0)], rtol=0, atol=1e-6)


def test_actual_antimeridian_crossing_requires_explicit_split(tmp_path):
    source = frame([LineString([(179, 0), (-179, 0)])])
    with pytest.raises(ValueError, match='antimeridian'):
        reprojection.reproject_batch(source, tmp_path / 'dateline_crossing', 3857)
    assert_nothing_published(tmp_path / 'dateline_crossing')


@pytest.mark.parametrize('longitude', [180, -180])
def test_equivalent_antimeridian_point_belongs_to_utm60_boundary(tmp_path, longitude):
    output = only_output(reprojection.reproject_batch(
        frame([Point(longitude, 1)]), tmp_path / 'utm60_boundary', 32660))
    assert np.isfinite(shapely.get_coordinates(output.geometry)).all()


def test_area_warning_policy_is_explicit_and_keeps_a_trace(tmp_path):
    source = frame([Point(30, -4)])  # Outside UTM 33S's area, still computable.
    with pytest.raises(ValueError):
        reprojection.reproject_batch(source, tmp_path / 'outside', 32733)
    assert_nothing_published(tmp_path / 'outside')
    result = reprojection.reproject_batch(source, tmp_path / 'accepted', 32733, area_policy='warn')
    assert np.isfinite(shapely.get_coordinates(only_output(result).geometry)).all()
    manifest = json.loads(Path(result.manifest).read_text(encoding='utf-8'))
    def warnings(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == 'warnings' and item:
                    yield item
                yield from warnings(item)
        elif isinstance(value, list):
            for item in value:
                yield from warnings(item)
    assert list(warnings(manifest)), 'Explicit out-of-area use must leave a nonempty warning.'


def test_ballpark_datum_change_requires_explicit_acceptance_and_is_labelled(tmp_path):
    # This unnamed datum has no registered datum transformation to WGS 84.
    source = frame([Point(15, -4)], crs='+proj=longlat +ellps=clrk66 +type=crs')
    with pytest.raises(ValueError):
        reprojection.reproject_batch(source, tmp_path / 'ballpark_refused', 4326)
    assert_nothing_published(tmp_path / 'ballpark_refused')
    catalogue = reprojection.inspect_reprojection(source, 4326, allow_ballpark=True)
    operations = catalogue['layers'][0]['catalogue']['operations']
    assert operations and all(operation['ballpark'] for operation in operations)
    result = reprojection.reproject_batch(source, tmp_path / 'ballpark_accepted', 4326,
                                          allow_ballpark=True)
    output = only_output(result)
    np.testing.assert_allclose(output.geometry.iloc[0].coords[0], [15, -4], rtol=0, atol=1e-10)
    assert all(operation['accuracy'] is None for operation in operations)


def test_missing_preferred_grid_blocks_publication_until_alternative_is_explicitly_allowed(tmp_path, monkeypatch):
    original_options = reprojection._options
    def missing_preferred_grid(*args, **kwargs):
        group, catalogue = original_options(*args, **kwargs)
        catalogue['best_available'] = False
        catalogue['unavailable_operations'] = [{
            'name': 'Preferred test datum operation', 'accuracy': 0.1,
            'area_of_use': None,
            'grids': [{'name': 'required_test_grid.tif', 'available': False,
                       'url': 'https://example.invalid/required_test_grid.tif',
                       'direct_download': False, 'open_license': True}],
        }]
        catalogue['warnings'] = ['Preferred operation requires required_test_grid.tif.']
        return group, catalogue
    monkeypatch.setattr(reprojection, '_options', missing_preferred_grid)
    source = frame([Point(15, -4)])
    inspection = reprojection.inspect_reprojection(source, 3857)
    catalogue = inspection['layers'][0]['catalogue']
    assert catalogue['best_available'] is False
    assert catalogue['unavailable_operations'][0]['grids'][0]['name'] == 'required_test_grid.tif'
    with pytest.raises(ValueError, match='required_test_grid'):
        reprojection.reproject_batch(source, tmp_path / 'grid_refused', 3857)
    assert_nothing_published(tmp_path / 'grid_refused')
    result = reprojection.reproject_batch(source, tmp_path / 'grid_alternative', 3857,
                                          require_best=False)
    np.testing.assert_allclose(only_output(result).geometry.iloc[0].coords[0], mercator(15, -4),
                               rtol=0, atol=1e-6)
    report = json.loads(Path(result.manifest).read_text(encoding='utf-8'))['layers'][0]
    assert report['best_available'] is False
    assert report['warnings']
    assert report['unavailable_operations'] == catalogue['unavailable_operations']


def test_permissive_grid_policy_never_substitutes_for_an_explicit_missing_operation(tmp_path, monkeypatch):
    original_options = reprojection._options
    def missing_preferred_grid(*args, **kwargs):
        group, catalogue = original_options(*args, **kwargs)
        catalogue['best_available'] = False
        return group, catalogue
    monkeypatch.setattr(reprojection, '_options', missing_preferred_grid)
    source = frame([Point(15, -4)])
    layer_id = reprojection.discover_vector_layers(source)[0]['id']
    with pytest.raises(ValueError, match='unavailable|unknown'):
        reprojection.reproject_batch(source, tmp_path / 'missing_choice', 3857,
                                     require_best=False, operations={layer_id: 'missing-grid-operation'})
    assert_nothing_published(tmp_path / 'missing_choice')


def test_empty_coordinates_have_null_bounds_and_strict_json_not_nan(tmp_path):
    source = frame([None, Point()], code=['missing', 'empty'])
    result = reprojection.reproject_batch(source, tmp_path / 'empty', 3857)
    output = only_output(result)
    assert output.code.tolist() == ['missing', 'empty']
    assert output.geometry.iloc[0] is None
    assert output.geometry.iloc[1].is_empty
    def non_json_constant(value):
        raise AssertionError(f'Invalid JSON constant in reproducible report: {value}')
    json.loads(Path(result.manifest).read_text(encoding='utf-8'), parse_constant=non_json_constant)


@pytest.mark.parametrize('parameters', [
    {'area_policy': 'silently_ignore'},
    {'accuracy': 0},
    {'accuracy': -1},
    {'accuracy': math.inf},
    {'area_of_interest': (0, -91, 10, 10)},
    {'area_of_interest': (0, 20, 10, 10)},
    {'area_of_interest': (0, 0, math.nan, 10)},
])
def test_invalid_selection_parameters_are_rejected_without_output(tmp_path, parameters):
    with pytest.raises((ValueError, TypeError)):
        reprojection.reproject_batch(frame([Point(15, -4)]), tmp_path / 'bad_parameters',
                                     3857, **parameters)
    assert_nothing_published(tmp_path / 'bad_parameters')


@pytest.mark.parametrize('crs', [None, 4979, 4978, 7789, 9000])
def test_missing_or_unsupported_source_crs_fails_before_publication(tmp_path, crs):
    source = frame([Point(15, -4, 10)], crs=crs)
    with pytest.raises(ValueError):
        reprojection.reproject_batch(source, tmp_path / 'bad_crs', 3857)
    assert_nothing_published(tmp_path / 'bad_crs')


@pytest.mark.parametrize('target', [4979, 4978, 9000])
def test_unsupported_target_crs_cannot_silently_drop_dimensions_or_epoch(tmp_path, target):
    with pytest.raises(ValueError):
        reprojection.reproject_batch(frame([Point(15, -4, 10)]), tmp_path / 'bad_target', target)
    assert_nothing_published(tmp_path / 'bad_target')


@pytest.mark.skipif(not hasattr(shapely, 'has_m'), reason='Measured geometry requires Shapely 2.1+')
def test_measured_coordinates_are_rejected_instead_of_silently_dropped(tmp_path):
    measured = shapely.from_wkt('POINT M (15 -4 25)')
    assert shapely.has_m(measured)
    with pytest.raises(ValueError):
        reprojection.reproject_batch(frame([measured]), tmp_path / 'measured', 3857)
    assert_nothing_published(tmp_path / 'measured')


def test_measured_file_is_rejected_before_pyogrio_discards_its_m_ordinate(tmp_path):
    source = tmp_path / 'measured_source.gpkg'
    frame([Point(15, -4)], code=['measured']).to_file(
        source, layer='sample', index=False, layer_options={'SPATIAL_INDEX': 'NO'})
    # A tiny valid ISO WKB PointM fixture, independent of Shapely's own M
    # support. GeoPackage's horizontal envelope and SRS header remain valid.
    with sqlite3.connect(source) as connection:
        blob = connection.execute('SELECT geom FROM sample').fetchone()[0]
        envelope = (blob[3] >> 1) & 7
        offset = 8 + {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}[envelope]
        point_m = struct.pack('<BIddd', 1, 2001, 15., -4., 25.)
        connection.execute('UPDATE sample SET geom=?', (blob[:offset] + point_m,))
        connection.execute('UPDATE gpkg_geometry_columns SET m=1, z=0')
    original = source.read_bytes()
    with pytest.raises(ValueError, match='[Mm]easured|ordinate|[Mm] '):
        reprojection.reproject_batch(source, tmp_path / 'measured_file', 3857)
    assert source.read_bytes() == original
    assert_nothing_published(tmp_path / 'measured_file')


def test_batch_failure_does_not_publish_an_earlier_successful_layer(tmp_path):
    valid = frame([Point(15, -4)], code=['valid'])
    invalid = frame([Point(0, 91)], code=['invalid'])
    with pytest.raises(ValueError):
        reprojection.reproject_batch([valid, invalid], tmp_path / 'partial', 3857)
    assert_nothing_published(tmp_path / 'partial')


@pytest.mark.parametrize('when', ['before', 'during'])
def test_cancellation_never_leaves_a_published_batch(tmp_path, when):
    event = Event()
    if when == 'before':
        event.set()
    calls = []
    def stop(completed, total):
        calls.append((completed, total))
        if completed and completed == total:
            event.set()
    sources = [frame([Point(15, -4)]), frame([Point(16, -5)])]
    with pytest.raises(ProcessingCancelled):
        reprojection.reproject_batch(sources, tmp_path / 'cancelled', 3857,
                                     progress=stop, cancel=event)
    assert_nothing_published(tmp_path / 'cancelled')
    if when == 'during':
        assert calls and event.is_set()


def test_write_failure_after_one_completed_layer_removes_staging_and_whole_batch(tmp_path, monkeypatch):
    original_write = reprojection._write_layer
    written = []
    def fail_second_layer(data, path, **kwargs):
        if written:
            assert written[0].is_file(), 'The first layer must really have reached staging.'
            raise OSError('Simulated second-layer disk write failure')
        original_write(data, path, **kwargs)
        written.append(path)
    monkeypatch.setattr(reprojection, '_write_layer', fail_second_layer)
    with pytest.raises(OSError, match='second-layer'):
        reprojection.reproject_batch([frame([Point(15, -4)]), frame([Point(16, -5)])],
                                     tmp_path / 'disk_failure', 3857)
    assert written and not written[0].exists()
    assert_nothing_published(tmp_path / 'disk_failure')


def test_destinations_cannot_replace_sources_or_existing_results(tmp_path):
    source = tmp_path / 'source.gpkg'
    frame([Point(15, -4)], code=['original']).to_file(source, index=False)
    original = source.read_bytes()
    for destination in (source, tmp_path):
        with pytest.raises((ValueError, FileExistsError)):
            reprojection.reproject_batch(source, destination, 3857)
        assert source.read_bytes() == original
    occupied = tmp_path / 'occupied'; occupied.mkdir()
    sentinel = occupied / 'keep.txt'; sentinel.write_text('Keep this content.', encoding='utf-8')
    with pytest.raises((ValueError, FileExistsError)):
        reprojection.reproject_batch(source, occupied, 3857)
    assert sentinel.read_text(encoding='utf-8') == 'Keep this content.'
