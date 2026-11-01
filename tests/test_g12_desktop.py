"""G12 explicit distance bands, worker publication, sessions and compact forms."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import threading

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import geopandas as gpd
import pytest
from shapely.geometry import Point, box

pytest.importorskip('PySide6')
from PySide6.QtCore import QEventLoop, QSettings, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

import cartomize as cm
from cartomize.desktop_session import capture_widgets, restore_widgets
from cartomize.desktop_vector import VectorPage
from cartomize.tableio import read_table


@pytest.fixture(scope='module')
def application():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def page(application):
    widget = VectorPage()
    choose(widget.operation, 'buffer_rings')
    yield widget
    widget.close()
    widget.deleteLater()
    application.processEvents()


def choose(control, value):
    index = control.findData(value)
    assert index >= 0, value
    control.setCurrentIndex(index)


def source_file(tmp_path, *, multiple=False, geographic=False, polygon=False):
    path = tmp_path / 'source.gpkg'
    shapes = [box(0, 0, 10, 10)] if polygon else [Point(0, 0), Point(10, 0)]
    data = gpd.GeoDataFrame({'123': ['001'] if polygon else ['001', 'NA']}, geometry=shapes, crs=3857)
    if geographic:
        data = data.to_crs(4326)
    data.to_file(path, layer='007', index=False)
    if multiple:
        gpd.GeoDataFrame({'other_id': ['Alternative']}, geometry=[Point(0, 0)], crs=3857).to_file(
            path, layer='other', index=False)
    return path


def configure(page, source, tmp_path):
    page.source.edit.setText(str(source))
    page.refresh_fields()
    choose(page.rings_layer, '007')
    choose(page.rings_id, '123')
    page.rings_distances.setText('1; 2')
    page.rings_quad_segs.setValue(1)
    choose(page.rings_unit, 'm2')
    page.output.edit.setText(str(tmp_path))
    page.rings_folder.setText('rings')


def test_multilayer_input_requires_selection_and_updates_available_identifiers(page, tmp_path):
    source = source_file(tmp_path, multiple=True)
    page.source.edit.setText(str(source))
    page.output.edit.setText(str(tmp_path))
    page.refresh_fields()
    assert page.rings_layer.currentData() is None
    with pytest.raises(ValueError, match='explicitement la couche source'):
        page.job({})
    choose(page.rings_layer, '007')
    choose(page.rings_id, '123')
    assert callable(page.job({}))
    choose(page.rings_layer, 'other')
    assert page.rings_id.currentData() is None
    assert page.rings_id.findData('123') == -1
    assert page.rings_id.findData('other_id') > 0
    assert callable(page.job({}))


@pytest.mark.parametrize('crs', ['', 'EPSG:4326', 'not-a-projection'])
def test_geographic_source_requires_explicit_projected_crs(page, tmp_path, crs):
    source = source_file(tmp_path, geographic=True)
    configure(page, source, tmp_path)
    page.rings_crs.setText(crs)
    with pytest.raises(ValueError, match='SCR projeté'):
        page.job({})
    page.rings_crs.setText('EPSG:3857')
    assert callable(page.job({}))
    assert 'EPSG:3857' in page.rings_crs_note.text()


@pytest.mark.parametrize('distances', ['', '10;', '0; 10', '-1; 10', '10; 10', '20; 10', '10; inf', '10,5; 20'])
def test_invalid_distance_lists_are_refused_without_reordering(page, tmp_path, distances):
    source = source_file(tmp_path)
    configure(page, source, tmp_path)
    page.rings_distances.setText(distances)
    with pytest.raises(ValueError, match='distance|décimales'):
        page.job({})
    assert page.rings_distances.text() == distances
    assert not (tmp_path / 'rings').exists()


def test_job_captures_exact_layers_parameters_and_worker_hooks(page, tmp_path, monkeypatch):
    source = source_file(tmp_path)
    configure(page, source, tmp_path)
    page.rings_crs.setText('EPSG:3857')
    page.rings_distances.setText('1.5; 2.75')
    page.rings_quad_segs.setValue(32)
    page.rings_include_input.setChecked(True)
    choose(page.rings_mode, 'independent')
    choose(page.rings_unit, 'km2')
    import cartomize.desktop_rings as rings
    captured = []
    monkeypatch.setattr(rings, 'execute_operation', lambda *args, **kwargs: captured.append((args, kwargs)))
    run = page.job({})
    page.source.edit.clear()
    page.rings_folder.setText('future')
    page.rings_distances.setText('10; 20')
    page.rings_crs.setText('EPSG:4326')
    page.rings_include_input.setChecked(False)
    choose(page.rings_mode, 'dissolved')
    event, progress = threading.Event(), lambda *_: None
    assert run(progress, event) == tmp_path / 'rings' / 'operation.json'
    args, kwargs = captured[0]
    assert args == ('vector.buffer_rings', dict(data=str(source), distances=[1.5, 2.75], layer='007',
        metric_crs='EPSG:3857', mode='independent', id_field='123', include_input=True,
        quad_segs=32, area_unit='km2'), tmp_path / 'rings')
    assert kwargs == dict(progress=progress, cancel=event)


def test_notes_explain_intervals_source_overlap_and_polygon_interior(page, tmp_path):
    source = source_file(tmp_path)
    configure(page, source, tmp_path)
    assert page.output.mode == 'directory' and page.cancellable
    assert '0–1 m ; 1–2 m' in page.rings_intervals_note.text()
    choose(page.rings_mode, 'independent')
    assert 'sources différentes' in page.rings_policy_note.text()
    assert 'se recouvrir' in page.rings_policy_note.text()
    assert 'exclue' in page.rings_policy_note.text()
    page.rings_include_input.setChecked(True)
    assert 'incluse' in page.rings_policy_note.text()
    choose(page.operation, 'buffer')
    assert page.output.mode == 'save'
    assert not page.rings_section.isVisible()
    choose(page.operation, 'tabulate_area')
    assert page.output.mode == 'directory'
    assert not page.rings_section.isVisible()
    choose(page.operation, 'buffer_rings')
    assert page.output.mode == 'directory' and page.cancellable
    assert page.form.labelForField(page.source).text() == 'Fichier des sources'
    assert page.rings_id.currentData() == '123'


def test_session_restores_layer_distances_and_all_explicit_parameters(page, application, tmp_path):
    source = source_file(tmp_path, multiple=True)
    configure(page, source, tmp_path)
    page.rings_crs.setText('EPSG:3857')
    page.rings_distances.setText('10.5; 20.75; 40')
    choose(page.rings_mode, 'independent')
    choose(page.rings_unit, 'km2')
    page.rings_include_input.setChecked(True)
    page.rings_quad_segs.setValue(32)
    state = deepcopy(capture_widgets(page))
    restored = VectorPage()
    try:
        restore_widgets(restored, state)
        restored.restore_controls()
        assert restored.operation.currentData() == 'buffer_rings'
        assert restored.rings_layer.currentData() == '007'
        assert restored.rings_id.currentData() == '123'
        assert restored.rings_distances.text() == '10.5; 20.75; 40'
        assert restored.rings_crs.text() == 'EPSG:3857'
        assert restored.rings_mode.currentData() == 'independent'
        assert restored.rings_unit.currentData() == 'km2'
        assert restored.rings_include_input.isChecked()
        assert restored.rings_quad_segs.value() == 32
        assert restored.output.text() == str(tmp_path)
        assert callable(restored.job({}))
    finally:
        restored.close()
        application.processEvents()


def test_dormant_ring_controls_remain_unchanged_when_restoring_another_operation(page, application, tmp_path):
    source = source_file(tmp_path)
    configure(page, source, tmp_path)
    choose(page.operation, 'extract_features')
    state = deepcopy(capture_widgets(page))
    restored = VectorPage()
    try:
        restore_widgets(restored, state)
        restored.restore_controls()
        after = capture_widgets(restored)
        for name in state:
            if name.startswith('rings_'):
                assert after[name] == state[name], name
        assert restored.operation.currentData() == 'extract_features'
        assert restored.output.mode == 'directory'
    finally:
        restored.close()
        application.processEvents()


def test_processing_dialog_preserves_numeric_names_and_explicit_ring_choices(application):
    from cartomize.desktop_processing import OperationDialog
    parameters = dict(data='source.gpkg', distances=[100, 250.5, 1000], layer='007',
                      metric_crs='EPSG:32733', mode='independent', id_field='123',
                      include_input=True, quad_segs=32, area_unit='m2')
    record = dict(id='rings', operation='vector.buffer_rings', parameters=parameters)
    dialog = OperationDialog([], record=record)
    try:
        assert dialog.value() == record
        choose(dialog.controls['mode'], 'dissolved')
        choose(dialog.controls['area_unit'], 'km2')
        dialog.controls['distances'].setCurrentText('[25, 50, 100]')
        updated = dialog.value()['parameters']
        assert updated['distances'] == [25, 50, 100]
        assert updated['mode'] == 'dissolved'
        assert updated['area_unit'] == 'km2'
        assert updated['layer'] == '007'
        assert updated['id_field'] == '123'
    finally:
        dialog.close()


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


@pytest.mark.parametrize('mode', ['dissolved', 'independent'])
def test_worker_publishes_distance_bounds_balances_and_exact_labels(application, tmp_path, monkeypatch, mode):
    import cartomize.desktop as desktop
    monkeypatch.setattr(desktop, 'QSettings', lambda *args: QSettings(str(tmp_path / 'worker.ini'), QSettings.Format.IniFormat))
    source = source_file(tmp_path)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    window = desktop.CartomizeWindow()
    try:
        window.select_tool('vector')
        page = window.tool('vector')
        choose(page.operation, 'buffer_rings')
        configure(page, source, tmp_path)
        choose(page.rings_mode, mode)
        window.start()
        wait_for_window(window, application)
        products = json.loads(Path(window.output_path).read_text(encoding='utf-8'))['products']
        for key in ('data', 'table', 'sources', 'balances', 'summary', 'audit'):
            assert products[key] in window.workspace.records
            assert page._rings_buttons[key].isEnabled()
        table = read_table(products['table'])
        assert table.area.tolist() == ([4.0, 12.0] if mode == 'dissolved' else [2.0, 6.0, 2.0, 6.0])
        assert table.lower_m.tolist() == ([0.0, 1.0] if mode == 'dissolved' else [0.0, 1.0, 0.0, 1.0])
        assert table.upper_m.tolist() == ([1.0, 2.0] if mode == 'dissolved' else [1.0, 2.0, 1.0, 2.0])
        balances = read_table(products['balances'])
        assert balances.expected_area.tolist() == ([16.0] if mode == 'dissolved' else [8.0, 8.0])
        assert balances.overlap_area.eq(0).all()
        assert balances.uncovered_area.eq(0).all()
        assert balances.closure_error.abs().max() < 1e-12
        source_view = page.open_rings_product('sources')
        assert source_view.views.currentWidget() is source_view._table
        for _ in range(100):
            if len(source_view._table.frame) == 2:
                break
            QTest.qWait(20)
        assert source_view._table.frame.id_value.tolist() == ['001', 'NA']
        page.rings_table_button.click()
        assert window.workspace.catalog.currentData() == products['table']
        viewer = page.open_rings_product('table')
        for _ in range(500):
            if len(viewer.frame) == len(table):
                break
            QTest.qWait(20)
        assert len(viewer.frame) == len(table), "Le tableau de résultats n'a pas fini de charger."
        assert viewer.frame.upper_m.tolist() == table.upper_m.tolist()
        page.rings_folder.setText('future')
        page.rings_distances.setText('20; 100')
        page.rings_balances_button.click()
        assert window.workspace.catalog.currentData() == products['balances']
        assert '2 source(s), 2 intervalle(s)' in page.rings_result_status.text()
        assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    finally:
        if window.thread is not None:
            window.cancel()
            window.thread.wait(10000)
            application.processEvents()
        window.close()
        application.processEvents()


@pytest.mark.parametrize('include_input', [False, True])
def test_polygon_interior_choice_changes_only_first_band(page, tmp_path, include_input):
    source = source_file(tmp_path, polygon=True)
    configure(page, source, tmp_path)
    page.rings_include_input.setChecked(include_input)
    result = page.job({})(lambda *_: None, threading.Event())
    products = json.loads(result.read_text(encoding='utf-8'))['products']
    table = read_table(products['table'])
    assert table.area.tolist() == [142.0 if include_input else 42.0, 46.0]
    summary = json.loads(Path(products['summary']).read_text(encoding='utf-8'))
    assert summary['parameters']['include_input'] is include_input


def test_cancelled_job_keeps_input_and_removes_partial_products(page, tmp_path):
    source = source_file(tmp_path)
    configure(page, source, tmp_path)
    before = source.read_bytes()
    event = threading.Event()
    calls = []

    def progress(done, total):
        calls.append((done, total))
        if done > 0:
            event.set()

    with pytest.raises(cm.ProcessingCancelled):
        page.job({})(progress, event)
    assert calls and event.is_set()
    assert not (tmp_path / 'rings').exists()
    assert source.read_bytes() == before


def test_portable_session_relocates_source_and_every_result(application, tmp_path, monkeypatch):
    import cartomize.desktop as desktop
    from cartomize.session import load_session, save_session
    monkeypatch.setattr(desktop, 'QSettings', lambda *args: QSettings(str(tmp_path / 'portable.ini'), QSettings.Format.IniFormat))
    source = source_file(tmp_path)
    original, restored = desktop.CartomizeWindow(), desktop.CartomizeWindow()
    try:
        original.select_tool('vector')
        page = original.tool('vector')
        choose(page.operation, 'buffer_rings')
        configure(page, source, tmp_path)
        path = page.job({})(lambda *_: None, threading.Event())
        page.show_result(path)
        archive = save_session(original.capture_session(), tmp_path / 'rings.cmz', portable=True)
        extracted = tmp_path / 'restored'
        loaded = load_session(archive, directory=extracted)
        assert not loaded.missing
        (tmp_path / 'rings').rename(tmp_path / 'old-rings')
        restored.restore_session(loaded.state)
        page = restored.tool('vector')
        assert Path(page.source.text()).is_relative_to(extracted)
        assert Path(page.rings_result_path.text()).is_relative_to(extracted)
        assert page.rings_id.currentData() == '123'
        record = page._rings_result_record()
        for key in ('data', 'table', 'sources', 'balances', 'summary', 'audit'):
            assert Path(record['products'][key]).is_relative_to(extracted)
            assert Path(record['products'][key]).is_file()
        page.rings_table_button.click()
        assert restored.workspace.catalog.currentData() == record['products']['table']
    finally:
        original.close()
        restored.close()
        application.processEvents()


@pytest.mark.parametrize('mode,font_size', [('dissolved', 12), ('dissolved', 16), ('independent', 12), ('independent', 16)])
def test_g12_controls_fit_compact_window(application, tmp_path, monkeypatch, mode, font_size):
    import cartomize.desktop as desktop
    monkeypatch.setattr(desktop, 'QSettings', lambda *args: QSettings(str(tmp_path / 'compact.ini'), QSettings.Format.IniFormat))
    source = source_file(tmp_path)
    window = desktop.CartomizeWindow()
    try:
        window._workbench.font_size.setValue(font_size)
        window.resize(1100, 740)
        window.show()
        window.select_tool('vector')
        page = window.tool('vector')
        choose(page.operation, 'buffer_rings')
        configure(page, source, tmp_path)
        choose(page.rings_mode, mode)
        QTest.qWait(40)
        scroll = window.stack.currentWidget()
        controls = [page.rings_layer, page.rings_id, page.rings_distances, page.rings_mode,
                    page.rings_include_input, page.rings_policy_note, page.rings_crs, page.rings_unit,
                    page.rings_quad_segs, page.rings_folder, page.rings_table_button,
                    page.rings_audit_button, page.output]
        for control in controls:
            scroll.ensureWidgetVisible(control)
            QTest.qWait(10)
            geometry = dict(mode=mode, font_size=font_size, viewport=scroll.viewport().size().toTuple(),
                            minimum=page.minimumSizeHint().toTuple(), page=page.size().toTuple(),
                            horizontal_range=scroll.horizontalScrollBar().maximum(),
                            style=application.style().objectName())
            if geometry['horizontal_range']:
                names = {id(value): key for key, value in vars(page).items() if isinstance(value, QWidget)}
                geometry['widest_controls'] = sorted([
                    dict(name=names.get(id(child), child.objectName()), width=child.width(),
                         minimum=child.minimumSizeHint().width(), type=type(child).__name__,
                         text=getattr(child, 'text', lambda: '')()[:100])
                    for child in page.findChildren(QWidget) if child.isVisible()
                ], key=lambda record: record['minimum'], reverse=True)[:15]
                print('G12 form geometry: ' + json.dumps(geometry, ensure_ascii=False))
            assert scroll.horizontalScrollBar().maximum() == 0, json.dumps(geometry, ensure_ascii=False)
            # A four-digit spin box can keep its natural width; the other
            # inputs and product buttons occupy the available form column.
            minimum = control.minimumSizeHint().width() if control is page.rings_quad_segs else 100
            assert minimum <= control.width() <= scroll.viewport().width()
        assert window.run_button.isVisible()
    finally:
        window.close()
        application.processEvents()
