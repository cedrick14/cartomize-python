"""Scientific pixel fidelity, responsive rendering and real integrated outputs."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json
import time
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
import rasterio
from rasterio.transform import from_origin

pytest.importorskip('PySide6')
from PySide6.QtWidgets import QApplication,QDialog
from PySide6.QtCore import QEventLoop,QTimer,QPointF
from cartomize.viewer_data import render_raster,pixel_values,table_page,render_pdf,pdf_info
from cartomize.desktop import CartomizeWindow
from cartomize.desktop_results import ResultsWorkspace,MapDocument
from cartomize.desktop_tables import TablePanel


@pytest.fixture(scope='session')
def app(): return QApplication.instance() or QApplication([])


def wait_for(predicate,timeout=10):
    if predicate(): return
    loop=QEventLoop(); timer=QTimer(); start=time.monotonic()
    timer.timeout.connect(lambda:loop.quit() if predicate() or time.monotonic()-start>timeout else None)
    timer.start(10); loop.exec(); timer.stop()
    assert predicate(),'Result view did not finish'


def test_categorical_zoom_preserves_codes_zero_and_nodata(write_raster):
    data=np.tile(np.array([0,1,2,255],dtype='uint8'),(40,10))
    path=write_raster('classes.tif',data,nodata=255)
    classes={0:('Non-forêt','#ccb282'),1:('Forêt','#26743b'),2:('Changement','#cd593b')}
    frame=render_raster(path,(0,0,4,2),(4,8),classes=classes,resampling='bilinear')
    assert frame['source_window']==(0,0,4,2) and frame['resampling']=='nearest'
    assert frame['rgba'][0,0].tolist()==[204,178,130,255]
    assert frame['rgba'][0,2].tolist()==[38,116,59,255]
    assert frame['rgba'][0,6,3]==0
    assert pixel_values(path,0,0,[1])==[0.] and pixel_values(path,3,0,[1])==[None]


def test_native_rgba_black_is_visible_and_source_is_unchanged(write_raster):
    data=np.zeros((4,12,12),dtype='uint8');data[3]=255;data[3,0,0]=0
    path=write_raster('display.tif',data,nodata=0)
    with rasterio.open(path,'r+') as src:
        src.colorinterp=(rasterio.enums.ColorInterp.red,rasterio.enums.ColorInterp.green,rasterio.enums.ColorInterp.blue,rasterio.enums.ColorInterp.alpha)
        src.update_tags(CARTOMIZE_PRODUCT='display_rgba')
    before=path.read_bytes(); frame=render_raster(path,(0,0,12,12),(12,12),bands=(1,2,3))
    assert frame['rgba'][1,1].tolist()==[0,0,0,255] and frame['rgba'][0,0,3]==0
    assert pixel_values(path,1,1,[1,2,3])==[0.,0.,0.]
    assert pixel_values(path,0,0,[1,2,3])==[None,None,None]
    assert path.read_bytes()==before


def test_raster_canvas_reads_finer_window_and_identifies_values(app,write_raster):
    data=np.arange(1024**2,dtype='float32').reshape(1024,1024)
    path=write_raster('continuous.tif',data,nodata=None)
    document=MapDocument(path);document.resize(800,650);document.show()
    canvas=document.canvas; wait_for(lambda:canvas.last_render is not None and not canvas._want_overview)
    initial=canvas.last_render['source_window'];canvas.zoom(8)
    wait_for(lambda:canvas.last_render['source_window'][2]<initial[2]/2)
    assert canvas.last_render['rgba'].shape[1]>canvas.last_render['source_window'][2]
    values=[];canvas.identified.connect(values.append);canvas.identify(QPointF(7.2,5.4));wait_for(lambda:bool(values))
    assert '5127' in values[0]
    document.dispose();document.close()


def test_two_georeferenced_results_share_extent_and_restore_portably(app,write_raster,tmp_path):
    a=write_raster('forest_2000.tif',np.ones((200,200),dtype='uint8'),transform=from_origin(300000,9500000,30,30),nodata=None)
    b=write_raster('forest_2026.tif',np.zeros((400,400),dtype='uint8'),transform=from_origin(300000,9500000,15,15),nodata=None)
    window=CartomizeWindow();window.show();window.workspace.register(a);window.workspace.register(b)
    comparison=window.workspace.compare(left=str(a),right=str(b));wait_for(lambda:all(d.canvas.last_render for d in comparison.documents))
    left,right=[d.canvas for d in comparison.documents];left.zoom(3)
    extent=left.geographic_extent();other=right.geographic_extent()
    np.testing.assert_allclose([(extent[0]+extent[2])/2,(extent[1]+extent[3])/2],[(other[0]+other[2])/2,(other[1]+other[3])/2],atol=60)
    archive=window.save_session_file(tmp_path/'workspace.cmz',portable=True)
    window.workspace.dispose();window.close()
    # The portable project must restore its own raster copies and comparison.
    a.unlink();b.unlink();restored=CartomizeWindow();restored.open_session_file(archive)
    view=restored.workspace.tabs.currentWidget();assert len(view.documents)==2 and view.link.isChecked()
    assert all(Path(doc.path).is_file() for doc in view.documents)
    restored.close();app.processEvents()


def test_table_paging_plot_and_structured_confusion_matrix(app,tmp_path):
    path=tmp_path/'areas.csv';pd.DataFrame({'classe':np.arange(4005),'surface_ha':np.arange(4005)*.25}).to_csv(path,index=False)
    second=table_page(path,2000);assert second['frame'].iloc[0]['classe']==2000 and second['more']
    table=TablePanel(path);table.show();wait_for(lambda:len(table.frame)==2000)
    table.plot_kind.setCurrentIndex(table.plot_kind.findData('line'));table.plot()
    assert len(table.figure.axes[0].lines)==1 and len(table.figure.axes[0].lines[0].get_ydata())==2000
    table.next.click();wait_for(lambda:table.offset==2000);table.dispose();table.close()
    report=tmp_path/'classification.json';report.write_text(json.dumps({'accuracy':.9,'confusion_matrix':[[8,1],[1,10]]}))
    panel=TablePanel(report);wait_for(lambda:'confusion_matrix' in panel._reports)
    panel.selection.setCurrentText('confusion_matrix');panel.plot_kind.setCurrentIndex(panel.plot_kind.findData('matrix'));panel.plot()
    np.testing.assert_array_equal(panel.figure.axes[0].images[0].get_array(),[[8,1],[1,10]])
    panel.dispose();panel.close()


def test_completed_processing_updates_embedded_view_without_dialog(app,write_raster,tmp_path):
    source=write_raster('bands.tif',np.array([np.full((30,40),.2),np.full((30,40),.6)],dtype='float32'))
    with rasterio.open(source,'r+') as src:src.descriptions=('red','nir')
    window=CartomizeWindow();window.show();window.select_tool('indices');page=window.tool('indices')
    page.source.edit.setText(str(source));page.output.edit.setText(str(tmp_path/'ndvi.tif'))
    window.start();wait_for(lambda:window.thread is None,30)
    view=window.workspace.tabs.currentWidget();assert isinstance(view,MapDocument)
    assert Path(view.path).name=='ndvi.tif';wait_for(lambda:view.canvas.last_render is not None)
    assert not any(isinstance(w,QDialog) and w.isVisible() for w in app.topLevelWidgets())
    count=window.workspace.tabs.count();window.workspace.show_output(tmp_path/'ndvi.tif')
    assert window.workspace.tabs.count()==count
    window.close();app.processEvents()


def test_manifest_registers_products_and_opens_map_inside_workspace(app,write_raster,tmp_path):
    from matplotlib.figure import Figure
    raster=write_raster('multibande.tif',np.ones((3,20,20),dtype='float32'))
    fig=Figure(figsize=(3,2));fig.add_subplot(111).plot([0,1],[1,0]);fig.savefig(tmp_path/'carte.svg')
    manifest=tmp_path/'production.json';manifest.write_text(json.dumps({'multiband':str(raster),'maps':['carte.svg']}))
    workspace=ResultsWorkspace();workspace.show();workspace.show_output(manifest)
    assert str(raster) in workspace.records and workspace.tabs.currentWidget().canvas.kind=='svg'
    workspace.dispose();workspace.close()


def test_vector_geometry_and_attribute_table_are_embedded(app,tmp_path):
    import geopandas as gpd
    from shapely.geometry import Polygon,Point
    path=tmp_path/'zones.gpkg'
    gpd.GeoDataFrame({'nom':['Zone A'],'surface':[10.]},geometry=[Polygon([(0,0),(100,0),(100,100),(0,100)],holes=[[(30,30),(70,30),(70,70),(30,70)]])],crs=32733).to_file(path)
    doc=MapDocument(path);doc.resize(750,600);doc.show();wait_for(lambda:doc.canvas.last_render is not None)
    assert doc.canvas.info['features']==1 and doc.views.count()==2
    wait_for(lambda:len(doc._table.frame)==1);assert doc._table.frame.iloc[0]['nom']=='Zone A'
    doc.dispose();doc.close()


def test_pdf_zoom_renders_selected_page_region(tmp_path):
    pytest.importorskip('pypdfium2')
    from matplotlib.figure import Figure
    from matplotlib.patches import Rectangle
    path=tmp_path/'map.pdf';fig=Figure(figsize=(4,3));ax=fig.add_axes([0,0,1,1]);ax.set_axis_off()
    ax.add_patch(Rectangle((0,0),.5,1,color='red'));ax.add_patch(Rectangle((.5,0),.5,1,color='blue'));fig.savefig(path)
    info=pdf_info(path);assert info['pages']==1
    frame=render_pdf(path,0,(180,40,60,100),(400,240))
    assert frame['rgba'].shape[0]>=399 and frame['rgba'].shape[1]>=239
    assert frame['rgba'][100,100,:3].tolist()==[0,0,255]


def test_old_render_does_not_replace_new_band_and_gui_keeps_running(app,write_raster,monkeypatch):
    import cartomize.desktop_canvas as module
    path=write_raster('two.tif',np.stack([np.zeros((100,100)),np.ones((100,100))]).astype('float32'),nodata=None)
    original=module.render_raster; calls=[]
    def slow(*args,**kwargs):
        calls.append(args[3]);time.sleep(.12);return original(*args,**kwargs)
    monkeypatch.setattr(module,'render_raster',slow)
    doc=MapDocument(path);doc.show();ticks=[];timer=QTimer();timer.timeout.connect(lambda:ticks.append(1));timer.start(5)
    wait_for(lambda:doc.canvas._busy);doc.mode.setCurrentIndex(doc.mode.findData(2))
    wait_for(lambda:doc.canvas.last_render is not None and doc.canvas.last_render.get('ranges')==((1.,1.),))
    assert len(ticks)>5 and calls[0]==(1,) and (2,) in calls
    timer.stop();doc.dispose();doc.close()


def test_comparison_reprojects_extent_between_coordinate_systems(app,write_raster):
    from rasterio.warp import transform_bounds
    from rasterio.transform import from_bounds
    from pyproj import Transformer
    a=write_raster('utm.tif',np.ones((200,200),dtype='float32'),transform=from_origin(300000,9500000,30,30))
    bounds=transform_bounds(32733,4326,300000,9494000,306000,9500000)
    b=write_raster('geographic.tif',np.ones((200,200),dtype='float32'),crs='EPSG:4326',transform=from_bounds(*bounds,200,200))
    view=ResultsWorkspace();view.resize(1100,750);view.show();view.register(a);view.register(b)
    comparison=view.compare(left=str(a),right=str(b));wait_for(lambda:all(d.canvas.last_render for d in comparison.documents))
    left,right=[d.canvas for d in comparison.documents];left.zoom(2)
    extent=left.geographic_extent();target=right.geographic_extent()
    expected=Transformer.from_crs(32733,4326,always_xy=True).transform((extent[0]+extent[2])/2,(extent[1]+extent[3])/2)
    np.testing.assert_allclose(expected,[(target[0]+target[2])/2,(target[1]+target[3])/2],atol=.0005)
    assert comparison.link.isEnabled();view.dispose();view.close()


def test_image_zoom_reads_original_crop(app,tmp_path):
    from PIL import Image
    from cartomize.desktop_canvas import render_image
    data=np.zeros((240,320,3),dtype='uint8');data[:,:160,0]=255;data[:,160:,2]=255
    path=tmp_path/'figure.png';Image.fromarray(data).save(path)
    frame=render_image(path,(200,50,40,80),(400,200));image=frame['image']
    assert image.width()==200 and image.height()==400
    pixel=image.pixelColor(100,200);assert (pixel.red(),pixel.green(),pixel.blue())==(0,0,255)


def test_view_catalogue_remains_available_when_tab_limit_is_reached(app,write_raster):
    workspace=ResultsWorkspace();workspace.show()
    paths=[write_raster(f'result_{i}.tif',np.full((12,12),i,dtype='float32'),nodata=None) for i in range(9)]
    for path in paths: workspace.open_result(path)
    assert len(workspace.records)==9 and workspace.tabs.count()==8
    assert str(paths[0]) in workspace.records
    workspace.open_result(paths[0]);assert Path(workspace.tabs.currentWidget().path)==paths[0]
    workspace.dispose();workspace.close()


def test_comparison_can_share_a_scientific_colour_scale(app,write_raster):
    values=np.linspace(0,1,400,dtype='float32').reshape(20,20)
    a=write_raster('first.tif',values);b=write_raster('second.tif',values+2)
    workspace=ResultsWorkspace();workspace.show();workspace.register(a);workspace.register(b)
    comparison=workspace.compare(left=str(a),right=str(b));wait_for(lambda:all(d.canvas.last_render for d in comparison.documents))
    comparison.common_scale.setChecked(True)
    wait_for(lambda:comparison._shared_applied)
    first,second=[d.canvas for d in comparison.documents]
    assert first.limits==second.limits
    np.testing.assert_allclose(first.limits,((.02,2.98),),atol=1e-6)
    workspace.dispose();workspace.close()


def test_tab_can_close_during_read_and_next_result_remains_usable(app,write_raster,monkeypatch):
    from PySide6.QtCore import QCoreApplication,QEvent
    from shiboken6 import isValid
    import cartomize.desktop_canvas as module
    original=module.render_raster;finished=[]
    first=write_raster('closing.tif',np.ones((100,100),dtype='float32'))
    second=write_raster('next.tif',np.full((100,100),2,dtype='float32'))
    def slow(*args,**kwargs):
        if str(args[0])==str(first): time.sleep(.1)
        result=original(*args,**kwargs);finished.append(str(args[0]));return result
    monkeypatch.setattr(module,'render_raster',slow)
    workspace=ResultsWorkspace();workspace.show();document=workspace.open_result(first)
    wait_for(lambda:document.canvas._busy)
    workspace.close_tab(workspace.tabs.indexOf(document))
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    assert not isValid(document.canvas)
    following=workspace.open_result(second)
    wait_for(lambda:str(first) in finished and following.canvas.last_render is not None)
    assert following.canvas.last_render['ranges']==((2.,2.),)
    workspace.close();app.processEvents()
