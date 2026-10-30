"""G06 verifies saved vector deliveries against independent input values."""
from datetime import date
import json
from pathlib import Path
import sqlite3
import threading

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
from pyproj import CRS
import pytest
import shapely
from shapely.geometry import Point, Polygon

from cartomize import ProcessingCancelled
from cartomize.vector_conversion import (VectorConversionError, convert_vector,
                                        inspect_vector_conversion, vector_conversion_formats)
from cartomize.vector_io import read_vector, write_geopackage


def source_file(tmp_path, fields=None, *, geometry=None, name='source', layer='features'):
    fields = {'code': ['001', 'NA'], 'amount': [1.25, 2.5]} if fields is None else fields
    size = len(next(iter(fields.values()))) if fields else len(geometry or [Point(1, 2)])
    if geometry is None:
        geometry = [Point(i + .125, i + .25) for i in range(size)]
    data = gpd.GeoDataFrame(fields, geometry=geometry, crs=32733)
    path = tmp_path / f'{name}.gpkg'
    write_geopackage(data, path, layer=layer)
    return path


def load_report(result):
    return json.loads(result.report.read_text(encoding='utf-8'))


def assert_unpublished(tmp_path, destination):
    assert not destination.exists()
    assert not list(tmp_path.glob('.cartomize-*'))


@pytest.mark.parametrize('driver', ['GPKG', 'GeoJSON', 'ESRI Shapefile', 'FlatGeobuf'])
def test_four_formats_preserve_actual_values_coordinates_and_crs(tmp_path, driver):
    source = source_file(tmp_path)
    original = source.read_bytes()
    result = convert_vector(source, tmp_path / 'delivery', driver=driver)
    saved = read_vector(result.data)
    assert saved.code.tolist() == ['001', 'NA']
    assert saved.amount.tolist() == [1.25, 2.5]
    assert [(p.x, p.y) for p in saved.geometry] == [(.125, .25), (1.125, 1.25)]
    assert saved.crs == CRS(32733)
    report = load_report(result)
    assert report['difference_count'] == 0
    assert report['checked_features'] == 2
    assert report['checked_attribute_values'] == 4
    assert report['crs_preserved'] and report['coordinates_preserved']
    assert [row['source_fid'] for row in report['rows']] == [1, 2]
    assert [row['output_row'] for row in report['rows']] == [0, 1]
    assert all(Path(path).is_file() for path in result.summary['files'])
    assert source.read_bytes() == original
    if driver == 'ESRI Shapefile':
        assert {Path(path).suffix for path in result.summary['files']} >= {'.shp', '.shx', '.dbf', '.prj', '.cpg'}


def test_geopackage_keeps_exact_nullable_int64_boolean_dates_z_and_business_fid(tmp_path):
    source = source_file(tmp_path, {'identifier': pd.Series([2**60 + 3, None], dtype='Int64'),
        'fid': ['0003', 'NA'], 'approved': pd.Series([True, None], dtype='boolean'),
        'visit': [date(2024, 2, 29), None],
        'observed': [pd.Timestamp('2024-02-29T10:30:00.123'), None],
        'place': ['Dimonika — forêt', 'Mvoûti']}, geometry=[Point(1, 2, 3), Point(4, 5, 6)])
    result = convert_vector(source, tmp_path / 'typed')
    with sqlite3.connect(result.data) as connection:
        rows = connection.execute('SELECT identifier,fid,approved,visit,observed,place FROM features ORDER BY rowid').fetchall()
    assert rows[0][:4] == (2**60 + 3, '0003', 1, '2024-02-29')
    assert rows[1][:5] == (None, 'NA', None, None, None)
    saved = read_vector(result.data)
    assert saved.geometry.iloc[0].wkb == Point(1, 2, 3).wkb
    assert saved.place.tolist() == ['Dimonika — forêt', 'Mvoûti']
    assert load_report(result)['difference_count'] == 0


def test_business_attribute_geometry_is_preserved_by_renaming(tmp_path):
    source = source_file(tmp_path, {'label': ['a', 'b']})
    result = convert_vector(source, tmp_path / 'renamed', field_map={'label': 'geometry'})
    saved = read_vector(result.data)
    assert saved['geometry'].tolist() == ['a', 'b']
    assert saved.geometry.name != 'geometry'
    assert saved.geometry.x.tolist() == [.125, 1.125]


@pytest.mark.parametrize('driver', ['GPKG', 'GeoJSON', 'FlatGeobuf'])
def test_null_geometries_remain_null_and_row_order_is_preserved(tmp_path, driver):
    source = source_file(tmp_path, geometry=[Point(50, 10), None])
    result = convert_vector(source, tmp_path / 'null', driver=driver)
    saved = read_vector(result.data)
    assert saved.code.tolist() == ['001', 'NA']
    assert saved.geometry.iloc[0].wkb == Point(50, 10).wkb
    assert saved.geometry.iloc[1] is None


def test_empty_geometries_are_kept_in_geopackage(tmp_path):
    source = source_file(tmp_path, geometry=[Point(), None])
    result = convert_vector(source, tmp_path / 'empty')
    saved = read_vector(result.data)
    assert saved.geometry.iloc[0].is_empty
    assert saved.geometry.iloc[1] is None


def test_multilayer_selection_is_explicit_and_inspection_lists_choices(tmp_path):
    source = source_file(tmp_path, {'code': ['first']}, layer='first')
    gpd.GeoDataFrame({'code': ['second']}, geometry=[Point(9, 9)], crs=32733).to_file(
        source, layer='second', driver='GPKG')
    inspection = inspect_vector_conversion(source)
    assert inspection['selected_layer'] is None
    assert {item['name'] for item in inspection['layers']} == {'first', 'second'}
    with pytest.raises(ValueError, match='explicitly'):
        convert_vector(source, tmp_path / 'implicit')
    result = convert_vector(source, tmp_path / 'selected', layer='second', output_layer='livraison')
    assert read_vector(result.data, layer='livraison').code.tolist() == ['second']
    assert result.summary['source_layer'] == 'second'
    assert result.summary['output_layer'] == 'livraison'


def test_shapefile_field_names_must_be_mapped_or_explicitly_reported(tmp_path):
    source = source_file(tmp_path, {'long_identifier': ['001', '002']})
    inspection = inspect_vector_conversion(source, driver='ESRI Shapefile')
    assert any(issue['kind'] == 'field_name' for issue in inspection['issues'])
    destination = tmp_path / 'strict'
    with pytest.raises(VectorConversionError) as caught:
        convert_vector(source, destination, driver='ESRI Shapefile')
    assert any(item['kind'] == 'field_name' for item in caught.value.report['differences'])
    assert_unpublished(tmp_path, destination)
    mapped = convert_vector(source, tmp_path / 'mapped', driver='ESRI Shapefile', field_map={'long_identifier': 'code'})
    assert read_vector(mapped.data).code.tolist() == ['001', '002']
    assert load_report(mapped)['difference_count'] == 0
    reported = convert_vector(source, tmp_path / 'reported', driver='ESRI Shapefile', loss_policy='report')
    report = load_report(reported)
    assert report['field_correspondence'][0]['source'] == 'long_identifier'
    assert report['field_correspondence'][0]['actual'] == 'long_ident'
    assert read_vector(reported.data)['long_ident'].tolist() == ['001', '002']


def test_shapefile_numeric_precision_loss_has_cell_by_cell_report(tmp_path):
    value = 1.2345678901234567
    source = source_file(tmp_path, {'measure': [value]})
    with pytest.raises(VectorConversionError):
        convert_vector(source, tmp_path / 'strict', driver='ESRI Shapefile')
    result = convert_vector(source, tmp_path / 'reported', driver='ESRI Shapefile', loss_policy='report')
    changes = [item for item in load_report(result)['differences'] if item['kind'] == 'attribute_value']
    assert len(changes) == 1
    assert changes[0]['source_row'] == 0
    assert changes[0]['source_field'] == 'measure'
    assert changes[0]['before'] == value
    assert changes[0]['after'] == read_vector(result.data)['measure'].iloc[0]
    assert changes[0]['before'] != changes[0]['after']


def test_shapefile_report_exposes_nullable_int64_rounding_as_changed_value(tmp_path):
    value = 2**60 + 3
    source = source_file(tmp_path, {'identifier': pd.Series([value, None], dtype='Int64')})
    result = convert_vector(source, tmp_path / 'reported_int64', driver='ESRI Shapefile', loss_policy='report')
    report = load_report(result)
    values = [item for item in report['differences'] if item['kind'] == 'attribute_value']
    assert len(values) == 1
    assert values[0]['before'] == value
    assert int(values[0]['after']) == 2**60
    assert report['field_correspondence'][0]['changed_values'] == 1


def test_datetime_to_shapefile_requires_explicit_report_policy(tmp_path):
    value = pd.Timestamp('2024-02-29T12:34:56.123')
    source = source_file(tmp_path, {'observed': [value, None]})
    with pytest.raises(ValueError, match='datetime'):
        convert_vector(source, tmp_path / 'strict', driver='ESRI Shapefile')
    result = convert_vector(source, tmp_path / 'reported', driver='ESRI Shapefile', loss_policy='report')
    saved = read_vector(result.data)
    assert saved.observed.iloc[0] == value.isoformat()
    assert pd.isna(saved.observed.iloc[1])
    assert any(change['kind'] == 'field_type' and change['after'] == 'string'
               for change in load_report(result)['differences'])


def test_shapefile_requested_encoding_is_applied_and_reopened(tmp_path):
    source = source_file(tmp_path, {'place': ['forêt', 'Mvoûti']})
    result = convert_vector(source, tmp_path / 'latin', driver='ESRI Shapefile', encoding='ISO-8859-1')
    assert read_vector(result.data).place.tolist() == ['forêt', 'Mvoûti']
    assert result.data.with_suffix('.cpg').read_text().strip().lower() in {'iso8859-1', 'iso-8859-1'}
    assert load_report(result)['difference_count'] == 0


def test_unrepresentable_text_is_refused_even_in_report_mode(tmp_path):
    source = source_file(tmp_path, {'place': ['森林']})
    destination = tmp_path / 'latin'
    with pytest.raises(ValueError, match='cannot be represented'):
        convert_vector(source, destination, driver='ESRI Shapefile', encoding='ISO-8859-1', loss_policy='report')
    assert_unpublished(tmp_path, destination)


def test_geojson_preserves_double_coordinates_without_rounding(tmp_path):
    point = Point(15.123456789012345, -4.123456789012345)
    source = source_file(tmp_path, {'value': [1.1234567890123457]}, geometry=[point])
    result = convert_vector(source, tmp_path / 'json', driver='GeoJSON')
    payload = json.loads(result.data.read_text())
    assert payload['features'][0]['geometry']['coordinates'] == [point.x, point.y]
    assert payload['features'][0]['properties']['value'] == 1.1234567890123457


@pytest.mark.parametrize('coordinate', [48.863695000000696, 1.2345678901234567e-20,
                                       1e-300, np.nextafter(0.0, 1.0)])
def test_geojson_keeps_ieee_digits_and_subnormal_coordinates(tmp_path, coordinate):
    # The first value is the actual Charonne vertex that GDAL's 17-digit
    # smart formatter incorrectly reduced to 48.863695000001.
    point = Point(2.4, coordinate)
    source = source_file(tmp_path, {'measure': [coordinate]}, geometry=[point])
    result = convert_vector(source, tmp_path / 'exact_geojson', driver='GeoJSON')
    feature = json.loads(result.data.read_text())['features'][0]
    assert float(feature['geometry']['coordinates'][1]).hex() == float(coordinate).hex()
    assert float(feature['properties']['measure']).hex() == float(coordinate).hex()
    assert read_vector(result.data).geometry.iloc[0].wkb == point.wkb


@pytest.mark.parametrize('native_ids', [False, True])
def test_geojson_properties_id_fid_ogc_fid_remain_business_attributes(tmp_path, native_ids):
    source = tmp_path / 'business_ids.geojson'
    features = []
    for index, identifier in enumerate([101, 202]):
        feature = dict(type='Feature', properties={'id': identifier, 'fid': f'00{index + 1}',
                       'OGC_FID': f'station-{index + 1}'},
                       geometry={'type': 'Point', 'coordinates': [2.0 + index, 48.0]})
        if native_ids:
            feature['id'] = 900 + index
        features.append(feature)
    source.write_text(json.dumps(dict(type='FeatureCollection', features=features)), encoding='utf-8')
    inspected = inspect_vector_conversion(source)
    assert [field['name'] for field in inspected['fields']] == ['id', 'fid', 'OGC_FID']
    result = convert_vector(source, tmp_path / 'ids')
    # SQLite is independent of the source reader that formerly consumed id.
    with sqlite3.connect(result.data) as connection:
        assert connection.execute('SELECT id,fid,OGC_FID FROM features ORDER BY rowid').fetchall() == [
            (101, '001', 'station-1'), (202, '002', 'station-2')]
    expected_fids = [900, 901] if native_ids else [101, 202]
    assert [row['source_fid'] for row in load_report(result)['rows']] == expected_fids
    assert result.summary['field_count'] == 3


def test_source_reader_missing_declared_attribute_stops_before_publication(tmp_path, monkeypatch):
    import cartomize.vector_conversion as conversion
    source = source_file(tmp_path, {'id': [101], 'label': ['forest']})
    native_read = conversion.read_vector
    def truncated_reader(path, **kwargs):
        return native_read(path, **kwargs).drop(columns=['id'])
    monkeypatch.setattr(conversion, 'read_vector', truncated_reader)
    destination = tmp_path / 'missing_attribute'
    with pytest.raises(ValueError, match='declared attribute.*id'):
        convert_vector(source, destination)
    assert_unpublished(tmp_path, destination)


def test_shapefile_polygon_ring_reordering_is_explicitly_reported(tmp_path):
    polygon = Polygon([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)])
    source = source_file(tmp_path, {'code': ['forest']}, geometry=[polygon])
    result = convert_vector(source, tmp_path / 'polygon', driver='ESRI Shapefile', loss_policy='report')
    saved = read_vector(result.data).geometry.iloc[0]
    assert saved.area == polygon.area
    assert shapely.normalize(saved).wkb == shapely.normalize(polygon).wkb
    if saved.wkb != polygon.wkb:
        change = next(item for item in load_report(result)['differences'] if item['kind'] == 'geometry_representation')
        assert change['before'] == polygon.wkb_hex
        assert change['after'] == saved.wkb_hex


def test_flatgeobuf_null_geometry_and_nullable_int64_convert_back_to_geopackage(tmp_path):
    source = source_file(tmp_path, {'identifier': pd.Series([2**60 + 3, None], dtype='Int64')},
                         geometry=[Point(1, 2), None])
    flat = convert_vector(source, tmp_path / 'flat', driver='FlatGeobuf')
    result = convert_vector(flat.data, tmp_path / 'back')
    with sqlite3.connect(result.data) as connection:
        assert connection.execute('SELECT identifier FROM features ORDER BY rowid').fetchall() == [(2**60 + 3,), (None,)]
    assert read_vector(result.data).geometry.iloc[1] is None
    assert load_report(result)['difference_count'] == 0


@pytest.mark.parametrize('kwargs,match', [
    ({'driver': 'CSV'}, 'driver'), ({'loss_policy': 'allow'}, 'loss_policy'),
    ({'encoding': 'latin1'}, 'UTF-8'), ({'encoding': 'not-an-encoding'}, 'encoding'),
    ({'field_map': {'code': None}}, 'does not drop'),
    ({'field_map': {'absent': 'code'}}, 'existing source'),
    ({'field_map': {'code': 'AMOUNT'}}, 'distinct'),
    ({'output_layer': '../bad'}, 'output_layer'), ({'layer': 'absent'}, 'existing layer'),
])
def test_invalid_options_fail_without_publication(tmp_path, kwargs, match):
    source = source_file(tmp_path)
    destination = tmp_path / 'invalid'
    with pytest.raises(ValueError, match=match):
        convert_vector(source, destination, **kwargs)
    assert_unpublished(tmp_path, destination)


def test_existing_destination_is_not_overwritten(tmp_path):
    source = source_file(tmp_path)
    destination = tmp_path / 'existing'
    destination.mkdir()
    marker = destination / 'keep.txt'
    marker.write_text('keep')
    with pytest.raises(FileExistsError):
        convert_vector(source, destination)
    assert marker.read_text() == 'keep'


@pytest.mark.parametrize('stage', [0, 1, 2, 3, 4])
def test_cancellation_cleans_staged_outputs_at_every_stage(tmp_path, stage):
    source = source_file(tmp_path)
    destination = tmp_path / 'cancelled'
    cancelled = threading.Event()
    def progress(current, total):
        if current == stage:
            cancelled.set()
    with pytest.raises(ProcessingCancelled):
        convert_vector(source, destination, progress=progress, cancel=cancelled)
    assert_unpublished(tmp_path, destination)


def test_coordinate_corruption_is_refused_even_with_report_policy(tmp_path, monkeypatch):
    import cartomize.vector_conversion as conversion
    source = source_file(tmp_path)
    real_read = conversion._read
    def corrupt(path, layer):
        data, info = real_read(path, layer)
        if Path(path).name == 'data.gpkg':
            data.loc[data.index[0], data.geometry.name] = Point(99, 99)
        return data, info
    monkeypatch.setattr(conversion, '_read', corrupt)
    destination = tmp_path / 'corrupt'
    with pytest.raises(ValueError, match='geometry coordinates'):
        convert_vector(source, destination, loss_policy='report')
    assert_unpublished(tmp_path, destination)


def test_formats_describe_installed_capabilities():
    records = {item['driver']: item for item in vector_conversion_formats()}
    assert set(records) == {'GPKG', 'GeoJSON', 'ESRI Shapefile', 'FlatGeobuf'}
    assert all(item['available'] for item in records.values())
    assert records['ESRI Shapefile']['encodings'] == 'configurable'
