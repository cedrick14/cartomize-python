"""Result views keep their readers and controls while moving between hosts."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')

import json
from pathlib import Path
import re
import time

import numpy as np
import pandas as pd
import pytest

pytest.importorskip('PySide6')
from PySide6.QtCore import QCoreApplication,QEvent,QEventLoop,QTimer,QSettings,Qt
from PySide6.QtGui import QColor,QPalette
from PySide6.QtWidgets import QApplication,QDockWidget,QMainWindow,QWidget
from shiboken6 import isValid

from cartomize.desktop_results import ResultsWorkspace


@pytest.fixture(scope='session')
def app():
    return QApplication.instance() or QApplication([])


def wait_for(predicate,timeout=10):
    if predicate(): return
    loop=QEventLoop(); timer=QTimer(); deadline=time.monotonic()+timeout
    timer.timeout.connect(lambda:loop.quit() if predicate() or time.monotonic()>deadline else None)
    timer.start(10); loop.exec(); timer.stop()
    assert predicate(),'The result view did not finish.'


def finish(workspace,app):
    workspace.close(); app.processEvents()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)


@pytest.fixture
def docked_workspace(app):
    from cartomize.desktop_docking import DockController
    host=QMainWindow(); workspace=ResultsWorkspace(); host.setCentralWidget(workspace)
    host.dock_manager=DockController(host); host.resize(1200,800); host.show()
    yield host,workspace
    workspace.dispose(); host.dock_manager.shutdown(); host.close(); app.processEvents()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)


def test_detach_resize_reattach_preserves_the_actual_map_and_style(app,write_raster):
    path=write_raster('map.tif',np.arange(10000,dtype='float32').reshape(100,100))
    original=path.read_bytes(); workspace=ResultsWorkspace(); workspace.resize(1000,700); workspace.show()
    try:
        document=workspace.open_result(path); canvas=document.canvas
        wait_for(lambda:canvas.last_render is not None)
        document.palette.setCurrentIndex(document.palette.findData('terrain')); canvas.zoom(3)
        generation=canvas._generation
        dock=workspace.detach_document(document)
        assert workspace.detached_docks[document] is dock
        assert dock.widget() is document and dock.isFloating()
        assert workspace.tabs.indexOf(document)==-1
        assert workspace.open_result(path) is document
        assert workspace.focus_document(document) is document
        assert dock.isMaximized()
        workspace.focus_document(document); assert not dock.isMaximized()
        dock.resize(730,540); app.processEvents()
        assert not canvas._closed and not canvas._fitted
        assert canvas._generation==generation and canvas.palette_name=='terrain'
        assert workspace.reattach_document(document) is document
        assert workspace.tabs.currentWidget() is document
        assert not workspace.detached_docks
        assert document.canvas is canvas and isValid(canvas) and not canvas._closed
        assert canvas.palette_name=='terrain' and not canvas._fitted
        assert path.read_bytes()==original
    finally:
        finish(workspace,app)


def test_chart_controls_and_export_survive_detachment(app,tmp_path):
    source=tmp_path/'surface.csv'
    pd.DataFrame({'distance':[0,100,250,500],'surface':[5,9,16,24]}).to_csv(source,index=False)
    workspace=ResultsWorkspace(); workspace.show()
    try:
        document=workspace.open_result(source); wait_for(lambda:len(document.frame)==4)
        document.plot_kind.setCurrentIndex(document.plot_kind.findData('line')); document.plot()
        figure,canvas=document.figure,document.canvas
        dock=workspace.detach_document(document); dock.resize(780,600); app.processEvents()
        assert document.figure is figure and document.canvas is canvas
        assert document.tabs.currentIndex()==1
        output=tmp_path/'detached_graph.png'; figure.savefig(output)
        assert output.is_file() and output.stat().st_size>1000
        assert workspace.reattach_document(document) is document
        assert document.figure is figure and document.canvas is canvas
        np.testing.assert_array_equal(figure.axes[0].lines[0].get_ydata(),[5,9,16,24])
    finally:
        finish(workspace,app)


def test_refresh_preserves_the_detached_place_and_catalogue_identity(app,write_raster):
    path=write_raster('refresh.tif',np.ones((30,30),dtype='float32'))
    workspace=ResultsWorkspace(); workspace.show()
    try:
        old=workspace.open_result(path); dock=workspace.detach_document(old)
        dock.resize(600,450); app.processEvents(); dock_id=dock.objectName()
        current=workspace.open_result(path,refresh=True)
        assert current is not old and old._closed
        current_dock=workspace.detached_docks[current]
        assert current_dock.isFloating() and current_dock.objectName()==dock_id
        assert current_dock.widget() is current
        assert len(workspace.all_documents())==1 and len(workspace.records)==1
        assert workspace._documents[str(path)] is current
        wait_for(lambda:current.canvas.last_render is not None)
    finally:
        finish(workspace,app)


def test_refresh_keeps_the_result_in_its_dock_group(app,write_raster,docked_workspace):
    host,workspace=docked_workspace
    first=write_raster('group_refresh.tif',np.ones((20,20),dtype='float32'))
    second=write_raster('group_peer.tif',np.full((20,20),2,dtype='float32'))
    old=workspace.open_result(first); peer=workspace.open_result(second)
    old_dock=workspace.detach_document(old); peer_dock=workspace.detach_document(peer)
    host.dock_manager.dock(peer_dock,Qt.DockWidgetArea.BottomDockWidgetArea)
    host.dock_manager.dock(old_dock,Qt.DockWidgetArea.BottomDockWidgetArea,relative=peer_dock,tabify=True)
    old_id=old_dock.objectName()
    current=workspace.open_result(first,refresh=True)
    current_dock=workspace.detached_docks[current]
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete); app.processEvents()
    assert current is not old and current_dock.objectName()==old_id
    assert not current_dock.isFloating()
    assert peer_dock in host.tabifiedDockWidgets(current_dock)
    assert current_dock in host.dock_manager.docks
    assert host.dock_manager.return_callback(current_dock) is not None
    assert current_dock.widget() is current and peer_dock.widget() is peer
    assert len(workspace.all_documents())==len(workspace.records)==2
    wait_for(lambda:current.canvas.last_render is not None)


@pytest.mark.parametrize('saved_id',[
    'toolParametersDock','result-'+'g'*20,'comparison-'+'b'*32,'collision',
])
def test_restored_result_ids_cannot_collide_with_existing_panels(app,write_raster,docked_workspace,saved_id):
    host,workspace=docked_workspace
    parameters=QDockWidget('Paramètres',host); parameters.setObjectName('toolParametersDock')
    parameters.setWidget(QWidget()); host.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea,parameters)
    host.dock_manager.register(parameters)
    first=workspace.open_result(write_raster('existing.tif',np.ones((20,20),dtype='float32')))
    existing=workspace.detach_document(first)
    document=workspace.open_result(write_raster('restored.tif',np.full((20,20),2,dtype='float32')))
    requested=existing.objectName() if saved_id=='collision' else saved_id
    workspace._restore_placement(document,dict(mode='dock',dock_id=requested,floating=False))
    dock=workspace.detached_docks[document]
    assert re.fullmatch(r'result-[0-9a-f]{20}',dock.objectName())
    assert dock.objectName() not in {parameters.objectName(),existing.objectName(),requested}
    assert dock.widget() is document and not document._closed
    assert parameters in host.dock_manager.docks and existing in host.dock_manager.docks
    assert dock in host.dock_manager.docks and len(workspace.all_documents())==2
    dock_id=dock.objectName()
    workspace._restore_placement(document,dict(mode='dock',dock_id=existing.objectName(),floating=False))
    assert workspace.detached_docks[document] is dock
    assert workspace._placement(document)['dock_id']==dock_id


def test_result_action_icons_follow_palette_changes(app):
    workspace=ResultsWorkspace()
    try:
        for foreground,background in (('#f5f6f7','#20252d'),('#161b22','#f7f8fa')):
            palette=QPalette(workspace.palette())
            palette.setColor(QPalette.ColorRole.WindowText,QColor(foreground))
            palette.setColor(QPalette.ColorRole.Window,QColor(background))
            workspace.setPalette(palette)
            for control in (workspace.detach_button,workspace.focus_button):
                raster=control.icon().pixmap(18,18).toImage()
                colors=[raster.pixelColor(x,y) for y in range(raster.height()) for x in range(raster.width())]
                assert any(color==QColor(foreground) for color in colors)
                assert control.accessibleName() and control.toolTip()
                assert control.width()==control.height()==26
    finally:
        finish(workspace,app)


@pytest.mark.parametrize('placement',[
    dict(mode='dock',floating=False,area=[]),
    dict(mode='dock',floating=False,area={}),
    dict(mode='dock',floating=True,geometry=[10**100,0,640,480]),
    dict(mode='dock',floating=True,geometry=[0,0,640,10**100]),
    dict(mode='dock',floating=True,geometry=[2**31-1,0,640,480]),
    dict(mode='dock',floating=True,geometry=[0,0,-640,480]),
])
def test_malformed_json_placement_keeps_the_result_open(app,write_raster,docked_workspace,placement):
    host,workspace=docked_workspace
    path=write_raster('malformed_placement.tif',np.ones((20,20),dtype='float32'))
    workspace.open_result(path)
    state=json.loads(json.dumps(workspace.capture()))
    state['views'][0]['placement'].update(placement)
    workspace.restore(state)
    document=workspace._documents[str(path)]; dock=workspace.detached_docks[document]
    assert dock.widget() is document and document in workspace.all_documents()
    assert dock in host.dock_manager.docks and not document._closed
    if placement['floating']:
        assert dock.isFloating() and dock.width()>0 and dock.height()>0
    else:
        assert not dock.isFloating()
        assert host.dockWidgetArea(dock)==Qt.DockWidgetArea.RightDockWidgetArea
    wait_for(lambda:document.canvas.last_render is not None)


def test_detached_view_can_close_during_read_and_next_view_renders(app,write_raster,monkeypatch):
    import cartomize.desktop_canvas as module
    original=module.render_raster; started=[]; completed=[]
    first=write_raster('closing.tif',np.ones((30,30),dtype='float32'))
    second=write_raster('following.tif',np.full((30,30),2,dtype='float32'))
    def delayed(*args,**kwargs):
        if str(args[0])==str(first): started.append(True); time.sleep(.15)
        result=original(*args,**kwargs); completed.append(str(args[0])); return result
    monkeypatch.setattr(module,'render_raster',delayed)
    workspace=ResultsWorkspace(); workspace.show()
    try:
        document=workspace.open_result(first); dock=workspace.detach_document(document)
        wait_for(lambda:bool(started)); dock.close()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        assert not isValid(document.canvas)
        assert not workspace.detached_docks and str(first) not in workspace._documents
        next_document=workspace.open_result(second)
        wait_for(lambda:str(first) in completed and next_document.canvas.last_render is not None)
        assert next_document.canvas.last_render['ranges']==((2.,2.),)
    finally:
        finish(workspace,app)


def test_json_session_roundtrip_restores_floating_and_anchored_views(app,write_raster):
    paths=[write_raster(f'view_{i}.tif',np.full((20,20),i,dtype='float32')) for i in range(3)]
    host=QMainWindow(); workspace=ResultsWorkspace(); host.setCentralWidget(workspace); host.resize(1200,800); host.show()
    try:
        views=[workspace.open_result(path) for path in paths]
        first=workspace.detach_document(views[0]); second=workspace.detach_document(views[1])
        first.setFloating(False); host.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea,first)
        second.setFloating(False); host.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea,second)
        host.tabifyDockWidget(first,second)
        floating=workspace.detach_document(views[2]); floating.resize(600,450)
        state=json.loads(json.dumps(workspace.capture()))
        workspace.restore(state)
        assert len(workspace.detached_docks)==3 and len(workspace.all_documents())==3
        restored=[workspace._documents[str(path)] for path in paths]
        docks=[workspace.detached_docks[document] for document in restored]
        assert not docks[0].isFloating() and not docks[1].isFloating()
        assert docks[1] in host.tabifiedDockWidgets(docks[0])
        assert docks[2].isFloating()
        assert host.dockWidgetArea(docks[0])==Qt.DockWidgetArea.BottomDockWidgetArea
    finally:
        workspace.dispose(); host.close(); app.processEvents()


def test_eight_view_limit_counts_detached_documents_and_retains_files(app,write_raster):
    workspace=ResultsWorkspace(); workspace.show()
    paths=[write_raster(f'limit_{i}.tif',np.full((12,12),i,dtype='float32')) for i in range(9)]
    try:
        for path in paths[:8]:
            document=workspace.open_result(path)
            if len(workspace.detached_docks)<4: workspace.detach_document(document)
        assert len(workspace.all_documents())==8
        workspace.open_result(paths[8])
        assert len(workspace.all_documents())==8 and len(workspace.records)==9
        for document,dock in workspace.detached_docks.items():
            assert workspace.open_result(document.path) is document and dock.widget() is document
        assert all(path.is_file() for path in paths)
    finally:
        finish(workspace,app)


def test_portable_project_restores_a_detached_comparison_and_its_data(app,write_raster,tmp_path,monkeypatch):
    import cartomize.desktop as desktop
    monkeypatch.setattr(desktop,'QSettings',lambda *args:QSettings(str(tmp_path/'appearance.ini'),QSettings.Format.IniFormat))
    first=write_raster('period_a.tif',np.ones((40,40),dtype='float32'))
    second=write_raster('period_b.tif',np.full((40,40),2,dtype='float32'))
    window=desktop.CartomizeWindow(); restored=None
    try:
        window.show(); window.workspace.register(first); window.workspace.register(second)
        comparison=window.workspace.compare(left=str(first),right=str(second))
        wait_for(lambda:all(document.canvas.last_render is not None for document in comparison.documents))
        canvas=comparison.documents[0].canvas; canvas.zoom(2)
        dock=window.workspace.detach_document(comparison)
        assert dock.widget() is comparison and not canvas._closed
        archive=window.save_session_file(tmp_path/'detached.cmz',portable=True)
        window.close(); app.processEvents()
        first.unlink(); second.unlink()
        restored=desktop.CartomizeWindow(); restored.open_session_file(archive); restored.show()
        assert len(restored.workspace.detached_docks)==1
        current,current_dock=next(iter(restored.workspace.detached_docks.items()))
        assert current_dock.widget() is current and current_dock.isFloating()
        assert len(current.documents)==2 and current.link.isChecked()
        assert all(Path(document.path).is_file() for document in current.documents)
        wait_for(lambda:all(document.canvas.last_render is not None for document in current.documents))
        assert restored.workspace.reattach_document(current) is current
        assert restored.workspace.tabs.currentWidget() is current
    finally:
        if restored is not None and isValid(restored): restored.close()
        if isValid(window): window.close()
        app.processEvents()
