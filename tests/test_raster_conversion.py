"""G06 contracts checked against reopened raster files, not writer mocks."""
import json
from pathlib import Path
import threading
from xml.etree import ElementTree as ET

import numpy as np
import pytest
import rasterio
from rasterio.enums import ColorInterp, Resampling
from rasterio.io import MemoryFile
from rasterio.shutil import copy as raster_copy
from rasterio.transform import from_origin

from cartomize.algebra import ProcessingCancelled
from cartomize.raster_conversion import convert_raster, inspect_raster_conversion


def raster(tmp_path, values, *, nodata=None, mask=None, name='source.tif', crs='EPSG:32733'):
    values = np.asarray(values)
    if values.ndim == 2:
        values = values[np.newaxis]
    path = tmp_path / name
    with rasterio.open(path, 'w', driver='GTiff', width=values.shape[2],
            height=values.shape[1], count=len(values), dtype=values.dtype,
            nodata=nodata, crs=crs, transform=from_origin(321000, 9450000, 30, 30)) as dst:
        dst.write(values)
        if mask is not None:
            dst.write_mask(np.asarray(mask, dtype='uint8'))
    return path


@pytest.mark.parametrize('driver', ['GTiff', 'COG'])
@pytest.mark.parametrize('compression', ['none', 'lzw', 'deflate', 'zstd'])
def test_delivery_preserves_all_bands_grid_and_distinct_masks(tmp_path, driver, compression):
    values = np.asarray([[[1, 0, 3], [4, 5, 6]], [[7, 8, 9], [0, 11, 12]]], dtype='uint16')
    source = raster(tmp_path, values, nodata=0)
    result = convert_raster(source, tmp_path / 'delivery', driver=driver, compression=compression)
    with rasterio.open(source) as before, rasterio.open(result.data) as after:
        assert np.array_equal(before.read(), after.read())
        assert np.array_equal(before.read_masks(), after.read_masks())
        assert after.crs == before.crs and after.transform == before.transform
        assert after.count == 2 and after.dtypes == ('uint16', 'uint16')
        assert ('none' if after.compression is None else after.compression.name.lower()) == compression
        if driver == 'COG':
            assert after.tags(ns='IMAGE_STRUCTURE')['LAYOUT'] == 'COG'
    assert result.summary['verified'] and result.summary['lossless']
    report = json.loads(result.report.read_text())
    assert [band['valid_samples'] for band in report['bands']] == [5, 5]
    assert report['verification']['full_resolution_samples'] == 'all'
    manifest = json.loads(result.manifest.read_text())
    assert manifest['products']['data'] == str(result.data)
    assert not list(result.data.parent.glob('_staging*'))


@pytest.mark.parametrize('driver', ['GTiff', 'COG'])
def test_labels_scales_units_custom_metadata_and_overviews(tmp_path, driver):
    source = raster(tmp_path, np.arange(4096, dtype='int16').reshape(64, 64))
    with rasterio.open(source, 'r+') as dst:
        dst.set_band_description(1, 'Élévation — Mvouti')
        dst.scales = (0.25,)
        dst.offsets = (-10.0,)
        dst.set_band_unit(1, 'm')
        dst.update_tags(author='Cédrick', project='Mayombe')
        dst.update_tags(1, sensor='test')
        dst.update_tags(ns='CUSTOM', code='échantillon')
        dst.build_overviews([2, 4], Resampling.nearest)
    result = convert_raster(source, tmp_path / 'delivery', driver=driver)
    with rasterio.open(result.data) as after:
        assert after.descriptions == ('Élévation — Mvouti',)
        assert after.scales == (0.25,) and after.offsets == (-10.0,)
        assert after.units == ('m',)
        assert after.tags()['author'] == 'Cédrick'
        assert after.tags(1)['sensor'] == 'test'
        assert after.tags(ns='CUSTOM')['code'] == 'échantillon'
        assert after.overviews(1) == [2, 4]
    if driver == 'COG':
        manifest = json.loads(result.manifest.read_text())
        if result.summary['auxiliary_files']:
            assert not result.summary['self_contained']
            assert str(result.data) + '.aux.xml' in manifest['files']
            assert Path(str(result.data) + '.aux.xml').is_file()


def test_dtype_can_change_without_changing_values(tmp_path):
    source = raster(tmp_path, [[0, 1], [2, 254]], nodata=None)
    result = convert_raster(source, tmp_path / 'delivery', dtype='uint8', nodata=255)
    with rasterio.open(result.data) as after:
        assert after.dtypes == ('uint8',) and after.nodata == 255
        assert after.read_masks().all()
        assert np.array_equal(after.read(1), [[0, 1], [2, 254]])
    assert result.summary['changed_samples'] == 0


def test_common_mask_survives_removing_nodata(tmp_path):
    source = raster(tmp_path, np.array([[0, -9999], [4, -9999]], dtype='int16'), nodata=-9999)
    result = convert_raster(source, tmp_path / 'delivery', nodata=None, dtype='uint8')
    with rasterio.open(result.data) as after:
        assert after.nodata is None
        assert np.array_equal(after.read_masks(1), [[255, 0], [255, 0]])
        assert after.read(1)[0, 0] == 0  # Valid zero stays valid.


def test_different_band_masks_cannot_silently_become_common(tmp_path):
    source = raster(tmp_path, np.array([[[0, 1]], [[2, 0]]], dtype='uint8'), nodata=0)
    with pytest.raises(ValueError, match='per-band validity'):
        convert_raster(source, tmp_path / 'delivery', nodata=None)
    assert not (tmp_path / 'delivery').exists()


def test_explicit_mask_keeps_valid_source_sentinel_when_removed(tmp_path):
    source = raster(tmp_path, np.array([[0, 2], [7, 4]], dtype='uint8'), nodata=0,
                    mask=[[255, 255], [0, 255]])
    result = convert_raster(source, tmp_path / 'delivery', nodata=None)
    with rasterio.open(result.data) as after:
        assert after.read_masks(1)[0, 0] == 255 and after.read(1)[0, 0] == 0
    with pytest.raises(ValueError, match='collides'):
        convert_raster(source, tmp_path / 'collision')
    assert not (tmp_path / 'collision').exists()


@pytest.mark.parametrize('value, dtype', [(256, 'uint8'), (-1, 'uint8'), (2**31, 'int32')])
def test_overflow_is_rejected_even_with_report_policy(tmp_path, value, dtype):
    source = raster(tmp_path, np.array([[0, value]], dtype='int64'))
    for policy in ['error', 'report']:
        target = tmp_path / policy
        with pytest.raises(ValueError, match='overflow'):
            convert_raster(source, target, dtype=dtype, loss_policy=policy)
        assert not target.exists()


def test_float_to_integer_rounding_requires_explicit_policy(tmp_path):
    source = raster(tmp_path, np.array([[1.25, 2.5, 3.5, -1.5]], dtype='float64'))
    with pytest.raises(ValueError, match='rounded'):
        convert_raster(source, tmp_path / 'strict', dtype='int16')
    assert not (tmp_path / 'strict').exists()
    result = convert_raster(source, tmp_path / 'reported', dtype='int16', loss_policy='report')
    with rasterio.open(result.data) as after:
        assert np.array_equal(after.read(1), [[1, 2, 4, -2]])
    assert result.summary['changed_samples'] == 4
    assert result.summary['max_absolute_error'] == 0.5
    assert not result.summary['lossless']


@pytest.mark.parametrize('dtype,values', [
    ('int64', [2**53 + 1, 2**63 - 1]),
    ('uint64', [2**53 + 1, 2**64 - 1]),
])
def test_large_integer_float_conversion_detects_exact_precision_loss(tmp_path, dtype, values):
    source = raster(tmp_path, np.array([values], dtype=dtype))
    with pytest.raises(ValueError, match='precision'):
        convert_raster(source, tmp_path / 'strict', dtype='float64')
    result = convert_raster(source, tmp_path / 'reported', dtype='float64', loss_policy='report')
    assert result.summary['changed_samples'] == 2
    assert result.summary['max_absolute_error'] == 1.0


def test_float32_precision_loss_recorded_and_statistics_not_reused(tmp_path):
    source = raster(tmp_path, np.array([[0.1, 1.0]], dtype='float64'))
    with rasterio.open(source, 'r+') as dst:
        dst.update_tags(1, STATISTICS_MINIMUM='0.1', keep='source')
    with pytest.raises(ValueError, match='precision'):
        convert_raster(source, tmp_path / 'strict', dtype='float32')
    result = convert_raster(source, tmp_path / 'reported', dtype='float32', loss_policy='report')
    assert result.summary['changed_samples'] == 1
    assert result.summary['max_absolute_error'] > 0
    with rasterio.open(result.data) as after:
        assert 'STATISTICS_MINIMUM' not in after.tags(1)
        assert after.tags(1)['keep'] == 'source'
    report = json.loads(result.report.read_text())
    assert report['changes']['discarded_stale_statistics'][0]['key'] == 'STATISTICS_MINIMUM'


@pytest.mark.parametrize('nodata', ['nan', float('nan')])
def test_nan_nodata_replaces_finite_sentinel_and_roundtrips_json(tmp_path, nodata):
    source = raster(tmp_path, np.array([[0.0, -9999.0], [1.0, 2.0]], dtype='float32'), nodata=-9999)
    result = convert_raster(source, tmp_path / 'delivery', nodata=nodata)
    with rasterio.open(result.data) as after:
        assert np.isnan(after.nodata)
        assert np.isnan(after.read(1)[0, 1])
        assert np.array_equal(after.read_masks(1), [[255, 0], [255, 255]])
    assert json.loads(result.report.read_text())['output']['nodata'] == ['nan']


def test_valid_nan_cannot_be_relabelled_as_missing(tmp_path):
    source = raster(tmp_path, np.array([[float('nan'), 2.0]], dtype='float32'))
    with pytest.raises(ValueError, match='collides'):
        convert_raster(source, tmp_path / 'delivery', nodata='nan')
    assert not (tmp_path / 'delivery').exists()
    kept = convert_raster(source, tmp_path / 'kept')
    with rasterio.open(kept.data) as after:
        assert after.read_masks().all()
        assert np.isnan(after.read(1)[0, 0])


def test_nodata_collision_is_checked_after_rounding(tmp_path):
    source = raster(tmp_path, np.array([[254.9, 2.0]], dtype='float32'))
    with pytest.raises(ValueError, match='collides'):
        convert_raster(source, tmp_path / 'delivery', dtype='uint8', nodata=255, loss_policy='report')
    assert not (tmp_path / 'delivery').exists()


@pytest.mark.parametrize('nodata', [np.int64(2**53 + 1), np.uint64(2**63 + 1)])
def test_numpy_integer_nodata_must_be_exactly_representable_as_float(tmp_path, nodata):
    source = raster(tmp_path, np.array([[1.0, 2.0]], dtype='float64'))
    with pytest.raises(ValueError, match='NoData cannot be represented exactly'):
        convert_raster(source, tmp_path / 'delivery', nodata=nodata)
    assert not (tmp_path / 'delivery').exists()


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -float('inf')])
def test_valid_nonfinite_samples_cannot_become_integers(tmp_path, value):
    source = raster(tmp_path, np.array([[value, 1.0]], dtype='float32'))
    with pytest.raises(ValueError, match='NaN or infinite'):
        convert_raster(source, tmp_path / 'delivery', dtype='int16', loss_policy='report')
    assert not (tmp_path / 'delivery').exists()


@pytest.mark.parametrize('driver', ['GTiff', 'COG'])
def test_alpha_mask_values_and_all_channels_survive(tmp_path, driver):
    values = np.array([[[3, 4, 5]], [[6, 7, 8]], [[9, 10, 11]], [[0, 127, 255]]], dtype='uint8')
    source = raster(tmp_path, values)
    with rasterio.open(source, 'r+') as dst:
        dst.colorinterp = (ColorInterp.red, ColorInterp.green, ColorInterp.blue, ColorInterp.alpha)
    result = convert_raster(source, tmp_path / 'delivery', driver=driver)
    with rasterio.open(source) as before, rasterio.open(result.data) as after:
        assert np.array_equal(before.read_masks(), after.read_masks())
        assert np.array_equal(after.read(4), values[3])
        assert before.colorinterp == after.colorinterp
        assert np.array_equal(before.read()[:, :, 1:], after.read()[:, :, 1:])


def test_palette_is_preserved_and_unsafe_palette_retyping_rejected(tmp_path):
    source = raster(tmp_path, np.array([[0, 1], [2, 1]], dtype='uint8'), nodata=0)
    with rasterio.open(source, 'r+') as dst:
        dst.write_colormap(1, {0: (0, 0, 0, 0), 1: (0, 180, 40, 255), 2: (160, 80, 0, 255)})
    result = convert_raster(source, tmp_path / 'delivery', driver='COG')
    with rasterio.open(source) as before, rasterio.open(result.data) as after:
        assert before.colormap(1) == after.colormap(1)
    with pytest.raises(ValueError, match='palette'):
        convert_raster(source, tmp_path / 'changed', dtype='uint16')


def test_complete_readback_rejects_writer_corruption(tmp_path, monkeypatch):
    from cartomize import raster_conversion as conversion
    source = raster(tmp_path, np.array([[1, 2], [3, 4]], dtype='uint8'))
    real = conversion._write_metadata
    def corrupt(src, dst, tags):
        real(src, dst, tags)
        dst.write(np.array([[99]], dtype='uint8'), 1, window=rasterio.windows.Window(0, 0, 1, 1))
    monkeypatch.setattr(conversion, '_write_metadata', corrupt)
    with pytest.raises(ValueError, match='pixel values'):
        convert_raster(source, tmp_path / 'delivery')
    assert not (tmp_path / 'delivery').exists()


def test_cancellation_never_publishes_partial_directory(tmp_path):
    source = raster(tmp_path, np.ones((300, 300), dtype='uint8'))
    event = threading.Event()
    def progress(done, total):
        if done:
            event.set()
    with pytest.raises(ProcessingCancelled):
        convert_raster(source, tmp_path / 'delivery', block_size=128, progress=progress, cancel=event)
    assert not (tmp_path / 'delivery').exists()
    assert not list(tmp_path.glob('.cartomize-*'))


def test_existing_destination_preserved(tmp_path):
    source = raster(tmp_path, np.ones((2, 2), dtype='uint8'))
    target = tmp_path / 'delivery'
    target.mkdir()
    (target / 'existing.txt').write_text('keep')
    with pytest.raises(FileExistsError):
        convert_raster(source, target)
    assert (target / 'existing.txt').read_text() == 'keep'


def test_inspection_is_json_safe_and_keeps_unknown_crs(tmp_path):
    source = raster(tmp_path, np.ones((2, 3), dtype='float32'), nodata=float('nan'), crs=None)
    report = inspect_raster_conversion(source, driver='COG')
    json.dumps(report, allow_nan=False)
    assert report['schema'] == 'cartomize.raster_conversion_inspection.v1'
    assert report['source']['nodata'] == ['nan']
    assert report['nodata'] == 'nan' and report['crs'] is None
    assert (report['width'], report['height'], report['count']) == (3, 2, 1)


def classified_vrt(tmp_path, *, categories=True, table=True, values=None, nodata=None):
    values = np.asarray([[0, 1], [1, 0]], dtype='uint8') if values is None else np.asarray(values)
    underlying = raster(tmp_path, values, nodata=nodata, name='classified.tif')
    path = tmp_path / 'classified.vrt'
    raster_copy(underlying, path, driver='VRT')
    root = ET.parse(path).getroot()
    band = root.find('VRTRasterBand')
    if categories:
        labels = ET.SubElement(band, 'CategoryNames')
        for label in ['Eau', 'Forêt dense']:
            ET.SubElement(labels, 'Category').text = label
    if table:
        rat = ET.SubElement(band, 'GDALRasterAttributeTable', tableType='thematic')
        fields = [('Value', 1 if values.dtype.kind == 'f' else 0, 5), ('Name', 2, 2),
                  ('PixelCount', 0, 1), ('Red', 0, 6), ('Green', 0, 7), ('Blue', 0, 8), ('Alpha', 0, 9)]
        for index, (name, dtype, usage) in enumerate(fields):
            field = ET.SubElement(rat, 'FieldDefn', index=str(index))
            for key, value in [('Name', name), ('Type', dtype), ('Usage', usage)]:
                ET.SubElement(field, key).text = str(value)
        for index, (value, name, color) in enumerate([(0, 'Eau', [0, 0, 255]),
                                                     (float(values.max()), 'Forêt dense', [0, 160, 0])]):
            row = ET.SubElement(rat, 'Row', index=str(index))
            for value in [value, name, int(np.sum(values == value)), *color, 255]:
                ET.SubElement(row, 'F').text = str(value)
    ET.ElementTree(root).write(path, encoding='utf-8', xml_declaration=False)
    return path, underlying


def exported_band(path):
    """Ask the GDAL VRT driver to expose effective metadata after reopening."""
    with MemoryFile(ext='.vrt') as probe:
        raster_copy(path, probe.name, driver='VRT')
        return ET.fromstring(probe.read()).find('VRTRasterBand')


@pytest.mark.parametrize('driver', ['GTiff', 'COG'])
@pytest.mark.parametrize('categories,table', [(True, True), (True, False), (False, True)])
def test_categories_and_raster_attribute_table_survive_delivery(tmp_path, driver, categories, table):
    source, underlying = classified_vrt(tmp_path, categories=categories, table=table)
    original = {path: path.read_bytes() for path in (source, underlying)}
    result = convert_raster(source, tmp_path / 'delivery', driver=driver)
    band = exported_band(result.data)
    if categories:
        assert [node.text for node in band.find('CategoryNames')] == ['Eau', 'Forêt dense']
    else:
        assert band.find('CategoryNames') is None
    if table:
        rat = band.find('GDALRasterAttributeTable')
        assert [field.findtext('Name') for field in rat.findall('FieldDefn')] == [
            'Value', 'Name', 'PixelCount', 'Red', 'Green', 'Blue', 'Alpha']
        assert [field.findtext('Usage') for field in rat.findall('FieldDefn')] == ['5', '2', '1', '6', '7', '8', '9']
        assert [[cell.text for cell in row] for row in rat.findall('Row')] == [
            ['0', 'Eau', '2', '0', '0', '255', '255'],
            ['1', 'Forêt dense', '2', '0', '160', '0', '255']]
    else:
        assert band.find('GDALRasterAttributeTable') is None
    with rasterio.open(result.data) as delivered:
        assert np.array_equal(delivered.read(1), [[0, 1], [1, 0]])
        if driver == 'COG':
            assert delivered.tags(ns='IMAGE_STRUCTURE')['LAYOUT'] == 'COG'
    assert result.summary['classification_metadata_verified']
    assert result.summary['auxiliary_files'] == ['data.tif.aux.xml']
    assert not result.summary['self_contained']
    assert str(result.data) + '.aux.xml' in json.loads(result.manifest.read_text())['files']
    for path, content in original.items():
        assert path.read_bytes() == content
        assert not Path(str(path) + '.aux.xml').exists()


def test_raster_attribute_table_codes_cannot_be_quantized_in_report_mode(tmp_path):
    source, _ = classified_vrt(tmp_path, categories=False, values=np.array([[0.0, 1.5]], dtype='float64'))
    with pytest.raises(ValueError, match='class values'):
        convert_raster(source, tmp_path / 'delivery', dtype='int16', loss_policy='report')
    assert not (tmp_path / 'delivery').exists()


def test_category_codes_beneath_mask_are_preserved_and_nodata_change_is_controlled(tmp_path):
    source, _ = classified_vrt(tmp_path, nodata=0)
    kept = convert_raster(source, tmp_path / 'kept', nodata=None, driver='COG')
    with rasterio.open(kept.data) as after:
        assert np.array_equal(after.read(1), [[0, 1], [1, 0]])
        assert np.array_equal(after.read_masks(1), [[0, 255], [255, 0]])
    assert [node.text for node in exported_band(kept.data).find('CategoryNames')] == ['Eau', 'Forêt dense']
    with pytest.raises(ValueError, match='stored class codes'):
        convert_raster(source, tmp_path / 'changed', nodata=255, loss_policy='report')
    assert not (tmp_path / 'changed').exists()


def test_exact_uint64_source_nodata_is_not_accepted_through_rounded_alias(tmp_path):
    number = 2**53 + 1
    underlying = raster(tmp_path, np.array([[number, 1]], dtype='uint64'), name='uint64.tif')
    source = tmp_path / 'uint64.vrt'
    raster_copy(underlying, source, driver='VRT')
    root = ET.parse(source).getroot()
    ET.SubElement(root.find('VRTRasterBand'), 'NoDataValue').text = str(number)
    ET.ElementTree(root).write(source, encoding='utf-8', xml_declaration=False)
    source_bytes, pixels_bytes = source.read_bytes(), underlying.read_bytes()
    with rasterio.open(source) as original:
        assert original.nodata == 2**53  # Rasterio's ambiguous double accessor.
        assert np.array_equal(original.read_masks(1), [[0, 255]])
    with pytest.raises(ValueError, match='above 2\\*\\*53'):
        convert_raster(source, tmp_path / 'preserve')
    assert not (tmp_path / 'preserve').exists()
    explicit = convert_raster(source, tmp_path / 'explicit', nodata=0)
    with rasterio.open(explicit.data) as delivered:
        assert np.array_equal(delivered.read(1), [[0, 1]])
        assert np.array_equal(delivered.read_masks(1), [[0, 255]])
    assert json.loads(explicit.report.read_text())['source']['nodata'] == [number]
    assert source.read_bytes() == source_bytes and underlying.read_bytes() == pixels_bytes


@pytest.mark.parametrize('options,match', [
    ({'dtype': 'complex64'}, 'dtype'),
    ({'compression': 'jpeg'}, 'compression'),
    ({'nodata': True}, 'boolean'),
    ({'nodata': '0'}, 'NoData'),
    ({'nodata': -9999}, 'NoData'),
    ({'nodata': 2**70}, 'NoData'),
    ({'block_size': 129}, 'block_size'),
    ({'overviews': [4, 2]}, 'Overview'),
    ({'overviews': [True]}, 'Overview'),
    ({'resampling': 'magic'}, 'resampling'),
    ({'loss_policy': 'allow'}, 'loss_policy'),
    ({'driver': 'JPEG'}, 'drivers'),
])
def test_invalid_options_fail_without_publication(tmp_path, options, match):
    source = raster(tmp_path, np.ones((8, 8), dtype='uint8'))
    with pytest.raises(ValueError, match=match):
        convert_raster(source, tmp_path / 'delivery', **options)
    assert not (tmp_path / 'delivery').exists()
