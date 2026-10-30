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
        assert len(window.tool_pages)==21
        checks.append('installed desktop and 21 tool pages')
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
        checks.extend(_vector_quality_checks(cm, root))
        checks.extend(_vector_reprojection_checks(cm, root))
        checks.extend(_vector_merge_checks(cm, root))
        checks.extend(_g01_checks(cm, root, window, wait_for))
        checks.extend(_conversion_checks(cm, root, window, wait_for))
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
                'executable':sys.executable,'module':str(installed),
                'check_count':len(checks),'checks':checks}
        output.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False))
    finally:
        if window.thread is not None:
            window.cancel();wait_for(lambda:window.thread is None)
        window.close();app.processEvents()


def _g01_checks(cm, root, window, wait_for):
    """Run the installed G01 worker on an explicitly selected, typed file layer."""
    from contextlib import closing
    import sqlite3
    import numpy as np
    import geopandas as gpd
    import pyogrio
    from pyproj import CRS
    import shapely
    from shapely.geometry import Point, Polygon, box
    from cartomize.viewer_data import table_page

    source = root / 'g01-source.gpkg'
    gpd.GeoDataFrame({'reference': ['background']}, geometry=[Point(20, 20)], crs=32733).to_file(
        source, layer='reference', index=False)
    original_shapes = [Polygon([(.12, .12), (2.12, 2.12), (.12, 2.12), (2.12, .12), (.12, .12)]),
                       box(3.11, .11, 4.11, 1.11), None, Polygon()]
    pyogrio.raw.write(source, shapely.to_wkb(original_shapes), [
        np.array(['0001', 'NA', '0003', '0004'], dtype=object),
        np.array([2**60 + 3, 0, 7, 8], dtype='int64'),
        np.array(['2024-02-29', '2024-03-01', '1970-01-01', '2024-03-03'], dtype='datetime64[D]'),
    ], ['identifier', 'large_id', 'survey_date'],
        field_mask=[None, np.array([False, True, False, False]), np.array([False, False, True, False])],
        layer='to_repair', driver='GPKG', geometry_type='Unknown', promote_to_multi=False,
        crs=CRS(32733).to_wkt(), layer_options={'SPATIAL_INDEX': 'NO'})
    original_bytes = source.read_bytes()
    try:
        cm.audit_geometries(source)
    except ValueError as error:
        assert 'layer' in str(error)
    else:
        raise AssertionError('The installed G01 workflow selected the first layer implicitly.')

    window.transfer_result({'data': str(source), 'kind': 'vector'}, 'vector')
    page = window.tool('vector')
    page.operation.setCurrentIndex(page.operation.findData('repair_geometries'))
    page.refresh_fields()
    assert page.quality_layer.currentData() is None
    page.quality_layer.setCurrentIndex(page.quality_layer.findData('to_repair'))
    page.quality_id.setCurrentText('identifier')
    page.repair_method.setCurrentIndex(page.repair_method.findData('linework'))
    page.repair_missing.setCurrentIndex(page.repair_missing.findData('drop'))
    page.repair_empty.setCurrentIndex(page.repair_empty.findData('drop'))
    page.repair_type_changes.setCurrentIndex(page.repair_type_changes.findData('allow'))
    page.repair_tolerance.setValue(.25)
    page.crs.setText('')
    page.output.edit.setText(str(root))
    page.quality_folder.setText('g01-installed')
    window.run_button.click()
    wait_for(lambda: window.thread is None)
    operation = root / 'g01-installed' / 'operation.json'
    assert operation.is_file(), window.status.text()
    record = json.loads(operation.read_text(encoding='utf-8'))
    products = record['products']
    before = cm.read_file(products['before'])
    after = cm.read_file(products['data'])
    report = table_page(products['report'])['frame']
    summary = json.loads(Path(products['summary']).read_text(encoding='utf-8'))
    assert len(before) == 4 and len(after) == 2
    assert [None if geometry is None else geometry.wkb for geometry in before.geometry] == [
        None if geometry is None else geometry.wkb for geometry in original_shapes]
    assert after.identifier.tolist() == ['0001', 'NA']
    assert after.geom_type.tolist() == ['MultiPolygon', 'Polygon']
    assert after.geometry.area.tolist() == [2., 1.]
    assert summary['source_layer'] == 'to_repair' and summary['tolerance'] == .25
    assert summary['repair_changed_features'] == 1 and summary['precision_changed_features'] == 2
    assert report.feature_id.tolist() == ['0001', 'NA', '0003', '0004']
    assert report.output_row.dropna().tolist() == [0, 1]
    assert report.rejected_row.dropna().tolist() == [0, 1]
    with closing(sqlite3.connect(products['data'])) as connection:
        types = {row[1]: row[2].upper() for row in connection.execute('PRAGMA table_info(features)')}
        assert types['survey_date'] == 'DATE' and types['large_id'] == 'INTEGER'
        assert connection.execute('SELECT identifier,large_id,survey_date FROM features').fetchall() == [
            ('0001', 2**60 + 3, '2024-02-29'), ('NA', None, '2024-03-01')]
    assert source.read_bytes() == original_bytes
    table = page.open_quality_product('report')
    wait_for(lambda: len(table.frame) == 4)
    column = list(table.frame.columns).index('feature_id')
    assert table.model.data(table.model.index(0, column)) == '0001'
    assert table.model.data(table.model.index(1, column)) == 'NA'
    comparison = page.compare_quality_results()
    assert comparison is not None and comparison.link.isChecked()
    assert [document.path for document in comparison.documents] == [products['before'], products['data']]
    return [
        'installed G01 desktop worker: explicit layer, XY grid, GEOS/grid changes and retained/rejected row mapping',
        'installed G01 publication: exact original WKB, Polygon/MultiPolygon types, DATE, nullable int64 and labels',
        'installed G01 views: exact report identifiers and synchronized before/after comparison',
    ]


def _vector_quality_checks(cm, root):
    """Exercise the shipped quality code and its complete file products."""
    import geopandas as gpd
    from shapely.geometry import Polygon, box
    data = gpd.GeoDataFrame({'code': ['a', 'b', 'c'], 'fid': [4, 4, 4]}, geometry=[
        Polygon([(0, 0), (4, 4), (0, 4), (4, 0), (0, 0)]),
        box(10, 0, 12, 2), box(10, 0, 12, 2)], crs=32733)
    assert cm.audit_geometries(data).summary['invalid_geometries'] == 1
    repaired = cm.repair_geometries(data, id_field='code')
    assert repaired.data.is_valid.all() and repaired.data.area.sum() == 16.
    unique = cm.deduplicate(repaired.data, geometry='topological', id_field='code')
    assert unique.data.code.tolist() == ['a', 'b'] and unique.data.area.sum() == 12.
    topology = cm.check_topology(unique.data, rules=['duplicates', 'overlaps'])
    assert topology.data.empty
    destination = root / 'vector-quality'
    record = cm.execute_operation('vector.repair_geometries', {'data': data, 'id_field': 'code'}, destination)
    assert all(Path(path).is_file() for path in record['products'].values())
    assert gpd.read_file(record['primary']).fid.tolist() == [4, 4, 4]
    return ['installed vector quality: invalid polygon repaired, exact areas 16 then 12 m2, duplicate removed, clean topology',
            'installed quality bundle: all related products readable and business fid attribute retained']


def _vector_reprojection_checks(cm, root):
    """Check the installed batch against an analytic coordinate reference."""
    import math
    import geopandas as gpd
    from shapely.geometry import Point
    data = gpd.GeoDataFrame({'code': ['001', '002'], 'fid': [7, 7],
                            'identifier': [2**53 + 1, 2**53 + 3]},
                           geometry=[Point(15, -4), Point(16, -5)], crs=4326)
    source = root / 'batch-input.gpkg'
    data.to_file(source, layer='sites', index=False, layer_options={'FID': 'source_record'})
    data.iloc[:1].to_file(source, layer='subset', index=False, layer_options={'FID': 'source_record'})
    inspection = cm.inspect_reprojection(source, 3857)
    assert len(inspection['layers']) == 2
    selections = {layer['id']: layer['catalogue']['operations'][0]['id']
                  for layer in inspection['layers']}
    result = cm.reproject_batch(source, root / 'vector-batch', 3857, operations=selections)
    assert result.summary['feature_count'] == 3
    for path in result.layers.values():
        output = gpd.read_file(path)
        for position, point in enumerate(output.geometry):
            lon, lat = (15 + position), (-4 - position)
            expected = (6378137 * math.radians(lon),
                        6378137 * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)))
            assert abs(point.x - expected[0]) < 1e-6 and abs(point.y - expected[1]) < 1e-6
        assert output.identifier.tolist() == data.identifier.iloc[:len(output)].tolist()
        assert output.fid.tolist() == [7] * len(output)
    assert all(row['selection'] == 'explicit' and row['operation']['definition']
               for row in result.summary['layers'])
    assert 'vector.reproject_batch' in {entry['id'] for entry in cm.operation_catalog()}
    return ['installed vector reprojection: automatic discovery of two GeoPackage layers, explicit operations and retained identifiers',
            'installed reprojection coordinates: analytic Mercator reference within 1 micrometre, complete manifest and CSV report']


def _vector_merge_checks(cm, root):
    """Exercise packaged typed I/O and named plan products against SQLite."""
    from contextlib import closing
    import math
    import sqlite3
    import numpy as np
    import pyogrio
    from pyproj import CRS
    import shapely
    from shapely.geometry import Point

    fields = ('identifier', 'code', 'survey_date', 'observed_at', 'approved', 'fid')
    expected = [
        (2**60 + 3, '001', '2024-02-29', '2024-02-29T10:30:00.123Z', 1, 7),
        (None, '002', None, None, None, 7),
        (2**53 + 1, '003', '2024-03-02', '2024-03-02T10:00:00.250Z', 0, 7),
    ]
    expected_types = dict(zip(fields, ('INTEGER', 'TEXT', 'DATE', 'DATETIME', 'BOOLEAN', 'INTEGER')))

    def quoted(name):
        return '"' + name.replace('"', '""') + '"'

    def saved_attributes(path, columns):
        # Close SQLite explicitly before temporary-directory cleanup on Windows.
        with closing(sqlite3.connect(path)) as connection:
            layers = connection.execute('SELECT table_name, srs_id FROM gpkg_geometry_columns').fetchall()
            assert len(layers) == 1 and layers[0][1] == 32733
            layer = layers[0][0]
            info = connection.execute(f'PRAGMA table_info({quoted(layer)})').fetchall()
            primary = next(row[1] for row in info if row[5] == 1)
            assert primary != 'fid', 'The business fid must remain an ordinary attribute.'
            types = {row[1]: row[2].upper() for row in info}
            assert {name: types[name] for name in fields} == expected_types
            selected = ', '.join(quoted(name) for name in columns)
            return connection.execute(
                f'SELECT {selected} FROM {quoted(layer)} ORDER BY {quoted(primary)}').fetchall()

    # All fixtures and products are local to this context, including on failure.
    # Absolute source paths exercise the installed reader independently of cwd.
    with tempfile.TemporaryDirectory(prefix='merge-probe-', dir=Path(root).resolve()) as temporary:
        work = Path(temporary).resolve()
        first, second = work / 'survey_a.gpkg', work / 'survey_b.gpkg'
        geometries = [Point(500000, 9500000), Point(500200, 9500000), Point(500400, 9500200)]
        nulls = np.array([False, True])
        pyogrio.raw.write(first, geometry=shapely.to_wkb(geometries[:2]),
            field_data=[np.array([2**60 + 3, 0], dtype='int64'),
                        np.array(['001', '002'], dtype=object),
                        np.array(['2024-02-29', 'NaT'], dtype='datetime64[D]'),
                        np.array(['2024-02-29T10:30:00.123', 'NaT'], dtype='datetime64[ms]'),
                        np.array([True, False], dtype=bool), np.array([7, 7], dtype='int64')],
            fields=['visit_id', 'site_code', 'recorded_on', 'seen_at', 'verified', 'fid'],
            field_mask=[nulls, None, None, None, nulls, None], layer='survey_a', driver='GPKG',
            geometry_type='Point', crs=CRS(32733).to_wkt(), promote_to_multi=False,
            layer_options={'FID': 'source_record'},
            gdal_tz_offsets={'seen_at': np.full(2, 100, dtype=np.int32)})
        pyogrio.raw.write(second, geometry=shapely.to_wkb(geometries[2:]),
            field_data=[np.array(['9007199254740993'], dtype=object),
                        np.array(['003'], dtype=object), np.array(['2024-03-02'], dtype=object),
                        np.array(['2024-03-02T12:00:00.250+02:00'], dtype=object),
                        np.array(['false'], dtype=object), np.array([7], dtype='int64')],
            fields=['legacy_id', 'local_code', 'date_iso', 'instant_iso', 'approval', 'business_id'],
            layer='survey_b', driver='GPKG', geometry_type='Point', crs=CRS(32733).to_wkt(),
            promote_to_multi=False, layer_options={'FID': 'source_record'})
        originals = {path: path.read_bytes() for path in (first, second)}
        sources = [{'path': str(first), 'layer': 'survey_a'},
                   {'path': str(second), 'layer': 'survey_b'}]
        inspection = cm.inspect_merge(sources)
        assert inspection['schema'] == 'cartomize.vector_merge_inspection.v1'
        assert inspection['layer_count'] == 2 and inspection['feature_count'] == 3
        layers = inspection['layers']
        maps = {
            layers[0]['id']: dict(zip(('visit_id', 'site_code', 'recorded_on', 'seen_at', 'verified', 'fid'), fields)),
            layers[1]['id']: dict(zip(('legacy_id', 'local_code', 'date_iso', 'instant_iso', 'approval', 'business_id'), fields)),
        }
        schema = dict(zip(fields, ('int64', 'string', 'date', 'datetime_utc', 'boolean', 'int64')))
        result = cm.merge_layers(sources, work / 'merged', schema=schema, field_maps=maps)
        assert isinstance(result, cm.MergedVectors)
        assert all(Path(path).is_file() for path in (result.manifest, result.data, result.report, result.issues))
        record = json.loads(result.manifest.read_text(encoding='utf-8'))
        assert record['schema'] == 'cartomize.vector_merge.v1' and record['status'] == 'complete'
        assert record['feature_count'] == 3 and record['source_count'] == 2
        assert record['conversion_error_count'] == 0
        provenance = record['provenance_columns']
        semantics = ('source_id', 'source_name', 'source_path', 'source_layer', 'source_row')
        assert set(provenance) == set(semantics)
        expected_provenance = [(layer['id'], layer['name'], layer['path'], layer['layer'], row)
                               for layer in layers for row in range(layer['features'])]
        assert saved_attributes(result.data, tuple(provenance[name] for name in semantics)) == expected_provenance
        assert cm.read_file(result.data).geometry.to_wkb().tolist() == [point.wkb for point in geometries]
        assert saved_attributes(result.data, fields) == expected

        # A second execution tests the registry and @step:data resolution, then
        # reopens its typed output in another operation before writing again.
        catalog = {entry['id']: entry for entry in cm.operation_catalog()}
        assert {'data', 'manifest', 'report', 'issues'} <= set(catalog['vector.merge_layers']['products'])
        plan = cm.processing_plan([
            dict(id='merged', operation='vector.merge_layers', parameters={
                'sources': sources, 'schema': schema, 'field_maps': maps}),
            dict(id='buffered', operation='vector.buffer', parameters={'data': '@merged:data', 'distance': 25}),
        ])
        plan_path = cm.run_plan(plan, work / 'plan')
        document = json.loads(Path(plan_path).read_text(encoding='utf-8'))
        products = document['products']['merged']
        assert all(Path(path).is_file() for path in products.values())
        planned_manifest = Path(products['manifest'])
        planned = json.loads(planned_manifest.read_text(encoding='utf-8'))
        assert planned['data'] == products['data']
        assert '.cartomize-' not in planned_manifest.read_text(encoding='utf-8')
        assert '.cartomize-' not in Path(plan_path).read_text(encoding='utf-8')
        buffered_path = Path(document['results']['buffered'])
        all_fields = fields + tuple(provenance[name] for name in semantics)
        complete_expected = [values + origin for values, origin in zip(expected, expected_provenance)]
        assert saved_attributes(products['data'], all_fields) == complete_expected
        assert saved_attributes(buffered_path, all_fields) == complete_expected
        buffered = cm.read_file(buffered_path)
        assert len(buffered) == 3 and buffered.geometry.is_valid.all()
        assert CRS(buffered.crs) == CRS(32733)
        np.testing.assert_allclose(buffered.geometry.area, math.pi * 25**2, rtol=.01)
        assert all(path.read_bytes() == original for path, original in originals.items())
        assert not list(work.rglob('.cartomize-*'))
    return ['installed vector merge: two heterogeneous GeoPackage schemas mapped to three rows with complete provenance',
            'installed merge types: exact nullable int64 above 2**53, leading-zero codes, DATE and UTC DATETIME verified by SQLite',
            'installed merge plan: named data product feeds 25 m buffers with typed attributes and source files intact']


def _conversion_checks(cm, root, window, wait_for):
    """Exercise the installed G06 engines and the dedicated desktop worker."""
    from contextlib import closing
    import sqlite3
    import geopandas as gpd
    import numpy as np
    import pandas as pd
    import rasterio
    from rasterio.transform import from_origin
    from shapely.geometry import Point

    source = root / 'g06-source.gpkg'
    frame = gpd.GeoDataFrame({
        'code': pd.Series(['001', 'NA'], dtype='string'),
        'identifier': pd.Series([2**53 + 1, None], dtype='Int64'),
    }, geometry=[Point(300000, 9500000), Point(300030, 9500030)], crs=32733)
    frame.to_file(source, layer='observations', index=False)
    converted = cm.convert_vector(source, root / 'g06-fgb', driver='FlatGeobuf')
    saved = cm.read_file(converted.data)
    assert saved.code.tolist() == ['001', 'NA']
    assert int(saved.identifier.iloc[0]) == 2**53 + 1 and pd.isna(saved.identifier.iloc[1])
    assert converted.summary['difference_count'] == 0

    raster = root / 'g06-source.tif'
    pixels = np.array([[0, 1, 65535], [2, 3, 1]], dtype='uint16')
    with rasterio.open(raster, 'w', driver='GTiff', width=3, height=2, count=1, dtype='uint16',
                       crs=32733, transform=from_origin(300000, 9500000, 30, 30), nodata=65535) as dataset:
        dataset.write(pixels, 1)
        dataset.set_band_description(1, 'classes')
        dataset.update_tags(1, survey='G06 installed probe')
        dataset.update_tags(1, ns='VALIDATION', origin='analytic fixture')
    delivered = cm.convert_raster(raster, root / 'g06-cog', driver='COG', dtype='uint8', nodata=255)
    with rasterio.open(raster) as before, rasterio.open(delivered.data) as after:
        assert before.crs == after.crs and before.transform == after.transform
        np.testing.assert_array_equal(before.read_masks(), after.read_masks())
        valid = before.read_masks() > 0
        np.testing.assert_array_equal(before.read()[valid], after.read()[valid])
        assert after.tags(1)['survey'] == 'G06 installed probe'
        assert after.tags(1, ns='VALIDATION')['origin'] == 'analytic fixture'
        assert after.tags(ns='IMAGE_STRUCTURE')['LAYOUT'] == 'COG'

    window.transfer_result({'data': str(source), 'kind': 'vector'}, 'conversion')
    page = window.tool('conversion')
    page.inspect_button.click()
    wait_for(lambda: window.thread is None)
    assert page.layer.currentIndex() >= 0, window.status.text()
    page.vector_driver.setCurrentIndex(page.vector_driver.findData('GPKG'))
    page.output.edit.setText(str(root))
    page.folder.setText('g06-installed-desktop')
    window.run_button.click()
    wait_for(lambda: window.thread is None)
    result = Path(page.converted_data.text())
    assert result.is_file(), window.status.text()
    with closing(sqlite3.connect(result)) as connection:
        assert connection.execute('SELECT code, identifier FROM features ORDER BY rowid').fetchall() == [
            ('001', 2**53 + 1), ('NA', None)]
    assert Path(page.converted_report.text()).is_file()
    return ['installed G06 vector: FlatGeobuf retains nullable int64 and textual identifiers',
            'installed G06 raster: COG dtype/NoData conversion preserves masks, pixels, grid and metadata',
            'installed G06 desktop: inspection, conversion worker and reopenable report succeed']


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
