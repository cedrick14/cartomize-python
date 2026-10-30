"""Map viewport and saved-layout regressions for the dock-based workbench."""
import os
import time
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import numpy as np
import pytest
from rasterio.transform import from_origin
pytest.importorskip('PySide6')
from PySide6.QtCore import QEventLoop, QSettings, QTimer, Qt
from PySide6.QtWidgets import QApplication
import cartomize.desktop as desktop


def wait_for(predicate):
    loop=QEventLoop(); timer=QTimer(); deadline=time.monotonic()+30
    timer.timeout.connect(lambda: loop.quit() if predicate() or time.monotonic()>deadline else None)
    timer.start(10)
    if not predicate(): loop.exec()
    timer.stop()
    assert predicate()


def assert_usable_comparison(comparison):
    assert len(comparison.documents)==2
    wait_for(lambda: all(d and d.canvas.last_render for d in comparison.documents))
    canvases=tuple(d.canvas for d in comparison.documents)
    for canvas in canvases:
        assert canvas.viewport().width()>100
        assert canvas.viewport().height()>70
        assert canvas.geographic_extent() is not None
    return canvases


@pytest.mark.parametrize('font_size', [12,14,16])
def test_comparison_keeps_both_canvases_usable(write_raster, font_size, tmp_path, monkeypatch):
    app=QApplication.instance() or QApplication([])
    monkeypatch.setattr(desktop, 'QSettings', lambda *args:
                        QSettings(str(tmp_path/'preferences.ini'), QSettings.Format.IniFormat))
    a=write_raster('a.tif',np.ones((200,200),dtype='uint8'),transform=from_origin(300000,9500000,30,30),nodata=None)
    b=write_raster('b.tif',np.zeros((400,400),dtype='uint8'),transform=from_origin(300000,9500000,15,15),nodata=None)
    window=desktop.CartomizeWindow()
    previous=int(window._preferences.value('appearance/font_size',12))
    try:
        window._workbench.font_size.setValue(font_size)
        window.resize(1280,800); window.show(); app.processEvents()
        window.workspace.register(a); window.workspace.register(b)
        comparison=window.workspace.compare(left=str(a),right=str(b))
        left,right=assert_usable_comparison(comparison)
        left.zoom(3)
        e,o=left.geographic_extent(),right.geographic_extent()
        np.testing.assert_allclose([(e[0]+e[2])/2,(e[1]+e[3])/2],[(o[0]+o[2])/2,(o[1]+o[3])/2],atol=60)
        state=window.capture_session()
        assert state['workspace_order']=='map-controls'
        # Older sessions stored two widths in controls/map order. Their restore
        # must keep today's parameters dock and both comparison canvases usable.
        state.pop('workspace_order');state['splitter']=[400,800]
        window.restore_session(state)
        app.processEvents()
        assert window.centralWidget() is window.workspace_splitter
        assert window.workspace_splitter.indexOf(window.workspace)==0
        assert window.workspace_splitter.indexOf(window.controls_panel)==-1
        assert window.parameters_dock.widget() is window.controls_panel
        assert window.parameters_dock.isVisible() and not window.parameters_dock.isFloating()
        assert window.dockWidgetArea(window.parameters_dock)==Qt.DockWidgetArea.RightDockWidgetArea
        restored=window.workspace.tabs.currentWidget()
        left,right=assert_usable_comparison(restored)
        assert [str(document.path) for document in restored.documents]==[str(a),str(b)]
        e,o=left.geographic_extent(),right.geographic_extent()
        np.testing.assert_allclose([(e[0]+e[2])/2,(e[1]+e[3])/2],[(o[0]+o[2])/2,(o[1]+o[3])/2],atol=60)
    finally:
        window._workbench.font_size.setValue(previous)
        window.close(); app.processEvents()
