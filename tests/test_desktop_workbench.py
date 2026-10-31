"""Integration tests of the actual workbench, with real geospatial files."""
import json
import os
from pathlib import Path
import time

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
import pytest
import rasterio

pytest.importorskip('PySide6')
from PySide6.QtCore import QEventLoop, QSettings, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox


def wait_until(predicate, timeout=30):
    if predicate():
        return
    loop = QEventLoop()
    timer = QTimer()
    deadline = time.monotonic() + timeout
    timer.timeout.connect(lambda: loop.quit() if predicate() or time.monotonic() > deadline else None)
    timer.start(10)
    loop.exec()
    timer.stop()
    assert predicate(), 'Desktop operation did not finish before timeout'


@pytest.fixture(scope='module')
def application(tmp_path_factory):
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope,
                      str(tmp_path_factory.mktemp('workbench-settings')))
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(application):
    from cartomize.desktop import CartomizeWindow
    result = CartomizeWindow()
    result.show()
    application.processEvents()
    yield result
    if result.thread is not None:
        result.cancel()
        wait_until(lambda: result.thread is None)
    result.close()
    application.processEvents()


def test_workbench_layout_catalogue_and_themes(window, application):
    from cartomize.desktop_theme import COLORS
    workbench = window._workbench
    assert window.centralWidget() is window.workspace_splitter
    assert window.workspace_splitter.indexOf(window.workspace) == 0
    assert window.tools_dock.widget() is window.catalogue
    assert window.bottom_dock.widget() is workbench.bottom_tabs
    assert workbench.bottom_tabs.count() == 4
    assert window.navigation.count() == len(window.tool_pages) == 21
    workbench.category.setCurrentIndex(workbench.category.findData('Raster'))
    window.tool_search.setText('INDICES')
    visible = [window.navigation.item(i).text() for i in range(window.navigation.count())
               if not window.navigation.item(i).isHidden()]
    assert len(visible) == 1 and 'Indices' in visible[0]
    workbench.select_tool('vector')
    assert window.stack.currentWidget().widget() is window.tool('vector')
    for theme in ('dark', 'light', 'system'):
        window.theme_selector.setCurrentIndex(window.theme_selector.findData(theme))
        application.processEvents()
        assert window._preferences.value('appearance/theme') == theme
        assert window._effective_theme in COLORS
    workbench.font_size.setValue(14)
    assert int(window._preferences.value('appearance/font_size')) == 14
    window.tools_dock.hide()
    workbench.reset_layout()
    assert window.tools_dock.isVisible()


def test_real_raster_import_transfer_and_calculation(window, write_raster, tmp_path):
    data = np.array([np.full((24, 24), .2), np.full((24, 24), .6)], dtype='float32')
    path = write_raster('spectral.tif', data)
    with rasterio.open(path, 'r+') as src:
        src.descriptions = ('red', 'nir')
    document = window.project_explorer.open_path(str(path))
    assert document is not None
    assert str(path.resolve()) in window.workspace.records
    assert any(Path(record['data']) == path for record in window.results)
    window.transfer_result({'data': str(path), 'kind': 'raster'}, 'indices')
    target = tmp_path / 'ndvi-workbench.tif'
    window.tool('indices').output.edit.setText(str(target))
    QTest.mouseClick(window.run_button, Qt.MouseButton.LeftButton)
    wait_until(lambda: window.thread is None)
    assert target.is_file(), window.status.text()
    with rasterio.open(target) as src:
        np.testing.assert_allclose(src.read(1), .5, atol=1e-6)
    window._workbench.synchronize()
    assert str(target.resolve()) in window.console_panel.context_paths
    assert window._workbench.loaded.topLevelItemCount() >= 2


def test_real_vector_import_buffer_and_project_reopen(window, tmp_path):
    import geopandas as gpd
    from shapely.geometry import Point
    source = tmp_path / 'points.gpkg'
    gpd.GeoDataFrame({'nom': ['A']}, geometry=[Point(300000, 9500000)], crs=32733).to_file(source)
    assert window.project_explorer.open_path(source) is not None
    window.transfer_result({'data': str(source), 'kind': 'vector'}, 'vector')
    page = window.tool('vector')
    page.operation.setCurrentIndex(page.operation.findData('buffer'))
    page.distance.setValue(200)
    output = tmp_path / 'buffer.gpkg'
    page.output.edit.setText(str(output))
    QTest.mouseClick(window.run_button, Qt.MouseButton.LeftButton)
    wait_until(lambda: window.thread is None)
    assert output.is_file(), window.status.text()
    assert gpd.read_file(output).area.iloc[0] == pytest.approx(np.pi * 200 ** 2, rel=.01)
    session = tmp_path / 'travail.cartomize.json'
    window.save_session_file(session)
    assert session.is_file()
    page.distance.setValue(300)
    window.project_explorer.open_path(session)
    assert page.distance.value() == 200
    assert window.session_path == str(session)


def test_console_persistent_namespace_error_recovery_and_shutdown(window):
    console = window.console_panel
    console.editor.setPlainText('value = 21\nvalue * 2')
    QTest.mouseClick(console.execute_button, Qt.MouseButton.LeftButton)
    wait_until(lambda: not console.busy, timeout=60)
    assert '42' in console.output.toPlainText()
    console.editor.setPlainText('value + 1')
    console.execute()
    wait_until(lambda: not console.busy)
    assert '22' in console.output.toPlainText()
    console.editor.setPlainText('raise ValueError("workbench-check")')
    console.execute()
    wait_until(lambda: not console.busy)
    assert 'workbench-check' in console.output.toPlainText()
    console.editor.setPlainText('value * 3')
    console.execute()
    wait_until(lambda: not console.busy)
    assert '63' in console.output.toPlainText()
    console.shutdown()
    assert console.process.state() == console.process.ProcessState.NotRunning


def test_console_interrupt_and_restart(window):
    console = window.console_panel
    console.editor.setPlainText('import time\ntime.sleep(60)')
    console.execute()
    wait_until(lambda: console._ready, timeout=60)
    console.interrupt()
    wait_until(lambda: not console.busy)
    console.editor.setPlainText('6 * 7')
    console.execute()
    wait_until(lambda: not console.busy, timeout=60)
    assert '42' in console.output.toPlainText()


def test_environment_and_all_tool_actions(window):
    workbench = window._workbench
    diagnostics = json.loads(window.environment_panel.diagnostic_text())
    assert diagnostics['packages']['cartomize'] != 'Non installé'
    for key in window.tool_pages:
        workbench.actions['tool_' + key].trigger()
        assert window.stack.currentWidget().widget() is window.tool(key)
    workbench.show_environment()
    assert workbench.bottom_tabs.currentWidget() is window.environment_panel


def test_workbench_logs_receive_processing_stages(window, application):
    workbench = window._workbench
    workbench.begin_processing('Prétraitement automatique N1→N5', focus_logs=True)
    assert workbench.bottom_tabs.currentWidget() is workbench.logs
    before = workbench.logs.toPlainText()
    workbench.log_stage('N1 — Calibration radiométrique : prête')
    workbench.log_stage('N2 — Correction atmosphérique : déjà appliquée')
    application.processEvents()
    content = workbench.logs.toPlainText()
    assert len(content) > len(before)
    assert 'Prétraitement automatique N1→N5' in content
    assert 'N1 — Calibration radiométrique : prête' in content
    assert 'N2 — Correction atmosphérique : déjà appliquée' in content
