"""Download external teaching datasets and retain a verifiable provenance manifest.

No original dataset is committed to this repository. Archives are extracted
only after checking paths and expanded sizes. Tutorials are inspected, not
executed as arbitrary downloaded Python code.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import time
import urllib.request
import zipfile

TUTORIAL_REF = '72c7f3168e1e4e257caf84eb7b3fcaa47ade09c0'
TUTORIAL_BASE = f'https://raw.githubusercontent.com/jorisvandenbossche/geopandas-tutorial/{TUTORIAL_REF}'
FILES = ['ne_110m_admin_0_countries.zip', 'ne_110m_populated_places.zip',
         'ne_50m_rivers_lake_centerlines.zip', 'paris_districts.geojson',
         'paris_bike_stations.geojson', 'paris_trees.gpkg', 'paris_land_use.zip',
         'cod_mines_curated_all_opendata_p_ipis.geojson', 'cod_conservation.zip',
         'raw/paris-population.csv']
NOTEBOOKS = ['01-introduction-geospatial-data.ipynb', '02-coordinate-reference-systems.ipynb',
             '03-spatial-relationships-joins.ipynb', '04-spatial-operations-overlays.ipynb',
             '05-more-on-visualization.ipynb', '06-scaling-geopandas-dask.ipynb',
             'case-conflict-mapping.ipynb']
EARTHLAB_URL = 'https://ndownloader.figshare.com/files/16371473'


def download(url, target):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.is_file():
        temporary = target.with_suffix(target.suffix + '.part')
        for attempt in range(3):
            try:
                request = urllib.request.Request(url, headers={'User-Agent': 'Cartomize-real-project-validation/1.0'})
                with urllib.request.urlopen(request, timeout=90) as response, temporary.open('wb') as handle:
                    total = 0
                    while chunk := response.read(1024 * 1024):
                        total += len(chunk)
                        if total > 512 * 1024**2:
                            raise ValueError('Download exceeds the 512 MiB safety limit')
                        handle.write(chunk)
                temporary.replace(target)
                break
            except Exception:
                temporary.unlink(missing_ok=True)
                if attempt == 2:
                    raise
                time.sleep(2 * (attempt + 1))
    digest = hashlib.sha256()
    with target.open('rb') as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return {'url': url, 'path': str(target), 'bytes': target.stat().st_size, 'sha256': digest.hexdigest()}


def extract(path, directory):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path) as archive:
        if sum(x.file_size for x in archive.infolist()) > 2 * 1024**3:
            raise ValueError('Archive exceeds the 2 GiB expanded limit')
        for member in archive.infolist():
            relative = Path(member.filename.replace('\\', '/'))
            resolved = (directory / relative).resolve()
            if not resolved.is_relative_to(directory):
                raise ValueError('Unsafe archive member')
            if (member.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('Archive symlinks are not accepted')
        archive.extractall(directory)
    return directory


def prepare(root):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    sources = []
    for name in FILES:
        sources.append(download(f'{TUTORIAL_BASE}/data/{name}', root / 'geopandas' / name))
        if name.endswith('.zip'):
            extract(root / 'geopandas' / name, root / 'geopandas' / Path(name).stem)
    for name in NOTEBOOKS + ['LICENSE']:
        sources.append(download(f'{TUTORIAL_BASE}/{name}', root / 'tutorial' / name))
    sources.append(download(EARTHLAB_URL, root / 'colorado-flood.zip'))
    extract(root / 'colorado-flood.zip', root / 'earthlab')
    manifest = {'tutorial_repository': 'jorisvandenbossche/geopandas-tutorial',
                'tutorial_commit': TUTORIAL_REF, 'source_type': 'External published teaching datasets, not generated fixtures',
                'earthlab_tutorial': 'https://earthdatascience.org/courses/use-data-open-source-python/data-stories/colorado-floods-2013/measure-changes-in-terrain-caused-by-floods/',
                'sources': sources}
    (root / 'provenance.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return root, manifest


def inventory(root):
    import geopandas as gpd
    import rasterio
    result = {'vectors': {}, 'rasters': {}, 'notebooks': {}}
    for name in FILES:
        if name.endswith('.csv'):
            continue
        path = root / 'geopandas' / name
        if name.endswith('.zip'):
            path = next((root / 'geopandas' / Path(name).stem).rglob('*.shp'))
        frame = gpd.read_file(path)
        result['vectors'][name] = {'path': str(path), 'features': len(frame), 'crs': str(frame.crs),
            'columns': list(frame.columns), 'invalid': int((~frame.geometry.is_valid).sum()),
            'bounds': frame.total_bounds.tolist()}
    for path in (root / 'earthlab').rglob('*'):
        if path.suffix.lower() in {'.tif', '.tiff'}:
            with rasterio.open(path) as src:
                result['rasters'][str(path.relative_to(root))] = {'shape': list(src.shape), 'crs': str(src.crs),
                    'count': src.count, 'nodata': src.nodata, 'transform': list(src.transform)[:6]}
    result['earthlab_shapefiles'] = [str(p.relative_to(root)) for p in (root / 'earthlab').rglob('*.shp')]
    for name in NOTEBOOKS:
        cells = json.loads((root / 'tutorial' / name).read_text(encoding='utf-8'))['cells']
        result['notebooks'][name] = [{'cell': i, 'source': ''.join(c['source'])}
                                    for i,c in enumerate(cells) if c['cell_type'] == 'code']
    return result


if __name__ == '__main__':
    root, provenance = prepare(Path(sys.argv[1]) if len(sys.argv)>1 else Path('.real-project-data'))
    result = inventory(root)
    destination = Path('reports/real-projects')
    destination.mkdir(parents=True, exist_ok=True)
    (destination/'inventory.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    (destination/'provenance.json').write_text(json.dumps(provenance, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='notebooks'}, ensure_ascii=False, indent=2))
