"""The dedicated raster page preserves zonal-statistics choices in workers."""
import os
import threading
import time

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from shapely.geometry import box

pytest.importorskip('PySide6')
from PySide6.QtCore import QEventLoop, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import cartomize as cm
from cartomize.desktop import CartomizeWindow, Worker
from cartomize.desktop_tools_base import RasterToolsPage


@pytest.fixture(scope='module')
def application():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def page(application):
    widget = RasterToolsPage()
    widget.operation.setCurrentIndex(widget.operation.findData('zonal_stats'))
    try:
        yield widget
    finally:
        widget.close()
        widget.deleteLater()
        application.processEvents()


@pytest.fixture
def inputs(write_raster, tmp_path):
    source = write_raster('scaled.tif', np.array([[0, 10, -9999], [20, 30, 40]], dtype='int16'))
    with rasterio.open(source, 'r+') as dst:
        dst.scales = (0.5,)
        dst.offsets = (-1,)
    zones = tmp_path / 'zones.gpkg'
    gpd.GeoDataFrame({'name': ['partial', 'outside', 'small']}, geometry=[
        box(299990, 9499980, 300030, 9500000),
        box(300050, 9499980, 300070, 9500000),
        box(300001, 9499997, 300003, 9499999),
    ], crs=32733).to_file(zones, index=False)
    return source, zones


def configure(page, inputs, tmp_path):
    source, zones = inputs
    destination = tmp_path / 'statistics.gpkg'
    page.source.edit.setText(str(source))
    page.secondary.edit.setText(str(zones))
    page.output.edit.setText(str(destination))
    return destination


def execute(job):
    event = threading.Event()
    worker = Worker(job, event)
    successes, failures, progress = [], [], []
    worker.succeeded.connect(successes.append)
    worker.failed.connect(failures.append)
    worker.progress.connect(lambda done, total: progress.append((done, total)))
    loop = QEventLoop()
    worker.finished.connect(loop.quit)
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    timer.start(10000)
    worker.start()
    loop.exec()
    timer.stop()
    if worker.isRunning():
        event.set()
        worker.wait(10000)
        pytest.fail('Zonal-statistics worker did not finish')
    worker.wait()
    worker.deleteLater()
    return successes, failures, progress


def wait_until(condition, timeout=10):
    loop = QEventLoop()
    timer = QTimer()
    deadline = time.monotonic() + timeout
    timer.timeout.connect(lambda: loop.quit() if condition() or time.monotonic() >= deadline else None)
    timer.start(10)
    loop.exec()
    timer.stop()
    assert condition(), 'Desktop worker did not reach the expected state'


def test_default_statistics_apply_band_calibration_and_keep_valid_zero(page, inputs, tmp_path):
    destination = configure(page, inputs, tmp_path)
    assert page.value_mode.currentData() == 'physical'
    assert page.all_touched.currentData() is False
    assert not page.include_coverage.isChecked()
    assert page.max_zone_pixels.value() == 250_000_000
    successes, failures, progress = execute(page.job({'overwrite': False}))
    assert not failures, failures
    assert successes == [str(destination)]
    assert progress[-1] == (3, 3)
    result = gpd.read_file(destination)
    assert set(result.columns) == {'name', 'geometry', 'count', 'min', 'max', 'mean', 'sum', 'std'}
    assert result['name'].tolist() == ['partial', 'outside', 'small']
    assert result['count'].tolist() == [5, 0, 0]
    assert result['min'].iloc[0] == -1
    assert result['max'].iloc[0] == 19
    assert result['mean'].iloc[0] == 9
    assert result['sum'].iloc[0] == 45
    assert result['std'].iloc[0] == pytest.approx(np.sqrt(50))
    assert result.loc[1:, ['min', 'max', 'mean', 'sum', 'std']].isna().all().all()
    assert result.crs.to_epsg() == 32733


def test_worker_captures_raw_mode_prefix_coverage_and_limits(page, inputs, tmp_path):
    destination = configure(page, inputs, tmp_path)
    page.value_mode.setCurrentIndex(page.value_mode.findData('raw'))
    page.zonal_prefix.setText('dn_')
    page.include_coverage.setChecked(True)
    page.max_zone_pixels.setValue(8)
    job = page.job({'overwrite': False, 'block_size': 1})
    # A pending worker must use its captured parameters, not the live widgets.
    page.value_mode.setCurrentIndex(page.value_mode.findData('physical'))
    page.zonal_prefix.setText('changed_')
    page.include_coverage.setChecked(False)
    page.all_touched.setCurrentIndex(page.all_touched.findData(True))
    page.max_zone_pixels.setValue(1)
    successes, failures, progress = execute(job)
    assert not failures, failures
    assert successes == [str(destination)]
    result = gpd.read_file(destination)
    assert not any(column.startswith('changed_') for column in result)
    assert 'count' not in result
    assert result['dn_count'].tolist() == [5, 0, 0]
    assert result['dn_min'].iloc[0] == 0
    assert result['dn_mean'].iloc[0] == 20
    assert result['dn_sum'].iloc[0] == 100
    assert result['dn_zone_pixels'].tolist() == [8, 4, 0]
    assert result['dn_raster_pixels'].tolist() == [6, 0, 0]
    assert result['dn_coverage_percent'].iloc[:2].tolist() == [62.5, 0]
    assert np.isnan(result['dn_coverage_percent'].iloc[2])
    assert progress[-1] == (3, 3)


@pytest.mark.parametrize('operation', ['zonal_stats', 'clip'])
def test_all_touched_choice_reaches_zonal_and_clip_algorithms(page, inputs, tmp_path, operation):
    source, _ = inputs
    mask = tmp_path / 'small.gpkg'
    gpd.GeoDataFrame({'name': ['small']}, geometry=[box(300001, 9499997, 300003, 9499999)],
                     crs=32733).to_file(mask, index=False)
    page.operation.setCurrentIndex(page.operation.findData(operation))
    destination = tmp_path / ('small_result.gpkg' if operation == 'zonal_stats' else 'small_result.tif')
    page.source.edit.setText(str(source))
    page.secondary.edit.setText(str(mask))
    page.output.edit.setText(str(destination))
    page.all_touched.setCurrentIndex(page.all_touched.findData(True))
    job = page.job({'overwrite': False})
    page.all_touched.setCurrentIndex(page.all_touched.findData(False))
    successes, failures, _ = execute(job)
    assert not failures, failures
    assert successes == [str(destination)]
    if operation == 'zonal_stats':
        result = gpd.read_file(destination)
        assert result['count'].tolist() == [1]
        assert result['mean'].tolist() == [-1]
    else:
        with rasterio.open(destination) as result:
            assert result.read(1, masked=True).compressed().tolist() == [0]


def test_candidate_pixel_limit_rejects_before_writing(page, inputs, tmp_path):
    destination = configure(page, inputs, tmp_path)
    page.include_coverage.setChecked(True)
    page.max_zone_pixels.setValue(7)
    successes, failures, _ = execute(page.job({'overwrite': False}))
    assert not successes
    assert failures and 'max_zone_pixels' in failures[0]
    assert not destination.exists()


def test_zonal_worker_can_be_cancelled_from_window(application, inputs, tmp_path, monkeypatch):
    original = cm.raster.zonal_stats
    started = threading.Event()

    def waiting_stats(*args, **kwargs):
        started.set()
        assert kwargs['cancel'].wait(10), 'Cancel button did not reach the processing event'
        return original(*args, **kwargs)

    monkeypatch.setattr(cm.raster, 'zonal_stats', waiting_stats)
    window = CartomizeWindow()
    window.select_tool('raster')
    page = window.tool('raster')
    page.operation.setCurrentIndex(page.operation.findData('zonal_stats'))
    destination = configure(page, inputs, tmp_path)
    try:
        window.start()
        wait_until(started.is_set)
        assert window.cancel_button.isEnabled()
        assert not window.stack.isEnabled()
        QTest.mouseClick(window.cancel_button, Qt.MouseButton.LeftButton)
        wait_until(lambda: window.thread is None)
        assert window.status.text() == 'Traitement interrompu.'
        assert not destination.exists()
        assert window.stack.isEnabled()
    finally:
        if window.thread is not None:
            window.cancel()
            wait_until(lambda: window.thread is None)
        window.close()
        application.processEvents()


def test_zonal_controls_are_visible_only_for_their_operations(page):
    zonal = [page.value_mode, page.zonal_prefix, page.include_coverage, page.max_zone_pixels]
    assert all(not widget.isHidden() for widget in zonal)
    assert not page.zonal_note.isHidden()
    assert page.cancellable
    for operation in ['clip', 'reproject', 'reclassify', 'class_areas', 'change_matrix']:
        page.operation.setCurrentIndex(page.operation.findData(operation))
        assert all(widget.isHidden() for widget in zonal)
        assert all(page.form.labelForField(widget).isHidden() for widget in zonal)
        assert page.zonal_note.isHidden()
        assert page.all_touched.isHidden() == (operation != 'clip')
        assert not page.cancellable
    page.operation.setCurrentIndex(page.operation.findData('zonal_stats'))
    assert all(not widget.isHidden() for widget in zonal)
    assert not page.all_touched.isHidden()
    assert page.cancellable
