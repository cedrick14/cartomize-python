"""Compact displays retain map space and reachable execution controls."""
import os
import time

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import numpy as np
import pytest
pytest.importorskip('PySide6')
from PySide6.QtCore import QEventLoop, QPoint, QSettings, QTimer
from PySide6.QtWidgets import QApplication, QBoxLayout
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
def compact_window(tmp_path):
    app = QApplication.instance() or QApplication([])
    old_format = QSettings.defaultFormat()
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / 'settings'))
    window = CartomizeWindow()
    try:
        yield app, window
    finally:
        window.close()
        app.processEvents()
        QSettings.setDefaultFormat(old_format)


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
