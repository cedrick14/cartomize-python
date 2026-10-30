"""G06 decisions survive workers/sessions and lead to inspectable deliveries."""
from copy import deepcopy
import json
import os
from pathlib import Path
import threading

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import Point

pytest.importorskip('PySide6')
from PySide6.QtCore import QEventLoop, QSettings, Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QStyle, QStyleOptionComboBox, QWidget

from cartomize.desktop_conversion import ConversionPage
from cartomize.desktop_session import capture_widgets, restore_widgets


@pytest.fixture(scope='module')
def application():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def page(application):
    widget = ConversionPage()
    yield widget
    widget.close()
    widget.deleteLater()
    application.processEvents()


def vector_file(tmp_path, *, multilayer=False):
    source = tmp_path / 'source.gpkg'
    gpd.GeoDataFrame({'village_name': ['Mboukou', 'Bilala'], 'population': [8, 12]},
        geometry=[Point(15, -4.3), Point(15.1, -4.2)], crs=4326).to_file(source, layer='villages', index=False)
    if multilayer:
        gpd.GeoDataFrame({'village_name': ['Dimonika'], 'population': [10]},
            geometry=[Point(15.2, -4.1)], crs=4326).to_file(source, layer='other', index=False)
    return source


def raster_file(tmp_path):
    source = tmp_path / 'source.tif'
    with rasterio.open(source, 'w', driver='GTiff', width=32, height=32, count=1,
                       dtype='int16', nodata=-9999, crs='EPSG:32733',
                       transform=from_origin(500000, 9500000, 30, 30)) as dataset:
        values = np.arange(1024, dtype='int16').reshape(32, 32)
        values[0, 0] = -9999
        dataset.write(values, 1)
    return source


def inspect(page, source):
    page.source.edit.setText(str(source))
    path = page.inspection_job()(lambda *_: None, threading.Event())
    page.show_result(path)
    return path


def select(page, name):
    for index in range(page.layer.count()):
        if page.layer.itemText(index) == name:
            page.layer.setCurrentIndex(index)
            return
    raise AssertionError(name)


def rename(page, source, target):
    for row in range(page.field_map.rowCount()):
        if page.field_map.item(row, 0).text() == source:
            page.field_map.item(row, 1).setText(target)
            return
    raise AssertionError(source)


def test_multilayer_source_needs_explicit_choice_and_preserves_each_mapping(page, tmp_path):
    source = vector_file(tmp_path, multilayer=True)
    inspect(page, source)
    assert page.layer.count() == 2
    assert page.layer.currentIndex() == -1
    page.output.edit.setText(str(tmp_path))
    with pytest.raises(ValueError, match='explicitement'):
        page.job({})
    select(page, 'villages')
    with pytest.raises(ValueError, match='champs'):
        page.job({})
    inspect(page, source)
    rename(page, 'village_name', 'village')
    select(page, 'other')
    inspect(page, source)
    rename(page, 'village_name', 'locality')
    select(page, 'villages')
    assert page.field_mapping() == {'village_name': 'village'}
    assert page._selected_layer()['name'] == 'villages'


def test_vector_job_captures_format_layer_renaming_policy_and_destination(page, tmp_path, monkeypatch):
    source = vector_file(tmp_path)
    inspect(page, source)
    page.vector_driver.setCurrentIndex(page.vector_driver.findData('ESRI Shapefile'))
    page.encoding.setCurrentText('CP1252')
    page.loss_policy.setCurrentIndex(page.loss_policy.findData('report'))
    rename(page, 'village_name', 'village')
    page.output_layer.setText('places')
    page.output.edit.setText(str(tmp_path))
    page.folder.setText('captured')
    import cartomize.desktop_conversion as conversion
    captured = []
    monkeypatch.setattr(conversion, 'execute_operation', lambda *args, **kwargs: captured.append((args, kwargs)))
    run = page.job({})
    page.source.edit.setText(str(tmp_path / 'later.gpkg'))
    page.vector_driver.setCurrentIndex(0)
    rename(page, 'village_name', 'changed')
    page.folder.setText('later')
    assert run(lambda *_: None, threading.Event()) == tmp_path / 'captured' / 'operation.json'
    args, kwargs = captured[0]
    assert args[0] == 'vector.convert'
    assert args[1] == dict(source=str(source), layer='villages', driver='ESRI Shapefile',
        encoding='CP1252', output_layer='places', field_map={'village_name': 'village'}, loss_policy='report')
    assert args[2] == tmp_path / 'captured'


def test_raster_job_captures_nodata_pyramids_numeric_type_and_compression(page, tmp_path, monkeypatch):
    page.kind.setCurrentIndex(page.kind.findData('raster'))
    source = raster_file(tmp_path)
    inspect(page, source)
    page.raster_driver.setCurrentIndex(page.raster_driver.findData('COG'))
    page.dtype.setCurrentIndex(page.dtype.findData('float32'))
    page.nodata_mode.setCurrentIndex(page.nodata_mode.findData('value'))
    page.nodata_value.setText('0')
    page.compression.setCurrentIndex(page.compression.findData('deflate'))
    page.overviews_mode.setCurrentIndex(page.overviews_mode.findData('custom'))
    page.overviews.setText('4, 2, 8')
    page.resampling.setCurrentIndex(page.resampling.findData('average'))
    page.tile_size.setCurrentIndex(page.tile_size.findData(256))
    page.output.edit.setText(str(tmp_path))
    import cartomize.desktop_conversion as conversion
    captured = []
    monkeypatch.setattr(conversion, 'execute_operation', lambda *args, **kwargs: captured.append((args, kwargs)))
    run = page.job({})
    page.nodata_value.setText('255')
    page.dtype.setCurrentIndex(0)
    page.overviews.clear()
    run(lambda *_: None, threading.Event())
    assert captured[0][0][0] == 'raster.convert'
    parameters = captured[0][0][1]
    assert parameters['dtype'] == 'float32'
    assert parameters['nodata'] == 0
    assert parameters['overviews'] == [2, 4, 8]
    assert parameters['resampling'] == 'average'
    assert parameters['compression'] == 'deflate'
    assert parameters['block_size'] == 256


@pytest.mark.parametrize('value,expected', [('nan', 'nan'), ('-9999', -9999), ('0.5', .5), ('9007199254740993', 9007199254740993)])
def test_nodata_parsing_does_not_confuse_zero_none_or_large_integers(page, value, expected):
    page.nodata_mode.setCurrentIndex(page.nodata_mode.findData('value'))
    page.nodata_value.setText(value)
    assert page.raster_parameters()['nodata'] == expected
    page.nodata_mode.setCurrentIndex(page.nodata_mode.findData('none'))
    assert page.raster_parameters()['nodata'] is None
    page.nodata_mode.setCurrentIndex(page.nodata_mode.findData('preserve'))
    assert page.raster_parameters()['nodata'] == 'preserve'


@pytest.mark.parametrize('value', ['', 'inf', '-Infinity', 'texte'])
def test_invalid_explicit_nodata_is_rejected(page, value):
    page.nodata_mode.setCurrentIndex(page.nodata_mode.findData('value'))
    page.nodata_value.setText(value)
    with pytest.raises(ValueError, match='NoData'):
        page.raster_parameters()


def test_vector_and_raster_session_choices_and_results_restore(page, application, tmp_path):
    source = vector_file(tmp_path, multilayer=True)
    inspect(page, source)
    select(page, 'villages')
    inspect(page, source)
    rename(page, 'village_name', 'locality')
    page.vector_driver.setCurrentIndex(page.vector_driver.findData('ESRI Shapefile'))
    page.encoding.setCurrentText('CP1252')
    page.output.edit.setText(str(tmp_path))
    page.nodata_mode.setCurrentIndex(page.nodata_mode.findData('value'))
    page.nodata_value.setText('-9999')
    page.converted_data.setText(str(source))
    report = tmp_path / 'report.json'
    report.write_text('{}', encoding='utf-8')
    page.converted_report.setText(str(report))
    states = deepcopy(capture_widgets(page))
    restored = ConversionPage()
    try:
        restore_widgets(restored, states)
        restored.restore_controls()
        assert restored.field_mapping() == {'village_name': 'locality'}
        assert restored._selected_layer()['name'] == 'villages'
        assert restored.encoding.currentText() == 'CP1252'
        assert restored.raster_parameters()['nodata'] == -9999
        assert restored.report_button.isEnabled() and restored.data_button.isEnabled()
        assert callable(restored.job({}))
        # Repeated restores on an already populated page must not leak the
        # previous selected layer's edited mapping into the saved selection.
        select(restored, 'other')
        inspect(restored, source)
        rename(restored, 'population', 'count')
        restore_widgets(restored, states)
        restored.restore_controls()
        select(restored, 'other')
        inspect(restored, source)
        assert restored.field_mapping() is None
    finally:
        restored.close()
        application.processEvents()


def test_stale_source_inspection_and_cancelled_inspection_never_enable_old_layer(page, tmp_path):
    source = vector_file(tmp_path)
    page.source.edit.setText(str(source))
    run = page.inspection_job()
    page.source.edit.setText(str(tmp_path / 'other.gpkg'))
    path = run(lambda *_: None, threading.Event())
    page.show_result(path)
    assert page.layer.count() == 0
    assert 'précédents' in page.inspection_status.text()
    page.source.edit.setText(str(source))
    event = threading.Event()
    event.set()
    import cartomize as cm
    run = page.inspection_job()
    temporary = Path(page._preview_dirs[-1].name)
    with pytest.raises(cm.ProcessingCancelled):
        run(lambda *_: None, event)
    assert not temporary.exists()


def test_portable_session_relocates_inspection_identity_with_renamed_fields(page, application, tmp_path):
    from cartomize.session import save_session, load_session
    source = vector_file(tmp_path)
    inspect(page, source)
    rename(page, 'village_name', 'locality')
    page.output.edit.setText(str(tmp_path))
    archive = save_session({'widgets': capture_widgets(page)}, tmp_path / 'conversion.cmz', portable=True)
    loaded = load_session(archive, directory=tmp_path / 'relocated')
    assert not loaded.missing
    restored = ConversionPage()
    try:
        restore_widgets(restored, loaded.state['widgets'])
        restored.restore_controls()
        assert restored.source.text() != str(source)
        assert Path(restored.source.text()).is_file()
        assert restored._selected_layer()['source_signature'] == restored.source_configuration()[2]
        assert restored.field_mapping() == {'village_name': 'locality'}
        assert callable(restored.job({}))
    finally:
        restored.close()
        application.processEvents()


def wait_for_window(window, application):
    if window.thread is not None:
        loop = QEventLoop()
        timer = QTimer()
        timer.timeout.connect(lambda: loop.quit() if window.thread is None else None)
        timer.start(10)
        QTimer.singleShot(20000, loop.quit)
        loop.exec()
        timer.stop()
    assert window.thread is None, window.status.text()
    assert window.status.text().startswith('Traitement terminé'), window.status.text()
    application.processEvents()


@pytest.mark.parametrize('kind', ['vector', 'raster'])
def test_conversion_uses_worker_and_loads_data_report_and_transfers(application, tmp_path, monkeypatch, kind):
    import cartomize.desktop as desktop
    monkeypatch.setattr(desktop, 'QSettings', lambda *args: QSettings(str(tmp_path / 'worker.ini'), QSettings.Format.IniFormat))
    source = vector_file(tmp_path) if kind == 'vector' else raster_file(tmp_path)
    window = desktop.CartomizeWindow()
    try:
        window.select_tool('conversion')
        page = window.tool('conversion')
        page.kind.setCurrentIndex(page.kind.findData(kind))
        page.source.edit.setText(str(source))
        page.output.edit.setText(str(tmp_path))
        if kind == 'vector':
            page.vector_driver.setCurrentIndex(page.vector_driver.findData('FlatGeobuf'))
        else:
            page.raster_driver.setCurrentIndex(page.raster_driver.findData('COG'))
        page.inspect_source()
        wait_for_window(window, application)
        window.start()
        wait_for_window(window, application)
        record = json.loads(Path(window.output_path).read_text(encoding='utf-8'))
        products = record['products']
        assert products['data'] in window.workspace.records
        assert products['report'] in window.workspace.records
        assert any(item['data'] == products['data'] for item in window.results)
        assert page.report_button.isEnabled() and page.data_button.isEnabled()
        page.report_button.click()
        assert window.workspace.catalog.currentData() == products['report']
        page.data_button.click()
        assert window.workspace.catalog.currentData() == products['data']
        assert window.result_target.findData('conversion') >= 0
    finally:
        if window.thread is not None:
            window.cancel()
            window.thread.wait(10000)
            application.processEvents()
        window.close()
        application.processEvents()


@pytest.mark.parametrize('kind,font_size,wide_layer_metrics', [
    pytest.param('vector', 12, False, id='vector-12'),
    pytest.param('vector', 16, False, id='vector-16'),
    pytest.param('raster', 16, False, id='raster-16'),
    pytest.param('vector', 12, True, id='vector-12-wide-layer'),
    pytest.param('vector', 16, True, id='vector-16-wide-layer'),
])
def test_conversion_controls_fit_compact_window(application, tmp_path, monkeypatch, kind, font_size, wide_layer_metrics):
    import cartomize.desktop as desktop
    if wide_layer_metrics:
        import cartomize.desktop_conversion as conversion
        original_combo = conversion._combo

        def wide_combo(choices, *args, **kwargs):
            control = original_combo(choices, *args, **kwargs)
            if not choices:  # Layer selector, before Qt caches its size hint.
                font = control.font()
                font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, font_size / 2)
                control.setFont(font)
            return control

        monkeypatch.setattr(conversion, '_combo', wide_combo)
    monkeypatch.setattr(desktop, 'QSettings', lambda *args: QSettings(str(tmp_path / 'compact.ini'), QSettings.Format.IniFormat))
    window = desktop.CartomizeWindow()
    try:
        window._workbench.font_size.setValue(font_size)
        window.resize(1100, 740)
        window.show()
        window.select_tool('conversion')
        page = window.tool('conversion')
        page.kind.setCurrentIndex(page.kind.findData(kind))
        source = vector_file(tmp_path) if kind == 'vector' else raster_file(tmp_path)
        inspect(page, source)
        page.output.edit.setText(str(tmp_path))
        if kind == 'raster':
            page.nodata_mode.setCurrentIndex(page.nodata_mode.findData('value'))
            page.nodata_value.setText('-9999')
            page.overviews_mode.setCurrentIndex(page.overviews_mode.findData('custom'))
        QTest.qWait(40)
        scroll = window.stack.currentWidget()
        for control in (page.source, page.field_map if kind == 'vector' else page.compression,
                        page.loss_policy, page.output, page.report_button):
            scroll.ensureWidgetVisible(control)
            QTest.qWait(10)
            geometry = dict(
                viewport=scroll.viewport().size().toTuple(), page=page.size().toTuple(),
                minimum=page.minimumSizeHint().toTuple(), kind=kind, font_size=font_size,
                wide_layer_metrics=wide_layer_metrics, style=application.style().objectName(),
                horizontal_range=scroll.horizontalScrollBar().maximum())
            if geometry['horizontal_range']:
                names = {id(value): key for key, value in vars(page).items() if isinstance(value, QWidget)}

                def dimensions(widget):
                    text = getattr(widget, 'text', getattr(widget, 'currentText', lambda: ''))()
                    return dict(type=type(widget).__name__, name=names.get(id(widget), widget.objectName()),
                        text=text[:120], text_width=widget.fontMetrics().horizontalAdvance(text),
                        minimum_size_hint=widget.minimumSizeHint().toTuple(),
                        size_hint=widget.sizeHint().toTuple(), minimum_size=widget.minimumSize().toTuple(),
                        geometry=widget.geometry().getRect(), font_family=widget.font().family(),
                        font_pixels=widget.font().pixelSize(), font_points=widget.font().pointSizeF(),
                        horizontal_policy=widget.sizePolicy().horizontalPolicy().name,
                        word_wrap=widget.wordWrap() if isinstance(widget, QLabel) else None)

                geometry['page_dimensions'] = dimensions(page)
                geometry['vector_section'] = dimensions(page.vector_section)
                geometry['vector_layout_minimum'] = page.vector_section.layout().minimumSize().toTuple()
                geometry['page_layout_minimum'] = page.layout.minimumSize().toTuple()
                geometry['controls'] = sorted([
                    dimensions(child) for child in page.findChildren(QWidget)
                    if child.isVisible() and (id(child) in names or isinstance(child, QLabel)
                        or child.parentWidget() in (page.source, page.output))
                ], key=lambda item: item['minimum_size_hint'][0], reverse=True)
                print('Conversion form geometry: ' + json.dumps(geometry, ensure_ascii=False))
            assert scroll.horizontalScrollBar().maximum() == 0, json.dumps(geometry, ensure_ascii=False)
            assert control.width() <= scroll.viewport().width()
            assert control.width() >= 100
        for control in ([page.kind, page.layer, page.vector_driver, page.encoding, page.loss_policy]
                        if kind == 'vector' else [page.kind, page.raster_driver, page.dtype, page.nodata_mode,
                            page.compression, page.tile_size, page.overviews_mode, page.resampling, page.loss_policy]):
            assert control.width() >= 100, (control.currentText(), control.size().toTuple())
        assert window.run_button.isVisible()
        if kind == 'vector':
            header = page.field_map.horizontalHeader()
            assert header.height() >= header.fontMetrics().height() + 12
            option = QStyleOptionComboBox()
            page.layer.initStyleOption(option)
            text_area = page.layer.style().subControlRect(QStyle.ComplexControl.CC_ComboBox, option,
                QStyle.SubControl.SC_ComboBoxEditField, page.layer)
            assert page.layer.fontMetrics().horizontalAdvance(page.layer.placeholderText()) <= text_area.width()
        assert page.vector_section.isVisible() == (kind == 'vector')
        assert page.raster_section.isVisible() == (kind == 'raster')
    finally:
        window.close()
        application.processEvents()
