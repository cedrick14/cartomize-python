"""Registered, serializable operations shared by plans, the CLI and desktop.

Only named operators are accepted. A document cannot select Python callables,
change the output directory or overwrite an input. Every operation publishes a
new directory atomically and returns a primary product and its related files.
"""
from pathlib import Path
import inspect
import os
import json
from .storage import new_directory, save_json, json_value
from .imagery import _check_cancel


def _catalog():
    from . import vector, raster
    from . import vector_workflows
    from .algebra import calculate, reduce_rasters
    from .terrain import terrain, convolve
    from .focal import focal
    from .indices import spectral_indices
    from .nodata import mask_background
    from .color import color_composite
    from .classification import classify_landcover, cluster_raster
    result = {}
    def add(key, label, function, output, tool, fields=None):
        result[key] = dict(label=label, function=function, output=output, tool=tool, fields=fields)
    def measures(source, quantity='area', unit=None, metric_crs=None):
        data=vector.read_file(source) if isinstance(source,(str,Path)) else source.copy()
        values=(vector.area(data,unit or 'ha',metric_crs=metric_crs) if quantity=='area'
                else vector.length(data,unit or 'm',metric_crs=metric_crs))
        if values.name in data:raise ValueError('Le champ de mesure existe déjà : '+values.name)
        data[values.name]=values
        return data
    for key,label in [('clip','Découpage vectoriel'),('buffer','Zone tampon'),('sjoin','Jointure spatiale'),
                      ('nearest','Jointure de proximité'),('dissolve','Dissolution'),('reproject','Reprojection vectorielle'),
                      ('make_valid','Réparation des géométries')]:
        add('vector.'+key,label,getattr(vector,key),'vector','vector')
    for key,label in [('select_attributes','Sélection par attribut'),
                      ('select_location','Sélection spatiale'),
                      ('geometry_operation','Transformation des géométries'),
                      ('spatial_summary','Synthèse des observations par zone'),
                      ('latest_records','Dernier relevé par identifiant')]:
        add('vector.'+key,label,getattr(vector_workflows,key),'vector','vector')
    def table_input(data,table_dtypes,delimiter,encoding):
        from .tableio import read_table
        import pandas as pd
        if isinstance(data,(str,Path)):
            return read_table(data,dtype=table_dtypes,delimiter=delimiter,encoding=encoding)
        table=pd.DataFrame(data).copy()
        return table.astype(table_dtypes) if table_dtypes is not None else table
    def table_join(data,table,*,left_on,right_on=None,how='left',validate='many_to_one',
                   null_keys='unmatched',table_dtypes=None,delimiter=None,encoding='utf-8-sig'):
        return vector_workflows.join_attributes(data,
            table_input(table,table_dtypes,delimiter,encoding),left_on=left_on,
            right_on=right_on,how=how,validate=validate,null_keys=null_keys)
    def table_points(data,x='longitude',y='latitude',crs='EPSG:4326',*,
                     table_dtypes=None,delimiter=None,encoding='utf-8-sig'):
        return vector.from_xy(table_input(data,table_dtypes,delimiter,encoding),x=x,y=y,crs=crs)
    add('vector.join_attributes','Jointure attributaire',table_join,'vector','vector')
    add('vector.from_xy','Points depuis un tableau XY',table_points,'vector','vector')
    add('vector.validate','Diagnostic des géométries',vector.validate,'document','vector')
    from .vector_quality import audit_geometries, repair_geometries
    from .vector_topology import check_topology
    from .vector_duplicates import deduplicate
    from .vector_reprojection import reproject_batch
    add('vector.reproject_batch', 'Reprojection vectorielle par lot', reproject_batch, 'document', 'vector')
    from .vector_merge import merge_layers
    add('vector.merge_layers', 'Harmonisation et fusion de couches', merge_layers, 'vector', 'vector')
    from .vector_conversion import convert_vector
    from .raster_conversion import convert_raster
    add('vector.convert', 'Conversion et conditionnement vectoriel', convert_vector, 'vector', 'conversion')
    add('raster.convert', 'Conversion et conditionnement raster', convert_raster, 'raster', 'conversion')
    from .vector_selection import extract_features
    add('vector.extract_features', 'Extraction attributaire et spatiale avec bilan', extract_features, 'vector', 'vector')
    from .vector_tabulation import tabulate_area
    add('vector.tabulate_area', 'Table croisée des surfaces par zone', tabulate_area, 'vector', 'vector')
    from .vector_rings import buffer_rings
    add('vector.buffer_rings', 'Anneaux de distance avec bilan des surfaces', buffer_rings, 'vector', 'vector')
    for key, label, function in [
        ('audit_geometries', 'Diagnostic détaillé des géométries', audit_geometries),
        ('repair_geometries', 'Réparation avec rapport des changements', repair_geometries),
        ('check_topology', 'Contrôle topologique', check_topology),
        ('deduplicate', 'Traitement des doublons', deduplicate),
    ]:
        add('vector.' + key, label, function, 'vector', 'vector')
    from functools import partial
    for mode,label in [('intersection','Intersection'),('union','Union'),('difference','Différence'),('symmetric_difference','Différence symétrique')]:
        add('vector.'+mode,label,partial(vector.overlay,how=mode),'vector','vector')
    add('vector.area','Superficies vectorielles',partial(measures,quantity='area'),'vector','vector')
    add('vector.length','Longueurs vectorielles',partial(measures,quantity='length'),'vector','vector')
    for key,label,kind in [('clip','Extraction par masque','raster'),('reproject','Reprojection raster','raster'),
                           ('reclassify','Reclassification','raster'),('zonal_stats','Statistiques zonales','vector'),
                           ('class_areas','Superficies par classe','table'),('change_matrix','Matrice de transition','table')]:
        add('raster.'+key,label,getattr(raster,key),kind,'raster')
    for key,label,function,tool in [('calculate','Algèbre raster',calculate,'calculator'),
        ('focal','Statistiques focales',focal,'focal'),('reduce','Statistiques multirasters',reduce_rasters,'temporal'),
        ('terrain','Dérivées du terrain',terrain,'terrain'),('convolve','Convolution',convolve,'terrain'),
        ('indices','Indices spectraux',spectral_indices,'indices'),('background','Masquage du fond',mask_background,'project'),
        ('composite','Composition colorée',color_composite,'composite'),
        ('classify','Classification supervisée',classify_landcover,'classification'),('cluster','Classification non supervisée',cluster_raster,'classification')]:
        add(key,label,function,'raster',tool)
    from .hydrology import hydrology
    from .routing import shortest_path
    from .catalogs import search_stac,download_stac
    from .imagery import prepare_imagery
    from .scenes import discover_scenes
    def preparation(sources,destination,band_order=('blue','green','red','nir'),aoi=None,
                    target_crs=None,resolution=None,overlap='first',resampling='nearest',
                    mask_clouds=True,mask_saturation=True,allow_mixed_dates=False,
                    all_touched=False,max_pixels=250_000_000,progress=None,cancel=None):
        return prepare_imagery(discover_scenes(sources),destination,band_order=band_order,
            aoi=aoi,target_crs=target_crs,resolution=resolution,overlap=overlap,
            resampling=resampling,mask_clouds=mask_clouds,mask_saturation=mask_saturation,
            allow_mixed_dates=allow_mixed_dates,all_touched=all_touched,
            max_pixels=max_pixels,progress=progress,cancel=cancel).path
    def imagery_audit(sources,destination,*,aoi,band_order=None,target_crs=None,
                      resolution=None,resampling='nearest',mask_clouds=True,
                      mask_saturation=True,allow_mixed_dates=False,all_touched=False,
                      max_pixels=250_000_000,coverage_threshold=100.,progress=None,cancel=None):
        from .imagery_audit import audit_imagery
        return audit_imagery(discover_scenes(sources),destination,aoi=aoi,
            band_order=band_order,target_crs=target_crs,resolution=resolution,
            resampling=resampling,mask_clouds=mask_clouds,mask_saturation=mask_saturation,
            allow_mixed_dates=allow_mixed_dates,all_touched=all_touched,max_pixels=max_pixels,
            coverage_threshold=coverage_threshold,progress=progress,cancel=cancel).manifest
    def imagery_preprocessing(sources,destination,*,aoi,band_order=None,target_crs=None,
                              resolution=None,overlap='first',resampling='nearest',
                              mask_clouds=True,mask_saturation=True,allow_mixed_dates=False,
                              all_touched=False,max_pixels=250_000_000,coverage_threshold=100.,
                              allow_partial=False,multiband=True,separate_bands=False,
                              composition=None,percentiles=(2,98),gamma=1.,catalog=None,
                              progress=None,cancel=None):
        from .imagery_automatic import preprocess_imagery
        return preprocess_imagery(sources,destination,aoi=aoi,band_order=band_order,
            target_crs=target_crs,resolution=resolution,overlap=overlap,resampling=resampling,
            mask_clouds=mask_clouds,mask_saturation=mask_saturation,
            allow_mixed_dates=allow_mixed_dates,all_touched=all_touched,max_pixels=max_pixels,
            coverage_threshold=coverage_threshold,allow_partial=allow_partial,
            multiband=multiband,separate_bands=separate_bands,composition=composition,
            percentiles=percentiles,gamma=gamma,catalog=catalog,progress=progress,cancel=cancel).manifest
    add('prepare','Prétraitement multispectral',preparation,'raster','prepare')
    add('imagery.audit','Diagnostic de couverture des images',imagery_audit,'document','prepare')
    add('imagery.preprocess','Prétraitement automatique avec contrôle de couverture',imagery_preprocessing,'document','prepare')
    add('hydrology','Analyse hydrologique D8',hydrology,'raster','processing')
    add('routing','Plus court chemin',shortest_path,'vector','processing')
    add('stac.search','Recherche de scènes STAC',search_stac,'document','processing')
    add('stac.download','Téléchargement des scènes STAC',download_stac,'document','processing')
    return result


_ENGINE = {'workers':1,'block_size':512,'memory_limit_mb':512,'align':False,'resampling':'nearest','dtype':'float32','compression':'lzw'}
BLOCK_OPERATIONS={'calculate','indices','reduce','focal','terrain','convolve'}
CUDA_OPERATIONS={'calculate','indices','reduce'}
_HIDDEN = {'destination','overwrite','progress','cancel','stage','options','kwargs','how_fixed','quantity'}
VECTOR_QUALITY_OPERATIONS = {
    'vector.audit_geometries', 'vector.repair_geometries',
    'vector.check_topology', 'vector.deduplicate',
}


def _write_vector_quality(result, work, *, cancel=None):
    """Write related products inside the caller's atomic output directory.

    GPKG's internal feature id is deliberately named outside the source schema:
    an input attribute called ``fid`` remains an ordinary business identifier.
    """
    products = {}
    layers = [('data', result.data), ('issues', result.issues), ('rejected', result.rejected)]
    if result.before is not None:
        layers.append(('before', result.before))
    for name, layer in layers:
        _check_cancel(cancel)
        if layer is None:
            layer = result.data.iloc[:0].copy()
        if name != 'data' and layer is result.data:
            products[name] = products['data']
            continue
        folded = [str(column).casefold() for column in layer.columns]
        if len(set(folded)) != len(folded):
            raise ValueError('Les noms de champs doivent être distincts sans tenir compte de la casse pour GeoPackage.')
        fid = '_cartomize_fid'
        while fid.casefold() in folded:
            fid += '_'
        path = work / (name + '.gpkg')
        if result.before is not None:
            # G01 publishes only after exact attribute/WKB verification.
            # Keep the established G02/G03 interface outside this completion.
            from .vector_io import write_geopackage
            write_geopackage(layer, path, cancel=cancel)
        else:
            layer.to_file(path, driver='GPKG', index=False, layer='features',
                          layer_options={'FID': fid})
        products[name] = path
    _check_cancel(cancel)
    result.report.to_csv(work / 'report.csv', index=False, encoding='utf-8-sig')
    products['report'] = work / 'report.csv'
    if result.before is not None:
        from .vector_io import field_kind
        dtypes = {'int64': 'Int64', 'float64': 'Float64', 'boolean': 'boolean'}
        label_columns = result.summary.get('report_label_columns', [])
        types = {name: ('string' if name in label_columns else dtypes.get(field_kind(result.report[name]), 'string'))
                 for name in result.report.columns}
        save_json(dict(schema='cartomize.table.v1', types=types, label_columns=label_columns),
                  work / 'report.csv.schema.json')
    save_json(result.summary, work / 'summary.json')
    products['summary'] = work / 'summary.json'
    return products


def _selection_audit_value(value, *, identity=False):
    """Keep temporal and index labels typed, and large identifiers exact in JSON."""
    from datetime import date, datetime
    from decimal import Decimal
    import numpy as np
    import pandas as pd
    from .vector_io import is_missing
    if isinstance(value, tuple):
        return dict(type='tuple', items=[_selection_audit_value(item, identity=True) for item in value])
    if is_missing(value):
        return None
    if isinstance(value, (datetime, pd.Timestamp, np.datetime64)):
        return dict(type='datetime', value=pd.Timestamp(value).isoformat())
    if isinstance(value, date):
        return dict(type='date', value=value.isoformat())
    if isinstance(value, np.generic):
        return _selection_audit_value(value.item(), identity=identity)
    if isinstance(value, Decimal):
        return dict(type='decimal', value=str(value))
    if identity and isinstance(value, int) and not isinstance(value, bool):
        return dict(type='integer', value=str(value))
    if isinstance(value, float) and not np.isfinite(value):
        return dict(type='float', value=str(value))
    return json_value(value)


def _write_vector_selection(result, work, *, cancel=None):
    """Publish both exact partitions and their positional audit together."""
    from .vector_io import write_geopackage
    import pandas as pd
    products = {}
    for name in ('data', 'rejected'):
        _check_cancel(cancel)
        path = work / (name + '.gpkg')
        write_geopackage(getattr(result, name), path, layer='features',
                         types=result.summary['source_attribute_types'], cancel=cancel)
        products[name] = path
    _check_cancel(cancel)
    report = result.report
    report.to_csv(work / 'report.csv', index=False, encoding='utf-8-sig')
    # Identity labels must not be inferred as floats or missing-value tokens by
    # the desktop table viewer; typed originals also live in the JSON audit.
    labels = [name for name in ('source_index', 'source_id') if name in report]
    types = {}
    for name in report:
        dtype = report[name].dtype
        types[name] = ('string' if name in labels else 'boolean' if pd.api.types.is_bool_dtype(dtype)
                       else 'Int64' if pd.api.types.is_integer_dtype(dtype) else 'string')
    save_json(dict(schema='cartomize.table.v1', types=types, label_columns=labels),
              work / 'report.csv.schema.json')
    records = []
    for position, row in enumerate(report.itertuples(index=False, name=None)):
        if position % 1024 == 0:
            _check_cancel(cancel)
        records.append({name: _selection_audit_value(value, identity=name in labels)
                        for name, value in zip(report.columns, row)})
    save_json(dict(schema='cartomize.vector_selection.audit.v1',
                   row_numbering='zero_based_source_order',
                   columns={name: str(report[name].dtype) for name in report},
                   records=records), work / 'audit.json')
    save_json(result.summary, work / 'summary.json')
    products.update(report=work / 'report.csv', audit=work / 'audit.json', summary=work / 'summary.json')
    _check_cancel(cancel)
    return products


def _write_vector_tabulation(result, work, *, cancel=None, progress=None):
    """Publish all area products after exact vector and table readback."""
    return _write_verified_vector_tables(result, work,
        vector_names=('data', 'zones', 'gaps', 'overlaps'),
        table_names=('table', 'matrix', 'categories'),
        audit_schema='cartomize.vector_tabulation.audit.v1',
        error_label='Area table', cancel=cancel, progress=progress)


def _write_vector_rings(result, work, *, cancel=None, progress=None):
    """Publish the rings, source registry and balances as one verified result."""
    return _write_verified_vector_tables(result, work,
        vector_names=('data', 'sources'), table_names=('table', 'balances'),
        audit_schema='cartomize.vector_rings.audit.v1',
        error_label='Ring table', cancel=cancel, progress=progress)


def _write_verified_vector_tables(result, work, *, vector_names, table_names,
                                  audit_schema, error_label, cancel=None, progress=None):
    """Share exact vector/CSV publication between tabulation and distance-ring results."""
    import hashlib
    import pandas as pd
    from .vector_io import write_geopackage

    products = {}
    tables = {}
    verified = {}
    steps = len(vector_names) + len(table_names) + 2

    def advance(step):
        _check_cancel(cancel)
        if progress is not None:
            progress(8000 + 2000 * step // steps, 10000)
        _check_cancel(cancel)

    advance(0)
    for number, name in enumerate(vector_names, 1):
        data = getattr(result, name)
        path = work / (name + '.gpkg')
        write_geopackage(data, path, layer='features', cancel=cancel)
        products[name] = path
        tables[name] = pd.DataFrame(data.drop(columns=data.geometry.name))
        verified[path.name] = dict(rows=len(data), sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                                   verification='exact_attributes_geometry_and_crs')
        advance(number)
    for number, name in enumerate(table_names, len(vector_names) + 1):
        data = getattr(result, name)
        path = work / (name + '.csv')
        types = {}
        for column in data:
            dtype = data[column].dtype
            types[column] = ('boolean' if pd.api.types.is_bool_dtype(dtype)
                             else 'Int64' if pd.api.types.is_integer_dtype(dtype)
                             else 'Float64' if pd.api.types.is_float_dtype(dtype) else 'string')
        labels = [column for column in data if types[column] == 'string']
        data.to_csv(path, index=False, encoding='utf-8-sig')
        save_json(dict(schema='cartomize.table.v1', types=types, label_columns=labels,
                       area_unit=result.summary['area_unit'],
                       measurement_crs=result.summary['measurement_crs']),
                  path.with_suffix('.csv.schema.json'))
        _check_cancel(cancel)
        # Pandas' nullable Float64 parser can bypass the C round-trip converter.
        # Parse native doubles first, then restore nullability without changing
        # the values; exact publication verification must remain exact.
        read_types = {column: 'float64' if dtype == 'Float64' else dtype
                      for column, dtype in types.items()}
        reopened = pd.read_csv(path, sep=',', engine='c', float_precision='round_trip',
                               encoding='utf-8-sig', dtype=read_types, keep_default_na=False,
                               na_values={column: [''] for column in data if column not in labels})
        reopened = reopened.astype({column: dtype for column, dtype in types.items()
                                    if dtype == 'Float64'})
        try:
            pd.testing.assert_frame_equal(reopened, data.reset_index(drop=True),
                                          check_dtype=False, check_exact=True)
        except AssertionError as error:
            raise ValueError(error_label + ' readback differs from the computed values: ' + name) from error
        tables[name] = data
        products[name] = path
        verified[path.name] = dict(rows=len(data), sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                                   verification='exact_labels_and_numeric_values')
        advance(number)
    records = {}
    for name, table in tables.items():
        rows = []
        for position, row in enumerate(table.itertuples(index=False, name=None)):
            if position % 1024 == 0:
                _check_cancel(cancel)
            rows.append({column: _selection_audit_value(value) for column, value in zip(table.columns, row)})
        records[name] = dict(columns={column: str(table[column].dtype) for column in table}, records=rows)
    save_json(dict(schema=audit_schema,
                   area_unit=result.summary['area_unit'], measurement_crs=result.summary['measurement_crs'],
                   label_encoding='canonical_text_with_explicit_type',
                   verified_files=verified, tables=records), work / 'audit.json')
    products['audit'] = work / 'audit.json'
    advance(steps - 1)
    save_json(result.summary, work / 'summary.json')
    products['summary'] = work / 'summary.json'
    advance(steps)
    return products


def operation_catalog():
    """Machine-readable operator names, parameter defaults and output types."""
    rows=[]
    for key,spec in _catalog().items():
        parameters=[]
        for name,p in inspect.signature(spec['function']).parameters.items():
            if (name=='how' and key in {'vector.intersection','vector.union','vector.difference','vector.symmetric_difference'}) or name in _HIDDEN or p.kind in (p.VAR_POSITIONAL,p.VAR_KEYWORD):continue
            required=p.default is p.empty
            parameters.append(dict(name=name,required=required,default=None if required else json_value(p.default)))
        products=['primary']
        if key in BLOCK_OPERATIONS:
            for name,default in dict(execution='threads',scheduler_address=None).items():parameters.append(dict(name=name,required=False,default=default))
        if key in CUDA_OPERATIONS:parameters.append(dict(name='device',required=False,default='cpu'))
        if key=='hydrology':products+=['filled','direction','accumulation','streams','watersheds']
        if key=='imagery.audit':products+=['coverage','gaps']
        if key=='imagery.preprocess':products+=['audit','coverage','gaps','preparation','multiband','source_index','composition','report']
        if key=='prepare':products+=['result_source_index']
        if key=='classify':products+=['classification','confidence']
        if key in VECTOR_QUALITY_OPERATIONS:
            products += ['data', 'report', 'summary', 'issues', 'rejected']
        if key in {'vector.audit_geometries', 'vector.repair_geometries'}:
            products += ['before']
        if key == 'vector.reproject_batch':
            products += ['manifest', 'report']
        if key == 'vector.merge_layers':
            products += ['data', 'manifest', 'report', 'issues']
        if key in {'vector.convert', 'raster.convert'}:
            products += ['data', 'manifest', 'report']
        if key == 'vector.extract_features':
            products += ['data', 'rejected', 'report', 'audit', 'summary']
        if key == 'vector.tabulate_area':
            products += ['data', 'table', 'matrix', 'zones', 'categories', 'gaps', 'overlaps', 'audit', 'summary']
        if key == 'vector.buffer_rings':
            products += ['data', 'table', 'sources', 'balances', 'audit', 'summary']
        if key=='classify':
            from .classification import fit_classifier
            present={p['name'] for p in parameters}
            for name,p in inspect.signature(fit_classifier).parameters.items():
                if name not in present and name not in _HIDDEN:parameters.append(dict(name=name,required=p.default is p.empty,default=None if p.default is p.empty else json_value(p.default)))
        rows.append(dict(id=key,label=spec['label'],tool=spec['tool'],output=spec['output'],parameters=parameters,products=products))
    return rows


def operation_spec(name):
    try:return next(row for row in operation_catalog() if row['id']==name)
    except StopIteration:raise ValueError('Opération non enregistrée : '+str(name)) from None


def validate_parameters(operation,parameters):
    spec=_catalog().get(operation)
    if spec is None:raise ValueError('Opération non enregistrée : '+str(operation))
    if not isinstance(parameters,dict):raise ValueError('Les paramètres doivent être un objet.')
    forbidden=set(parameters)&(_HIDDEN|{'function','backend','scheduler'})
    if forbidden:raise ValueError('Paramètres réservés : '+', '.join(sorted(forbidden)))
    signature=inspect.signature(spec['function'])
    allowed={p.name for p in signature.parameters.values() if p.kind not in (p.VAR_KEYWORD,p.VAR_POSITIONAL)}
    # **options only conveys the documented block-engine options, never arbitrary arguments.
    if 'options' in signature.parameters:allowed.update(_ENGINE)
    if operation in BLOCK_OPERATIONS:allowed.update({'execution','scheduler_address'})
    if operation in CUDA_OPERATIONS:allowed.add('device')
    if operation=='classify':
        from .classification import fit_classifier
        allowed.update(set(inspect.signature(fit_classifier).parameters)-_HIDDEN)
    if operation in {'vector.intersection','vector.union','vector.difference','vector.symmetric_difference'}:allowed.discard('how')
    unknown=set(parameters)-allowed
    if unknown:raise ValueError('Paramètres inconnus : '+', '.join(sorted(unknown)))
    supplied=dict(parameters)
    if operation=='classify' and supplied.get('model'):supplied.setdefault('training',None)
    if 'destination' in signature.parameters:supplied['destination']='output'
    try:signature.bind(**supplied)
    except TypeError as exc:raise ValueError(str(exc)) from None
    return spec


def _paths(value):
    if isinstance(value,(str,Path)) and not str(value).startswith('@'):
        try:
            path=Path(value)
            if path.is_file():yield path.resolve()
        except (OSError,ValueError):pass
    elif isinstance(value,dict):
        for item in value.values():yield from _paths(item)
    elif isinstance(value,(tuple,list)):
        for item in value:yield from _paths(item)


def execute_operation(operation,parameters,destination,*,workers=1,block_size=512,memory_limit_mb=512,execution='threads',scheduler_address=None,device='cpu',progress=None,cancel=None):
    """Run one registered operator and return a reopenable product record."""
    spec=validate_parameters(operation,parameters);_check_cancel(cancel)
    sources=list(_paths(parameters));destination=Path(destination).resolve()
    if any(p==destination or destination in p.parents for p in sources):
        raise ValueError('Le dossier de sortie contient une source.')
    with new_directory(destination) as work:
        import geopandas as gpd
        import pandas as pd
        p=dict(parameters);function=spec['function'];signature=inspect.signature(function)
        if operation in BLOCK_OPERATIONS:
            p.setdefault('execution',execution);p.setdefault('scheduler_address',scheduler_address)
        if operation in CUDA_OPERATIONS:p.setdefault('device',device)
        if operation=='raster.reclassify':p['mapping']={float(k):v for k,v in p['mapping'].items()}
        # JSON raster assets use [path, band], accepted by the array engine.
        if 'destination' in signature.parameters:
            p['destination']=work/'products' if operation in {'classify','cluster','hydrology','stac.download','imagery.audit','imagery.preprocess','vector.reproject_batch','vector.merge_layers','vector.convert','raster.convert'} else work/'result.tif'
        for name,value in [('workers',workers),('block_size',block_size),('memory_limit_mb',memory_limit_mb)]:
            if 'options' in signature.parameters or name in signature.parameters or operation=='classify' and name=='workers':p.setdefault(name,value)
        if operation=='classify' and p.get('model'):p.setdefault('training',None)
        for name,value in [('progress',progress),('cancel',cancel)]:
            if name in signature.parameters or 'options' in signature.parameters:p[name]=value
        if operation in {'vector.tabulate_area', 'vector.buffer_rings'} and progress is not None:
            p['progress'] = lambda done, total: progress(int(8000 * done / max(total, 1)), 10000)
        from .imagery_automatic import ImageryCoverageError, diagnostic_destination
        try:
            result=function(**p)
        except ImageryCoverageError as exc:
            # The operation directory is still temporary here. Keep the
            # diagnostic outside it before rollback removes all science files.
            raise exc.preserve(diagnostic_destination(destination),cancel=cancel) from None
        _check_cancel(cancel)
        from .vector_quality_result import VectorQualityResult
        from .vector_reprojection import ReprojectedBatch
        from .vector_merge import MergedVectors
        from .vector_conversion import ConvertedVector
        from .raster_conversion import ConvertedRaster
        from .vector_selection import VectorSelectionResult
        from .vector_tabulation import AreaTabulationResult
        from .vector_rings import BufferRingsResult
        quality_products = None
        reprojection_products = None
        merge_products = None
        conversion_products = None
        selection_products = None
        tabulation_products = None
        rings_products = None
        if isinstance(result, BufferRingsResult):
            rings_products = _write_vector_rings(result, work, cancel=cancel, progress=progress)
            primary = rings_products['data']
        elif isinstance(result, AreaTabulationResult):
            tabulation_products = _write_vector_tabulation(result, work, cancel=cancel, progress=progress)
            primary = tabulation_products['data']
        elif isinstance(result, VectorSelectionResult):
            selection_products = _write_vector_selection(result, work, cancel=cancel)
            primary = selection_products['data']
        elif isinstance(result, VectorQualityResult):
            quality_products = _write_vector_quality(result, work, cancel=cancel)
            primary = quality_products['issues' if operation == 'vector.audit_geometries' else 'data']
        elif isinstance(result, ReprojectedBatch):
            primary = result.manifest
            reprojection_products = {'manifest': result.manifest, 'report': result.report, **result.layers}
        elif isinstance(result, MergedVectors):
            primary = result.data
            merge_products = {key: getattr(result, key) for key in ('data', 'manifest', 'report', 'issues')}
        elif isinstance(result, (ConvertedVector, ConvertedRaster)):
            primary = result.data
            conversion_products = {key: getattr(result, key) for key in ('data', 'manifest', 'report')}
        elif isinstance(result,gpd.GeoDataFrame):
            primary=work/'result.gpkg'
            from .vector_io import write_geopackage
            write_geopackage(result, primary, layer='result', cancel=cancel)
        elif isinstance(result,(pd.DataFrame,pd.Series)):
            primary=work/'result.csv';result.to_csv(primary,index=True)
        elif isinstance(result,dict):
            save_json(result,work/'result.json')
            primary=Path(result['path']) if spec['output']=='raster' and 'path' in result else work/'result.json'
        elif isinstance(result,(str,Path)):primary=Path(result)
        else:raise ValueError('Type de produit inattendu pour '+operation)
        if not primary.is_file():raise RuntimeError('Le traitement n’a pas créé son produit.')
        files=[str(destination/p.relative_to(work)) for p in sorted(work.rglob('*')) if p.is_file()]
        record=dict(schema='cartomize.operation.result.v1',operation=operation,
                    primary=str(destination/primary.relative_to(work)),kind=spec['output'],files=files)
        metadata=getattr(result,'attrs',{}).get('cartomize')
        if metadata is not None:record['metadata']=json_value(metadata)
        products={'primary':record['primary']}
        if rings_products is not None:
            products.update({key: str(destination / path.relative_to(work))
                             for key, path in rings_products.items()})
            record['metadata'] = json_value(result.summary)
        elif tabulation_products is not None:
            products.update({key: str(destination / path.relative_to(work))
                             for key, path in tabulation_products.items()})
            record['metadata'] = json_value(result.summary)
        elif selection_products is not None:
            products.update({key: str(destination / path.relative_to(work))
                             for key, path in selection_products.items()})
            record['metadata'] = json_value(result.summary)
        elif quality_products is not None:
            products.update({key: str(destination / path.relative_to(work))
                             for key, path in quality_products.items()})
            record['metadata'] = json_value(result.summary)
        elif reprojection_products is not None:
            products.update({key: str(destination / path.relative_to(work))
                             for key, path in reprojection_products.items()})
            record['metadata'] = {key: result.summary[key] for key in
                                  ('status', 'target_crs', 'layer_count', 'feature_count')}
        elif merge_products is not None:
            products.update({key: str(destination / path.relative_to(work))
                             for key, path in merge_products.items()})
            record['metadata'] = {key: result.summary[key] for key in
                                  ('status', 'target_crs', 'source_count', 'feature_count',
                                   'provenance_columns', 'conversion_error_count')}
        elif conversion_products is not None:
            products.update({key: str(destination / path.relative_to(work))
                             for key, path in conversion_products.items()})
            record['metadata'] = json_value(result.summary)
        elif operation=='imagery.preprocess':
            document=json.loads(primary.read_text(encoding='utf-8'))
            record['metadata']={key:document[key] for key in
                ('status','usable_percent','threshold_met','allow_partial','coverage_threshold',
                 'selected_scene_ids','mosaic') if key in document}
            def named_product(name,value):
                if value is None:return
                path=Path(value)
                if not path.is_file():raise RuntimeError('Produit du prétraitement absent : '+name)
                products[name]=str(destination/path.relative_to(work))
            for key in ('audit','coverage','gaps','preparation'):
                named_product(key,document.get(key))
            prepared=document.get('products',[])
            for number,item in enumerate(prepared,1):
                prefix='' if len(prepared)==1 else f'product_{number}_'
                for key in ('multiband','source_index','composition','report'):
                    named_product(prefix+key,item.get(key))
                for index,band in item.get('bands',{}).items():
                    named_product(prefix+'band_'+str(index),band['path'])
        else:
            for path in sorted(work.rglob('*')):
                if path.is_file() and path.suffix.lower() in {'.tif','.gpkg','.csv'}:
                    key=path.stem
                    if key in products and products[key]!=str(destination/path.relative_to(work)):raise ValueError('Produits intermédiaires de même nom : '+key)
                    products[key]=str(destination/path.relative_to(work))
        record['products']=products
        from .storage import relocate_products
        save_json(record,work/'operation.json')
        relocate_products(work,destination)
        record=json.loads((work/'operation.json').read_text(encoding='utf-8'))
        _check_cancel(cancel)
    return record
