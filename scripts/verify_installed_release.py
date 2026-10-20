"""Install a built wheel in a clean virtual environment and exercise it.

The probe is executed with Python isolated mode, outside the source checkout.
No editable package or inherited site-packages are used.
"""
from pathlib import Path
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import venv
import zipfile
from email.parser import BytesParser


def probe(output, expected):
    import cartomize as cm
    import numpy as np
    import geopandas as gpd
    import rasterio
    from rasterio.transform import from_origin
    from shapely.geometry import Point
    from PySide6.QtCore import QEventLoop, QSettings, QTimer
    from PySide6.QtWidgets import QApplication

    output=Path(output).resolve();output.parent.mkdir(parents=True,exist_ok=True)
    root=output.parent/'installed-data';root.mkdir(exist_ok=True)
    installed=Path(cm.__file__).resolve()
    assert Path(sys.prefix).resolve() in installed.parents, installed
    assert cm.__version__==expected, (cm.__version__,expected)
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat,QSettings.Scope.UserScope,str(root/'settings'))
    app=QApplication.instance() or QApplication([])

    def wait_for(predicate, timeout=60):
        loop=QEventLoop();timer=QTimer();deadline=time.monotonic()+timeout
        timer.timeout.connect(lambda:loop.quit() if predicate() or time.monotonic()>deadline else None)
        timer.start(10)
        if not predicate():loop.exec()
        timer.stop()
        assert predicate(), 'Installed desktop operation timed out'

    checks=[]
    window=cm.launch(block=False)
    try:
        window.show();app.processEvents()
        assert window.windowTitle()=='Cartomize'
        assert len(window.tool_pages)==20
        checks.append('installed desktop and 20 tool pages')
        for theme in ('light','dark','system'):
            window.theme_selector.setCurrentIndex(window.theme_selector.findData(theme))
            app.processEvents()
        checks.append('light dark and system appearance')
        raster=root/'spectral.tif'
        values=np.array([np.full((24,24),.2),np.full((24,24),.6)],dtype='float32')
        with rasterio.open(raster,'w',driver='GTiff',width=24,height=24,count=2,dtype='float32',crs=32733,transform=from_origin(300000,9500000,30,30),nodata=-9999) as dst:
            dst.write(values);dst.descriptions=('red','nir')
        assert window.project_explorer.open_path(raster) is not None
        window.transfer_result({'data':str(raster),'kind':'raster'},'indices')
        ndvi=root/'ndvi.tif'
        window.tool('indices').output.edit.setText(str(ndvi))
        window.run_button.click()
        wait_for(lambda:window.thread is None)
        assert ndvi.is_file(),window.status.text()
        with rasterio.open(ndvi) as src:np.testing.assert_allclose(src.read(1),.5,atol=1e-6)
        checks.append('GeoTIFF import and NDVI calculation')
        points=root/'points.gpkg'
        gpd.GeoDataFrame({'nom':['Site A']},geometry=[Point(300300,9499700)],crs=32733).to_file(points)
        assert window.project_explorer.open_path(points) is not None
        window.transfer_result({'data':str(points),'kind':'vector'},'vector')
        tool=window.tool('vector')
        tool.operation.setCurrentIndex(tool.operation.findData('buffer'))
        tool.distance.setValue(200)
        buffer=root/'buffer.gpkg';tool.output.edit.setText(str(buffer))
        window.run_button.click();wait_for(lambda:window.thread is None)
        assert buffer.is_file(),window.status.text()
        area=float(gpd.read_file(buffer).area.iloc[0])
        assert abs(area-np.pi*200**2)/(np.pi*200**2)<.01
        checks.append('GeoPackage import and 200 m vector buffer')
        map_output=cm.Map(title='Validation Cartomize',crs='EPSG:32733')
        map_output.add_layer(str(buffer),name='Tampon')
        for extension in ('pdf','png','svg'):
            destination=root/f'carte.{extension}'
            map_output.export(str(destination),dpi=100)
            assert destination.is_file() and destination.stat().st_size>100
        checks.append('PDF PNG and SVG map exports')
        session=root/'session.cartomize.json'
        window.save_session_file(session)
        window.open_session_file(session)
        checks.append('project save and reopen')
        console=window.console_panel
        console.editor.setPlainText('cm.__version__')
        console.execute();wait_for(lambda:not console.busy)
        assert expected in console.output.toPlainText()
        checks.append('installed Python console kernel')
        report={'status':'passed','version':cm.__version__,'python':sys.version.split()[0],
                'executable':sys.executable,'module':str(installed),'checks':checks}
        output.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False))
    finally:
        if window.thread is not None:
            window.cancel();wait_for(lambda:window.thread is None)
        window.close();app.processEvents()


def main():
    if len(sys.argv)>1 and sys.argv[1]=='--probe':
        probe(sys.argv[2],sys.argv[3]);return
    parser=argparse.ArgumentParser()
    parser.add_argument('--wheel',required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    wheel=Path(args.wheel).resolve()
    report=Path(args.output).resolve();report.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(wheel) as archive:
        metadata_name=next(n for n in archive.namelist() if n.endswith('.dist-info/METADATA'))
        version=BytesParser().parsebytes(archive.read(metadata_name))['Version']
    with tempfile.TemporaryDirectory(prefix='cartomize-install-') as temp:
        target=Path(temp)/'venv'
        venv.EnvBuilder(with_pip=True,system_site_packages=False).create(target)
        python=target/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
        environment=dict(os.environ,QT_QPA_PLATFORM='offscreen',MPLBACKEND='Agg')
        environment.pop('PYTHONPATH',None)
        subprocess.run([str(python),'-m','pip','install','-q',str(wheel)+'[gui]'],cwd=temp,env=environment,check=True,timeout=600)
        subprocess.run([str(python),'-m','pip','check'],cwd=temp,env=environment,check=True,timeout=60)
        subprocess.run([str(python),'-I',str(Path(__file__).resolve()),'--probe',str(report),version],cwd=temp,env=environment,check=True,timeout=180)
        subprocess.run([str(python),'-I','-m','cartomize','--help'],cwd=temp,env=environment,check=True,timeout=60)


if __name__=='__main__':
    main()
