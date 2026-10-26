"""Editable harmonisation decisions survive sessions and the normal worker."""
from copy import deepcopy
import json
import os
from pathlib import Path
import threading

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point

pytest.importorskip('PySide6')
from PySide6.QtCore import QEventLoop, QSettings, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from cartomize.desktop_merge import INSPECTION_SCHEMA
from cartomize.desktop_session import capture_widgets, restore_widgets
from cartomize.desktop_vector import VectorPage


@pytest.fixture(scope='module')
def application():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def page(application):
    widget = VectorPage()
    widget.operation.setCurrentIndex(widget.operation.findData('merge_layers'))
    yield widget
    widget.close()
    widget.deleteLater()
    application.processEvents()


def source_file(tmp_path):
    source = tmp_path / 'sources.gpkg'
    gpd.GeoDataFrame({'code': ['001', '002'], 'count': pd.Series([12, None], dtype='Int64'),
                     'active': [True, False]},
        geometry=[Point(15., -4.3), Point(15.1, -4.2)], crs=4326).to_file(source, layer='alpha', index=False)
    gpd.GeoDataFrame({'village_id': ['003'], 'population': ['7'], 'approved': ['false']},
        geometry=[Point(15.2, -4.1)], crs=4326).to_file(source, layer='beta', index=False)
    gpd.GeoDataFrame({'code': ['excluded']}, geometry=[Point(16., -4.)], crs=4326).to_file(
        source, layer='excluded', index=False)
    return source


def inspect_page(page, source, tmp_path):
    page.add_merge_sources([source])
    page.output.edit.setText(str(tmp_path))
    report = page.merge_inspection_job()(lambda *_: None, threading.Event())
    page.show_result(report)
    return report


def layer_item(page, name):
    for row in range(page.merge_layers.count()):
        item = page.merge_layers.item(row)
        if item.data(Qt.ItemDataRole.UserRole)['layer'] == name:
            return item
    raise AssertionError(name)


def select_layer(page, name):
    item = layer_item(page, name)
    identifier = item.data(Qt.ItemDataRole.UserRole)['id']
    page.merge_layer_choice.setCurrentIndex(page.merge_layer_choice.findData(identifier))
    return item


def map_field(page, source, target):
    for row in range(page.merge_mapping.rowCount()):
        if page.merge_mapping.item(row, 0).text() == source:
            choice = page.merge_mapping.cellWidget(row, 2)
            if target is None:
                choice.setCurrentIndex(0)
            elif choice.findData(target) >= 0:
                choice.setCurrentIndex(choice.findData(target))
            else:
                choice.setEditText(target)
            return
    raise AssertionError(source)


def configure_merge(page):
    page.merge_schema.setRowCount(0)
    for name, specification in {
        'code': {'type': 'string', 'nullable': False},
        'inhabitants': {'type': 'int64', 'nullable': False, 'default': 0},
        'accepted': {'type': 'boolean', 'nullable': False, 'default': False},
        'note': {'type': 'string', 'nullable': False, 'default': ''},
    }.items():
        page.add_merge_field(name, specification)
    select_layer(page, 'alpha')
    map_field(page, 'count', 'inhabitants')
    map_field(page, 'active', 'accepted')
    select_layer(page, 'beta')
    map_field(page, 'village_id', 'code')
    map_field(page, 'population', 'inhabitants')
    map_field(page, 'approved', 'accepted')
    layer_item(page, 'excluded').setCheckState(Qt.CheckState.Unchecked)


def preview_fixture(page, tmp_path):
    """A stable inspection record for UI-specific failure and restoration cases."""
    source = tmp_path / 'sources.gpkg'
    source.touch()
    page.add_merge_sources([source])
    page.output.edit.setText(str(tmp_path))
    layers = []
    for name, fields in [('alpha', ['code', 'count', 'active']),
                         ('beta', ['village_id', 'population', 'approved']),
                         ('excluded', ['code'])]:
        layers.append(dict(id='source_' + name, name=name, path=str(source), layer=name,
            source_crs='EPSG:4326', features=2 if name == 'alpha' else 1, bounds=[15, -4.3, 16, -4.],
            geometry_types=['Point'], fields=[dict(name=field, dtype='string', type='string',
                nullable=False, null_count=0, target=field) for field in fields]))
    schema = {field['name']: {'type': 'string', 'nullable': True}
              for layer in layers for field in layer['fields']}
    report = tmp_path / 'preview.json'
    report.write_text(json.dumps(dict(schema=INSPECTION_SCHEMA,
        signature=page.merge_source_configuration()[2], inspection=dict(layers=layers,
            suggested_schema=schema, conflicts=[], common_crs='EPSG:4326'))), encoding='utf-8')
    page.show_result(report)
    return report


def test_tables_map_multilayer_sources_and_publish_exact_merged_values(page, tmp_path):
    source = source_file(tmp_path)
    original = source.read_bytes()
    inspect_page(page, source, tmp_path)
    assert page.merge_layers.count() == 3
    assert page.merge_source_fields.rowCount() > 0
    configure_merge(page)
    record_path = page.job({'overwrite': False})(lambda *_: None, threading.Event())
    record = json.loads(Path(record_path).read_text(encoding='utf-8'))
    files = {Path(path) for path in record['products'].values() if str(path).endswith('.gpkg')}
    assert len(files) == 1
    merged = gpd.read_file(next(iter(files)), layer='features')
    assert merged.code.tolist() == ['001', '002', '003']
    assert merged.inhabitants.tolist() == [12, 0, 7]
    assert merged.accepted.tolist() == [True, False, False]
    assert merged.note.tolist() == ['', '', '']
    assert merged.geometry.x.tolist() == [15., 15.1, 15.2]
    assert source.read_bytes() == original


def test_merge_job_snapshots_schema_mapping_selection_and_policies(page, tmp_path, monkeypatch):
    preview_fixture(page, tmp_path)
    configure_merge(page)
    page.merge_conversion_errors.setCurrentIndex(page.merge_conversion_errors.findData('null'))
    page.merge_missing_fields.setCurrentIndex(page.merge_missing_fields.findData('error'))
    page.merge_extra_fields.setCurrentIndex(page.merge_extra_fields.findData('drop'))
    page.merge_target_crs.setText('EPSG:3857')
    page.merge_folder.setText('captured')
    captured = []
    import cartomize.desktop_merge as desktop_merge
    monkeypatch.setattr(desktop_merge, 'execute_operation', lambda *args, **kwargs: captured.append((args, kwargs)))
    run = page.job({'overwrite': False})
    page.merge_schema.item(0, 0).setText('later')
    map_field(page, 'village_id', None)
    layer_item(page, 'excluded').setCheckState(Qt.CheckState.Checked)
    page.merge_conversion_errors.setCurrentIndex(0)
    page.merge_target_crs.clear()
    page.merge_folder.setText('later')
    result = run(lambda *_: None, threading.Event())
    arguments, _ = captured[0]
    assert arguments[0] == 'vector.merge_layers'
    parameters = arguments[1]
    assert [source['layer'] for source in parameters['sources']] == ['alpha', 'beta']
    assert parameters['field_maps']['source_beta'] == {'village_id': 'code', 'population': 'inhabitants', 'approved': 'accepted'}
    assert parameters['schema']['accepted'] == {'type': 'boolean', 'nullable': False, 'default': False}
    assert parameters['schema']['note']['default'] == ''
    assert parameters['conversion_errors'] == 'null'
    assert parameters['missing_fields'] == 'error'
    assert parameters['extra_fields'] == 'drop'
    assert parameters['target_crs'] == 'EPSG:3857'
    assert result == tmp_path / 'captured' / 'operation.json'


def test_session_round_trip_keeps_tables_active_layer_typed_map_and_signals(page, application, tmp_path):
    preview_fixture(page, tmp_path)
    configure_merge(page)
    map_field(page, 'approved', 'accepted_custom')
    captured = deepcopy(capture_widgets(page))
    restored = VectorPage()
    try:
        restore_widgets(restored, captured)
        restored.restore_controls()
        assert capture_widgets(restored) == captured
        assert restored.merge_layer_choice.currentData() == 'source_beta'
        assert layer_item(restored, 'excluded').checkState() == Qt.CheckState.Unchecked
        map_field(restored, 'approved', 'accepted')
        assert layer_item(restored, 'beta').data(Qt.ItemDataRole.UserRole)['field_map']['approved'] == 'accepted'
        select_layer(restored, 'alpha')
        assert layer_item(restored, 'beta').data(Qt.ItemDataRole.UserRole)['field_map']['approved'] == 'accepted'
        assert callable(restored.job({'overwrite': False}))
        restored.operation.setCurrentIndex(restored.operation.findData('reproject_batch'))
        assert restored.output.mode == 'directory' and restored.cancellable
        assert restored.merge_section.isHidden() and not restored.batch_section.isHidden()
        restored.operation.setCurrentIndex(restored.operation.findData('repair_geometries'))
        assert restored.output.mode == 'directory'
        restored.operation.setCurrentIndex(restored.operation.findData('buffer'))
        assert restored.output.mode == 'save'
        assert not restored.source.isHidden()
        assert not restored.cancellable
    finally:
        restored.close()
        restored.deleteLater()
        application.processEvents()


def test_empty_new_controls_have_identical_session_state_after_restore(page, application):
    before = deepcopy(capture_widgets(page))
    restored = VectorPage()
    try:
        restore_widgets(restored, before)
        restored.restore_controls()
        assert capture_widgets(restored) == before
    finally:
        restored.close()
        restored.deleteLater()
        application.processEvents()


@pytest.mark.parametrize('old_batch', [True, False], ids=['1.6', '1.5'])
def test_old_session_keeps_selected_tool_and_exposes_merge(page, application, old_batch):
    page.operation.setCurrentIndex(page.operation.findData('reproject_batch' if old_batch else 'buffer'))
    previous = {name: state for name, state in capture_widgets(page).items()
                if not name.startswith('merge_') and (old_batch or not name.startswith('batch_'))}
    previous['operation']['items'] = [entry for entry in previous['operation']['items']
                                     if entry[1] != 'merge_layers' and (old_batch or entry[1] != 'reproject_batch')]
    restored = VectorPage()
    try:
        restore_widgets(restored, previous)
        restored.restore_controls()
        assert restored.operation.currentData() == ('reproject_batch' if old_batch else 'buffer')
        assert restored.operation.findData('merge_layers') >= 0
        assert restored.operation.findData('reproject_batch') >= 0
        restored.operation.setCurrentIndex(restored.operation.findData('merge_layers'))
        assert restored.output.mode == 'directory' and restored.cancellable
    finally:
        restored.close()
        restored.deleteLater()
        application.processEvents()


def test_changed_sources_reject_stale_preview_and_job(page, tmp_path):
    report = preview_fixture(page, tmp_path)
    configure_merge(page)
    page.add_merge_sources([tmp_path / 'added.gpkg'])
    page.show_result(report)
    assert 'précédentes' in page.merge_status.text()
    with pytest.raises(ValueError, match='sources ont changé'):
        page.job({'overwrite': False})


def test_reinspection_retains_edited_schema_maps_and_layer_checkboxes(page, tmp_path):
    report = preview_fixture(page, tmp_path)
    configure_merge(page)
    before = page.merge_schema_parameters()
    page.show_result(report)
    assert page.merge_schema_parameters() == before
    assert layer_item(page, 'beta').data(Qt.ItemDataRole.UserRole)['field_map']['population'] == 'inhabitants'
    assert layer_item(page, 'excluded').checkState() == Qt.CheckState.Unchecked
    assert page.merge_layer_choice.currentData() == 'source_beta'


@pytest.mark.parametrize('kind,text,expected', [('string', '001', '001'), ('string', '', ''),
    ('boolean', ' FALSE ', False), ('boolean', 'vrai', True),
    ('int64', str(2**53 + 3), 2**53 + 3), ('float64', '2.5', 2.5)])
def test_typed_defaults_preserve_text_boolean_and_integer_values(page, kind, text, expected):
    page.add_merge_field('value', {'type': kind, 'nullable': False})
    page.merge_schema.cellWidget(0, 3).setCurrentIndex(2)
    page.merge_schema.item(0, 4).setText(text)
    assert page.merge_schema_parameters()['value'] == {'type': kind, 'nullable': False, 'default': expected}


@pytest.mark.parametrize('kind,text', [('boolean', 'perhaps'), ('int64', '2.4'),
    ('int64', str(2**63)), ('float64', 'nan'), ('float64', '9007199254740993'),
    ('float64', '9.007199254740993e15')])
def test_invalid_typed_default_is_rejected_before_worker(page, kind, text):
    page.add_merge_field('value', {'type': kind})
    page.merge_schema.cellWidget(0, 3).setCurrentIndex(2)
    page.merge_schema.item(0, 4).setText(text)
    with pytest.raises(ValueError, match='défaut invalide'):
        page.merge_schema_parameters()


def test_conflicting_types_and_mapping_collisions_require_explicit_resolution(page, tmp_path):
    preview_fixture(page, tmp_path)
    configure_merge(page)
    page.merge_schema.cellWidget(0, 1).setCurrentIndex(0)
    with pytest.raises(ValueError, match='Choisir le type'):
        page.job({'overwrite': False})
    page.merge_schema.cellWidget(0, 1).setCurrentIndex(1)
    map_field(page, 'population', 'code')
    with pytest.raises(ValueError, match='même champ cible'):
        page.job({'overwrite': False})


def test_inspection_error_and_precancel_cleanup_temporary_directory(page, tmp_path, monkeypatch):
    import cartomize.vector_merge as vector_merge
    from cartomize import ProcessingCancelled
    page.add_merge_sources([tmp_path / 'input.gpkg'])
    cancelled = threading.Event()
    cancelled.set()
    run = page.merge_inspection_job()
    with pytest.raises(ProcessingCancelled):
        run(lambda *_: None, cancelled)
    assert not Path(page._merge_preview_dirs[-1].name).exists()
    def fail(*args, **kwargs):
        raise ValueError('inspection failure')
    monkeypatch.setattr(vector_merge, 'inspect_merge', fail)
    run = page.merge_inspection_job()
    with pytest.raises(ValueError, match='inspection failure'):
        run(lambda *_: None, threading.Event())
    assert not Path(page._merge_preview_dirs[-1].name).exists()


@pytest.mark.parametrize('font_size,wide_labels', [(12, False), (16, False), (12, True)],
                         ids=['12', '16', 'wide_native_labels'])
def test_merge_form_fits_compact_window(application, tmp_path, monkeypatch, font_size, wide_labels):
    import cartomize.desktop as desktop
    monkeypatch.setattr(desktop, 'QSettings', lambda *args: QSettings(str(tmp_path / 'appearance.ini'), QSettings.Format.IniFormat))
    window = desktop.CartomizeWindow()
    try:
        window._workbench.font_size.setValue(font_size)
        window.resize(1100, 740)
        window.show()
        window.select_tool('vector')
        page = window.tool('vector')
        page.operation.setCurrentIndex(page.operation.findData('merge_layers'))
        preview_fixture(page, tmp_path)
        configure_merge(page)
        if wide_labels:
            page.merge_recursive.setStyleSheet('font-size: 24px;')
        QTest.qWait(50)
        scroll = window.stack.currentWidget()
        for control in (page.merge_inspect_button, page.merge_schema, page.merge_mapping, page.output):
            scroll.ensureWidgetVisible(control)
            QTest.qWait(20)
            geometry = dict(font_size=font_size, wide_labels=wide_labels,
                style=application.style().objectName(), viewport=scroll.viewport().size().toTuple(),
                page=page.size().toTuple(), minimum_hint=page.minimumSizeHint().toTuple(),
                layout_minimum=page.layout.minimumSize().toTuple(),
                merge_minimum=page.merge_section.minimumSizeHint().toTuple(),
                horizontal_range=scroll.horizontalScrollBar().maximum())
            if geometry['horizontal_range']:
                names = {id(value): key for key, value in vars(page).items() if isinstance(value, QWidget)}
                geometry['widest_controls'] = sorted([
                    dict(minimum_width=child.minimumSizeHint().width(), width=child.width(),
                         type=type(child).__name__, name=names.get(id(child), child.objectName()),
                         text=getattr(child, 'text', lambda: '')()[:120],
                         font_family=child.font().family(), font_pixels=child.font().pixelSize())
                    for child in page.findChildren(QWidget) if child.isVisible()
                ], key=lambda record: record['minimum_width'], reverse=True)[:12]
                print('Merge form geometry: ' + json.dumps(geometry, ensure_ascii=False))
            assert scroll.horizontalScrollBar().maximum() == 0, json.dumps(geometry, ensure_ascii=False)
            assert control.width() <= scroll.viewport().width()
        assert page.merge_recursive.width() >= page.merge_recursive.minimumSizeHint().width()
        assert page.merge_recursive.height() >= page.merge_recursive.sizeHint().height()
        # The last editable default must be completely reachable even in the
        # narrow panel; stretching that column formerly clipped its text.
        page.merge_schema.horizontalScrollBar().setValue(page.merge_schema.horizontalScrollBar().maximum())
        QTest.qWait(10)
        rectangle = page.merge_schema.visualItemRect(page.merge_schema.item(2, 4))
        assert rectangle.left() >= 0
        assert rectangle.right() < page.merge_schema.viewport().width()
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


def test_inspection_and_merge_use_window_worker_and_results_workspace(application, tmp_path, monkeypatch):
    import cartomize.desktop as desktop
    monkeypatch.setattr(desktop, 'QSettings', lambda *args: QSettings(str(tmp_path / 'worker.ini'), QSettings.Format.IniFormat))
    source = source_file(tmp_path)
    window = desktop.CartomizeWindow()
    try:
        window.select_tool('vector')
        page = window.tool('vector')
        page.operation.setCurrentIndex(page.operation.findData('merge_layers'))
        page.add_merge_sources([source])
        page.output.edit.setText(str(tmp_path))
        page.inspect_merge_sources()
        wait_for_window(window, application)
        configure_merge(page)
        window.start()
        wait_for_window(window, application)
        record = json.loads(Path(window.output_path).read_text(encoding='utf-8'))
        products = list(dict.fromkeys(path for path in record['products'].values() if str(path).endswith('.gpkg')))
        assert len(products) == 1
        assert products[0] in window.workspace.records
        assert gpd.read_file(products[0]).code.tolist() == ['001', '002', '003']
    finally:
        if window.thread is not None:
            window.cancel()
            window.thread.wait(10000)
            application.processEvents()
        window.close()
        application.processEvents()
