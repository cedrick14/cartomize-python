"""G06 remains faithful through the public API, command line and saved plans."""
import hashlib
import json
from pathlib import Path
import sqlite3
from threading import Event

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import rasterio
from shapely.geometry import Point

import cartomize as cm
from cartomize.cli import main
from cartomize.vector_io import write_geopackage


def source_vector(tmp_path):
    data = gpd.GeoDataFrame({
        'code': pd.Series(['001', 'NA', '003'], dtype='string'),
        'identifier': pd.Series([2**53 + 1, None, 0], dtype='Int64'),
        'name': pd.Series(['Forêt de Mvouti', 'Échantillon', 'Eau'], dtype='string'),
    }, geometry=[Point(300000, 9500000), Point(300020, 9500030), Point(300040, 9500060)], crs=32733)
    path = tmp_path / 'survey.gpkg'
    write_geopackage(data, path, layer='survey')
    return path


def assert_vector_values(path, layer='features'):
    # SQLite checks storage without using the conversion reader as its oracle.
    with sqlite3.connect(path) as connection:
        result = connection.execute(f'SELECT code, identifier, name FROM "{layer}" ORDER BY rowid').fetchall()
        assert result == [('001', 2**53 + 1, 'Forêt de Mvouti'),
                          ('NA', None, 'Échantillon'), ('003', 0, 'Eau')]


def assert_products_relocated(record, destination):
    assert record['primary'] == record['products']['data']
    for path in record['products'].values():
        assert Path(path).is_file()
        assert Path(path).is_relative_to(destination)
    for path in destination.rglob('*.json'):
        assert '.cartomize-' not in path.read_text(encoding='utf-8')


def test_conversion_catalog_and_public_api_are_connected():
    for operation, kind in [('vector.convert', 'vector'), ('raster.convert', 'raster')]:
        spec = next(row for row in cm.operation_catalog() if row['id'] == operation)
        assert spec['tool'] == 'conversion' and spec['output'] == kind
        assert set(spec['products']) == {'primary', 'data', 'manifest', 'report'}
        assert 'source' in {row['name'] for row in spec['parameters'] if row['required']}
        assert {row['name']: row['default'] for row in spec['parameters']}['loss_policy'] == 'error'
    assert callable(cm.convert_vector) and callable(cm.convert_raster)


def test_cli_vector_conversion_preserves_business_values_and_sources(tmp_path, capsys):
    source = source_vector(tmp_path)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    destination = tmp_path / 'delivery'
    assert main(['vector-conversion-options', str(source), '--layer', 'survey']) == 0
    inspection = json.loads(capsys.readouterr().out)
    assert isinstance(inspection, dict)
    assert main(['convert-vector', str(source), str(destination), '--layer', 'survey']) == 0
    record = json.loads(capsys.readouterr().out)
    assert record['operation'] == 'vector.convert'
    assert_products_relocated(record, destination)
    assert_vector_values(record['primary'])
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
    assert not list(tmp_path.rglob('.cartomize-*'))


def test_generic_process_conversion_exposes_manifest_and_report(tmp_path, capsys):
    source = source_vector(tmp_path)
    parameters = tmp_path / 'parameters.json'
    parameters.write_text(json.dumps(dict(source=str(source), layer='survey',
                                         field_map={'name': 'label'}, driver='GPKG')), encoding='utf-8')
    destination = tmp_path / 'delivery'
    assert main(['process', 'vector.convert', str(parameters), str(destination)]) == 0
    record = json.loads(capsys.readouterr().out)
    assert_products_relocated(record, destination)
    with sqlite3.connect(record['primary']) as connection:
        assert connection.execute('SELECT code, label FROM features ORDER BY rowid').fetchall() == [
            ('001', 'Forêt de Mvouti'), ('NA', 'Échantillon'), ('003', 'Eau')]
    document = json.loads(Path(record['products']['manifest']).read_text(encoding='utf-8'))
    assert document['schema'] == 'cartomize.vector_conversion.v1'


@pytest.mark.parametrize('reference', ['@converted', '@converted:data'])
def test_plan_vector_conversion_can_feed_downstream_processing(tmp_path, reference):
    source = source_vector(tmp_path)
    plan = cm.processing_plan([
        dict(id='converted', operation='vector.convert', parameters=dict(source=str(source), layer='survey')),
        dict(id='buffered', operation='vector.buffer', parameters=dict(data=reference, distance=10)),
    ])
    destination = tmp_path / 'plan'
    manifest = cm.run_plan(plan, destination)
    document = json.loads(Path(manifest).read_text(encoding='utf-8'))
    assert_vector_values(document['products']['converted']['data'])
    assert_vector_values(document['results']['buffered'], layer='result')
    frame = cm.read_file(document['results']['buffered'])
    np.testing.assert_allclose(frame.area, np.pi * 10**2, rtol=.01)
    for path in destination.rglob('*.json'):
        assert '.cartomize-' not in path.read_text(encoding='utf-8')


@pytest.mark.parametrize('driver', ['GTiff', 'COG'])
def test_cli_raster_delivery_keeps_masks_grid_and_values(write_raster, tmp_path, capsys, driver):
    values = np.array([[1, 2, 255], [0, 1, 2]], dtype='uint8')
    source = write_raster('classes.tif', values, nodata=255)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    destination = tmp_path / 'delivery'
    assert main(['raster-conversion-options', str(source)]) == 0
    assert isinstance(json.loads(capsys.readouterr().out), dict)
    assert main(['convert-raster', str(source), str(destination), '--driver', driver,
                 '--compression', 'deflate', '--dtype', 'uint16', '--nodata', '65535']) == 0
    record = json.loads(capsys.readouterr().out)
    assert_products_relocated(record, destination)
    with rasterio.open(source) as before, rasterio.open(record['primary']) as after:
        assert before.crs == after.crs and before.transform == after.transform
        np.testing.assert_array_equal(before.read_masks(), after.read_masks())
        valid = before.read_masks() > 0
        np.testing.assert_array_equal(before.read()[valid], after.read()[valid])
        assert after.nodata == 65535 and after.dtypes == ('uint16',)
        assert after.compression.value.upper() == 'DEFLATE'
        if driver == 'COG':
            assert after.tags(ns='IMAGE_STRUCTURE').get('LAYOUT') == 'COG'
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest


@pytest.mark.parametrize('nodata', ['none', 'nan'])
def test_cli_distinguishes_nodata_removal_and_nan(write_raster, tmp_path, capsys, nodata):
    source = write_raster('float.tif', np.array([[1., -9999.], [0., 2.]], dtype='float32'))
    assert main(['convert-raster', str(source), str(tmp_path / 'out'), '--nodata', nodata]) == 0
    record = json.loads(capsys.readouterr().out)
    with rasterio.open(source) as before, rasterio.open(record['primary']) as after:
        np.testing.assert_array_equal(before.read_masks(), after.read_masks())
        if nodata == 'none':
            assert after.nodata is None
        else:
            assert np.isnan(after.nodata)


def test_plan_can_chain_raster_delivery_and_preserve_cog_layout(write_raster, tmp_path):
    source = write_raster('classes.tif', np.array([[1, 2], [255, 0]], dtype='uint8'), nodata=255)
    plan = cm.processing_plan([
        dict(id='cog', operation='raster.convert', parameters=dict(source=str(source), driver='COG')),
        dict(id='uncompressed', operation='raster.convert', parameters=dict(source='@cog:data', compression='none')),
    ])
    destination = tmp_path / 'plan'
    manifest = cm.run_plan(plan, destination)
    document = json.loads(Path(manifest).read_text(encoding='utf-8'))
    with rasterio.open(document['products']['cog']['data']) as cog:
        assert cog.tags(ns='IMAGE_STRUCTURE').get('LAYOUT') == 'COG'
    with rasterio.open(source) as before, rasterio.open(document['results']['uncompressed']) as after:
        np.testing.assert_array_equal(before.read(masked=True), after.read(masked=True))
        np.testing.assert_array_equal(before.read_masks(), after.read_masks())
    for path in destination.rglob('*.json'):
        assert '.cartomize-' not in path.read_text(encoding='utf-8')


def test_cli_refuses_numeric_overflow_without_partial_delivery(write_raster, tmp_path, capsys):
    source = write_raster('wide.tif', np.array([[1, 300]], dtype='uint16'), nodata=None)
    destination = tmp_path / 'delivery'
    assert main(['convert-raster', str(source), str(destination), '--dtype', 'uint8']) != 0
    assert capsys.readouterr().err
    assert not destination.exists() and not list(tmp_path.rglob('.cartomize-*'))


@pytest.mark.parametrize('operation', ['vector.convert', 'raster.convert'])
def test_cancelled_conversion_operation_does_not_create_any_output(tmp_path, operation):
    event = Event()
    event.set()
    with pytest.raises(cm.ProcessingCancelled):
        cm.execute_operation(operation, dict(source=str(tmp_path / 'unused')), tmp_path / 'cancelled', cancel=event)
    assert not (tmp_path / 'cancelled').exists()


def test_cli_nodata_rejects_ambiguous_values_before_running(tmp_path):
    for value in ('true', 'inf', 'nullish', '[]'):
        with pytest.raises(SystemExit) as error:
            main(['convert-raster', 'unused.tif', str(tmp_path / 'unused'), '--nodata', value])
        assert error.value.code == 2
