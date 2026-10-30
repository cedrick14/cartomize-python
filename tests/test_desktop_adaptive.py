"""Compact displays retain map space and reachable execution controls."""
import os
import time

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import numpy as np
import pytest
pytest.importorskip('PySide6')
from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QPoint, QSettings, QTimer, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QBoxLayout, QLabel, QToolBar, QToolButton, QWidgetItem
from shiboken6 import isValid
from cartomize.desktop import CartomizeWindow


def wait_for(predicate, timeout=20):
    loop = QEventLoop()
    timer = QTimer()
    deadline = time.monotonic() + timeout
    timer.timeout.connect(lambda: loop.quit() if predicate() or time.monotonic() >= deadline else None)
    timer.start(10)
    if not predicate():
        loop.exec()
    timer.stop()
    assert predicate()


@pytest.fixture
def compact_window(tmp_path, monkeypatch):
    import cartomize.desktop as desktop
    app = QApplication.instance() or QApplication([])
    preferences = tmp_path / 'preferences.ini'
    monkeypatch.setattr(desktop, 'QSettings', lambda *args:
                        QSettings(str(preferences), QSettings.Format.IniFormat))
    window = CartomizeWindow()
    assert window._preferences.fileName() == str(preferences)
    try:
        yield app, window
    finally:
        window.close()
        app.processEvents()


@pytest.mark.parametrize('font_size', [12, 14, 16])
def test_compact_viewport_and_actions(compact_window, write_raster, font_size):
    app, window = compact_window
    window._workbench.font_size.setValue(font_size)
    window.resize(1100, 740)
    window.show()
    source = write_raster('display.tif', np.arange(80000, dtype='float32').reshape(200, 400))
    window.register_result({'data': str(source)})
    document = window.workspace.open_result(str(source))
    wait_for(lambda: document.canvas.last_render is not None)
    for tool in ('raster', 'vector', 'mapping', 'indices'):
        window.select_tool(tool)
        app.processEvents()
        button = window.run_button
        top = button.mapTo(window.controls_panel, QPoint(0, 0))
        assert button.isVisible()
        assert window.controls_panel.rect().contains(top)
        assert window.controls_panel.rect().contains(top + QPoint(button.width()-1, button.height()-1))
        page = window.tool(tool)
        inner = window.stack.currentWidget()
        window.parameters_scroll.ensureWidgetVisible(window.stack)
        inner.ensureWidgetVisible(page.output)
        app.processEvents()
        assert page.output.isVisible()
        assert document.canvas.viewport().height() >= 100
        assert document.canvas.viewport().width() >= 100
    assert window._adaptive_workspace._transfer_row.direction() == QBoxLayout.Direction.TopToBottom
    assert window.bottom_dock.height() < 200


def test_console_and_restored_layout_keep_controls_reachable(compact_window):
    app, window = compact_window
    window.resize(1100, 740)
    window.show()
    window._workbench.show_console()
    wait_for(lambda: window.bottom_dock.height() >= 210)
    assert window.console_panel.execute_button.isVisible()
    window._workbench.reset_layout()
    app.processEvents()
    window._adaptive_workspace.fit()
    assert window.run_button.isVisible()
    assert window.parameters_scroll.widgetResizable()
    assert window.workspace.height() >= 360
    window.resize(1600, 1000)
    app.processEvents()
    window._workbench.bottom_tabs.setCurrentWidget(window._workbench.logs)
    app.processEvents()
    assert window.workspace.height() >= 360


def test_compact_toolbar_labels_survive_action_updates(compact_window):
    _, window = compact_window
    workbench = window._workbench
    buttons = {button.defaultAction(): button for button in workbench.toolbar.findChildren(QToolButton)}
    for key, label, menu, shortcut in [
        ('open', 'Ouvrir', 'Ouvrir un projet', 'Ctrl+O'),
        ('save', 'Enregistrer', 'Enregistrer le projet', 'Ctrl+S'),
        ('import', 'Importer', 'Importer des données', 'Ctrl+I'),
        ('run', 'Exécuter', 'Exécuter le traitement', 'F5'),
    ]:
        action = workbench.actions[key]
        button = buttons[action]
        for enabled in (False, True, False, True):
            action.setEnabled(enabled)
            assert button.isEnabled() == enabled
            assert button.text() == label
            assert button.toolTip() == menu
            assert action.text() == menu
            assert action.shortcut().toString() == shortcut


@pytest.mark.parametrize('unexpected_wrapper', [False, True])
def test_toolbar_actions_survive_window_recreation(tmp_path, monkeypatch, unexpected_wrapper):
    """Keep Qt-owned button lookup out of construction and exercise real actions."""
    import cartomize.desktop as desktop
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(desktop, 'QSettings',
        lambda *args: QSettings(str(tmp_path / 'preferences.ini'), QSettings.Format.IniFormat))
    lookups = []
    if unexpected_wrapper:
        # Reproduce the return type seen in CI without corrupting native objects.
        marker = QLabel('Layout item, not a toolbar control')
        layout_item = QWidgetItem(marker)
        def widget_for_action(toolbar, action):
            lookups.append(action)
            return layout_item
        monkeypatch.setattr(QToolBar, 'widgetForAction', widget_for_action)
    for _ in range(3):
        window = desktop.CartomizeWindow()
        try:
            window.select_tool('prepare')
            window.show()
            QTest.qWait(10)
            action = window._workbench.actions['run']
            button = next(control for control in window._workbench.toolbar.findChildren(QToolButton)
                          if control.defaultAction() is action)
            triggered = QSignalSpy(action.triggered)
            clicked = QSignalSpy(window.run_button.clicked)
            QTest.mouseClick(button, Qt.MouseButton.LeftButton)
            assert triggered.count() == clicked.count() == 1
            assert window.thread is None  # Missing imagery inputs stop at validation.
            assert button.text() == 'Exécuter'
            assert action.shortcut().toString() == 'F5'
        finally:
            window.close()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            app.processEvents()
        assert not isValid(window)
        assert not isValid(action)
        assert not isValid(button)
    assert not lookups
