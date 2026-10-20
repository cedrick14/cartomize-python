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


def test_all_tool_pages_accessible(application):
    window = CartomizeWindow()
    try:
        assert window.navigation.count() == window.stack.count()
        for row in range(window.navigation.count()):
            window.navigation.setCurrentRow(row)
            application.processEvents()
            assert window.stack.currentIndex() == row
            assert window.stack.currentWidget() is not None
        window.tool_search.setText("indices")
        application.processEvents()
        assert any(
            not window.navigation.item(i).isHidden()
            for i in range(window.navigation.count())
        )
        window.tool_search.clear()
    finally:
        window.close()


def test_explorer_rejects_unsupported_file(application, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    window = CartomizeWindow()
    try:
        unknown = tmp_path / "unrecognized.bin"
        unknown.write_bytes(b"test")
        messages = []
        monkeypatch.setattr(
            QMessageBox, "information",
            lambda *args: messages.append(args),
        )
        window.project_explorer.open_path(unknown)
        assert messages
        assert not window.workspace.records
    finally:
        window.close()
