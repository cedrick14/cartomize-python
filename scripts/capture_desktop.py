"""Render screenshots of the actual Cartomize window using generated GIS fixtures."""
from pathlib import Path
import argparse
import json
import os
import platform
import time

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import numpy as np
import geopandas as gpd
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import Point
from PySide6.QtCore import QEventLoop, QSettings, QTimer
from PySide6.QtWidgets import QApplication
from cartomize.desktop import CartomizeWindow


def wait_for(predicate, seconds=30):
    loop=QEventLoop();timer=QTimer();deadline=time.monotonic()+seconds
    timer.timeout.connect(lambda:loop.quit() if predicate() or time.monotonic()>deadline else None)
    timer.start(10)
    if not predicate():loop.exec()
    timer.stop()
    if not predicate():raise RuntimeError('Desktop rendering did not complete')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',default='reports/desktop')
    args=parser.parse_args()
    output=Path(args.output).resolve();output.mkdir(parents=True,exist_ok=True)
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat,QSettings.Scope.UserScope,str(output/'settings'))
    app=QApplication.instance() or QApplication([])
    data=output/'data';data.mkdir(exist_ok=True)
    yy,xx=np.mgrid[-2:2:256j,-2:2:256j]
    values=(500+1200*np.exp(-xx**2-yy**2)+160*np.sin(xx*5)*np.cos(yy*3)).astype('float32')
    raster=data/'relief.tif'
    with rasterio.open(raster,'w',driver='GTiff',width=256,height=256,count=1,dtype='float32',crs='EPSG:32733',transform=from_origin(300000,9500000,30,30),nodata=-9999) as dst:
        dst.write(values,1);dst.set_band_description(1,'Altitude')
    source=data/'sites.shp'
    gpd.GeoDataFrame({'nom':['Site A','Site B']},geometry=[Point(302000,9497500),Point(305000,9495000)],crs=32733).to_file(source)
    window=CartomizeWindow()
    report={'platform':platform.platform(),'python':platform.python_version(),'source':'Generated reproducible GIS fixtures','views':{}}
    try:
        window._workbench.font_size.setValue(12)
        window.resize(1440,940);window.show();app.processEvents()
        assert window.project_explorer.open_path(source) is not None
        doc=window.project_explorer.open_path(raster)
        assert doc is not None
        doc.palette.setCurrentIndex(doc.palette.findData('terrain'))
        window._workbench.select_tool('vector')
        window.tool('vector').source.edit.setText(str(source))
        window.tool('vector').operation.setCurrentIndex(window.tool('vector').operation.findData('buffer'))
        window.tool('vector').distance.setValue(200)
        wait_for(lambda:doc.canvas.last_render is not None)
        for theme in ('light','dark'):
            window.theme_selector.setCurrentIndex(window.theme_selector.findData(theme))
            app.processEvents()
            viewport=doc.canvas.viewport()
            assert viewport.width()>100 and viewport.height()>70
            image=output/f'cartomize-{theme}.png'
            if not window.grab().save(str(image)):raise RuntimeError('Unable to save desktop screenshot')
            report['views'][theme]={'window':[window.width(),window.height()], 'map':[viewport.width(),viewport.height()], 'image':image.name}
        report['tools']=list(window.tool_pages)
        report['loaded_files']=len(window.workspace.records)
        report['status']='passed'
    finally:
        window.close();app.processEvents()
        (output/'capture.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':
    main()
