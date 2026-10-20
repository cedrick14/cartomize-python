"""Executable comparisons on external project data, not synthetic fixtures.

References use direct GeoPandas, Shapely, NumPy and Rasterio operations.
GeoPandas/Shapely share underlying engines with Cartomize: these checks
validate integration and invariants, not independent algorithm certification.
"""
from __future__ import annotations

import argparse
import ast
from contextlib import contextmanager
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import traceback

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('MPLBACKEND', 'Agg')

import geopandas as gpd
from geopandas.testing import assert_geodataframe_equal
import numpy as np
import pandas as pd
import rasterio
from rasterio.mask import mask as rio_mask
from rasterio.warp import reproject as rio_reproject, calculate_default_transform, Resampling
from shapely.geometry import Point
import cartomize as cm
from cartomize.vector_workflows import (select_attributes, select_location, geometry_operation,
                                       spatial_summary, join_attributes, latest_records)
from real_project_data import prepare, inventory, TUTORIAL_REF


def serial(value):
    if isinstance(value, dict):
        return {str(k):serial(v) for k,v in value.items()}
    if isinstance(value, (list,tuple)):
        return [serial(v) for v in value]
    if isinstance(value, np.generic):
        return serial(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if isinstance(value, Path):
        return str(value)
    return value


class Audit:
    def __init__(self, output):
        self.output = output
        self.rows = []
        self.metrics = {}

    @contextmanager
    def step(self, project, name, reference, access='API'):
        row = dict(project=project, step=name, reference=reference, access=access)
        start = time.perf_counter()
        try:
            yield row
            row['status'] = 'passed'
        except Exception as exc:
            row.update(status='failed', error=str(exc), traceback=traceback.format_exc())
        row['seconds'] = round(time.perf_counter()-start,3)
        self.rows.append(serial(row))
        print(json.dumps(serial(row),ensure_ascii=False),flush=True)

    def finish(self, provenance):
        try:
            commit = subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
        except Exception:
            commit = 'unknown'
        scope = [
            {'chapter':'01', 'topic':'Import, attributs, objets GeoPandas, export', 'coverage':'tested'},
            {'chapter':'02', 'topic':'SCR, reprojection, unités, géométries dérivées', 'coverage':'tested'},
            {'chapter':'03', 'topic':'Prédicats, sélections, jointures et agrégations spatiales', 'coverage':'tested'},
            {'chapter':'04', 'topic':'Tampons, intersections, dissolution, occupation du sol', 'coverage':'tested'},
            {'chapter':'05', 'topic':'Cartes statiques thématiques et export', 'coverage':'tested'},
            {'chapter':'05', 'topic':'Folium, fonds contextily, Cartopy, geoplot et ipyleaflet', 'coverage':'external_libraries_not_validated'},
            {'chapter':'06', 'topic':'Dask-GeoPandas distribué pour les vecteurs', 'coverage':'not_implemented_as_native_tool'},
            {'chapter':'case-conflict-mapping', 'topic':'Mines, zones protégées, distances, couronnes et effectifs', 'coverage':'tested'},
            {'chapter':'case-conflict-mapping', 'topic':'Accès au WFS historique et raster facultatif non livré avec le tutoriel', 'coverage':'not_executed'},
            {'chapter':'Earth Lab', 'topic':'MNS, MNT, hauteur de canopée, changements, masque, statistiques et pente', 'coverage':'tested'},
        ]
        report = {'cartomize':cm.__version__, 'commit':commit, 'python':platform.python_version(),
                  'platform':platform.platform(), 'tutorial_commit':TUTORIAL_REF,
                  'packages':{p:metadata.version(p) for p in ['geopandas','rasterio','numpy','pandas','shapely','PySide6-Essentials']},
                  'method':'Tutorial-derived scenarios on externally sourced datasets. No execution of downloaded notebook code.',
                  'shared_engines':'GeoPandas/GEOS and Rasterio/GDAL are shared; numeric raster references use direct masked array arithmetic.',
                  'passed':sum(r['status']=='passed' for r in self.rows),
                  'failed':sum(r['status']=='failed' for r in self.rows),
                  'metrics':serial(self.metrics), 'steps':self.rows, 'scope':scope,
                  'provenance':provenance}
        self.output.mkdir(parents=True,exist_ok=True)
        (self.output/'validation.json').write_text(json.dumps(serial(report),ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
        pd.DataFrame(self.rows).drop(columns=['traceback'],errors='ignore').to_csv(self.output/'etapes.csv',index=False)
        lines = ['# Validation sur des projets réels', '',
                 f"Cartomize {cm.__version__} | {report['platform']} | Python {report['python']}",
                 f"Commit : `{commit}`", '',f"{report['passed']} étapes réussies ; {report['failed']} échecs.", '',
                 'Les résultats décrivent les instantanés historiques des jeux de formation, pas leur état actuel.', '',
                 '## Correspondance des étapes', '', '| Projet | Étape | Accès | Résultat |', '|---|---|---|---|']
        lines += [f"| {r['project']} | {r['step']} | {r['access']} | {r['status']} |" for r in self.rows]
        lines += ['', '## Périmètre', '', '| Chapitre | Fonction | Couverture |', '|---|---|---|']
        lines += [f"| {r['chapter']} | {r['topic']} | {r['coverage']} |" for r in scope]
        lines += ['', '## Indicateurs calculés', '', '```json', json.dumps(serial(self.metrics),ensure_ascii=False,indent=2), '```', '',
                  '## Interprétation', '',
                  'Les contrôles comparent les mêmes données et les mêmes conventions de SCR, masque et prédicats. '
                  'Ils ne constituent pas une certification indépendante de GeoPandas, GEOS ou GDAL. '
                  'Une variation altimétrique ne prouve pas à elle seule un effet causal de la crue ; '
                  'la précision verticale et le recalage doivent être étudiés avant une estimation scientifique des volumes.', '',
                  '## Sources', '',
                  f'https://github.com/jorisvandenbossche/geopandas-tutorial/tree/{TUTORIAL_REF}',
                  'https://www.earthdatascience.org/courses/use-data-open-source-python/intro-raster-data-python/raster-data-processing/crop-raster-data-with-shapefile-in-python/',
                  '', 'Les fichiers originaux ne sont pas redistribués dans ce dossier. Le manifeste fournit les liens et empreintes SHA-256.']
        (self.output/'RAPPORT.md').write_text('\n'.join(lines),encoding='utf-8')
        print(json.dumps({'passed':report['passed'],'failed':report['failed'],'metrics':serial(self.metrics)},ensure_ascii=False),flush=True)
        return report['failed'] == 0


def same(left,right):
    assert_geodataframe_equal(left.reset_index(drop=True),right.reset_index(drop=True),
                             check_dtype=False,check_less_precise=True,normalize=True)


def save(frame,path):
    frame.to_file(path,driver='GPKG',index=False)
    return path


def raster_equals(path,expected,reference,atol=1e-5):
    expected = np.ma.masked_invalid(expected)
    with rasterio.open(path) as dst:
        actual = np.ma.masked_invalid(dst.read(1,masked=True))
        assert dst.crs == reference['crs'] and dst.transform == reference['transform']
        assert actual.shape == expected.shape
        np.testing.assert_array_equal(np.ma.getmaskarray(actual),np.ma.getmaskarray(expected))
        values = expected.compressed()
        np.testing.assert_allclose(actual.compressed(),values,rtol=1e-7,atol=atol)
        return {'pixels':int(expected.size), 'valid_pixels':int(expected.count()),
                'maximum_absolute_error':float(np.max(np.abs(actual.compressed()-values))) if values.size else None}


def tutorial_seine(root):
    notebook = json.loads((root/'tutorial/04-spatial-operations-overlays.ipynb').read_text(encoding='utf-8'))
    for cell in notebook['cells']:
        source = ''.join(cell['source'])
        if cell['cell_type']=='code' and 's_seine =' in source:
            for node in ast.walk(ast.parse(source)):
                if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=='from_features':
                    features = ast.literal_eval(node.args[0])
                    return gpd.GeoDataFrame.from_features(features,crs=4326)
    raise ValueError('The pinned tutorial no longer contains the Seine geometry')


def vector_cases(root,out,audit):
    paths = {}
    for name in ('ne_110m_admin_0_countries','ne_110m_populated_places','ne_50m_rivers_lake_centerlines','paris_land_use','cod_conservation'):
        paths[name] = next((root/'geopandas'/name).rglob('*.shp'))
    for name in ('paris_districts.geojson','paris_bike_stations.geojson','paris_trees.gpkg','cod_mines_curated_all_opendata_p_ipis.geojson'):
        paths[Path(name).stem] = root/'geopandas'/name
    data = {}
    for name,path in paths.items():
        with audit.step('Importation',name,'01 : geopandas.read_file') as record:
            data[name] = cm.read_file(path)
            same(data[name],gpd.read_file(path))
            record.update(features=len(data[name]),crs=str(data[name].crs),fields=len(data[name].columns)-1)
    countries=data['ne_110m_admin_0_countries'];cities=data['ne_110m_populated_places']
    districts=data['paris_districts'];stations=data['paris_bike_stations'];trees=data['paris_trees']
    land=data['paris_land_use'];raw_mines=data['cod_mines_curated_all_opendata_p_ipis'];parks=data['cod_conservation']
    audit.metrics['inputs']={key:len(value) for key,value in data.items()}
    with audit.step('Monde','Filtrer les pays africains','01 : sélection attributaire') as record:
        africa=select_attributes(countries,'continent','eq','Africa')
        same(africa,countries[countries.continent=='Africa'])
        record['features']=len(africa)
    with audit.step('Monde','Dissoudre les continents et sommer la population','04 : dissolve + agrégation'):
        actual=cm.dissolve(countries,by='continent',aggfunc={'pop_est':'sum'})
        expected=countries.dissolve(by='continent',aggfunc={'pop_est':'sum'})
        same(actual,expected)
        assert int(actual.pop_est.sum())==int(countries.pop_est.sum())
    with audit.step('Monde','Attribuer un pays aux villes','03 : jointure spatiale') as record:
        actual=cm.sjoin(cities,countries[['name','geometry']],predicate='within')
        expected=gpd.sjoin(cities,countries[['name','geometry']],predicate='within')
        same(actual,expected);record['matches']=len(actual)
    with audit.step('Paris','Reprojeter les quartiers en Lambert-93','02 : to_crs'):
        districts_m=cm.reproject(districts,2154);stations_m=cm.reproject(stations,2154)
        same(districts_m,districts.to_crs(2154));same(stations_m,stations.to_crs(2154))
        same(cm.reproject(districts_m,4326),districts)
    with audit.step('Paris','Mesurer superficies et périmètres','02 : area / length'):
        np.testing.assert_allclose(cm.area(districts_m,'m2'),districts_m.area,rtol=1e-12)
        np.testing.assert_allclose(cm.length(districts_m,'m'),districts_m.length,rtol=1e-12)
    with audit.step('Paris','Centroïdes, limites, enveloppes et simplification','04 : géométries dérivées'):
        for op in ['centroid','boundary','convex_hull','representative_point','simplify','explode']:
            actual=geometry_operation(districts_m,op,tolerance=10)
            if op=='explode':expected=districts_m.explode(index_parts=False,ignore_index=True)
            else:
                expected=districts_m.copy()
                expected.geometry=(districts_m.geometry.simplify(10,preserve_topology=True) if op=='simplify' else
                                   districts_m.geometry.representative_point() if op=='representative_point' else getattr(districts_m.geometry,op))
            same(actual,expected)
    with audit.step('Paris','Stations par quartier, avec alignement des SCR','03 : sjoin + groupby') as record:
        summary=spatial_summary(districts_m,stations,statistic='count',predicate='within',output_field='stations')
        joined=gpd.sjoin(stations_m,districts_m[['geometry']],predicate='within')
        expected=joined.groupby('index_right').size().reindex(districts_m.index,fill_value=0)
        np.testing.assert_array_equal(summary.stations,expected)
        assert int(summary.stations.sum())==len(joined)
        save(summary,out/'paris_stations_par_quartier.gpkg')
        record['matched_stations']=int(summary.stations.sum())
        audit.metrics['paris_matched_stations']=record['matched_stations']
    with audit.step('Paris','Capacité totale de vélos par quartier','03 : agrégation des attributs'):
        actual=spatial_summary(districts_m,stations,field='bike_stands',statistic='sum',predicate='within',output_field='capacity')
        joined=gpd.sjoin(stations_m,districts_m[['geometry']],predicate='within')
        expected=joined.groupby('index_right').bike_stands.sum().reindex(districts_m.index,fill_value=0)
        np.testing.assert_allclose(actual.capacity,expected)
    with audit.step('Paris','Arbres par quartier','03 : exercice des arbres') as record:
        actual=spatial_summary(districts_m,trees,predicate='within',output_field='trees')
        expected=gpd.sjoin(trees.to_crs(2154),districts_m[['geometry']],predicate='within').groupby('index_right').size().reindex(districts_m.index,fill_value=0)
        np.testing.assert_array_equal(actual.trees,expected)
        record['matched_trees']=int(actual.trees.sum());save(actual,out/'paris_arbres_par_quartier.gpkg')
    seine=tutorial_seine(root).to_crs(2154)
    save(seine,out/'seine_tutoriel.gpkg')
    with audit.step('Paris','Tampon de 150 m autour de la Seine','04 : exercice 1') as record:
        buffered=cm.buffer(seine,150)
        same(buffered,seine.set_geometry(seine.buffer(150)))
        save(buffered,out/'seine_tampon_150m.gpkg');record['metres']=150
    with audit.step('Paris','Quartiers à moins de 150 m de la Seine','04 : exercice 1') as record:
        near=select_location(districts_m,buffered,predicate='intersects')
        expected=districts_m[districts_m.intersects(buffered.geometry.union_all())]
        same(near,expected);record['districts']=len(near);save(near,out/'quartiers_proches_seine.gpkg')
        audit.metrics['districts_near_seine']=len(near)
    with audit.step('Paris','Intersection occupation du sol / quartier Muette','04 : exercices 3 à 5') as record:
        projected=cm.reproject(districts,land.crs)
        muette=select_attributes(projected,'district_name','eq','Muette')
        clipped=cm.clip(land,muette).sort_index()
        expected=gpd.clip(land,muette).sort_index()
        same(clipped,expected)
        clipped['area_m2']=cm.area(clipped,'m2')
        reference_areas=expected.area.groupby(expected['class']).sum().sort_index()
        areas=clipped.groupby('class').area_m2.sum().sort_index()
        np.testing.assert_allclose(areas,reference_areas,rtol=1e-8)
        shares=(100*areas/areas.sum()).rename('percentage')
        np.testing.assert_allclose(shares.sum(),100)
        table=pd.concat([areas.rename('area_m2'),shares],axis=1)
        table.to_csv(out/'muette_occupation_du_sol.csv')
        save(clipped,out/'muette_occupation_du_sol.gpkg')
        record.update(fragments=len(clipped),classes=len(table));audit.metrics['muette_land_use']=table.reset_index().to_dict('records')
    with audit.step('Paris','Superposition sur tous les quartiers','04 : overlay intersection') as record:
        inter=cm.overlay(land,projected[['id','district_name','geometry']],how='intersection',keep_geom_type=True)
        expected=gpd.overlay(land,projected[['id','district_name','geometry']],how='intersection',keep_geom_type=True)
        same(inter,expected)
        sums=inter.assign(area_m2=inter.area).groupby(['id','class']).area_m2.sum().sort_index()
        ref=expected.assign(area_m2=expected.area).groupby(['id','class']).area_m2.sum().sort_index()
        np.testing.assert_allclose(sums,ref,rtol=1e-8)
        sums.to_csv(out/'paris_occupation_par_quartier.csv');record['fragments']=len(inter)
    with audit.step('Paris','Jointure attributaire de la population','01 : pandas merge sur identifiant'):
        population=districts[['id','population']].copy()
        actual=join_attributes(districts[['id','district_name','geometry']],population,left_on='id')
        same(actual,districts[['id','district_name','geometry']].merge(population,on='id',validate='many_to_one'))
        assert int(actual.population.sum())==int(districts.population.sum())
    with audit.step('Paris','Station la plus proche des centroïdes','03 : distances et proximité') as record:
        centroids=geometry_operation(districts_m,'centroid')
        actual=cm.nearest(centroids,stations_m[['geometry']],how='left')
        brute=np.array([stations_m.distance(g).min() for g in centroids.geometry])
        grouped=actual.groupby(level=0).distance_m.min().reindex(centroids.index)
        np.testing.assert_allclose(grouped,brute,rtol=1e-10,atol=1e-7)
        record['maximum_distance_error_m']=float(np.max(np.abs(grouped.to_numpy()-brute)))
    with audit.step('Paris','Carte thématique des stations et export','05 : cartographie',access='API + export'):
        map_=cm.Map(title='Stations de vélos par quartier',crs=2154,credits='Source : jeu de formation GeoPandas, instantané historique')
        map_.add_layer(summary,name='Nombre de stations',column='stations')
        for extension in ('png','pdf','svg'):
            target=out/f'paris_stations.{extension}';map_.export(target,dpi=110)
            assert target.stat().st_size>1000

    selected_columns=['vid','project','visit_date','name','pcode','workers_numb','interference','mineral1','geometry']
    raw_mines=raw_mines[selected_columns]
    with audit.step('RDC','Filtrer les visites IPIS avec effectif positif','cas mines : étape 1') as record:
        filtered=select_attributes(select_attributes(raw_mines,'project','contains','IPIS'),'workers_numb','gt',0)
        baseline=raw_mines[raw_mines.project.str.contains('IPIS',na=False)&(raw_mines.workers_numb>0)]
        same(filtered,baseline);record['visits']=len(filtered)
    with audit.step('RDC','Conserver le dernier relevé complet par site','cas mines : étape 1, variante conservant les lignes') as record:
        last=latest_records(filtered,group_by='pcode',order_by='visit_date')
        expected=filtered.assign(_date=pd.to_datetime(filtered.visit_date,utc=True)).sort_values('_date',kind='stable').drop_duplicates('pcode',keep='last').drop(columns=['_date'])
        same(last,expected)
        assert last.pcode.is_unique
        original_last=baseline.sort_values('visit_date').groupby('pcode',as_index=False).last()
        assert set(last.pcode)==set(original_last.pcode)
        record.update(sites=len(last),semantics='Whole latest records; avoids mixing non-null columns across dates with groupby.last.')
        audit.metrics['ipis_sites']=len(last)
    with audit.step('RDC','Auditer et réparer les géométries des aires protégées','cas mines : contrôle des sources') as record:
        original_invalid=int((~parks.is_valid).sum())
        fixed=cm.make_valid(parks)
        expected=parks.set_geometry(parks.geometry.make_valid())
        same(fixed,expected);assert fixed.is_valid.all()
        record.update(invalid_before=original_invalid,invalid_after=int((~fixed.is_valid).sum()))
        audit.metrics['protected_areas_repaired']=original_invalid
    with audit.step('RDC','Aligner les mines et les aires protégées en UTM 35S','cas mines : conversion des SCR'):
        mines_m=cm.reproject(last,32735);parks_m=cm.reproject(fixed,32735)
        same(mines_m,last.to_crs(32735));same(parks_m,fixed.to_crs(32735))
        parks_m=parks_m[['NOM','geometry']].copy()
    with audit.step('RDC','Sélection des sites dans Kahuzi-Biega','cas mines : étape 2') as record:
        kahuzi=parks_m[parks_m.NOM.astype(str).str.contains('Kahuzi',case=False,na=False)]
        assert len(kahuzi)>0
        actual=select_location(mines_m,kahuzi,predicate='within')
        expected=mines_m[mines_m.within(kahuzi.geometry.union_all())]
        same(actual,expected);record['sites']=len(actual);audit.metrics['sites_kahuzi']=len(actual)
    with audit.step('RDC','Attribuer les sites aux aires protégées','cas mines : étape 3') as record:
        assigned=cm.sjoin(mines_m,parks_m,predicate='within')
        reference=gpd.sjoin(mines_m,parks_m,predicate='within')
        same(assigned,reference)
        record.update(assignments=len(assigned),distinct_sites=int(assigned.pcode.nunique()))
        audit.metrics['sites_in_protected_areas']=int(assigned.pcode.nunique())
    with audit.step('RDC','Effectifs de sites et travailleurs par aire protégée','cas mines : étape 3'):
        counts=spatial_summary(parks_m,mines_m,predicate='within',output_field='sites')
        workers=spatial_summary(counts,mines_m,field='workers_numb',statistic='sum',predicate='within',output_field='workers')
        baseline_counts=reference.groupby('index_right').size().reindex(parks_m.index,fill_value=0)
        baseline_workers=reference.groupby('index_right').workers_numb.sum().reindex(parks_m.index,fill_value=0)
        np.testing.assert_array_equal(workers.sites,baseline_counts)
        np.testing.assert_allclose(workers.workers,baseline_workers)
        workers.drop(columns='geometry').to_csv(out/'rdc_sites_par_aire_protegee.csv',index=False)
        save(workers,out/'rdc_aires_protegees_indicateurs.gpkg')
    with audit.step('RDC','Aire protégée la plus proche, contrôle exhaustif des distances','cas mines : étape 2') as record:
        nearest=cm.nearest(mines_m,parks_m,how='left')
        brute=np.array([parks_m.distance(g).min() for g in mines_m.geometry])
        actual=nearest.groupby(level=0).distance_m.min().reindex(mines_m.index)
        np.testing.assert_allclose(actual,brute,atol=1e-7,rtol=1e-10)
        record.update(sites_checked=len(brute),maximum_distance_error_m=float(np.max(np.abs(actual.to_numpy()-brute))))
    with audit.step('RDC','Couronnes extérieures de 10 km','cas mines : bordures des aires protégées') as record:
        rings=cm.buffer(parks_m,10000)
        rings.geometry=rings.geometry.difference(parks_m.geometry)
        expected=parks_m.set_geometry(parks_m.buffer(10000).difference(parks_m.geometry))
        same(rings,expected)
        assert (rings.intersection(parks_m.geometry).area<.01).all()
        results=cm.sjoin(mines_m,rings,predicate='within')
        same(results,gpd.sjoin(mines_m,expected,predicate='within'))
        record.update(assignments=len(results),distinct_sites=int(results.pcode.nunique()))
        audit.metrics['sites_in_10km_rings']=int(results.pcode.nunique())
    with audit.step('RDC','Carte agrégée des sites par aire protégée','cas mines : visualisation'):
        map_=cm.Map(title='Sites miniers recensés par aire protégée',crs=32735,
                    credits='Sources : IPIS / données de formation GeoPandas. Instantané historique ; pas un inventaire actuel.')
        map_.add_layer(workers,name='Sites recensés',column='sites')
        map_.export(out/'rdc_sites_par_aire.png',dpi=110)
        assert (out/'rdc_sites_par_aire.png').stat().st_size>1000
    return {'districts':save(districts_m,out/'paris_quartiers_l93.gpkg'),
            'stations':save(stations_m,out/'paris_stations_l93.gpkg'),
            'summary':summary,'land':paths['paris_land_use'], 'seine':out/'seine_tutoriel.gpkg'}


def raster_cases(root,out,audit):
    base=root/'earthlab/spatial/boulder-leehill-rd'
    paths={key:base/f'{period}-flood/lidar/{period}_{kind}.tif'
           for key,period,kind in [('dtm','pre','DTM'),('dsm','pre','DSM'),('post_dtm','post','DTM'),('post_dsm','post','DSM')]}
    arrays={}
    with audit.step('LiDAR','Importer quatre MNT/MNS et contrôler les grilles','Earth Lab : ouverture GeoTIFF') as record:
        reference=None
        for name,path in paths.items():
            with rasterio.open(path) as src:
                if reference is None:reference={'crs':src.crs,'transform':src.transform,'shape':src.shape}
                assert (src.crs,src.transform,src.shape)==(reference['crs'],reference['transform'],reference['shape'])
                arrays[name]=np.ma.masked_invalid(src.read(1,masked=True).astype('float64'))
            info=cm.raster.inspect(path);assert (info['height'],info['width'])==reference['shape']
        record.update(shape=list(reference['shape']),pixels=arrays['dtm'].size,crs=str(reference['crs']))
        audit.metrics['lidar_grid']={'width':reference['shape'][1],'height':reference['shape'][0],'pixel_size_m':1}
    chm=out/'canopy_height_pre.tif';postchm=out/'canopy_height_post.tif';diff=out/'terrain_change.tif'
    options=dict(workers=2,block_size=256,memory_limit_mb=256,dtype='float64',overwrite=True)
    with audit.step('LiDAR','Hauteur de canopée avant crue : MNS − MNT','Earth Lab : arithmétique raster') as record:
        cm.calculate('surface - terrain',{'surface':paths['dsm'],'terrain':paths['dtm']},chm,**options)
        expected=arrays['dsm']-arrays['dtm'];record.update(raster_equals(chm,expected,reference))
        audit.metrics['canopy_pre']={'mean_m':float(expected.mean()),'max_m':float(expected.max()),'valid_pixels':int(expected.count())}
    with audit.step('LiDAR','Hauteur de canopée après crue','Earth Lab : arithmétique raster') as record:
        cm.calculate('surface - terrain',{'surface':paths['post_dsm'],'terrain':paths['post_dtm']},postchm,**options)
        record.update(raster_equals(postchm,arrays['post_dsm']-arrays['post_dtm'],reference))
    with audit.step('LiDAR','Variation altimétrique après − avant','Earth Lab : comparaison temporelle') as record:
        cm.calculate('after - before',{'before':paths['dtm'],'after':paths['post_dtm']},diff,**options)
        expected=arrays['post_dtm']-arrays['dtm'];record.update(raster_equals(diff,expected,reference))
        audit.metrics['terrain_change']={'mean_m':float(expected.mean()),'min_m':float(expected.min()),'max_m':float(expected.max()),'valid_pixels':int(expected.count())}
    mask_path=base/'clip-extent.shp';clipped=out/'canopy_clipped.tif'
    with audit.step('LiDAR','Extraire le raster avec le shapefile de la zone d’étude','Earth Lab : crop raster') as record:
        cm.raster.clip(chm,mask_path,clipped,overwrite=True)
        mask_gdf=gpd.read_file(mask_path)
        with rasterio.open(chm) as src:
            expected,transform=rio_mask(src,mask_gdf.to_crs(src.crs).geometry,indexes=1,crop=True,filled=False)
            ref={'crs':src.crs,'transform':transform}
        record.update(raster_equals(clipped,expected,ref))
    with audit.step('LiDAR','Statistiques zonales de la hauteur de canopée','Earth Lab : masque et statistiques') as record:
        zones=gpd.read_file(mask_path);actual=cm.raster.zonal_stats(chm,zones)
        with rasterio.open(chm) as src:
            for i,geom in enumerate(zones.to_crs(src.crs).geometry):
                sample,_=rio_mask(src,[geom],indexes=1,crop=True,filled=False)
                values=np.ma.masked_invalid(sample).compressed().astype('float64')
                assert actual.iloc[i]['count']==len(values)
                for column,func in [('min',np.min),('max',np.max),('mean',np.mean),('sum',np.sum),('std',np.std)]:
                    np.testing.assert_allclose(actual.iloc[i][column],func(values),rtol=1e-10,atol=1e-8)
        actual.drop(columns='geometry').to_csv(out/'canopy_zonal_statistics.csv',index=False)
        record['zones']=len(actual)
    classes=[]
    for period,path,array in [('pre',chm,arrays['dsm']-arrays['dtm']),('post',postchm,arrays['post_dsm']-arrays['post_dtm'])]:
        with audit.step('LiDAR',f'Classes de hauteur {period} : <2, 2–10, ≥10 m','Earth Lab : classification par seuils') as record:
            target=out/f'canopy_classes_{period}.tif';classes.append(target)
            cm.calculate('where(height < 2, 0, where(height < 10, 1, 2))',{'height':path},target,**options)
            expected=np.ma.array(np.where(array.data<2,0,np.where(array.data<10,1,2)),mask=np.ma.getmaskarray(array))
            record.update(raster_equals(target,expected,reference))
    with audit.step('LiDAR','Superficies exactes par classe de hauteur','Earth Lab : répartition spatiale'):
        actual=cm.raster.class_areas(classes[0],unit='m2')
        with rasterio.open(classes[0]) as src:
            values,counts=np.unique(src.read(1,masked=True).compressed(),return_counts=True)
        np.testing.assert_array_equal(actual['class'],values);np.testing.assert_array_equal(actual.pixels,counts)
        np.testing.assert_array_equal(actual.area_m2,counts)
        actual.to_csv(out/'canopy_class_areas.csv',index=False)
        audit.metrics['canopy_class_areas']=actual.to_dict('records')
    with audit.step('LiDAR','Matrice de transition avant / après','Earth Lab : comparaison des classes'):
        actual=cm.raster.change_matrix(*classes)
        with rasterio.open(classes[0]) as a,rasterio.open(classes[1]) as b:
            x=a.read(1,masked=True);y=b.read(1,masked=True)
            valid=~np.ma.getmaskarray(x)&~np.ma.getmaskarray(y)
            pairs,counts=np.unique(np.column_stack([x.data[valid],y.data[valid]]),axis=0,return_counts=True)
        expected=pd.DataFrame({'from':pairs[:,0],'to':pairs[:,1],'pixels':counts})
        pd.testing.assert_frame_equal(actual,expected,check_dtype=False)
        actual.to_csv(out/'canopy_transition_matrix.csv',index=False)
        assert int(actual.pixels.sum())==int(valid.sum())
    with audit.step('LiDAR','Reprojection vers une grille de 5 m','Earth Lab : alignement et rééchantillonnage') as record:
        target=out/'terrain_5m.tif';cm.raster.reproject(paths['dtm'],target,32613,resolution=5,resampling='bilinear',overwrite=True)
        with rasterio.open(paths['dtm']) as src:
            transform,w,h=calculate_default_transform(src.crs,32613,src.width,src.height,*src.bounds,resolution=5)
            reference_values=np.full((h,w),np.nan)
            rio_reproject(rasterio.band(src,1),reference_values,src_transform=src.transform,src_crs=src.crs,
                          src_nodata=src.nodata,dst_transform=transform,dst_crs=32613,dst_nodata=np.nan,resampling=Resampling.bilinear)
        record.update(raster_equals(target,np.ma.masked_invalid(reference_values),{'crs':rasterio.crs.CRS.from_epsg(32613),'transform':transform},atol=1e-5))
    with audit.step('LiDAR','Pente de Horn sur le MNT, fenêtres et bords','Dérivée topographique : référence matricielle explicite') as record:
        slope=out/'terrain_slope.tif';cm.terrain(paths['dtm'],slope,products=['slope'],**options)
        z=arrays['dtm'];v=z.filled(np.nan)
        east=((v[:-2,2:]+2*v[1:-1,2:]+v[2:,2:])-(v[:-2,:-2]+2*v[1:-1,:-2]+v[2:,:-2]))/8
        north=((v[:-2,:-2]+2*v[:-2,1:-1]+v[:-2,2:])-(v[2:,:-2]+2*v[2:,1:-1]+v[2:,2:]))/8
        expected=np.full(z.shape,np.nan);expected[1:-1,1:-1]=np.degrees(np.arctan(np.hypot(east,north)))
        from scipy.ndimage import minimum_filter
        valid=minimum_filter((~np.ma.getmaskarray(z)).astype('uint8'),size=3,mode='constant',cval=0).astype(bool)
        expected[~valid]=np.nan
        record.update(raster_equals(slope,np.ma.masked_invalid(expected),reference))
    with audit.step('LiDAR','Exporter une carte des variations altimétriques','Earth Lab : visualisation des différences'):
        map_=cm.Map(title='Variation altimétrique après − avant',crs=32613,
                    credits='Source : Earth Lab / Colorado Flood. Différences brutes ; incertitude verticale non évaluée.')
        map_.add_layer(diff,name='Variation (m)',kind='raster',cmap='RdBu_r')
        map_.export(out/'terrain_change.png',dpi=110)
        assert (out/'terrain_change.png').stat().st_size>1000
    return {'chm':chm,'dem':paths['dtm'],'mask':mask_path,'camera':base/'pre-flood/camera/preCamera_Comp.tif'}


def gui_cases(vectors,rasters,out,audit):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt,QSettings
    from PySide6.QtTest import QTest
    from cartomize.desktop import CartomizeWindow
    app=QApplication.instance() or QApplication([])
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat,QSettings.Scope.UserScope,str(out/'preferences'))
    window=CartomizeWindow();window.show();QTest.qWait(80)
    def finish(timeout=120):
        deadline=time.monotonic()+timeout
        while window.thread is not None and time.monotonic()<deadline:
            QTest.qWait(20)
        assert window.thread is None, 'Processing did not finish'
        assert window.status.text().startswith('Traitement terminé'),window.status.text()
    def execute(op,source,destination,**parameters):
        window.select_tool('vector');page=window.tool('vector')
        index=page.operation.findData(op);assert index>=0,op
        page.operation.setCurrentIndex(index);page.source.edit.setText(str(source));page.output.edit.setText(str(destination))
        for key,value in parameters.items():
            widget=getattr(page,key)
            if hasattr(widget,'edit'):widget.edit.setText(str(value))
            elif hasattr(widget,'setCurrentText'):widget.setCurrentText(str(value))
            elif hasattr(widget,'setValue'):widget.setValue(value)
            else:widget.setText(str(value))
        QTest.mouseClick(window.run_button,Qt.MouseButton.LeftButton);finish()
        assert destination.is_file()
        return cm.read_file(destination)
    try:
        with audit.step('Interface','Importer les vrais GeoPackage et visualiser les données','Importation et affichage Qt',access='GUI'):
            window.project_explorer.open_path(vectors['districts']);window.project_explorer.open_path(vectors['stations'])
            app.processEvents();assert len(window.results)>=2
        with audit.step('Interface','Sélection attributaire du quartier Muette','Même résultat que GeoPandas',access='GUI'):
            actual=execute('select_attributes',vectors['districts'],out/'gui_muette.gpkg',attribute='district_name',filter_value='Muette')
            expected=gpd.read_file(vectors['districts']);expected=expected[expected.district_name=='Muette']
            same(actual,expected)
        with audit.step('Interface','Tampon de 150 m sur la Seine','Même géométrie que GeoPandas',access='GUI'):
            actual=execute('buffer',vectors['seine'],out/'gui_seine_buffer.gpkg',distance=150)
            source=gpd.read_file(vectors['seine']);same(actual,source.set_geometry(source.buffer(150)))
        with audit.step('Interface','Sélection des quartiers voisins de la Seine','Même identifiants que GeoPandas',access='GUI'):
            actual=execute('select_location',vectors['districts'],out/'gui_near_seine.gpkg',secondary=out/'gui_seine_buffer.gpkg',predicate='intersects')
            source=gpd.read_file(vectors['districts']);mask=gpd.read_file(out/'gui_seine_buffer.gpkg')
            same(actual,source[source.intersects(mask.geometry.union_all())])
        with audit.step('Interface','Compter les stations par quartier','Même effectifs que sjoin + groupby',access='GUI'):
            page=window.tool('vector');page.summary_stat.setCurrentIndex(page.summary_stat.findData('count'))
            actual=execute('spatial_summary',vectors['districts'],out/'gui_counts.gpkg',secondary=vectors['stations'],predicate='within',result_field='stations')
            same(actual,vectors['summary'])
        with audit.step('Interface','Exécuter un découpage raster sur le shapefile réel','Même pixels et masque que Rasterio',access='GUI'):
            window.select_tool('raster');page=window.tool('raster')
            page.operation.setCurrentIndex(page.operation.findData('clip'))
            page.source.edit.setText(str(rasters['chm']));page.secondary.edit.setText(str(rasters['mask']))
            target=out/'gui_canopy_clip.tif';page.output.edit.setText(str(target))
            QTest.mouseClick(window.run_button,Qt.MouseButton.LeftButton);finish()
            with rasterio.open(rasters['chm']) as src:
                expected,transform=rio_mask(src,gpd.read_file(rasters['mask']).to_crs(src.crs).geometry,indexes=1,crop=True,filled=False)
                ref={'crs':src.crs,'transform':transform}
            raster_equals(target,expected,ref)
        with audit.step('Interface','Afficher une orthophoto de 128 millions de pixels','Lecture asynchrone de la zone visible',access='GUI') as record:
            doc=window.workspace.open_result(str(rasters['camera']))
            deadline=time.monotonic()+90
            while not doc.canvas.last_render and time.monotonic()<deadline:QTest.qWait(25)
            assert doc.canvas.last_render,doc.note.text()
            with rasterio.open(rasters['camera']) as src:record.update(width=src.width,height=src.height,bands=src.count)
            window.resize(1500,950)
            for theme in ['light','dark']:
                window.theme_selector.setCurrentIndex(window.theme_selector.findData(theme));QTest.qWait(180)
                assert window.grab().save(str(out/f'interface_orthophoto_{theme}.png'))
        with audit.step('Interface','Enregistrer et rouvrir le projet réel','Sessions et conservation des données',access='GUI'):
            session=out/'analyse_reelle.cartomize.json';window.save_session_file(session)
            window.open_session_file(session);assert window.session_path==str(session)
    finally:
        if window.thread is not None:
            window.cancel();finish()
        window.close();QTest.qWait(50)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--data',default='.real-project-data');parser.add_argument('--output',default='reports/real-projects')
    args=parser.parse_args();out=Path(args.output).resolve();out.mkdir(parents=True,exist_ok=True)
    root,provenance=prepare(Path(args.data));audit=Audit(out)
    original={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (root/'geopandas').rglob('*') if p.is_file()}
    try:
        vectors=vector_cases(root,out,audit)
        rasters=raster_cases(root,out,audit)
        gui_cases(vectors,rasters,out,audit)
    except Exception as exc:
        audit.rows.append(dict(project='Pipeline',step='Prérequis des analyses',reference='Execution',access='API',status='failed',error=str(exc),traceback=traceback.format_exc()))
        traceback.print_exc()
    with audit.step('Intégrité','Préserver les données originales','Empreintes SHA-256 avant et après'):
        assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==digest for p,digest in original.items())
    return 0 if audit.finish(provenance) else 1


if __name__=='__main__':
    raise SystemExit(main())
