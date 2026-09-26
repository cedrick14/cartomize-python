"""Datasets and display helpers for the Cartomize practical course."""
from pathlib import Path
import hashlib
import json
import os
import tempfile
import zipfile

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import Point, LineString, box

ROOT = Path(__file__).resolve().parent
CRS = 'EPSG:32733'
ROLES = ('blue', 'green', 'red', 'nir', 'swir1', 'swir2', 'rededge1')
CLASSES = {1: ('Végétation simulée', '#276344'),
           2: ('Sol simulé', '#c7a76d'), 3: ('Eau simulée', '#5586a4')}


def run_directory(name):
    base = Path(os.environ.get('CARTOMIZE_COURSE_OUTPUT', ROOT/'outputs'))
    base.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=name+'_', dir=base))


def write_raster(path, data, *, transform=None, crs=CRS, nodata=None, names=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.asarray(data)
    if data.ndim == 2:
        data = data[None, ...]
    with rasterio.open(path, 'w', driver='GTiff', height=data.shape[1],
                       width=data.shape[2], count=data.shape[0], dtype=data.dtype,
                       transform=transform or from_origin(300000, 9500000, 30, 30),
                       crs=crs, nodata=nodata, compress='lzw') as dst:
        dst.write(data)
        if names:
            dst.descriptions = tuple(names)
        dst.update_tags(DATA_ORIGIN='synthetic tutorial fixture; not an observation')
    return path


def demo(directory):
    """Generate a deterministic, wholly synthetic landscape and reference points."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    transform = from_origin(300000, 9500000, 30, 30)
    y, x = np.mgrid[:96, :128]
    code = np.where(x + .6*y < 100, 1, 2).astype('uint8')
    code[((x-40)**2/14**2 + (y-45)**2/32**2) < 1] = 3
    inside = ((x-64)/61)**2 + ((y-48)/45)**2 < 1
    means = np.array([[.07,.13,.05,.52,.22,.12,.27],
                      [.18,.22,.26,.32,.38,.30,.29],
                      [.06,.09,.04,.02,.01,.008,.03]], dtype='float32')
    rng = np.random.default_rng(260926)
    values = np.moveaxis(means[code-1], -1, 0)
    values = np.clip(values + rng.normal(0,.006,values.shape), .002, .95).astype('float32')
    values[:, ~inside] = np.nan
    paths = {'image': write_raster(directory/'reflectance.tif', values, nodata=np.nan, names=ROLES)}
    before = np.where(inside, code, 255).astype('uint8')
    after = before.copy()
    after[(x>65)&(x<88)&(y>35)&(y<75)&(before==1)] = 2
    after[(x>105)&(y>30)&(y<60)&(before==2)] = 1
    paths['before'] = write_raster(directory/'classes_t0.tif', before, nodata=255, names=['synthetic_class'])
    paths['after'] = write_raster(directory/'classes_t1.tif', after, nodata=255, names=['synthetic_class'])
    dem = (210 + .8*(96-y) + 25*np.sin(x/13) + 8*np.cos(y/9)).astype('float32')
    paths['dem'] = write_raster(directory/'dem.tif', dem, names=['synthetic_elevation_m'])
    zones = gpd.GeoDataFrame({'name':['Secteur ouest','Secteur est'], 'group':['Ensemble','Ensemble']},
        geometry=[box(300120,9497240,301920,9499880),box(301920,9497240,303720,9499880)], crs=CRS)
    aoi = gpd.GeoDataFrame({'name':['Emprise pédagogique']}, geometry=[box(300150,9497270,303690,9499850)], crs=CRS)
    roads = gpd.GeoDataFrame({'name':['Axe horizontal','Axe vertical']}, geometry=[
        LineString([(300300,9498500),(301900,9498500),(303500,9498500)]),
        LineString([(301900,9497300),(301900,9498500),(301900,9499800)])],crs=CRS)
    points = gpd.GeoDataFrame({'name':['Station A','Station B','Station C']},geometry=[
        Point(300600,9498500),Point(301900,9499000),Point(303100,9498500)],crs=CRS)
    train_rows, validation_rows = [], []
    for value in (1,2,3):
        rows,cols=np.where((before==value))
        selected=rng.choice(len(rows),90,replace=False)
        for k,index in enumerate(selected):
            row,col=int(rows[index]),int(cols[index])
            record={'classe':int(value),'libelle':CLASSES[value][0],
                    'geometry':Point(*rasterio.transform.xy(transform,row,col))}
            (train_rows if k<60 else validation_rows).append(record)
    frames={'zones':zones,'aoi':aoi,'roads':roads,'points':points,
            'training':gpd.GeoDataFrame(train_rows,crs=CRS),
            'validation':gpd.GeoDataFrame(validation_rows,crs=CRS)}
    for key,frame in frames.items():
        paths[key]=directory/(key+'.gpkg');frame.to_file(paths[key],index=False)
    scenes=[]
    for ident,left,right in [('A',0,80),('B',56,128)]:
        band_paths={}
        for b,role in enumerate(ROLES):
            band_paths[role]={'path':str(write_raster(directory/f'scene_{ident}/{role}.tif',
                values[b,:,left:right],transform=from_origin(300000+left*30,9500000,30,30),
                nodata=np.nan,names=[role]).resolve()),'scale':1.,'offset':0.,'unit':'reflectance'}
        scenes.append({'scene_id':f'synthetic_{ident}','sensor':'synthetic',
                       'acquired':'2026-01-01','bands':band_paths})
    paths['scenes']=directory/'scenes.json'
    paths['scenes'].write_text(json.dumps({'schema':'cartomize.scenes.v1','scenes':scenes}),encoding='utf-8')
    return paths


def show_raster(path, title='', *, band=1, cmap='viridis', vmin=None, vmax=None):
    with rasterio.open(path) as src:
        ratio=min(1,900/max(src.width,src.height))
        data=src.read(band,out_shape=(max(1,int(src.height*ratio)),max(1,int(src.width*ratio))),masked=True)
        bounds=src.bounds
    fig,ax=plt.subplots(figsize=(8,5),layout='constrained')
    im=ax.imshow(data,extent=(bounds.left,bounds.right,bounds.bottom,bounds.top),
                 cmap=cmap,vmin=vmin,vmax=vmax,interpolation='nearest')
    ax.set_title(title);ax.set_xlabel('X');ax.set_ylabel('Y')
    fig.colorbar(im,ax=ax,shrink=.85)
    return fig


def show_rgb(path, title=''):
    from cartomize import read_rgb
    image,bounds,metadata=read_rgb(path,bands='natural',max_size=1000)
    fig,ax=plt.subplots(figsize=(8,5),layout='constrained')
    ax.imshow(image,extent=bounds);ax.set_title(title);ax.set_axis_off()
    return fig


def gallery(fig, name):
    destination=Path(os.environ.get('CARTOMIZE_COURSE_GALLERY',ROOT/'gallery'))
    destination.mkdir(parents=True,exist_ok=True)
    fig.savefig(destination/(name+'.png'),dpi=160,bbox_inches='tight',facecolor='white')


def unzip_checked(source, target):
    target=Path(target).resolve();target.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(source) as archive:
        for member in archive.infolist():
            path=(target/member.filename).resolve()
            if not path.is_relative_to(target):
                raise ValueError('Archive : chemin extérieur au répertoire de destination.')
        archive.extractall(target)


def import_tuto(source, destination):
    """Import the supplied archive locally; retain its original metadata and files."""
    source=Path(source).expanduser().resolve();destination=Path(destination).resolve()
    if destination.exists():
        raise FileExistsError('Choisir un nouveau dossier d’importation.')
    unzip_checked(source,destination)
    for archive in list(destination.rglob('*.zip')):
        unzip_checked(archive,archive.with_suffix(''))
    records=[]
    for path in sorted(destination.rglob('*')):
        if path.suffix.lower()=='.tif':
            with rasterio.open(path) as src:
                records.append(dict(file=str(path.relative_to(destination)),kind='raster',
                    width=src.width,height=src.height,bands=src.count,crs=str(src.crs),
                    descriptions=src.descriptions,nodata=src.nodata,scales=src.scales,
                    offsets=src.offsets,bounds=tuple(src.bounds)))
        elif path.suffix.lower()=='.shp':
            frame=gpd.read_file(path)
            records.append(dict(file=str(path.relative_to(destination)),kind='vector',
                features=len(frame),crs=str(frame.crs),fields=list(frame.columns),
                bounds=frame.total_bounds.tolist()))
    manifest={'source_archive':source.name,'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
              'datasets':records}
    (destination/'inventory.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding='utf-8')
    return manifest


def supplied_data():
    root=Path(os.environ.get('CARTOMIZE_TUTO_DATA',ROOT/'data/private')).resolve()
    required={'composite':'Mvouti_Composite_2024_2025_cloudmask.tif',
              'okapi':'La Réserve de Faune à Okapis foret_RDC_2025.tif',
              'concessions':'Concession.shp','administration':'CONGO_BZ_UTM_33S.shp',
              'dimonika':'WDPA_WDOECM_May2026_Public_13694_shp-polygons.shp'}
    result={}
    for key,name in required.items():
        matches=list(root.rglob(name))
        if len(matches)!=1:
            raise FileNotFoundError(f'{name} : importer Tuto.zip avec scripts/import_tuto.py, puis définir CARTOMIZE_TUTO_DATA si nécessaire.')
        result[key]=matches[0]
    return result
