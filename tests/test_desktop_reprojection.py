"""Batch selections, geodetic operation choices and execution survive the UI."""
import json
import os
from pathlib import Path
import threading

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import geopandas as gpd
import pytest
from shapely.geometry import Point

pytest.importorskip('PySide6')
from PySide6.QtCore import QEventLoop, QSettings, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from cartomize.desktop_vector import VectorPage
from cartomize.desktop_session import capture_widgets, restore_widgets


@pytest.fixture(scope='module')
def application():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def page(application):
    widget = VectorPage()
    widget.operation.setCurrentIndex(widget.operation.findData('reproject_batch'))
    yield widget
    widget.close()
    widget.deleteLater()
    application.processEvents()


def source_file(tmp_path):
    source = tmp_path / 'sources.gpkg'
    gpd.GeoDataFrame({'identifier': [2**53 + 3], 'code': ['001'], 'fid': [44]},
        geometry=[Point(15., -4.3)], crs=4326).to_file(source, layer='sites', index=False,
            layer_options={'FID': 'internal_source_id'})
    gpd.GeoDataFrame({'code': ['002']}, geometry=[Point(15.4, -4.4)], crs=4326).to_file(
        source, layer='other_sites', index=False)
    return source


def inspect_page(page, source, tmp_path):
    page.add_reprojection_sources([source])
    page.batch_target_crs.setText('EPSG:32733')
    page.output.edit.setText(str(tmp_path))
    job = page.reprojection_inspection_job()
    report = job(lambda done, total: None, threading.Event())
    page.show_result(report)
    return report


def test_discover_multilayer_sources_and_execute_only_checked_layer(page, tmp_path):
    source = source_file(tmp_path)
    original = source.read_bytes()
    inspect_page(page, source, tmp_path)
    assert page.batch_layers.count() == 2
    names = [page.batch_layers.item(i).data(Qt.ItemDataRole.UserRole)['layer'] for i in range(2)]
    keep = names.index('sites')
    page.batch_layers.item(1 - keep).setCheckState(Qt.CheckState.Unchecked)
    page.batch_layers.setCurrentRow(keep)
    assert page.batch_operation.count() >= 2
    page.batch_operation.setCurrentIndex(1)
    assert page.batch_operation.currentData().startswith('op_')
    assert 'Précision annoncée' in page.batch_operation_details.toPlainText()
    job = page.job({'overwrite': False})
    manifest = job(lambda done, total: None, threading.Event())
    record = json.loads(Path(manifest).read_text(encoding='utf-8'))
    files = [Path(value) for value in record['products'].values() if str(value).endswith('.gpkg')]
    assert len(files) == 1
    result = gpd.read_file(files[0])
    assert result.crs.to_epsg() == 32733
    assert result.identifier.tolist() == [2**53 + 3]
    assert result.code.tolist() == ['001']
    assert result.fid.tolist() == [44]
    # UTM zone 33 has its central meridian at 15 degrees and a 500 km false easting.
    assert result.geometry.x.iloc[0] == pytest.approx(500000., abs=1e-5)
    assert source.read_bytes() == original


def test_batch_job_captures_selection_and_policy_before_worker_starts(page, tmp_path, monkeypatch):
    source = source_file(tmp_path)
    inspect_page(page, source, tmp_path)
    page.batch_layers.item(1).setCheckState(Qt.CheckState.Unchecked)
    first = page.batch_layers.item(0).data(Qt.ItemDataRole.UserRole)
    page.batch_layers.setCurrentRow(0)
    page.batch_operation.setCurrentIndex(1)
    operation = page.batch_operation.currentData()
    page.batch_require_best.setChecked(False)
    page.batch_area_policy.setCurrentIndex(page.batch_area_policy.findData('warn'))
    page.batch_folder.setText('captured')
    captured = []
    import cartomize.desktop_reprojection as desktop_reprojection
    monkeypatch.setattr(desktop_reprojection, 'execute_operation', lambda *args, **kwargs: captured.append((args, kwargs)))
    run = page.job({'overwrite': False})
    page.batch_operation.setCurrentIndex(0)
    page.batch_require_best.setChecked(True)
    page.batch_area_policy.setCurrentIndex(page.batch_area_policy.findData('error'))
    page.batch_layers.item(1).setCheckState(Qt.CheckState.Checked)
    page.batch_folder.setText('later')
    path = run(lambda *_: None, threading.Event())
    arguments, _ = captured[0]
    assert arguments[0] == 'vector.reproject_batch'
    assert arguments[1]['sources'] == [{'path': str(source), 'layer': first['layer']}]
    assert arguments[1]['operations'] == {first['id']: operation}
    assert arguments[1]['require_best'] is False
    assert arguments[1]['area_policy'] == 'warn'
    assert path == tmp_path / 'captured' / 'operation.json'


def test_saved_session_restores_layer_checkboxes_and_stable_operation_id(page, application, tmp_path):
    source = source_file(tmp_path)
    inspect_page(page, source, tmp_path)
    page.batch_layers.setCurrentRow(0)
    page.batch_operation.setCurrentIndex(1)
    selected_operation = page.batch_operation.currentData()
    page.batch_layers.item(1).setCheckState(Qt.CheckState.Unchecked)
    page.batch_require_best.setChecked(False)
    captured = capture_widgets(page)
    restored = VectorPage()
    try:
        restore_widgets(restored, captured)
        restored.restore_controls()
        assert restored.operation.currentData() == 'reproject_batch'
        assert restored.output.mode == 'directory'
        assert restored.cancellable
        assert restored.batch_layers.item(1).checkState() == Qt.CheckState.Unchecked
        assert restored.batch_layers.item(0).data(Qt.ItemDataRole.UserRole)['selected_operation'] == selected_operation
        assert restored.batch_operation.currentData() == selected_operation
        assert not restored.batch_require_best.isChecked()
        assert callable(restored.job({'overwrite': False}))
        restored.operation.setCurrentIndex(restored.operation.findData('buffer'))
        assert restored.output.mode == 'save'
        assert restored.batch_section.isHidden()
        assert not restored.source.isHidden()
        restored.operation.setCurrentIndex(restored.operation.findData('repair_geometries'))
        assert restored.output.mode == 'directory'
        assert not restored.quality_note.isHidden()
    finally:
        restored.close()
        restored.deleteLater()
        application.processEvents()


def test_changed_target_rejects_stale_preview_and_stale_job(page, tmp_path):
    source = source_file(tmp_path)
    preview = inspect_page(page, source, tmp_path)
    page.batch_target_crs.setText('EPSG:3857')
    page.show_result(preview)
    assert 'précédents' in page.batch_status.text()
    with pytest.raises(ValueError, match='ont changé'):
        page.job({'overwrite': False})


def test_previous_session_keeps_its_tool_and_exposes_new_batch_operation(page, application):
    page.operation.setCurrentIndex(page.operation.findData('buffer'))
    previous = {name: state for name, state in capture_widgets(page).items()
                if not name.startswith('batch_')}
    previous['operation']['items'] = [item for item in previous['operation']['items']
                                      if item[1] != 'reproject_batch']
    restored = VectorPage()
    try:
        restore_widgets(restored, previous)
        assert restored.operation.findData('reproject_batch') == -1
        restored.restore_controls()
        assert restored.operation.currentData() == 'buffer'
        assert restored.operation.findData('reproject_batch') >= 0
        assert restored.output.mode == 'save'
        restored.operation.setCurrentIndex(restored.operation.findData('reproject_batch'))
        assert restored.output.mode == 'directory'
        assert not restored.batch_section.isHidden()
    finally:
        restored.close()
        restored.deleteLater()
        application.processEvents()


def test_disappearing_explicit_operation_never_silently_becomes_automatic(page, tmp_path):
    source = source_file(tmp_path)
    preview = inspect_page(page, source, tmp_path)
    page.batch_layers.setCurrentRow(0)
    page.batch_operation.setCurrentIndex(1)
    choice = page.batch_operation.currentData()
    record = json.loads(Path(preview).read_text(encoding='utf-8'))
    record['inspection']['layers'][0]['catalogue']['operations'] = []
    record['inspection']['layers'][0]['catalogue']['best_available'] = False
    record['inspection']['layers'][0]['catalogue']['unavailable_operations'] = [
        {'name': 'Transformation avec grille', 'grids': [{'name': 'missing_grid.tif', 'available': False}]}]
    Path(preview).write_text(json.dumps(record), encoding='utf-8')
    page.show_result(preview)
    assert page.batch_operation.currentData() == choice
    assert 'indisponible' in page.batch_operation.currentText()
    assert 'Grille absente : missing_grid.tif' in page.batch_operation_details.toPlainText()
    assert page.batch_require_best.isChecked()
    with pytest.raises(ValueError, match='transformation disponible'):
        page.job({'overwrite': False})


@pytest.mark.parametrize('text', ['0', '-1', 'nan', 'inf', 'texte'])
def test_invalid_accuracy_is_rejected_before_starting(page, tmp_path, text):
    page.add_reprojection_sources([tmp_path / 'input.gpkg'])
    page.batch_target_crs.setText('EPSG:32733')
    page.batch_accuracy.setText(text)
    with pytest.raises(ValueError, match='précision'):
        page.reprojection_inspection_job()


def test_pre_cancelled_inspection_publishes_no_report(page, tmp_path):
    source = source_file(tmp_path)
    page.add_reprojection_sources([source])
    page.batch_target_crs.setText('EPSG:32733')
    run = page.reprojection_inspection_job()
    event = threading.Event()
    event.set()
    from cartomize import ProcessingCancelled
    with pytest.raises(ProcessingCancelled):
        run(lambda *_: None, event)
    assert not Path(page._batch_preview_dirs[-1].name).exists()


@pytest.mark.parametrize('font_size,wide_labels', [(12, False), (16, False), (12, True)],
                         ids=['12', '16', 'wide_native_labels'])
def test_batch_form_fits_compact_window(application, tmp_path, monkeypatch, font_size, wide_labels):
    import cartomize.desktop as desktop
    monkeypatch.setattr(desktop, 'QSettings', lambda *args: QSettings(str(tmp_path / 'appearance.ini'), QSettings.Format.IniFormat))
    window = desktop.CartomizeWindow()
    try:
        window._workbench.font_size.setValue(font_size)
        window.resize(1100, 740)
        window.show()
        window.select_tool('vector')
        page = window.tool('vector')
        page.operation.setCurrentIndex(page.operation.findData('reproject_batch'))
        checkboxes = (page.batch_recursive, page.batch_ballpark, page.batch_require_best)
        if wide_labels:
            # Reproduce native text wider than the Linux default. Unwrapped
            # checkbox labels force a horizontal scrollbar at these metrics.
            for checkbox in checkboxes:
                checkbox.setStyleSheet('font-size: 24px;')
        QTest.qWait(50)
        scroll = window.stack.currentWidget()
        for control in (page.batch_inspect_button, page.batch_layers, page.output):
            scroll.ensureWidgetVisible(control)
            QTest.qWait(20)
            geometry = {
                'font_size': font_size,
                'wide_labels': wide_labels,
                'style': application.style().objectName(),
                'viewport': scroll.viewport().size().toTuple(),
                'page': page.size().toTuple(),
                'minimum_hint': page.minimumSizeHint().toTuple(),
                'layout_minimum': page.layout.minimumSize().toTuple(),
                'batch_minimum': page.batch_section.minimumSizeHint().toTuple(),
                'horizontal_range': scroll.horizontalScrollBar().maximum(),
            }
            if geometry['horizontal_range']:
                names = {id(value): key for key, value in vars(page).items() if isinstance(value, QWidget)}
                geometry['widest_controls'] = sorted([
                    {'minimum_width': child.minimumSizeHint().width(),
                     'width': child.width(), 'type': type(child).__name__,
                     'name': names.get(id(child), child.objectName()),
                     'text': getattr(child, 'text', lambda: '')()[:120],
                     'font_family': child.font().family(),
                     'font_pixels': child.font().pixelSize(),
                     'font_points': child.font().pointSizeF()}
                    for child in page.findChildren(QWidget) if child.isVisible()
                ], key=lambda record: record['minimum_width'], reverse=True)[:12]
                print('Batch form geometry: ' + json.dumps(geometry, ensure_ascii=False))
            assert scroll.horizontalScrollBar().maximum() == 0, json.dumps(geometry, ensure_ascii=False)
            assert control.width() <= scroll.viewport().width()
        for checkbox in checkboxes:
            assert checkbox.width() >= checkbox.minimumSizeHint().width()
            assert checkbox.height() >= checkbox.sizeHint().height()
        assert window.run_button.isVisible()
        assert not page.source.isVisible()
    finally:
        window.close()
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


def test_inspection_and_batch_run_through_window_worker_and_load_layers(application, tmp_path, monkeypatch):
    import cartomize.desktop as desktop
    monkeypatch.setattr(desktop, 'QSettings', lambda *args: QSettings(str(tmp_path / 'worker.ini'), QSettings.Format.IniFormat))
    source = source_file(tmp_path)
    window = desktop.CartomizeWindow()
    try:
        window.select_tool('vector')
        page = window.tool('vector')
        page.operation.setCurrentIndex(page.operation.findData('reproject_batch'))
        page.add_reprojection_sources([source])
        page.batch_target_crs.setText('EPSG:32733')
        page.output.edit.setText(str(tmp_path))
        page.batch_folder.setText('window_batch')
        page.inspect_reprojection_sources()
        wait_for_window(window, application)
        assert page.batch_layers.count() == 2
        window.start()
        wait_for_window(window, application)
        record = json.loads(Path(window.output_path).read_text(encoding='utf-8'))
        products = [path for path in record['products'].values() if str(path).endswith('.gpkg')]
        assert len(products) == 2
        assert all(path in window.workspace.records for path in products)
        assert all(gpd.read_file(path).crs.to_epsg() == 32733 for path in products)
    finally:
        if window.thread is not None:
            window.cancel()
            window.thread.wait(10000)
            application.processEvents()
        window.close()
        application.processEvents()


def test_operation_dialog_uses_geodetic_policies_and_preserves_mapping(application):
    from cartomize.desktop_processing import OperationDialog
    parameters = dict(sources=[{'path': 'points.gpkg', 'layer': 'sites'}],
        target_crs='EPSG:32733', operations={'sites_id': 'op_definition'},
        area_of_interest=[12., -6., 18., 0.], accuracy=2.5,
        allow_ballpark=False, require_best=True, area_policy='warn')
    record = dict(id='projected', operation='vector.reproject_batch', parameters=parameters)
    dialog = OperationDialog([], record, allow_map=False)
    try:
        assert dialog.controls['area_policy'].currentData() == 'warn'
        assert dialog.controls['allow_ballpark'].isChecked() is False
        assert dialog.controls['require_best'].isChecked()
        result = dialog.value()
        for name, expected in parameters.items():
            assert result['parameters'][name] == expected
    finally:
        dialog.close()
        dialog.deleteLater()
        application.processEvents()
