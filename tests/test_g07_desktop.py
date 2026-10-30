"""G07 decisions survive sessions and produce inspectable extraction bundles."""
from copy import deepcopy
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import threading

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import geopandas as gpd
import numpy as np
from pyogrio.raw import write as raw_write
from pyproj import CRS
import pytest
import shapely
from shapely.geometry import Point, box

pytest.importorskip('PySide6')
from PySide6.QtCore import QEventLoop, QSettings, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

import cartomize as cm
from cartomize.desktop_session import capture_widgets, restore_widgets
from cartomize.desktop_vector import VectorPage


@pytest.fixture(scope='module')
def application():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def page(application):
    widget = VectorPage()
    widget.operation.setCurrentIndex(widget.operation.findData('extract_features'))
    yield widget
    widget.close()
    widget.deleteLater()
    application.processEvents()


def sources(tmp_path, *, multiple=False):
    source, mask = tmp_path / 'source.gpkg', tmp_path / 'mask.gpkg'
    raw_write(source, geometry=shapely.to_wkb([Point(i, 0) for i in range(4)]),
        field_data=[np.array([2**53 + i for i in range(1, 5)], dtype='int64'),
                    np.array(['Alpha', 'Beta', 'true', 'Delta'], dtype=object),
                    np.array([True, False, True, False], dtype=bool),
                    np.array(['2024-02-29', '2024-03-01', '2024-03-02', '2024-03-03'], dtype='datetime64[D]')],
        fields=['large_id', 'name', 'active', 'survey_date'],
        layer='observations', driver='GPKG', geometry_type='Point', crs=CRS(3857).to_wkt(),
        layer_options={'SPATIAL_INDEX': 'NO'})
    gpd.GeoDataFrame({'zone': ['interest']}, geometry=[box(-.5, -.5, 1.5, .5)], crs=3857).to_file(mask, layer='zones', index=False)
    if multiple:
        gpd.GeoDataFrame({'other': [7]}, geometry=[Point(5, 0)], crs=3857).to_file(source, layer='other', index=False)
        gpd.GeoDataFrame({'other_zone': [8]}, geometry=[box(5, 5, 6, 6)], crs=3857).to_file(mask, layer='other', index=False)
    return source, mask


def choose(control, value):
    index = control.findData(value)
    assert index >= 0, value
    control.setCurrentIndex(index)


def configure(page, source, mask, tmp_path):
    page.source.edit.setText(str(source))
    page.selection_mask.edit.setText(str(mask))
    page.refresh_fields()
    choose(page.selection_layer, 'observations')
    choose(page.selection_mask_layer, 'zones')
    choose(page.selection_id, 'large_id')
    page.output.edit.setText(str(tmp_path))
    page.selection_folder.setText('selection')


def add_filter(page, field='large_id', comparison='ge', value='9007199254740994'):
    page.selection_field.setCurrentText(field)
    choose(page.selection_comparison, comparison)
    page.selection_value.setPlainText(value)
    assert page.add_selection_filter(), page.selection_value_note.text()


def filters(page):
    return [page.selection_filters.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(page.selection_filters.count())]


def test_multilayer_sources_require_independent_choices_and_matching_fields(page, tmp_path):
    source, mask = sources(tmp_path, multiple=True)
    page.source.edit.setText(str(source))
    page.selection_mask.edit.setText(str(mask))
    page.output.edit.setText(str(tmp_path))
    page.refresh_fields()
    assert page.selection_layer.currentData() is None
    assert page.selection_mask_layer.currentData() is None
    with pytest.raises(ValueError, match='explicitement la couche source'):
        page.job({})
    choose(page.selection_layer, 'observations')
    add_filter(page)
    choose(page.selection_mode, 'combined')
    with pytest.raises(ValueError, match='couche du masque'):
        page.job({})
    choose(page.selection_mask_layer, 'zones')
    assert callable(page.job({}))
    choose(page.selection_layer, 'other')
    assert page.selection_field.currentText() == 'other'
    assert page.selection_id.currentData() is None
    with pytest.raises(ValueError, match='champ absent'):
        page.job({})


@pytest.mark.parametrize('field,comparison,text,expected', [
    ('large_id', 'gt', '9007199254740993.1', '9007199254740993.1'),
    ('large_id', 'in', '9007199254740993\n9007199254740995', ['9007199254740993', '9007199254740995']),
    ('name', 'eq', 'true', 'true'),
    ('name', 'in', 'Alpha\ntrue', ['Alpha', 'true']),
    ('active', 'eq', 'false', False),
    ('active', 'in', 'true\nfalse', [True, False]),
    ('survey_date', 'ge', '2024-03-01', '2024-03-01'),
    ('survey_date', 'in', '2024-02-29\n2024-03-03', ['2024-02-29', '2024-03-03']),
    ('large_id', 'is_null', '', None),
])
def test_filter_editor_preserves_exact_numbers_text_dates_and_booleans(page, tmp_path, field, comparison, text, expected):
    source, mask = sources(tmp_path)
    configure(page, source, mask, tmp_path)
    add_filter(page, field, comparison, text)
    assert filters(page) == [dict(field=field, comparison=comparison, value=expected)]


def test_invalid_boolean_does_not_add_silent_text_filter_and_edit_removal_work(page, tmp_path):
    source, mask = sources(tmp_path)
    configure(page, source, mask, tmp_path)
    page.selection_field.setCurrentText('active')
    page.selection_value.setPlainText('yes')
    assert page.add_selection_filter() is False
    assert not filters(page)
    assert 'true ou false' in page.selection_value_note.text()
    add_filter(page, 'active', 'eq', 'true')
    page.selection_value.setPlainText('false')
    assert page.replace_selection_filter()
    assert filters(page)[0]['value'] is False
    page.remove_selection_filter()
    assert not filters(page)


def test_job_captures_filters_layers_modes_inversion_and_worker_hooks(page, tmp_path, monkeypatch):
    source, mask = sources(tmp_path)
    configure(page, source, mask, tmp_path)
    add_filter(page)
    add_filter(page, 'active', 'eq', 'true')
    choose(page.selection_attribute_match, 'any')
    choose(page.selection_mode, 'combined')
    choose(page.selection_combination, 'or')
    choose(page.selection_predicate, 'within')
    page.selection_invert.setChecked(True)
    import cartomize.desktop_selection as selection
    captured = []
    monkeypatch.setattr(selection, 'execute_operation', lambda *args, **kwargs: captured.append((args, kwargs)))
    run = page.job({})
    page.selection_filters.clear()
    page.selection_invert.setChecked(False)
    page.selection_mask.edit.clear()
    page.selection_folder.setText('later')
    event, progress = threading.Event(), lambda *_: None
    assert run(progress, event) == tmp_path / 'selection' / 'operation.json'
    args, kwargs = captured[0]
    assert args == ('vector.extract_features', dict(data=str(source), layer='observations',
        filters=[dict(field='large_id', comparison='ge', value='9007199254740994'),
                 dict(field='active', comparison='eq', value=True)], attribute_match='any',
        mask=str(mask), mask_layer='zones', predicate='within', combination='or', invert=True,
        id_field='large_id'), tmp_path / 'selection')
    assert kwargs == dict(progress=progress, cancel=event)


def test_spatial_only_ignores_dormant_attribute_filters_and_can_return_to_simple_tools(page, tmp_path, monkeypatch):
    source, mask = sources(tmp_path)
    configure(page, source, mask, tmp_path)
    choose(page.selection_mode, 'spatial')
    import cartomize.desktop_selection as selection
    captured = []
    monkeypatch.setattr(selection, 'execute_operation', lambda *args, **kwargs: captured.append(args[1]))
    page.job({})(lambda *_: None, threading.Event())
    assert captured[0]['filters'] is None
    assert page.output.mode == 'directory' and page.cancellable
    choose(page.operation, 'select_attributes')
    assert page.output.mode == 'save'
    assert not page.selection_section.isVisible()
    choose(page.operation, 'extract_features')
    assert page.output.mode == 'directory' and page.cancellable


def test_widget_session_restores_multilayer_choices_filters_and_draft_values(page, application, tmp_path):
    source, mask = sources(tmp_path, multiple=True)
    configure(page, source, mask, tmp_path)
    add_filter(page)
    add_filter(page, 'active', 'eq', 'false')
    choose(page.selection_mode, 'combined')
    choose(page.selection_attribute_match, 'any')
    choose(page.selection_combination, 'or')
    page.selection_invert.setChecked(True)
    # A draft value is independent of the completed filter stored in the list.
    page.selection_field.setCurrentText('name')
    page.selection_value.setPlainText('draft')
    state = deepcopy(capture_widgets(page))
    restored = VectorPage()
    try:
        restore_widgets(restored, state)
        restored.restore_controls()
        assert restored.selection_layer.currentData() == 'observations'
        assert restored.selection_mask_layer.currentData() == 'zones'
        assert restored.selection_id.currentData() == 'large_id'
        assert filters(restored) == filters(page)
        assert restored.selection_mode.currentData() == 'combined'
        assert restored.selection_attribute_match.currentData() == 'any'
        assert restored.selection_combination.currentData() == 'or'
        assert restored.selection_invert.isChecked()
        assert restored.selection_field.currentText() == 'name'
        assert restored.selection_value.toPlainText() == 'draft'
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


@pytest.mark.parametrize('mode', ['attributes', 'combined'])
def test_worker_publishes_native_dates_exclusions_and_report_in_workspace(application, tmp_path, monkeypatch, mode):
    import cartomize.desktop as desktop
    monkeypatch.setattr(desktop, 'QSettings', lambda *args: QSettings(str(tmp_path / 'worker.ini'), QSettings.Format.IniFormat))
    source, mask = sources(tmp_path)
    original = [hashlib.sha256(path.read_bytes()).hexdigest() for path in (source, mask)]
    window = desktop.CartomizeWindow()
    try:
        window.select_tool('vector')
        page = window.tool('vector')
        choose(page.operation, 'extract_features')
        configure(page, source, mask, tmp_path)
        add_filter(page)
        choose(page.selection_mode, mode)
        window.start()
        wait_for_window(window, application)
        record = json.loads(Path(window.output_path).read_text(encoding='utf-8'))
        products = record['products']
        selected, rejected = cm.read_file(products['data']), cm.read_file(products['rejected'])
        selected_positions = [1] if mode == 'combined' else [1, 2, 3]
        rejected_positions = [0, 2, 3] if mode == 'combined' else [0]
        assert selected.large_id.tolist() == [2**53 + 1 + i for i in selected_positions]
        assert rejected.large_id.tolist() == [2**53 + 1 + i for i in rejected_positions]
        assert selected.survey_date.tolist() == [date(2024, 3, i) for i in selected_positions]
        assert [hashlib.sha256(path.read_bytes()).hexdigest() for path in (source, mask)] == original
        for key in ('data', 'rejected', 'report', 'audit', 'summary'):
            assert products[key] in window.workspace.records
        assert page.selection_report_button.isEnabled() and page.selection_rejected_button.isEnabled()
        assert '?' not in page.selection_result_status.text()
        page.selection_rejected_button.click()
        assert window.workspace.catalog.currentData() == products['rejected']
        page.selection_report_button.click()
        assert window.workspace.catalog.currentData() == products['report']
        table = page.open_selection_product('report')
        for _ in range(100):
            if len(table.frame) == 4:
                break
            QTest.qWait(20)
        assert len(table.frame) == 4
        assert table.frame.selected.tolist() == [i in selected_positions for i in range(4)]
        if mode == 'attributes':
            assert table.frame.spatial_match.isna().all()
        # Later edits never redirect the result buttons to an unexecuted job.
        page.selection_folder.setText('future')
        page.selection_data_button.click()
        assert window.workspace.catalog.currentData() == products['data']
    finally:
        if window.thread is not None:
            window.cancel()
            window.thread.wait(10000)
            application.processEvents()
        window.close()
        application.processEvents()


def test_portable_session_relocates_filters_sources_and_completed_bundle(application, tmp_path, monkeypatch):
    import cartomize.desktop as desktop
    from cartomize.session import load_session, save_session
    monkeypatch.setattr(desktop, 'QSettings', lambda *args: QSettings(str(tmp_path / 'portable.ini'), QSettings.Format.IniFormat))
    source, mask = sources(tmp_path)
    original, restored = desktop.CartomizeWindow(), desktop.CartomizeWindow()
    try:
        original.select_tool('vector')
        page = original.tool('vector')
        choose(page.operation, 'extract_features')
        configure(page, source, mask, tmp_path)
        add_filter(page, 'survey_date', 'in', '2024-02-29\n2024-03-03')
        choose(page.selection_mode, 'combined')
        path = page.job({})(lambda *_: None, threading.Event())
        page.show_result(path)
        archive = save_session(original.capture_session(), tmp_path / 'selection.cmz', portable=True)
        extracted = tmp_path / 'restored'
        loaded = load_session(archive, directory=extracted)
        assert not loaded.missing
        (tmp_path / 'selection').rename(tmp_path / 'original-selection')
        restored.restore_session(loaded.state)
        page = restored.tool('vector')
        assert Path(page.source.text()).is_relative_to(extracted)
        assert Path(page.selection_mask.text()).is_relative_to(extracted)
        assert Path(page.selection_result_path.text()).is_relative_to(extracted)
        assert filters(page) == [dict(field='survey_date', comparison='in', value=['2024-02-29', '2024-03-03'])]
        assert page.selection_layer.currentData() == 'observations'
        assert page.selection_mask_layer.currentData() == 'zones'
        record = page._selection_result_record()
        for key in ('data', 'rejected', 'report', 'audit', 'summary'):
            assert Path(record['products'][key]).is_relative_to(extracted)
            assert Path(record['products'][key]).is_file()
        page.selection_report_button.click()
        assert restored.workspace.catalog.currentData() == record['products']['report']
    finally:
        original.close()
        restored.close()
        application.processEvents()


@pytest.mark.parametrize('mode,font_size', [('attributes', 12), ('attributes', 16), ('combined', 12), ('combined', 16)])
def test_g07_controls_fit_compact_window(application, tmp_path, monkeypatch, mode, font_size):
    import cartomize.desktop as desktop
    monkeypatch.setattr(desktop, 'QSettings', lambda *args: QSettings(str(tmp_path / 'compact.ini'), QSettings.Format.IniFormat))
    source, mask = sources(tmp_path)
    window = desktop.CartomizeWindow()
    try:
        window._workbench.font_size.setValue(font_size)
        window.resize(1100, 740)
        window.show()
        window.select_tool('vector')
        page = window.tool('vector')
        choose(page.operation, 'extract_features')
        configure(page, source, mask, tmp_path)
        choose(page.selection_mode, mode)
        add_filter(page)
        QTest.qWait(40)
        scroll = window.stack.currentWidget()
        controls = [page.selection_layer, page.selection_filters, page.selection_value,
                    page.selection_invert, page.selection_report_button, page.output]
        if mode == 'combined':
            controls += [page.selection_mask, page.selection_mask_layer, page.selection_combination]
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
                print('G07 form geometry: ' + json.dumps(geometry, ensure_ascii=False))
            assert scroll.horizontalScrollBar().maximum() == 0, json.dumps(geometry, ensure_ascii=False)
            assert 100 <= control.width() <= scroll.viewport().width()
        assert window.run_button.isVisible()
    finally:
        window.close()
        application.processEvents()
