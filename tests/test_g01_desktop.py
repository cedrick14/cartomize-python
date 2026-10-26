"""G01 selects a real layer and exposes faithful, restorable repair results."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sqlite3
import threading

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import geopandas as gpd
import numpy as np
import pandas as pd
from pyogrio.raw import write as raw_write
from pyproj import CRS
import pytest
import shapely
from shapely.geometry import Polygon, box

pytest.importorskip('PySide6')
from PySide6.QtCore import QEventLoop, QSettings, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

import cartomize as cm
from cartomize.desktop_session import capture_widgets, restore_widgets
from cartomize.desktop_vector import VectorPage
from cartomize.viewer_data import table_page


@pytest.fixture(scope='module')
def application():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def page(application):
    widget = VectorPage()
    widget.operation.setCurrentIndex(widget.operation.findData('repair_geometries'))
    yield widget
    widget.close()
    widget.deleteLater()
    application.processEvents()


def source_file(tmp_path, *, multiple=True, crs=3857):
    path = tmp_path / 'source.gpkg'
    if multiple:
        gpd.GeoDataFrame({'reference_id': ['reference']}, geometry=[box(10, 10, 11, 11)],
                        crs=crs).to_file(path, layer='reference', index=False)
    geometries = [Polygon([(.12, .12), (2.12, 2.12), (.12, 2.12), (2.12, .12), (.12, .12)]),
                  box(3.11, .11, 4.11, 1.11), None, Polygon()]
    raw_write(path, geometry=shapely.to_wkb(geometries),
        field_data=[np.array(['0001', '0002', '0003', '0004'], dtype=object),
            np.array([2**60 + 3, 0, 7, 8], dtype='int64'),
            np.array(['2024-02-29', '2024-03-01', 'NaT', '2024-03-03'], dtype='datetime64[D]')],
        fields=['parcel_id', 'large_id', 'survey_date'],
        field_mask=[None, np.array([False, True, False, False]), None],
        layer='to_repair', driver='GPKG', geometry_type='Unknown', crs=CRS(crs).to_wkt(),
        promote_to_multi=False, layer_options={'SPATIAL_INDEX': 'NO'})
    return path


def configure(page, source, tmp_path):
    page.source.edit.setText(str(source))
    page.refresh_fields()
    page.quality_layer.setCurrentIndex(page.quality_layer.findData('to_repair'))
    page.quality_id.setCurrentText('parcel_id')
    page.repair_missing.setCurrentIndex(page.repair_missing.findData('drop'))
    page.repair_empty.setCurrentIndex(page.repair_empty.findData('drop'))
    page.output.edit.setText(str(tmp_path))
    page.quality_folder.setText('repair')


def run_page(page):
    path = page.job({'overwrite': False})(lambda *_: None, threading.Event())
    page.show_result(path)
    return json.loads(Path(path).read_text(encoding='utf-8'))


def test_multilayer_requires_choice_and_updates_identifier_fields(page, tmp_path):
    source = source_file(tmp_path)
    page.source.edit.setText(str(source))
    page.output.edit.setText(str(tmp_path))
    page.refresh_fields()
    assert page.quality_layer.currentData() is None
    assert page.quality_id.count() == 0
    with pytest.raises(ValueError, match='Choisir la couche'):
        page.job({'overwrite': False})
    page.quality_layer.setCurrentIndex(page.quality_layer.findData('reference'))
    assert [page.quality_id.itemText(i) for i in range(page.quality_id.count())] == ['reference_id']
    page.quality_id.setCurrentText('reference_id')
    page.quality_layer.setCurrentIndex(page.quality_layer.findData('to_repair'))
    assert 'parcel_id' in [page.quality_id.itemText(i) for i in range(page.quality_id.count())]
    assert page.quality_id.currentText() == ''
    assert '4 entité' in page.quality_layer_note.text()


def test_single_layer_is_selected_and_changing_file_requires_new_multilayer_choice(page, tmp_path):
    single_dir, multi_dir = tmp_path / 'single', tmp_path / 'multi'
    single_dir.mkdir()
    multi_dir.mkdir()
    single = source_file(single_dir, multiple=False)
    multiple = source_file(multi_dir)
    configure(page, single, tmp_path)
    assert page.quality_layer.currentData() == 'to_repair'
    page.source.edit.setText(str(multiple))
    with pytest.raises(ValueError, match='Choisir la couche'):
        page.job({'overwrite': False})


def test_grid_uses_source_projected_units_and_not_measurement_crs(page, tmp_path):
    source = source_file(tmp_path, multiple=False, crs=4326)
    configure(page, source, tmp_path)
    page.crs.setText('EPSG:3857')
    page.repair_tolerance.setValue(.25)
    assert 'SCR source projeté' in page.repair_grid_note.text()
    with pytest.raises(ValueError, match='SCR source projeté'):
        page.job({'overwrite': False})
    page.repair_tolerance.setValue(0)
    record = run_page(page)
    summary = json.loads(Path(record['products']['summary']).read_text())
    assert summary['tolerance'] == 0
    assert summary['measurement_crs'] == 'EPSG:3857'


def test_projected_foot_unit_is_visible_without_claiming_metres(page, tmp_path):
    source = source_file(tmp_path, multiple=False, crs=2277)
    configure(page, source, tmp_path)
    assert 'pied d’arpentage US' in page.repair_grid_note.text()
    assert 'EPSG:2277' in page.repair_grid_note.text()


def test_real_job_snapshots_layer_id_grid_and_repair_policies(page, tmp_path):
    source = source_file(tmp_path)
    original = source.read_bytes()
    configure(page, source, tmp_path)
    page.repair_method.setCurrentIndex(page.repair_method.findData('structure'))
    page.repair_collapsed.setChecked(False)
    page.repair_tolerance.setValue(.25)
    run = page.job({'overwrite': False})
    page.quality_layer.setCurrentIndex(page.quality_layer.findData('reference'))
    page.quality_id.setCurrentText('reference_id')
    page.repair_method.setCurrentIndex(page.repair_method.findData('linework'))
    page.repair_tolerance.setValue(2)
    page.repair_missing.setCurrentIndex(page.repair_missing.findData('keep'))
    page.quality_folder.setText('later')
    output = run(lambda *_: None, threading.Event())
    record = json.loads(Path(output).read_text())
    summary = json.loads(Path(record['products']['summary']).read_text())
    assert Path(output) == tmp_path / 'repair' / 'operation.json'
    assert summary['input_features'] == 4 and summary['output_features'] == 2
    assert summary['method'] == 'structure' and summary['keep_collapsed'] is False
    assert summary['tolerance'] == .25 and summary['id_field'] == 'parcel_id'
    corrected = cm.read_file(record['products']['data'])
    assert corrected.parcel_id.tolist() == ['0001', '0002']
    coordinates = shapely.get_coordinates(corrected.geometry)
    np.testing.assert_allclose(coordinates / .25, np.round(coordinates / .25))
    assert source.read_bytes() == original


def test_saved_controls_and_result_actions_restore_exactly(page, application, tmp_path):
    source = source_file(tmp_path)
    configure(page, source, tmp_path)
    page.repair_method.setCurrentIndex(page.repair_method.findData('structure'))
    page.repair_collapsed.setChecked(False)
    page.repair_tolerance.setValue(.125)
    record = run_page(page)
    captured = deepcopy(capture_widgets(page))
    restored = VectorPage()
    try:
        restore_widgets(restored, captured)
        restored.restore_controls()
        assert capture_widgets(restored) == captured
        assert restored.quality_layer.currentData() == 'to_repair'
        assert restored.quality_id.currentText() == 'parcel_id'
        assert restored.repair_tolerance.value() == .125
        assert restored.quality_report_button.isEnabled()
        assert restored.quality_compare_button.isEnabled()
        restored.operation.setCurrentIndex(restored.operation.findData('buffer'))
        assert restored.quality_layer.isHidden() and restored.repair_tolerance.isHidden()
        restored.operation.setCurrentIndex(restored.operation.findData('repair_geometries'))
        assert restored.quality_layer.currentData() == 'to_repair'
        assert restored.quality_id.currentText() == 'parcel_id'
        assert restored._quality_result_record()['products']['before'] == record['products']['before']
    finally:
        restored.close()
        restored.deleteLater()
        application.processEvents()


def test_previous_session_without_new_g01_controls_retains_existing_choices(page, application, tmp_path):
    source = source_file(tmp_path, multiple=False)
    configure(page, source, tmp_path)
    captured = deepcopy(capture_widgets(page))
    for key in ('quality_layer', 'repair_tolerance', 'quality_result_path'):
        captured.pop(key)
    restored = VectorPage()
    try:
        restore_widgets(restored, captured)
        restored.restore_controls()
        assert restored.operation.currentData() == 'repair_geometries'
        assert restored.quality_layer.currentData() == 'to_repair'
        assert restored.quality_id.currentText() == 'parcel_id'
        assert restored.repair_missing.currentData() == 'drop'
        assert restored.repair_tolerance.value() == 0
        assert not restored.quality_report_button.isEnabled()
    finally:
        restored.close()
        restored.deleteLater()
        application.processEvents()


def test_g01_controls_do_not_appear_in_other_quality_paths(page):
    for operation in ('check_topology', 'deduplicate'):
        page.operation.setCurrentIndex(page.operation.findData(operation))
        assert page.quality_layer.isHidden()
        assert page.repair_tolerance.isHidden()
        assert page.quality_results.isHidden()
    page.operation.setCurrentIndex(page.operation.findData('check_topology'))
    assert not page.topology_tolerance.isHidden()


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


def test_worker_publishes_selected_layer_and_usable_before_after_report(application, tmp_path, monkeypatch):
    import cartomize.desktop as desktop
    monkeypatch.setattr(desktop, 'QSettings', lambda *args: QSettings(str(tmp_path / 'ui.ini'), QSettings.Format.IniFormat))
    source = source_file(tmp_path)
    window = desktop.CartomizeWindow()
    try:
        window.select_tool('vector')
        page = window.tool('vector')
        page.operation.setCurrentIndex(page.operation.findData('audit_geometries'))
        configure(page, source, tmp_path)
        page.quality_folder.setText('audit')
        window.start()
        wait_for_window(window, application)
        audit = json.loads(Path(window.output_path).read_text())
        assert len(cm.read_file(audit['products']['before'])) == 4
        assert page.quality_issues_button.isEnabled() and page.quality_report_button.isEnabled()
        assert not page.quality_compare_button.isEnabled()
        page.operation.setCurrentIndex(page.operation.findData('repair_geometries'))
        page.quality_folder.setText('repair')
        window.start()
        wait_for_window(window, application)
        record = json.loads(Path(window.output_path).read_text())
        before = cm.read_file(record['products']['before'])
        after = cm.read_file(record['products']['data'])
        report = table_page(record['products']['report'])['frame']
        assert before.parcel_id.tolist() == ['0001', '0002', '0003', '0004']
        assert after.parcel_id.tolist() == ['0001', '0002']
        assert after.geom_type.tolist() == report.loc[report.retained, 'after_geometry_type'].tolist()
        assert report.feature_id.tolist() == ['0001', '0002', '0003', '0004']
        assert report.loc[report.retained, 'output_row'].tolist() == [0, 1]
        assert report.loc[~report.retained, 'rejected_row'].tolist() == [0, 1]
        with sqlite3.connect(record['products']['data']) as connection:
            types = {row[1]: row[2] for row in connection.execute('PRAGMA table_info(features)')}
        assert types['survey_date'] == 'DATE'
        assert int(after.large_id.iloc[0]) == 2**60 + 3
        assert pd.isna(after.large_id.iloc[1])
        issues = page.open_quality_product('issues')
        assert issues.path == record['products']['issues']
        document = page.open_quality_product('report')
        for _ in range(100):
            if len(document.frame):
                break
            QTest.qWait(20)
        assert len(document.frame) == 4
        column = list(document.frame.columns).index('feature_id')
        assert document.model.data(document.model.index(0, column)) == '0001'
        comparison = page.compare_quality_results()
        assert [document.path for document in comparison.documents] == [record['products']['before'], record['products']['data']]
        assert all(document is not None for document in comparison.documents)
        assert comparison.link.isChecked()
        assert 'Avant réparation' in window.workspace.records[record['products']['before']]['name']
        assert 'Après réparation' in window.workspace.records[record['products']['data']]['name']
    finally:
        if window.thread is not None:
            window.cancel()
            window.thread.wait(10000)
            application.processEvents()
        window.close()
        application.processEvents()


def test_portable_session_restores_before_after_and_exact_report_ids(application, tmp_path, monkeypatch):
    import cartomize.desktop as desktop
    from cartomize.session import load_session, save_session
    monkeypatch.setattr(desktop, 'QSettings', lambda *args: QSettings(str(tmp_path / 'portable.ini'), QSettings.Format.IniFormat))
    source = source_file(tmp_path)
    original, restored = desktop.CartomizeWindow(), desktop.CartomizeWindow()
    try:
        original.select_tool('vector')
        page = original.tool('vector')
        page.operation.setCurrentIndex(page.operation.findData('repair_geometries'))
        configure(page, source, tmp_path)
        page.repair_tolerance.setValue(.125)
        run_page(page)
        archive = save_session(original.capture_session(), tmp_path / 'project.cmz', portable=True)
        extracted = tmp_path / 'restored'
        loaded = load_session(archive, directory=extracted)
        assert not loaded.missing
        # Removing the original result path verifies that every action uses
        # the rewritten bundle inside the portable project.
        (tmp_path / 'repair').rename(tmp_path / 'original-repair')
        restored.restore_session(loaded.state)
        page = restored.tool('vector')
        assert page.quality_layer.currentData() == 'to_repair'
        assert page.quality_id.currentText() == 'parcel_id'
        assert page.repair_tolerance.value() == .125
        assert Path(page.quality_result_path.text()).is_relative_to(extracted)
        record = page._quality_result_record()
        for name in ('before', 'data', 'report', 'issues'):
            assert Path(record['products'][name]).is_relative_to(extracted)
            assert Path(record['products'][name]).is_file()
        assert Path(record['products']['report'] + '.schema.json').is_file()
        comparison = page.compare_quality_results()
        assert [document.path for document in comparison.documents] == [record['products']['before'], record['products']['data']]
        assert comparison.link.isChecked()
        report = page.open_quality_product('report')
        for _ in range(100):
            if len(report.frame):
                break
            QTest.qWait(20)
        assert report.frame.feature_id.tolist() == ['0001', '0002', '0003', '0004']
        column = list(report.frame.columns).index('feature_id')
        assert report.model.data(report.model.index(0, column)) == '0001'
        assert page.open_quality_product('issues').path == record['products']['issues']
    finally:
        original.close()
        restored.close()
        application.processEvents()


@pytest.mark.parametrize('font_size,wide_labels', [(12, False), (16, False), (12, True)],
                         ids=['12', '16', 'wide_native_labels'])
def test_g01_form_fits_compact_window(application, tmp_path, monkeypatch, font_size, wide_labels):
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
        page.operation.setCurrentIndex(page.operation.findData('repair_geometries'))
        configure(page, source, tmp_path)
        if wide_labels:
            page.repair_collapsed.setStyleSheet('font-size: 24px;')
        QTest.qWait(50)
        scroll = window.stack.currentWidget()
        for control in (page.quality_layer, page.repair_tolerance, page.quality_compare_button, page.output):
            scroll.ensureWidgetVisible(control)
            QTest.qWait(20)
            geometry = dict(font_size=font_size, wide_labels=wide_labels,
                viewport=scroll.viewport().size().toTuple(), page=page.size().toTuple(),
                minimum_hint=page.minimumSizeHint().toTuple(), layout_minimum=page.layout.minimumSize().toTuple(),
                horizontal_range=scroll.horizontalScrollBar().maximum(), style=application.style().objectName())
            if geometry['horizontal_range']:
                names = {id(value): key for key, value in vars(page).items() if isinstance(value, QWidget)}
                geometry['widest_controls'] = sorted([
                    dict(minimum_width=child.minimumSizeHint().width(), width=child.width(),
                         type=type(child).__name__, name=names.get(id(child), child.objectName()),
                         text=getattr(child, 'text', lambda: '')()[:120],
                         font_family=child.font().family(), font_pixels=child.font().pixelSize())
                    for child in page.findChildren(QWidget) if child.isVisible()
                ], key=lambda record: record['minimum_width'], reverse=True)[:12]
                print('G01 form geometry: ' + json.dumps(geometry, ensure_ascii=False))
            assert scroll.horizontalScrollBar().maximum() == 0, json.dumps(geometry, ensure_ascii=False)
            assert control.width() <= scroll.viewport().width()
        assert page.repair_collapsed.width() >= page.repair_collapsed.minimumSizeHint().width()
        assert page.repair_collapsed.height() >= page.repair_collapsed.sizeHint().height()
        assert window.run_button.isVisible()
    finally:
        window.close()
        application.processEvents()
