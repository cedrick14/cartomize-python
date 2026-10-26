"""Quality procedures survive real files, chained operations and desktop jobs."""
import json
import os
from pathlib import Path
import threading

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point, Polygon, box

import cartomize as cm
from cartomize.cli import main


def source_file(tmp_path):
    source = tmp_path / 'original.gpkg'
    identifiers = [2**53 + i for i in range(1, 6)]
    data = gpd.GeoDataFrame(
        {'identifier': identifiers, 'fid': [8, 8, 8, 8, 8],
         'code': ['001', '002', '003', '004', '005']},
        geometry=[Polygon([(0, 0), (4, 4), (0, 4), (4, 0), (0, 0)]),
                  box(10, 0, 12, 2), box(10, 0, 12, 2), None, Polygon()],
        crs=32733,
    )
    data.to_file(source, index=False, layer_options={'FID': 'internal_source_id'})
    return source, identifiers


def test_audit_cli_preserves_large_ids_and_original_fid(tmp_path, capsys):
    source, identifiers = source_file(tmp_path)
    original = source.read_bytes()
    config = tmp_path / 'parameters.json'
    config.write_text(json.dumps({'data': str(source), 'id_field': 'identifier'}), encoding='utf-8')
    assert main(['process', 'vector.audit_geometries', str(config), str(tmp_path / 'audit')]) == 0
    record = json.loads(capsys.readouterr().out)
    assert set(record['products']) == {'primary', 'data', 'report', 'summary', 'issues', 'rejected'}
    assert record['primary'] == record['products']['issues']
    assert all(Path(path).is_file() for path in record['products'].values())
    retained = gpd.read_file(record['products']['data'])
    assert retained.identifier.tolist() == identifiers
    assert retained.fid.tolist() == [8] * 5
    assert retained.code.tolist() == ['001', '002', '003', '004', '005']
    report = pd.read_csv(record['products']['report'], dtype={'feature_id': 'string'})
    assert report.feature_id.tolist() == list(map(str, identifiers))
    summary = json.loads(Path(record['products']['summary']).read_text(encoding='utf-8'))
    assert summary['invalid_geometries'] == 1
    assert summary['duplicate_geometries'] == 1
    assert source.read_bytes() == original


def test_repair_deduplication_and_topology_chain_is_reopenable(tmp_path):
    source, identifiers = source_file(tmp_path)
    original = source.read_bytes()
    steps = [
        dict(id='repair', operation='vector.repair_geometries', parameters={
            'data': str(source), 'id_field': 'identifier', 'missing': 'drop', 'empty': 'drop'}),
        dict(id='unique', operation='vector.deduplicate', parameters={
            'data': '@repair', 'id_field': 'identifier', 'geometry': 'topological'}),
        dict(id='topology', operation='vector.check_topology', parameters={
            'data': '@unique', 'id_field': 'identifier', 'rules': ['duplicates', 'overlaps']}),
    ]
    manifest = cm.run_plan(cm.processing_plan(steps), tmp_path / 'chain')
    record = json.loads(Path(manifest).read_text(encoding='utf-8'))
    repaired = gpd.read_file(record['results']['repair'])
    assert repaired.identifier.tolist() == identifiers[:3]
    assert repaired.geometry.is_valid.all()
    assert repaired.geometry.area.sum() == pytest.approx(16.)
    unique = gpd.read_file(record['results']['unique'])
    assert unique.identifier.tolist() == identifiers[:2]
    assert unique.geometry.area.sum() == pytest.approx(12.)
    assert len(gpd.read_file(record['results']['topology'])) == 0
    for step in steps:
        products = record['products'][step['id']]
        assert Path(products['report']).is_file()
        assert Path(products['summary']).is_file()
        assert Path(products['rejected']).is_file()
    assert len(gpd.read_file(record['products']['repair']['rejected'])) == 2
    assert len(gpd.read_file(record['products']['unique']['rejected'])) == 1
    assert source.read_bytes() == original


def test_quality_errors_and_cancellation_publish_no_partial_bundle(tmp_path):
    source, _ = source_file(tmp_path)
    with pytest.raises(ValueError):
        cm.execute_operation('vector.repair_geometries', {
            'data': str(source), 'missing': 'error'}, tmp_path / 'failed')
    assert not (tmp_path / 'failed').exists()
    event = threading.Event()
    def stop(completed, total):
        if completed:
            event.set()
    with pytest.raises(cm.ProcessingCancelled):
        cm.execute_operation('vector.audit_geometries', {'data': str(source)},
                             tmp_path / 'cancelled', progress=stop, cancel=event)
    assert not (tmp_path / 'cancelled').exists()
    assert not list(tmp_path.glob('.cartomize-*'))


def test_no_quality_operation_can_replace_a_source_directory(tmp_path):
    source, _ = source_file(tmp_path)
    original = source.read_bytes()
    with pytest.raises(ValueError, match='source'):
        cm.execute_operation('vector.audit_geometries', {'data': str(source)}, tmp_path)
    assert source.read_bytes() == original


def application():
    pytest.importorskip('PySide6')
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_chain_dialog_uses_deduplication_null_policy_and_reopens_it():
    app = application()
    from cartomize.desktop_processing import OperationDialog
    dialog = OperationDialog([])
    dialog.operation.setCurrentIndex(dialog.operation.findData('vector.deduplicate'))
    dialog.controls['data'].setCurrentText('input.gpkg')
    dialog.controls['keys'].setCurrentText('["code", "date"]')
    assert dialog.controls['null_keys'].currentData() == 'distinct'
    dialog.controls['keep'].setCurrentIndex(dialog.controls['keep'].findData('last'))
    dialog.controls['order_by'].setCurrentText('date')
    record = dialog.value()
    restored = OperationDialog([], record)
    assert restored.value() == record
    assert record['parameters']['keys'] == ['code', 'date']
    # Attribute joins retain their own unmatched/match/error policy.
    dialog.operation.setCurrentIndex(dialog.operation.findData('vector.join_attributes'))
    assert dialog.controls['null_keys'].currentData() == 'unmatched'
    for widget in (dialog, restored):
        widget.close(); widget.deleteLater()
    app.processEvents()


def test_desktop_quality_worker_captures_rules_and_restores_controls(tmp_path):
    app = application()
    from PySide6.QtCore import QEventLoop, QTimer
    from cartomize.desktop import Worker
    from cartomize.desktop_session import capture_widgets, restore_widgets
    from cartomize.desktop_vector import VectorPage
    source, identifiers = source_file(tmp_path)
    page = VectorPage()
    page.operation.setCurrentIndex(page.operation.findData('repair_geometries'))
    page.source.edit.setText(str(source))
    page.quality_id.setCurrentText('identifier')
    page.repair_missing.setCurrentIndex(page.repair_missing.findData('drop'))
    page.repair_empty.setCurrentIndex(page.repair_empty.findData('drop'))
    page.output.edit.setText(str(tmp_path))
    page.quality_folder.setText('bureau')
    job = page.job({'overwrite': False})
    captured = capture_widgets(page)
    page.repair_missing.setCurrentIndex(page.repair_missing.findData('error'))
    # The pending job owns a snapshot, not mutable widgets.
    worker = Worker(job, threading.Event())
    success, failures = [], []
    worker.succeeded.connect(success.append); worker.failed.connect(failures.append)
    loop = QEventLoop(); worker.finished.connect(loop.quit)
    timer = QTimer(); timer.setSingleShot(True); timer.timeout.connect(loop.quit); timer.start(15000)
    worker.start(); loop.exec(); timer.stop(); worker.wait(1000)
    assert not worker.isRunning()
    assert not failures, failures
    assert success == [str(tmp_path / 'bureau' / 'operation.json')]
    record = json.loads(Path(success[0]).read_text(encoding='utf-8'))
    assert gpd.read_file(record['primary']).identifier.tolist() == identifiers[:3]
    restored = VectorPage(); restore_widgets(restored, captured); restored.restore_controls()
    assert restored.repair_missing.currentData() == 'drop'
    assert restored.quality_id.currentText() == 'identifier'
    assert restored.output.mode == 'directory'
    assert not restored.quality_note.isHidden()
    assert restored.duplicate_keys.isHidden()
    restored.operation.setCurrentIndex(restored.operation.findData('buffer'))
    assert restored.output.mode == 'save'
    assert restored.quality_note.isHidden()
    worker.deleteLater()
    for widget in (page, restored):
        widget.close(); widget.deleteLater()
    app.processEvents()


@pytest.mark.parametrize('font_size', [12, 16])
def test_quality_forms_fit_compact_window(font_size, tmp_path, monkeypatch):
    app = application()
    from PySide6.QtCore import QSettings
    import cartomize.desktop as desktop
    monkeypatch.setattr(desktop, 'QSettings', lambda *args:
                        QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat))
    window = desktop.CartomizeWindow()
    try:
        window._workbench.font_size.setValue(font_size)
        window.resize(1100, 740)
        window.show(); window.select_tool('vector')
        page = window.tool('vector')
        for _, operation in page.QUALITY_OPERATIONS:
            page.operation.setCurrentIndex(page.operation.findData(operation))
            app.processEvents()
            inner = window.stack.currentWidget()
            inner.ensureWidgetVisible(page.output)
            app.processEvents()
            assert inner.horizontalScrollBar().maximum() == 0
            assert page.output.isVisible()
            assert window.run_button.isVisible()
    finally:
        window.close(); app.processEvents()


def test_desktop_repair_registers_bundle_and_reopens_primary(tmp_path, monkeypatch):
    app = application()
    from PySide6.QtCore import QEventLoop, QSettings, QTimer
    import cartomize.desktop as desktop
    monkeypatch.setattr(desktop, 'QSettings', lambda *args:
                        QSettings(str(tmp_path / 'preferences.ini'), QSettings.Format.IniFormat))
    source, identifiers = source_file(tmp_path)
    window = desktop.CartomizeWindow()
    try:
        window.select_tool('vector')
        page = window.tool('vector')
        page.operation.setCurrentIndex(page.operation.findData('repair_geometries'))
        page.source.edit.setText(str(source))
        page.quality_id.setCurrentText('identifier')
        page.repair_missing.setCurrentIndex(page.repair_missing.findData('drop'))
        page.repair_empty.setCurrentIndex(page.repair_empty.findData('drop'))
        page.output.edit.setText(str(tmp_path)); page.quality_folder.setText('window')
        window.start()
        if window.thread is not None:
            loop = QEventLoop(); timer = QTimer()
            timer.timeout.connect(lambda: loop.quit() if window.thread is None else None)
            timer.start(10); QTimer.singleShot(20000, loop.quit); loop.exec(); timer.stop()
        assert window.thread is None
        assert window.status.text().startswith('Traitement terminé'), window.status.text()
        record = json.loads(Path(window.output_path).read_text(encoding='utf-8'))
        for key in ('data', 'report', 'summary', 'issues', 'rejected'):
            assert record['products'][key] in window.workspace.records
        assert gpd.read_file(record['primary']).identifier.tolist() == identifiers[:3]
    finally:
        if window.thread is not None:
            window.cancel(); window.thread.wait(10000); app.processEvents()
        window.close(); app.processEvents()
