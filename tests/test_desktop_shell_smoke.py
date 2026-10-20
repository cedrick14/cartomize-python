"""Desktop smoke tests for Cartomize on headless Linux and Windows."""
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6.QtWidgets")
from PySide6.QtWidgets import QApplication, QDockWidget

from cartomize.desktop import CartomizeWindow


@pytest.fixture(scope="module")
def application():
    app = QApplication.instance() or QApplication([])
    yield app


def test_desktop_window_and_navigation(application):
    window = CartomizeWindow()
    try:
        assert window.windowTitle() == "Cartomize"
        assert window.navigation.count() >= 15
        assert window.project_explorer.isWidgetType()
        assert isinstance(window.project_explorer, QDockWidget)
        assert window.workspace is not None
    finally:
        window.close()


def test_theme_switching_and_persistence(application):
    window = CartomizeWindow()
    try:
        selector = window.theme_selector
        for value in ("dark", "light", "system"):
            index = selector.findData(value)
            assert index >= 0
            selector.setCurrentIndex(index)
            application.processEvents()
            assert window._preferences.value("appearance/theme") == value
    finally:
        window.close()


def test_project_explorer_opens_local_directory(application, tmp_path):
    window = CartomizeWindow()
    try:
        window.project_explorer.set_directory(tmp_path)
        assert Path(window.project_explorer.path_label.text()) == tmp_path.resolve()
        assert window.project_explorer.model.rowCount(window.project_explorer.tree.rootIndex()) >= 0
    finally:
        window.close()
