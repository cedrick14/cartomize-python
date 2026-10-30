"""Native panel gestures preserve tools, views and recoverable layouts."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
import pytest
pytest.importorskip('PySide6')
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid


@pytest.fixture
def desktop(tmp_path, monkeypatch):
    import cartomize.desktop as module
    app = QApplication.instance() or QApplication([])
    preferences = tmp_path / 'workspace.ini'
    monkeypatch.setattr(module, 'QSettings', lambda *args:
                        QSettings(str(preferences), QSettings.Format.IniFormat))
    window = module.CartomizeWindow()
    window.resize(1440, 940)
    window.show()
    app.processEvents()
    yield app, window, preferences
    if isValid(window):
        window.close()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def test_parameters_detach_resize_maximize_and_reopen_without_losing_values(desktop):
    app, window, _ = desktop
    window.select_tool('calculator')
    page = window.tool('calculator')
    page.expression.setPlainText('b1 * 2')
    dock = window.parameters_dock
    bar = dock.titleBarWidget()
    QTest.mouseClick(bar.float_button, Qt.MouseButton.LeftButton)
    assert dock.isFloating() and dock.widget() is window.controls_panel
    dock.resize(900, 610)
    app.processEvents()
    assert dock.width() >= 850
    assert page.expression.toPlainText() == 'b1 * 2'
    QTest.mouseClick(bar.focus_button, Qt.MouseButton.LeftButton)
    assert dock.isMaximized()
    QTest.mouseClick(bar.focus_button, Qt.MouseButton.LeftButton)
    assert not dock.isMaximized()
    QTest.mouseClick(bar.float_button, Qt.MouseButton.LeftButton)
    assert not dock.isFloating()
    assert window.dockWidgetArea(dock) == Qt.DockWidgetArea.RightDockWidgetArea
    QTest.mouseClick(bar.close_button, Qt.MouseButton.LeftButton)
    assert not dock.isVisible()
    window._workbench.actions['tool_calculator'].trigger()
    assert dock.isVisible() and page.expression.toPlainText() == 'b1 * 2'


def test_focus_and_escape_restore_exact_panel_visibility(desktop):
    app, window, _ = desktop
    window.bottom_dock.hide()
    visible = {dock.objectName(): dock.isVisible() for dock in window.dock_manager.docks}
    window._workbench.actions['focus_view'].trigger()
    app.processEvents()
    assert window.centralWidget().isVisible()
    assert not any(dock.isVisible() for dock in window.dock_manager.docks)
    QTest.keyClick(window, Qt.Key.Key_Escape)
    assert {dock.objectName(): dock.isVisible() for dock in window.dock_manager.docks} == visible
    QTest.mouseClick(window.parameters_dock.titleBarWidget().focus_button, Qt.MouseButton.LeftButton)
    app.processEvents()
    assert not window.centralWidget().isVisible()
    assert window.parameters_dock.isVisible()
    assert window.parameters_dock.width() > window.width() * .7
    QTest.keyClick(window.parameters_dock, Qt.Key.Key_Escape)
    assert window.centralWidget().isVisible()
    assert {dock.objectName(): dock.isVisible() for dock in window.dock_manager.docks} == visible


def test_drag_shows_placement_guides_and_docks_on_release(desktop):
    app, window, _ = desktop
    manager = window.dock_manager
    dock = window.parameters_dock
    bar = dock.titleBarWidget()
    QTest.mousePress(bar, Qt.MouseButton.LeftButton, pos=QPoint(40, 12))
    center = window.centralWidget().mapToGlobal(window.centralWidget().rect().center())
    QTest.mouseMove(bar, bar.mapFromGlobal(center), delay=10)
    app.processEvents()
    assert dock.isFloating() and manager.guides.isVisible()
    assert {'left', 'right', 'top', 'bottom'} <= set(manager.guides.targets)
    target = window.mapToGlobal(manager.guides.targets['outer_bottom'][0].center())
    QTest.mouseMove(bar, bar.mapFromGlobal(target), delay=10)
    assert manager.guides.active_target is not None
    assert not manager.guides.preview.isEmpty()
    QTest.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=bar.mapFromGlobal(target))
    app.processEvents()
    assert not manager.guides.isVisible()
    assert not dock.isFloating()
    assert window.dockWidgetArea(dock) == Qt.DockWidgetArea.BottomDockWidgetArea
    assert window.run_button.isVisible()


def test_escape_cancels_a_real_title_drag(desktop):
    app, window, _ = desktop
    dock = window.parameters_dock
    bar = dock.titleBarWidget()
    previous = window.dockWidgetArea(dock)
    QTest.mousePress(bar, Qt.MouseButton.LeftButton, pos=QPoint(40, 12))
    center = window.centralWidget().mapToGlobal(window.centralWidget().rect().center())
    QTest.mouseMove(bar, bar.mapFromGlobal(center), delay=10)
    assert window.dock_manager.guides.isVisible()
    QTest.keyClick(bar, Qt.Key.Key_Escape)
    app.processEvents()
    assert not window.dock_manager.guides.isVisible()
    assert not dock.isFloating() and window.dockWidgetArea(dock) == previous
    assert not window.dock_manager.user_layout
    QTest.mouseRelease(bar, Qt.MouseButton.LeftButton)


def test_closing_an_enlarged_panel_restores_the_workspace(desktop):
    app, window, _ = desktop
    window.bottom_dock.hide()
    dock = window.parameters_dock
    window.dock_manager.focus(dock)
    QTest.mouseClick(dock.titleBarWidget().close_button, Qt.MouseButton.LeftButton)
    app.processEvents()
    assert window.centralWidget().isVisible()
    assert not dock.isVisible() and not window.bottom_dock.isVisible()
    assert window.tools_dock.isVisible() and window.project_explorer.isVisible()
    assert window.dock_manager._focus_state is None


def test_click_and_cancelled_drag_preserve_a_maximized_floating_panel(desktop):
    app, window, _ = desktop
    dock = window.parameters_dock
    manager = window.dock_manager
    manager.set_floating(dock, True)
    dock.resize(600, 450)
    manager.focus(dock)
    app.processEvents()
    normal_size = dock.normalGeometry().size()
    bar = dock.titleBarWidget()
    QTest.mousePress(bar, Qt.MouseButton.LeftButton, pos=QPoint(40, 12))
    assert dock.isMaximized()
    QTest.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=QPoint(40, 12))
    assert dock.isMaximized()
    QTest.mousePress(bar, Qt.MouseButton.LeftButton, pos=QPoint(40, 12))
    center = window.centralWidget().mapToGlobal(window.centralWidget().rect().center())
    QTest.mouseMove(bar, bar.mapFromGlobal(center), delay=10)
    assert not dock.isMaximized() and manager.guides.isVisible()
    QTest.keyClick(bar, Qt.Key.Key_Escape)
    app.processEvents()
    assert dock.isMaximized() and dock.isFloating()
    assert dock.normalGeometry().size() == normal_size
    QTest.mouseRelease(bar, Qt.MouseButton.LeftButton)


def test_tabbed_panel_layout_and_floating_geometry_survive_restart(desktop):
    import cartomize.desktop as module
    app, window, _ = desktop
    manager = window.dock_manager
    manager.dock(window.parameters_dock, Qt.DockWidgetArea.LeftDockWidgetArea,
                 relative=window.tools_dock, tabify=True)
    assert window.parameters_dock in window.tabifiedDockWidgets(window.tools_dock)
    manager.set_floating(window.project_explorer, True)
    window.project_explorer.setGeometry(30, 50, 420, 400)
    window.bottom_dock.hide()
    window.close()
    app.processEvents()
    reopened = module.CartomizeWindow()
    try:
        reopened.show()
        app.processEvents()
        assert reopened.parameters_dock in reopened.tabifiedDockWidgets(reopened.tools_dock)
        assert reopened.project_explorer.isFloating()
        assert reopened.project_explorer.width() == 420
        assert not reopened.bottom_dock.isVisible()
        assert reopened.parameters_dock.widget() is reopened.controls_panel
    finally:
        reopened.close()
        app.processEvents()


def test_reset_restores_panels_and_returns_detached_result_without_disposal(desktop, write_raster):
    app, window, _ = desktop
    source = write_raster('layout.tif', np.ones((20, 20), dtype='float32'))
    document = window.workspace.open_result(source)
    canvas = document.canvas
    window.workspace.detach_document(document)
    window.dock_manager.dock(window.parameters_dock, Qt.DockWidgetArea.LeftDockWidgetArea)
    window.tools_dock.hide()
    window._workbench.reset_layout()
    app.processEvents()
    assert not window.workspace.detached_docks
    assert window.workspace.tabs.currentWidget() is document and document.canvas is canvas
    assert not canvas._closed and isValid(canvas)
    assert len(window.dock_manager.docks) == 4
    assert window.dockWidgetArea(window.parameters_dock) == Qt.DockWidgetArea.RightDockWidgetArea
    assert window.tools_dock.isVisible() and window.bottom_dock.isVisible()
    assert not window.dock_manager.user_layout
