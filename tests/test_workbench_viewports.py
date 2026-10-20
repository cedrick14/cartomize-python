"""Map viewport and saved-layout regressions for the dock-based workbench."""
import os
import time
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import numpy as np
import pytest
from rasterio.transform import from_origin
pytest.importorskip('PySide6')
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication
from cartomize.desktop import CartomizeWindow


def wait_for(predicate):
    loop=QEventLoop(); timer=QTimer(); deadline=time.monotonic()+30
    timer.timeout.connect(lambda: loop.quit() if predicate() or time.monotonic()>deadline else None)
    timer.start(10)
    if not predicate(): loop.exec()
    timer.stop()
    assert predicate()


@pytest.mark.parametrize('font_size', [12,14,16])
def test_comparison_keeps_both_canvases_usable(write_raster, font_size):
    app=QApplication.instance() or QApplication([])
    a=write_raster('a.tif',np.ones((200,200),dtype='uint8'),transform=from_origin(300000,9500000,30,30),nodata=None)
    b=write_raster('b.tif',np.zeros((400,400),dtype='uint8'),transform=from_origin(300000,9500000,15,15),nodata=None)
    window=CartomizeWindow()
    previous=int(window._preferences.value('appearance/font_size',12))
    try:
        window._workbench.font_size.setValue(font_size)
        window.resize(1280,800); window.show(); app.processEvents()
        window.workspace.register(a); window.workspace.register(b)
        comparison=window.workspace.compare(left=str(a),right=str(b))
        wait_for(lambda: all(d and d.canvas.last_render for d in comparison.documents))
        left,right=(d.canvas for d in comparison.documents)
        for canvas in (left,right):
            assert canvas.viewport().width()>100
            assert canvas.viewport().height()>70
            assert canvas.geographic_extent() is not None
        left.zoom(3)
        e,o=left.geographic_extent(),right.geographic_extent()
        np.testing.assert_allclose([(e[0]+e[2])/2,(e[1]+e[3])/2],[(o[0]+o[2])/2,(o[1]+o[3])/2],atol=60)
        window.workspace_splitter.setSizes([800,400])
        state=window.capture_session()
        assert state['workspace_order']=='map-controls'
        old_sizes=list(reversed(state['splitter']))
        state.pop('workspace_order');state['splitter']=old_sizes
        window.restore_session(state)
        sizes=window.workspace_splitter.sizes()
        assert sizes[0]>sizes[1]
    finally:
        window._workbench.font_size.setValue(previous)
        window.close(); app.processEvents()
