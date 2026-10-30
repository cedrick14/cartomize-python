"""G09 explicit choices, area accounting and reusable desktop results."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import threading

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import geopandas as gpd
import pytest
from shapely.geometry import box

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
    choose(widget.operation, 'tabulate_area')
    yield widget
    widget.close()
    widget.deleteLater()
    application.processEvents()


def choose(control, value):
    index = control.findData(value)
    assert index >= 0, value
    control.setCurrentIndex(index)


def sources(tmp_path, *, multiple=False, overlap=False, geographic=False):
    zones, classes = tmp_path / 'zones.gpkg', tmp_path / 'classes.gpkg'
    left = gpd.GeoDataFrame({'123': ['001', 'NA'], 'name': ['Zone ouest', 'Zone est']},
                            geometry=[box(0, 0, 10, 10), box(10, 0, 20, 10)], crs=3857)
    right = gpd.GeoDataFrame({'456': ['Forêt', 'Agriculture'], 'other': [1, 2]},
                             geometry=[box(0, 0, 6, 10), box(5 if overlap else 6, 0, 15, 10)], crs=3857)
    if geographic:
        left, right = left.to_crs(4326), right.to_crs(4326)
    left.to_file(zones, layer='007', index=False)
    right.to_file(classes, layer='008', index=False)
    if multiple:
        gpd.GeoDataFrame({'other_zone': ['Alternative']}, geometry=[box(0, 0, 1, 1)], crs=3857).to_file(
            zones, layer='other_zones', index=False)
        gpd.GeoDataFrame({'other_class': ['Alternative']}, geometry=[box(0, 0, 1, 1)], crs=3857).to_file(
            classes, layer='other_classes', index=False)
    return zones, classes


def configure(page, zones, classes, tmp_path):
    page.source.edit.setText(str(zones))
    page.tabulation_classes.edit.setText(str(classes))
    page.refresh_fields()
    choose(page.tabulation_zones_layer, '007')
    choose(page.tabulation_classes_layer, '008')
    choose(page.tabulation_zone_field, '123')
    choose(page.tabulation_class_field, '456')
    choose(page.tabulation_unit, 'm2')
    page.output.edit.setText(str(tmp_path))
    page.tabulation_folder.setText('tabulation')


def test_multilayer_inputs_require_independent_layers_and_schema_fields(page, tmp_path):
    zones, classes = sources(tmp_path, multiple=True)
    page.source.edit.setText(str(zones))
    page.tabulation_classes.edit.setText(str(classes))
    page.output.edit.setText(str(tmp_path))
    page.refresh_fields()
    assert page.tabulation_zones_layer.currentData() is None
    assert page.tabulation_classes_layer.currentData() is None
    with pytest.raises(ValueError, match='explicitement la couche des zones'):
        page.job({})
    choose(page.tabulation_zones_layer, '007')
    with pytest.raises(ValueError, match='explicitement la couche des catégories'):
        page.job({})
    choose(page.tabulation_classes_layer, '008')
    with pytest.raises(ValueError, match='regroupement des zones'):
        page.job({})
    choose(page.tabulation_zone_field, '123')
    with pytest.raises(ValueError, match='champ des catégories'):
        page.job({})
    choose(page.tabulation_class_field, '456')
    assert callable(page.job({}))
    choose(page.tabulation_zones_layer, 'other_zones')
    assert page.tabulation_zone_field.currentData() is None
    assert page.tabulation_zone_field.findData('123') == -1
    assert page.tabulation_zone_field.findData('other_zone') > 0
    assert page.tabulation_class_field.currentData() == '456'
    choose(page.tabulation_classes_layer, 'other_classes')
    assert page.tabulation_class_field.currentData() is None
    assert page.tabulation_class_field.findData('456') == -1
    assert page.tabulation_class_field.findData('other_class') > 0


@pytest.mark.parametrize('crs', ['', 'EPSG:4326', 'not-a-projection'])
def test_geographic_sources_require_valid_explicit_projected_measurement_crs(page, tmp_path, crs):
    zones, classes = sources(tmp_path, geographic=True)
    configure(page, zones, classes, tmp_path)
    page.tabulation_crs.setText(crs)
    with pytest.raises(ValueError, match='SCR projeté'):
        page.job({})
    page.tabulation_crs.setText('EPSG:3857')
    assert callable(page.job({}))
    assert 'EPSG:3857' in page.tabulation_crs_note.text()


def test_job_captures_exact_numeric_names_policy_choices_and_worker_hooks(page, tmp_path, monkeypatch):
    zones, classes = sources(tmp_path)
    configure(page, zones, classes, tmp_path)
    page.tabulation_crs.setText('EPSG:3857')
    choose(page.tabulation_overlap, 'report')
    choose(page.tabulation_zone_overlap, 'error')
    choose(page.tabulation_null_classes, 'unclassified')
    import cartomize.desktop_tabulation as tabulation
    captured = []
    monkeypatch.setattr(tabulation, 'execute_operation', lambda *args, **kwargs: captured.append((args, kwargs)))
    run = page.job({})
    page.source.edit.clear()
    page.tabulation_classes.edit.clear()
    page.tabulation_folder.setText('future')
    choose(page.tabulation_overlap, 'error')
    page.tabulation_crs.setText('EPSG:4326')
    event, progress = threading.Event(), lambda *_: None
    assert run(progress, event) == tmp_path / 'tabulation' / 'operation.json'
    args, kwargs = captured[0]
    assert args == ('vector.tabulate_area', dict(zones=str(zones), classes=str(classes),
        zones_layer='007', classes_layer='008', zone_field='123', class_field='456',
        metric_crs='EPSG:3857', area_unit='m2', overlap_policy='report',
        zone_overlap_policy='error', null_classes='unclassified'), tmp_path / 'tabulation')
    assert kwargs == dict(progress=progress, cancel=event)


def test_controls_explain_double_counting_and_return_to_existing_operations(page, tmp_path):
    zones, classes = sources(tmp_path)
    configure(page, zones, classes, tmp_path)
    assert page.output.mode == 'directory' and page.cancellable
    choose(page.tabulation_overlap, 'report')
    choose(page.tabulation_null_classes, 'unclassified')
    assert 'dépasser' in page.tabulation_policy_note.text()
    assert 'sans couverture' in page.tabulation_policy_note.text()
    choose(page.operation, 'area')
    assert page.output.mode == 'save'
    assert not page.tabulation_section.isVisible()
    choose(page.operation, 'extract_features')
    assert page.output.mode == 'directory'
    assert not page.tabulation_section.isVisible()
    choose(page.operation, 'tabulate_area')
    assert page.output.mode == 'directory' and page.cancellable
    assert page.form.labelForField(page.source).text() == 'Fichier des zones'
    assert page.tabulation_zone_field.currentData() == '123'


def test_session_restores_both_layers_fields_and_every_policy(page, application, tmp_path):
    zones, classes = sources(tmp_path, multiple=True)
    configure(page, zones, classes, tmp_path)
    page.tabulation_crs.setText('EPSG:3857')
    choose(page.tabulation_unit, 'km2')
    choose(page.tabulation_overlap, 'report')
    choose(page.tabulation_zone_overlap, 'error')
    choose(page.tabulation_null_classes, 'unclassified')
    state = deepcopy(capture_widgets(page))
    restored = VectorPage()
    try:
        restore_widgets(restored, state)
        restored.restore_controls()
        assert restored.operation.currentData() == 'tabulate_area'
        assert restored.tabulation_zones_layer.currentData() == '007'
        assert restored.tabulation_classes_layer.currentData() == '008'
        assert restored.tabulation_zone_field.currentData() == '123'
        assert restored.tabulation_class_field.currentData() == '456'
        assert restored.tabulation_crs.text() == 'EPSG:3857'
        assert restored.tabulation_unit.currentData() == 'km2'
        assert restored.tabulation_overlap.currentData() == 'report'
        assert restored.tabulation_zone_overlap.currentData() == 'error'
        assert restored.tabulation_null_classes.currentData() == 'unclassified'
        assert restored.output.text() == str(tmp_path)
        assert callable(restored.job({}))
    finally:
        restored.close()
        application.processEvents()


def test_dormant_tabulation_controls_do_not_change_a_restored_selection_session(page, application, tmp_path):
    zones, classes = sources(tmp_path)
    configure(page, zones, classes, tmp_path)
    choose(page.operation, 'extract_features')
    state = deepcopy(capture_widgets(page))
    restored = VectorPage()
    try:
        restore_widgets(restored, state)
        restored.restore_controls()
        after = capture_widgets(restored)
        for name in state:
            if name.startswith('tabulation_'):
                assert after[name] == state[name], name
        assert restored.operation.currentData() == 'extract_features'
        assert restored.output.mode == 'directory'
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


@pytest.mark.parametrize('policy', ['error', 'report'])
def test_worker_publishes_area_balances_and_openable_result_tables(application, tmp_path, monkeypatch, policy):
    import cartomize.desktop as desktop
    monkeypatch.setattr(desktop, 'QSettings', lambda *args: QSettings(str(tmp_path / 'worker.ini'), QSettings.Format.IniFormat))
    zones, classes = sources(tmp_path, overlap=policy == 'report')
    before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in (zones, classes)]
    window = desktop.CartomizeWindow()
    try:
        window.select_tool('vector')
        page = window.tool('vector')
        choose(page.operation, 'tabulate_area')
        configure(page, zones, classes, tmp_path)
        choose(page.tabulation_overlap, policy)
        window.start()
        wait_for_window(window, application)
        record = json.loads(Path(window.output_path).read_text(encoding='utf-8'))
        products = record['products']
        for key in ('data', 'table', 'matrix', 'zones', 'categories', 'gaps', 'overlaps', 'summary'):
            assert products[key] in window.workspace.records
            assert page._tabulation_buttons[key].isEnabled()
        table = read_table(products['table'])
        assert len(table) == 4
        area = {(r.zone_id, r.class_id): r.area for r in table.itertuples()}
        assert area == {('z000001', 'c000001'): 60, ('z000001', 'c000002'): 50 if policy == 'report' else 40,
                        ('z000002', 'c000001'): 0, ('z000002', 'c000002'): 50}
        balances = cm.read_file(products['zones'], layer='features')
        assert balances.covered_area.tolist() == [100, 50]
        assert balances.uncovered_area.tolist() == [0, 50]
        assert balances.overlap_area.tolist() == ([10, 0] if policy == 'report' else [0, 0])
        assert balances.excess_area.tolist() == ([10, 0] if policy == 'report' else [0, 0])
        assert [hashlib.sha256(p.read_bytes()).hexdigest() for p in (zones, classes)] == before
        page.tabulation_matrix_button.click()
        assert window.workspace.catalog.currentData() == products['matrix']
        viewer = page.open_tabulation_product('table')
        for _ in range(100):
            if len(viewer.frame) == 4:
                break
            QTest.qWait(20)
        assert len(viewer.frame) == 4
        assert set(viewer.frame.class_id) == {'c000001', 'c000002'}
        balance_view = page.open_tabulation_product('zones')
        assert balance_view.views.currentWidget() is balance_view._table
        for _ in range(100):
            if len(balance_view._table.frame) == 2:
                break
            QTest.qWait(20)
        assert len(balance_view._table.frame) == 2
        assert balance_view._table.frame.uncovered_area.tolist() == [0, 50]
        page.tabulation_folder.setText('future')
        page.tabulation_gaps_button.click()
        assert window.workspace.catalog.currentData() == products['gaps']
        summary = json.loads(Path(products['summary']).read_text(encoding='utf-8'))
        assert summary['zone_count'] == 2 and summary['class_count'] == 2
        assert '2 zone(s), 2 catégorie(s)' in page.tabulation_result_status.text()
    finally:
        if window.thread is not None:
            window.cancel()
            window.thread.wait(10000)
            application.processEvents()
        window.close()
        application.processEvents()


def test_cancelled_job_removes_partial_products_and_keeps_sources(page, tmp_path):
    zones, classes = sources(tmp_path)
    configure(page, zones, classes, tmp_path)
    before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in (zones, classes)]
    event = threading.Event()
    progress_calls = []

    def progress(done, total):
        progress_calls.append((done, total))
        if done > 0:
            event.set()

    with pytest.raises(cm.ProcessingCancelled):
        page.job({})(progress, event)
    assert progress_calls and event.is_set()
    assert not (tmp_path / 'tabulation').exists()
    assert [hashlib.sha256(p.read_bytes()).hexdigest() for p in (zones, classes)] == before


def test_portable_session_relocates_both_sources_tables_and_geometry_products(application, tmp_path, monkeypatch):
    import cartomize.desktop as desktop
    from cartomize.session import load_session, save_session
    monkeypatch.setattr(desktop, 'QSettings', lambda *args: QSettings(str(tmp_path / 'portable.ini'), QSettings.Format.IniFormat))
    zones, classes = sources(tmp_path)
    original, restored = desktop.CartomizeWindow(), desktop.CartomizeWindow()
    try:
        original.select_tool('vector')
        page = original.tool('vector')
        choose(page.operation, 'tabulate_area')
        configure(page, zones, classes, tmp_path)
        path = page.job({})(lambda *_: None, threading.Event())
        page.show_result(path)
        archive = save_session(original.capture_session(), tmp_path / 'tabulation.cmz', portable=True)
        extracted = tmp_path / 'restored'
        loaded = load_session(archive, directory=extracted)
        assert not loaded.missing
        (tmp_path / 'tabulation').rename(tmp_path / 'old-tabulation')
        restored.restore_session(loaded.state)
        page = restored.tool('vector')
        assert Path(page.source.text()).is_relative_to(extracted)
        assert Path(page.tabulation_classes.text()).is_relative_to(extracted)
        assert Path(page.tabulation_result_path.text()).is_relative_to(extracted)
        assert page.tabulation_zone_field.currentData() == '123'
        assert page.tabulation_class_field.currentData() == '456'
        record = page._tabulation_result_record()
        for key in ('data', 'table', 'matrix', 'zones', 'categories', 'gaps', 'overlaps', 'summary'):
            assert Path(record['products'][key]).is_relative_to(extracted)
            assert Path(record['products'][key]).is_file()
        page.tabulation_table_button.click()
        assert restored.workspace.catalog.currentData() == record['products']['table']
    finally:
        original.close()
        restored.close()
        application.processEvents()


@pytest.mark.parametrize('policy,font_size', [('error', 12), ('error', 16), ('report', 12), ('report', 16)])
def test_g09_controls_fit_compact_window(application, tmp_path, monkeypatch, policy, font_size):
    import cartomize.desktop as desktop
    monkeypatch.setattr(desktop, 'QSettings', lambda *args: QSettings(str(tmp_path / 'compact.ini'), QSettings.Format.IniFormat))
    zones, classes = sources(tmp_path)
    window = desktop.CartomizeWindow()
    try:
        window._workbench.font_size.setValue(font_size)
        window.resize(1100, 740)
        window.show()
        window.select_tool('vector')
        page = window.tool('vector')
        choose(page.operation, 'tabulate_area')
        configure(page, zones, classes, tmp_path)
        choose(page.tabulation_overlap, policy)
        QTest.qWait(40)
        scroll = window.stack.currentWidget()
        controls = [page.tabulation_zones_layer, page.tabulation_zone_field,
                    page.tabulation_classes, page.tabulation_classes_layer, page.tabulation_class_field,
                    page.tabulation_crs, page.tabulation_unit, page.tabulation_overlap,
                    page.tabulation_zone_overlap, page.tabulation_null_classes,
                    page.tabulation_matrix_button, page.tabulation_overlaps_button,
                    page.tabulation_policy_note, page.output]
        for control in controls:
            scroll.ensureWidgetVisible(control)
            QTest.qWait(10)
            geometry = dict(policy=policy, font_size=font_size, viewport=scroll.viewport().size().toTuple(),
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
                print('G09 form geometry: ' + json.dumps(geometry, ensure_ascii=False))
            assert scroll.horizontalScrollBar().maximum() == 0, json.dumps(geometry, ensure_ascii=False)
            assert 100 <= control.width() <= scroll.viewport().width()
        assert window.run_button.isVisible()
    finally:
        window.close()
        application.processEvents()
