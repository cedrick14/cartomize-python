import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import json
from pathlib import Path
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

pytest.importorskip('PySide6')
from PySide6.QtWidgets import QApplication, QFileDialog
from PySide6.QtCore import QEventLoop, QTimer
import cartomize as cm
from cartomize.desktop import CartomizeWindow


@pytest.fixture(scope='module')
def application():
    return QApplication.instance() or QApplication([])


def finish(window):
    if window.thread is not None:
        loop=QEventLoop();timer=QTimer()
        timer.timeout.connect(lambda:loop.quit() if window.thread is None else None)
        timer.start(10);QTimer.singleShot(20000,loop.quit);loop.exec();timer.stop()
    assert window.thread is None
    assert window.status.text().startswith('Traitement terminé'), window.status.text()


def test_selected_bands_pipeline_and_portable_session(application, write_raster, tmp_path, monkeypatch):
    files=[]
    for tile,x in [('181063',300000),('181064',300020)]:
        prefix=f'LC08_L2SP_{tile}_20260817_20260820_02_T1'
        for band in (2,3,4,5):
            files.append(str(write_raster(f'{prefix}_SR_B{band}.TIF',np.full((2,2),10000+band*100,dtype='uint16'),
                transform=from_origin(x,9500000,10,10),nodata=0)))
        write_raster(f'{prefix}_QA_PIXEL.TIF',np.full((2,2),64,dtype='uint16'),transform=from_origin(x,9500000,10,10),nodata=0)
    aoi=tmp_path/'zone.shp'
    cm.GeoDataFrame(geometry=[box(300010,9499980,300030,9500000)],crs=32733).to_file(aoi)
    monkeypatch.setattr(QFileDialog,'getOpenFileNames',lambda *a,**kw:(files,''))
    window=CartomizeWindow();window.select_tool('prepare');page=window.tool('prepare')
    page.select_files();assert page.assets.rowCount()==8
    page.aoi.edit.setText(str(aoi));assert page.clip.isChecked()
    page.colour.setChecked(True);page.separate.setChecked(True)
    page.rgb_red.setCurrentIndex(page.rgb_red.findData('nir'))
    page.rgb_green.setCurrentIndex(page.rgb_green.findData('red'))
    page.rgb_blue.setCurrentIndex(page.rgb_blue.findData('green'))
    page.output.edit.setText(str(tmp_path));page.name.setText('production')
    session=window.save_session_file(tmp_path/'session.cmz',portable=True)
    restored=CartomizeWindow();restored.open_session_file(session)
    restored_page=restored.tool('prepare')
    assert restored_page.rgb_red.currentData()=='nir' and restored_page.separate.isChecked()
    assert len(restored_page.selected_scenes())==2
    # Checkboxes restored into table cells still update the available RGB bands.
    for row in (0,4):restored_page.assets.cellWidget(row,0).setChecked(False)
    assert restored_page.rgb_red.findData('blue')==-1
    for row in (0,4):restored_page.assets.cellWidget(row,0).setChecked(True)
    restored_page.output.edit.setText(str(tmp_path));restored_page.name.setText('restored')
    restored.start();finish(restored)
    record=json.loads(Path(restored.output_path).read_text())
    with rasterio.open(record['products'][0]['multiband']) as src:
        assert src.width==2 and src.count==4
        np.testing.assert_allclose(src.read(3),10400*.0000275-.2,atol=1e-7)
    with rasterio.open(record['products'][0]['composition']) as src:
        assert src.tags()['source_bands']=='(4, 3, 2)'
    assert len(restored.results)==6
    assert restored.tool('indices').source.text()==record['products'][0]['multiband']
    restored.close();window.close()


def test_manual_bands_and_unchecked_mosaic(application, write_raster, tmp_path):
    files=[str(write_raster(name+'.tif',np.full((2,2),value,dtype='float32')))
           for name,value in [('a_red',0),('a_nir',2),('b_red',10),('b_nir',12)]]
    window=CartomizeWindow();window.select_tool('prepare');page=window.tool('prepare')
    page.mode.setCurrentIndex(1);page.files=files;page.load_inputs()
    for row in range(4):
        page.assets.item(row,1).setText('A' if row<2 else 'B')
        page.assets.item(row,2).setText('red' if row%2==0 else 'nir')
    page.mosaic.setChecked(False);page.multiband.setChecked(False);page.separate.setChecked(True)
    page.output.edit.setText(str(tmp_path));page.name.setText('scenes')
    window.start();finish(window)
    record=json.loads(Path(window.output_path).read_text())
    assert len(record['products'])==2
    for product,expected in zip(record['products'],[0,10]):
        assert product['multiband'] is None
        with rasterio.open(product['bands']['1']['path']) as src:
            assert src.read(1).tolist()==[[expected]*2]*2
            assert src.read_masks(1).min()==255
    window.close()


def test_classification_transfer_uses_scientific_product_and_settings(application,write_raster,tmp_path):
    from cartomize.desktop import CartomizeWindow
    scientific=write_raster('science.tif',np.ones((2,12,12),dtype='float32'))
    display=write_raster('display.tif',np.ones((4,12,12),dtype='uint8'),nodata=0)
    with rasterio.open(display,'r+') as dst:dst.update_tags(CARTOMIZE_PRODUCT='display_rgba')
    window=CartomizeWindow()
    assistant=window.tool('assistant');assistant.classification.setCurrentIndex(assistant.classification.findData('unsupervised'))
    assistant.validation.edit.setText(str(tmp_path/'validation.gpkg'));assistant.label_column.setText('libelle');assistant.group_column.setText('site')
    window.register_result({'data':str(display)});window.register_result({'data':str(scientific)})
    report=dict(inputs=[],layers=[],data_kind='scenes',issues=[],aoi=None)
    window.open_assistant_step('classification',report)
    page=window.tool('classification')
    assert page.source.text()==str(scientific)
    assert page.method.currentData()=='kmeans'
    assert page.validation.text()==str(tmp_path/'validation.gpkg')
    with pytest.raises(ValueError,match='scientifique'):window.transfer_result({'data':str(display)},'classification')
    order=list(window.tool_pages)
    assert order.index('prepare')<order.index('classification')<order.index('mapping')
    state=window.capture_session();window.restore_session(state)
    assert window.tool('assistant').group_column.text()=='site'
    window.close();application.processEvents()
