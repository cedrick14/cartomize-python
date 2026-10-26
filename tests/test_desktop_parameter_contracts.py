"""Typed processing choices, nullable records and the zonal parameter layout."""
import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest

pytest.importorskip('PySide6')
from PySide6.QtCore import QPoint, QSettings
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QPushButton

from cartomize.desktop_processing import OperationDialog


@pytest.fixture(scope='module')
def application():
    return QApplication.instance() or QApplication([])


CASES = [
    ('routing', 'snap', 'edge', ('edge', 'node'),
     {'source': 'network.gpkg', 'start': [0, 0], 'end': [1, 1]}),
    ('vector.join_attributes', 'null_keys', 'unmatched', ('unmatched', 'match', 'error'),
     {'data': 'zones.gpkg', 'table': 'table.csv', 'left_on': 'code'}),
    ('raster.zonal_stats', 'value_mode', 'physical', ('physical', 'raw'),
     {'source': 'image.tif', 'zones': 'zones.gpkg'}),
]


@pytest.mark.parametrize('operation,name,default,choices,required', CASES)
def test_french_choices_preserve_api_defaults_and_saved_values(application, operation, name, default, choices, required):
    editor = OperationDialog([], dict(id='step', operation=operation, parameters=required), allow_map=False)
    try:
        control = editor.controls[name]
        assert not control.isEditable()
        assert control.currentData() == default
        assert editor.value()['parameters'][name] == default
        for value in choices:
            control.setCurrentIndex(control.findData(value))
            assert control.currentText() != value
            record = editor.value()
            assert record['parameters'][name] == value
            restored = OperationDialog([], record, allow_map=False)
            try:
                assert restored.controls[name].currentData() == value
                assert restored.value() == record
            finally:
                restored.close()
                restored.deleteLater()
    finally:
        editor.close()
        editor.deleteLater()
        application.processEvents()


@pytest.mark.parametrize('operation,name,default,choices,required', CASES)
def test_unknown_saved_choice_is_visible_and_correctable(application, monkeypatch, operation, name, default, choices, required):
    editor = OperationDialog([], dict(id='step', operation=operation,
                                     parameters={**required, name: 'obsolete_policy'}), allow_map=False)
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda parent, title, message: warnings.append(message))
    try:
        control = editor.controls[name]
        assert control.currentIndex() == -1
        assert 'obsolete_policy' in control.placeholderText()
        with pytest.raises(ValueError, match='obsolete_policy'):
            editor.value()
        editor.accept()
        assert warnings and 'obsolete_policy' in warnings[0]
        assert editor.result() != QDialog.DialogCode.Accepted
        assert not hasattr(editor, 'result_record')
        control.setCurrentIndex(control.findData(default))
        editor.accept()
        assert editor.result() == QDialog.DialogCode.Accepted
        assert editor.result_record['parameters'][name] == default
    finally:
        editor.close()
        editor.deleteLater()
        application.processEvents()


def test_explicit_null_paths_and_parameters_survive_reopening(application):
    record = dict(id='predict', operation='classify', parameters={
        'source': 'image.tif', 'training': None, 'model': 'model.json',
        'validation': None, 'group_column': None,
    })
    editor = OperationDialog([], record, allow_map=False)
    try:
        for name in ('training', 'validation', 'group_column'):
            assert editor.controls[name].currentText() == ''
            assert editor.value()['parameters'][name] is None
        editor.controls['validation'].setCurrentText('validation.gpkg')
        saved = editor.value()
        assert saved['parameters']['validation'] == 'validation.gpkg'
        restored = OperationDialog([], saved, allow_map=False)
        try:
            assert restored.value() == saved
        finally:
            restored.close()
            restored.deleteLater()
    finally:
        editor.close()
        editor.deleteLater()
        application.processEvents()


def test_zonal_form_fits_default_window_and_keeps_browse_buttons_visible(application, tmp_path, monkeypatch):
    import cartomize.desktop as desktop
    monkeypatch.setattr(desktop, 'QSettings', lambda *args: QSettings(str(tmp_path / 'appearance.ini'), QSettings.Format.IniFormat))
    window = desktop.CartomizeWindow()
    try:
        window.resize(1440, 940)
        window.select_tool('raster')
        page = window.tool('raster')
        page.operation.setCurrentIndex(page.operation.findData('zonal_stats'))
        window.show()
        QTest.qWait(50)
        scroll = window.stack.currentWidget()
        viewport = scroll.viewport()
        assert window.width() == 1440 and window.height() == 940
        assert scroll.horizontalScrollBar().maximum() == 0
        assert 'zone_pixels' in page.include_coverage.toolTip()
        assert 'hors du raster' in page.include_coverage.toolTip()
        for field in (page.source, page.secondary, page.output):
            buttons = field.findChildren(QPushButton)
            assert buttons
            for button in buttons:
                left = button.mapTo(viewport, QPoint(0, 0)).x()
                assert 0 <= left < left + button.width() <= viewport.width()
    finally:
        window.close()
        application.processEvents()
