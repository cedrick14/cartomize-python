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


def _analysis_checks(cm, root):
    """Exercise coverage and calibration using one small shared raster fixture."""
    import numpy as np
    import geopandas as gpd
    import rasterio
    from rasterio.transform import from_origin
    from shapely.geometry import box

    source=root/'quantized.tif'
    values=np.array([[0,1000,-9999],[2000,3000,4000]],dtype='int16')
    scale,offset=.001,-.5
    with rasterio.open(source,'w',driver='GTiff',width=3,height=2,count=1,dtype='int16',
                       crs=32733,transform=from_origin(300000,9500000,10,10),nodata=-9999) as dst:
        dst.write(values,1);dst.scales=(scale,);dst.offsets=(offset,)
        dst.set_band_unit(1,'reflectance')
    zones=gpd.GeoDataFrame({'zone':['partly_outside']},
        geometry=[box(300000,9499980,300040,9500000)],crs=32733)
    scene=cm.Scene('installed-probe',{'red':cm.Band(source,scale=scale,offset=offset,unit='reflectance')},
                   sensor='custom',acquired='2026-10-26')
    # The diagnostic requires a new directory. A temporary workspace also lets
    # the installed probe be rerun without stale diagnostic products.
    with tempfile.TemporaryDirectory(prefix='coverage-probe-',dir=root) as temporary:
        audit=cm.audit_imagery([scene],Path(temporary)/'audit',aoi=zones,
                              mask_clouds=False,mask_saturation=False,max_pixels=8)
        assert isinstance(audit,cm.ImageryAudit)
        assert all(path.is_file() for path in (audit.manifest,audit.coverage,audit.gaps))
        report=json.loads(audit.manifest.read_text(encoding='utf-8'))
        assert report['schema']=='cartomize.imagery.audit.v1'
        assert report['version']==cm.__version__
        assert report['aoi_pixels']==8
        assert report['footprint_pixels']==6
        assert report['present_pixels']==report['usable_pixels']==5
        assert report['footprint_percent']==75
        assert report['present_percent']==report['usable_percent']==62.5
        assert report['coverage_status']=='partial'
        assert report['recommended_action']=='additional_scenes'
        assert report['recommended_scene_ids']==['installed-probe']
        footprint=np.array([[1,1,1,0],[1,1,1,0]],dtype='uint8')
        present=np.array([[1,1,0,0],[1,1,1,0]],dtype='uint8')
        with rasterio.open(audit.coverage) as src:
            assert src.count==3 and src.descriptions==('footprint','present','usable')
            np.testing.assert_array_equal(src.read(),np.stack((footprint,present,present)))
        with rasterio.open(audit.gaps) as src:
            np.testing.assert_array_equal(src.read(1),[[0,0,2,1],[0,0,0,1]])

        blocked=Path(temporary)/'blocked'
        try:
            cm.preprocess_imagery([scene],blocked,aoi=zones,mask_clouds=False,max_pixels=8)
        except cm.ImageryCoverageError as error:
            assert error.report['usable_percent']==62.5
            assert error.manifest.is_file() and error.diagnostic.gaps.is_file()
            assert not blocked.exists()
        else:
            raise AssertionError('The installed automatic workflow accepted insufficient coverage.')
        extra=Path(temporary)/'complement.tif'
        with rasterio.open(extra,'w',driver='GTiff',width=4,height=2,count=1,dtype='int16',
                           crs=32733,transform=from_origin(300000,9500000,10,10),nodata=-9999) as dst:
            dst.write(np.where(present, -9999, 9000).astype('int16'),1)
        complement=cm.Scene('complement',{'red':cm.Band(extra,scale=scale,offset=offset,unit='reflectance')},
                             sensor='custom',acquired='2026-10-26')
        automatic=cm.preprocess_imagery([scene,complement],Path(temporary)/'automatic',
            aoi=zones,mask_clouds=False,max_pixels=8)
        assert automatic.report['status']=='complete' and automatic.report['mosaic']
        assert automatic.report['usable_percent']==100
        with rasterio.open(automatic.products[0]['multiband']) as src:
            np.testing.assert_allclose(src.read(1),[[-.5,.5,8.5,8.5],[1.5,2.5,3.5,8.5]])
            assert src.read_masks(1).min()==255

    statistics=cm.raster.zonal_stats(source,zones,value_mode='physical',include_coverage=True,
                                    block_size=1,max_zone_pixels=8)
    row=statistics.iloc[0]
    assert row['count']==5 and row['zone_pixels']==8 and row['raster_pixels']==6
    assert row['coverage_percent']==62.5
    np.testing.assert_allclose([row[name] for name in ('min','max','mean','sum','std')],
                               [-.5,3.5,1.5,7.5,np.sqrt(2)])
    metadata=statistics.attrs['cartomize']
    assert metadata['schema']=='cartomize.zonal_stats.v1' and metadata['value_mode']=='physical'
    assert metadata['applied_scale']==scale and metadata['applied_offset']==offset
    assert metadata['unit']=='reflectance'
    return ['installed imagery coverage audit: 5 usable pixels of 8, gap rasters and recommendation',
            'automatic preparation: 62.5% refused with persistent gaps; complementary scene produces exactly 100%',
            'calibrated zonal statistics: mean 1.5, sum 7.5 and observed coverage 62.5%']


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
    # Keep each probe's products separate so validation can be repeated with
    # the same report path without overwriting an earlier run's exports.
    root=Path(tempfile.mkdtemp(prefix='installed-data-',dir=output.parent))
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
        checks.extend(_analysis_checks(cm,root))
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
