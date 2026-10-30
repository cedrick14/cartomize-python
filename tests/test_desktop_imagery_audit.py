"""Coverage diagnostics use the same selected scenes in the desktop worker."""
import json
import os
from pathlib import Path
import threading

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
import pytest
from rasterio.transform import from_origin
from shapely.geometry import box

pytest.importorskip('PySide6')
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

import cartomize as cm
from cartomize.desktop import CartomizeWindow


@pytest.fixture(scope='module')
def application():
    return QApplication.instance() or QApplication([])


def wait(window):
    if window.thread is not None:
        loop = QEventLoop()
        timer = QTimer()
        timer.timeout.connect(lambda: loop.quit() if window.thread is None else None)
        timer.start(10)
        QTimer.singleShot(20000, loop.quit)
        loop.exec()
        timer.stop()
    assert window.thread is None, window.status.text()


def configure(window, write_raster, tmp_path):
    files = []
    for scene, x in [('A', 300000), ('B', 300020)]:
        for band, value in [('red', .2), ('nir', .5)]:
            files.append(str(write_raster(f'{scene}_{band}.tif', np.full((2, 2), value, dtype='float32'),
                                          transform=from_origin(x, 9500000, 10, 10))))
    zone = tmp_path / 'zone.geojson'
    cm.GeoDataFrame(geometry=[box(300000, 9499980, 300040, 9500000)], crs=32733).to_file(zone)
    window.select_tool('prepare')
    page = window.tool('prepare')
    page.mode.setCurrentIndex(1)
    page.files = files
    page.load_inputs()
    page.clouds.setChecked(False)
    for row in range(4):
        page.assets.item(row, 1).setText('A' if row < 2 else 'B')
        page.assets.item(row, 2).setText('red' if row % 2 == 0 else 'nir')
    page.aoi.edit.setText(str(zone))
    page.dates.setChecked(True)
    page.output.edit.setText(str(tmp_path))
    page.name.setText('preparation')
    return page


def test_audit_worker_selected_scenes_then_preparation(application, write_raster, tmp_path, monkeypatch):
    window = CartomizeWindow()
    try:
        page = configure(window, write_raster, tmp_path)
        # The current, possibly manually edited selection is authoritative.
        monkeypatch.setattr(cm, 'discover_scenes', lambda *_: pytest.fail('The audit must not rediscover inputs'))
        page.diagnose_coverage()
        assert window.thread is not None
        wait(window)
        assert window.status.text().startswith('Traitement terminé'), window.status.text()
        report = json.loads(Path(window.output_path).read_text())
        assert report['schema'] == 'cartomize.imagery.audit.v1'
        assert report['usable_percent'] == pytest.approx(100.)
        assert report['recommended_action'] == 'mosaic'
        assert page.coverage_scenes.rowCount() == 2
        assert '100,00' in page.coverage_summary.text()
        assert page.apply_audit_button.isEnabled()
        for key in ('coverage', 'gaps'):
            assert report[key] in window.workspace.records
            layer = next(layer for layer in window.results if layer['data'] == report[key])
            assert layer['purpose'] == 'diagnostic'
            with pytest.raises(ValueError, match='scientifique'):
                window.transfer_result(layer, 'classification')
        assert str(Path(window.output_path)) in window.workspace.records
        page.apply_audit_proposal()
        assert page.mosaic.isChecked()
        assert {scene.scene_id for scene in page.selected_scenes()} == {'A', 'B'}
        window.start()
        wait(window)
        assert window.status.text().startswith('Traitement terminé'), window.status.text()
        products = json.loads(Path(window.output_path).read_text())['products']
        product = products[0]
        assert product['report'] in window.workspace.records
        assert product['source_index'] in window.workspace.records
        assert any(layer['data'] == product['source_index'] and layer['purpose'] == 'diagnostic'
                   for layer in window.results)
        assert window.tool('indices').source.text() == product['multiband']
    finally:
        window.close()
        application.processEvents()


def test_selection_and_parameters_invalidate_recommendation(application, write_raster, tmp_path):
    window = CartomizeWindow()
    try:
        page = configure(window, write_raster, tmp_path)
        page.diagnose_coverage()
        wait(window)
        assert page.apply_audit_button.isEnabled(), window.status.text()
        page.assets.cellWidget(2, 0).setChecked(False)
        assert not page.apply_audit_button.isEnabled()
        assert page._audit_report is None
        assert page.coverage_scenes.rowCount() == 0
        assert 'modifiés' in page.coverage_summary.text()
        page.assets.cellWidget(2, 0).setChecked(True)
        page.diagnose_coverage()
        wait(window)
        assert page.apply_audit_button.isEnabled(), window.status.text()
        assert Path(window.output_path).parent.name == 'preparation_diagnostic_02'
        page.clouds.setChecked(not page.clouds.isChecked())
        assert not page.apply_audit_button.isEnabled()
    finally:
        window.close()
        application.processEvents()


def test_failed_band_reload_discards_the_previous_recommendation(application, write_raster, tmp_path):
    window = CartomizeWindow()
    try:
        page = configure(window, write_raster, tmp_path)
        page.diagnose_coverage()
        wait(window)
        assert page.apply_audit_button.isEnabled(), window.status.text()
        previous_report = window.output_path

        page.files = [str(tmp_path / 'band_removed_after_selection.tif')]
        page.inspect_inputs()

        assert page.assets.rowCount() == 0
        assert page._audit_report is None
        assert not page.apply_audit_button.isEnabled()
        assert page.coverage_scenes.rowCount() == 0
        assert 'band_removed_after_selection.tif' in page.inventory.text()
        # The old report remains inspectable, but cannot control the new input.
        assert Path(previous_report).is_file()
        assert previous_report in window.workspace.records
    finally:
        window.close()
        application.processEvents()


def test_proposal_changes_only_scene_selection_and_mosaic(application, write_raster, tmp_path):
    window = CartomizeWindow()
    try:
        page = configure(window, write_raster, tmp_path)
        page.files.append(str(write_raster('B_blue.tif', np.full((2, 2), .1, dtype='float32'),
                                           transform=from_origin(300020, 9500000, 10, 10))))
        page.load_inputs()
        for row, (scene, band) in enumerate([('A','red'),('A','nir'),('B','red'),('B','nir'),('B','blue')]):
            page.assets.item(row, 1).setText(scene)
            page.assets.item(row, 2).setText(band)
        page.assets.cellWidget(4, 0).setChecked(False)
        page.resampling.setCurrentIndex(page.resampling.findData('bilinear'))
        page.separate.setChecked(True)
        page._audit_report = dict(recommended_action='single_scene', recommended_scene_ids=['B'], mosaic_recommended=True)
        page.apply_audit_proposal()
        assert {scene.scene_id for scene in page.selected_scenes()} == {'B'}
        assert set(page.selected_scenes()[0].bands) == {'red', 'nir'}
        assert not page.assets.cellWidget(4, 0).isChecked()
        assert not page.mosaic.isChecked()
        assert page.resampling.currentData() == 'bilinear'
        assert page.separate.isChecked()
        assert page.dates.isChecked()
        assert not page.apply_audit_button.isEnabled()
    finally:
        window.close()
        application.processEvents()


def test_audit_requires_selection_and_aoi_before_worker(application, write_raster, tmp_path):
    window = CartomizeWindow()
    try:
        window.select_tool('prepare')
        page = window.tool('prepare')
        page.diagnose_coverage()
        assert window.thread is None
        assert 'Analyser les bandes' in window.status.text()
        page = configure(window, write_raster, tmp_path)
        page.aoi.edit.clear()
        page.diagnose_coverage()
        assert window.thread is None
        assert 'zone d’étude' in window.status.text()
        assert not (tmp_path / 'preparation_diagnostic').exists()
    finally:
        window.close()
        application.processEvents()


def test_diagnostic_does_not_replace_an_active_worker(application, monkeypatch):
    window = CartomizeWindow()
    try:
        window.select_tool('calculator')
        calculator = window.tool('calculator')
        def current_job(progress, cancel):
            cancel.wait(10)
            if cancel.is_set():
                raise cm.ProcessingCancelled()
            raise RuntimeError('Test worker was not cancelled')
        monkeypatch.setattr(calculator, 'job', lambda options: current_job)
        window.start()
        worker = window.thread
        assert worker is not None
        page = window.tool('prepare')
        page.diagnose_coverage()
        assert window.thread is worker
        assert window.pages[window.stack.currentIndex()] is calculator
        assert page._next_action is None
        window.cancel()
        wait(window)
        assert window.status.text() == 'Traitement interrompu.'
    finally:
        if window.thread is not None:
            window.cancel()
            wait(window)
        window.close()
        application.processEvents()


def test_completed_diagnostic_cannot_restore_a_stale_proposal(application, write_raster, tmp_path, monkeypatch):
    from cartomize import imagery_audit
    entered, release = threading.Event(), threading.Event()
    original = imagery_audit.audit_imagery
    def delayed(*args, **kwargs):
        entered.set()
        if not release.wait(5):
            raise RuntimeError('Test diagnostic was not released')
        return original(*args, **kwargs)
    monkeypatch.setattr(imagery_audit, 'audit_imagery', delayed)
    window = CartomizeWindow()
    try:
        page = configure(window, write_raster, tmp_path)
        page.diagnose_coverage()
        assert entered.wait(5)
        assert not page.resolution.isEnabled()
        # The console or another integration can still edit a disabled widget.
        page.resolution.setValue(20)
        release.set()
        wait(window)
        assert window.status.text().startswith('Traitement terminé'), window.status.text()
        assert not page.apply_audit_button.isEnabled()
        assert page._audit_report is None
        assert 'configuration précédente' in page.coverage_summary.text()
        assert Path(window.output_path).is_file()
    finally:
        release.set()
        if window.thread is not None:
            wait(window)
        window.close()
        application.processEvents()
