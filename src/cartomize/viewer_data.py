"""Read-only, bounded data access for the integrated scientific results view.

Display stretching never changes the scientific files. Raster windows are read
again at the requested resolution; a thumbnail is not used as the zoom source.
"""
from collections import OrderedDict
from functools import lru_cache
from pathlib import Path
import json
import math
import threading

import numpy as np
import pandas as pd
import rasterio
from rasterio.enums import Resampling
from rasterio.windows import Window
from matplotlib import colormaps
from matplotlib.colors import to_rgba

RASTERS = {'.tif', '.tiff', '.jp2', '.vrt', '.img'}
VECTORS = {'.gpkg', '.shp', '.geojson'}
IMAGES = {'.png', '.jpg', '.jpeg', '.bmp', '.webp'}
SUPPORTED = RASTERS | VECTORS | IMAGES | {'.svg', '.pdf', '.csv', '.tsv', '.json'}
PDF_LOCK = threading.RLock()  # PDFium is not thread-safe, including separate documents.
_CACHE = OrderedDict()
_CACHE_LOCK = threading.Lock()
_CACHE_BYTES = 64 * 1024 * 1024


def identity(path):
    p = Path(path).resolve(); stat = p.stat()
    return str(p), stat.st_mtime_ns, stat.st_size


def bounded_shape(width, height, maximum=4096, pixels=8_000_000):
    factor = min(1., maximum / max(1, width, height), math.sqrt(pixels / max(1, width * height)))
    return max(1, round(height * factor)), max(1, round(width * factor))


def _cache(key, value=None):
    with _CACHE_LOCK:
        if value is None:
            result = _CACHE.get(key)
            if result is not None: _CACHE.move_to_end(key)
            return result
        _CACHE[key] = value; _CACHE.move_to_end(key)
        while sum(v['rgba'].nbytes for v in _CACHE.values()) > _CACHE_BYTES:
            _CACHE.popitem(last=False)
    return value


def raster_info(path, options=None):
    options = options or {}
    with rasterio.open(path) as src:
        tags = src.tags()
        classes = options.get('classes') or json.loads(tags.get('CARTOMIZE_CLASSES', '{}'))
        classes = {float(k): list(v) for k, v in classes.items()}
        if not classes:
            try:
                cmap = src.colormap(1)
                classes = {float(k): [f'Valeur {k}', '#%02x%02x%02x' % tuple(v[:3])]
                           for k, v in cmap.items() if v[3] and (src.nodata is None or k != src.nodata)}
            except ValueError: pass
        descriptions = [d or f'Bande {i}' for i, d in enumerate(src.descriptions, 1)]
        roles = [d.casefold() for d in descriptions]
        native = tuple(c.name for c in src.colorinterp[:3]) == ('red', 'green', 'blue')
        rgb = [1, 2, 3] if native else [roles.index(b) + 1 for b in ('red', 'green', 'blue')] if all(b in roles for b in ('red', 'green', 'blue')) else None
        return dict(kind='raster', path=str(Path(path).resolve()), width=src.width, height=src.height,
                    count=src.count, descriptions=descriptions, dtypes=list(src.dtypes), nodata=src.nodata,
                    crs=src.crs.to_string() if src.crs else None, bounds=list(src.bounds),
                    transform=list(src.transform)[:6], resolution=list(src.res), units=list(src.units),
                    scales=list(src.scales), offsets=list(src.offsets), overviews=src.overviews(1),
                    tags=tags, classes=classes, rgb=rgb, native_rgb=native)


@lru_cache(maxsize=128)
def _ranges(file_id, bands):
    with rasterio.open(file_id[0]) as src:
        h, w = bounded_shape(src.width, src.height, maximum=512, pixels=262144)
        sample = np.ma.masked_invalid(src.read(list(bands), out_shape=(len(bands), h, w), masked=True))
    result = []
    for band in sample:
        values = band.compressed()
        result.append(tuple(float(x) for x in np.percentile(values, [2, 98])) if values.size else (0., 1.))
    return tuple(result)


def render_raster(path, rect, shape, bands=(1,), palette='viridis', classes=None,
                  limits=None, resampling='nearest'):
    """Return an RGBA viewport and its native pixel rectangle, with bounded IO."""
    file_id = identity(path); bands = tuple(int(i) for i in bands)
    height, width = bounded_shape(shape[1], shape[0])
    classes = {float(k): v for k, v in (classes or {}).items()}
    key = (file_id, tuple(rect), height, width, bands, palette,
           json.dumps(classes, sort_keys=True), tuple(tuple(v) for v in limits) if limits else None, resampling)
    cached = _cache(key)
    if cached is not None: return cached
    with rasterio.open(path) as src:
        x, y, w, h = rect
        left, top = max(0, math.floor(x)), max(0, math.floor(y))
        right, bottom = min(src.width, math.ceil(x + w)), min(src.height, math.ceil(y + h))
        if right <= left or bottom <= top: raise ValueError('Emprise hors du raster.')
        window = Window(left, top, right - left, bottom - top)
        method = Resampling.nearest if classes else getattr(Resampling, resampling)
        data = np.ma.masked_invalid(src.read(list(bands), window=window,
            out_shape=(len(bands), height, width), masked=True, resampling=method))
        valid = ~np.any(np.ma.getmaskarray(data), axis=0)
        native = len(bands) == 3 and src.dtypes[bands[0]-1] == 'uint8' and (
            src.tags().get('CARTOMIZE_PRODUCT') == 'display_rgba' or
            tuple(src.colorinterp[i-1].name for i in bands) == ('red', 'green', 'blue'))
        alpha_band = next((i for i, c in enumerate(src.colorinterp, 1) if c.name == 'alpha'), None)
        alpha = None
        if native and alpha_band:
            alpha = src.read(alpha_band, window=window, out_shape=(height, width), resampling=Resampling.nearest)
            valid = alpha > 0
        descriptions = [src.descriptions[i-1] or f'Bande {i}' for i in bands]
    values = np.asarray(data.filled(0), dtype='float64')
    rgba = np.zeros((height, width, 4), dtype='uint8')
    legend = []
    used_ranges = ()
    if len(bands) == 1 and classes:
        for code, (label, color) in classes.items():
            rgba[values[0] == code] = np.round(np.asarray(to_rgba(color)) * 255).astype('uint8')
            legend.append((str(label), color, code))
        unknown = valid & ~np.isin(values[0], list(classes))
        rgba[unknown] = (130, 130, 130, 255)
        if unknown.any(): legend.append(('Valeur sans libellé', '#828282', None))
    else:
        used_ranges = tuple(tuple(v) for v in limits) if limits else _ranges(file_id, bands)
        if len(bands) == 3:
            for i in range(3):
                lo, hi = used_ranges[i]
                rgba[:, :, i] = np.clip(values[i] if native else
                    (values[i] - lo) / (hi - lo) * 255 if hi > lo else np.full((height, width), 127), 0, 255).astype('uint8')
            rgba[:, :, 3] = 255
            legend = [(name, color, band) for name, color, band in zip(descriptions, ('#bd3535', '#32824d', '#376ca7'), bands)]
        else:
            lo, hi = used_ranges[0]
            scaled = np.clip((values[0] - lo) / (hi - lo), 0, 1) if hi > lo else np.full((height, width), .5)
            rgba = colormaps[palette](scaled, bytes=True)
            legend = [(f'{lo:.6g}', None, lo), (f'{hi:.6g}', None, hi)]
    rgba[:, :, 3] = np.where(valid, alpha if alpha is not None else rgba[:, :, 3], 0)
    rgba = np.ascontiguousarray(rgba)
    return _cache(key, dict(rgba=rgba, rect=(left, top, right-left, bottom-top),
                           ranges=used_ranges, legend=legend, source_window=(left, top, right-left, bottom-top),
                           resampling=method.name, sampled_statistics=True))


def pixel_values(path, column, row, bands):
    with rasterio.open(path) as src:
        if not (0 <= column < src.width and 0 <= row < src.height): return None
        window=Window(int(column), int(row), 1, 1)
        alpha=next((i for i,c in enumerate(src.colorinterp,1) if c.name=='alpha'),None)
        display=src.tags().get('CARTOMIZE_PRODUCT')=='display_rgba' or tuple(c.name for c in src.colorinterp[:3])==('red','green','blue')
        if display and alpha:
            if src.read(alpha,window=window)[0,0]==0: return [None for _ in bands]
            data=np.ma.masked_invalid(src.read(list(bands),window=window,masked=False))
        else: data = np.ma.masked_invalid(src.read(list(bands), window=window, masked=True))
        return [None if np.ma.is_masked(v) else float(v) for v in data[:, 0, 0]]


def vector_info(path, options=None):
    import pyogrio
    opts = options or {}; info = pyogrio.read_info(path, layer=opts.get('layer'), force_total_bounds=True)
    bounds = info['total_bounds']
    if bounds is None or not np.isfinite(bounds).all(): bounds = (0, 0, 1, 1)
    xmin, ymin, xmax, ymax = bounds
    span = max(xmax-xmin, ymax-ymin, 1)
    if xmax == xmin: xmin -= span*.05; xmax += span*.05
    if ymax == ymin: ymin -= span*.05; ymax += span*.05
    return dict(kind='vector', path=str(Path(path).resolve()), crs=info['crs'], bounds=[xmin, ymin, xmax, ymax],
                features=int(info['features']), geometry=info['geometry_type'], fields=list(info['fields']),
                layer=info['layer_name'], classes=opts.get('classes') or {}, column=opts.get('column'),
                color=opts.get('color', '#46695a'))


def pdf_info(path):
    import pypdfium2 as pdfium
    with PDF_LOCK, pdfium.PdfDocument(path) as document:
        sizes = [list(document.get_page_size(i)) for i in range(len(document))]
        return dict(kind='pdf', path=str(Path(path).resolve()), pages=len(document), sizes=sizes,
                    width=sizes[0][0], height=sizes[0][1], crs=None)


def render_pdf(path, page_number, rect, shape):
    import pypdfium2 as pdfium
    key = ('pdf', identity(path), page_number, tuple(rect), tuple(shape))
    cached = _cache(key)
    if cached is not None: return cached
    with PDF_LOCK, pdfium.PdfDocument(path) as document:
        page = document[page_number]
        try:
            width, height = page.get_size(); x, y, w, h = rect
            x, y = max(0, x), max(0, y); w, h = min(w, width-x), min(h, height-y)
            scale = min(shape[1]/max(w, .001), shape[0]/max(h, .001))
            bitmap = page.render(scale=scale, crop=(x, max(0, height-y-h), max(0, width-x-w), y),
                                 rev_byteorder=True, fill_color=(255, 255, 255, 255))
            try:
                array = np.asarray(bitmap.to_pil().convert('RGBA')).copy()
            finally: bitmap.close()
        finally: page.close()
    return _cache(key, dict(rgba=array, rect=(x,y,w,h), legend=[], ranges=()))


def table_page(path, offset=0, size=2000, layer=None):
    """Read one attribute/CSV page, keeping full files outside UI memory."""
    path = Path(path)
    if path.suffix.lower() in VECTORS:
        import pyogrio
        data = pyogrio.read_dataframe(path, layer=layer, skip_features=offset, max_features=size+1, read_geometry=False)
    else:
        data = pd.read_csv(path, sep='\t' if path.suffix.lower()=='.tsv' else None, engine='python',
                           skiprows=range(1, offset+1), nrows=size+1, encoding='utf-8-sig')
    return dict(frame=data.iloc[:size].copy(), more=len(data)>size, offset=offset, size=size)


def report_tables(document):
    """Expose structured numeric reports, including confusion matrices."""
    result = {}
    def visit(value, key='Rapport', depth=0):
        if depth>5 or len(result)>=24: return
        if isinstance(value, list) and value and len(value)<=50000:
            if all(isinstance(v, dict) for v in value): result[key] = pd.json_normalize(value)
            elif all(isinstance(v, (list, tuple)) for v in value): result[key] = pd.DataFrame(value)
            elif all(isinstance(v, (str, int, float, bool, type(None))) for v in value): result[key] = pd.DataFrame({'Valeur': value})
        elif isinstance(value, dict):
            flat = {k:v for k,v in value.items() if isinstance(v,(str,int,float,bool,type(None)))}
            if flat: result[key] = pd.DataFrame({'Propriété': list(flat), 'Valeur': list(flat.values())})
            for k, v in value.items():
                if isinstance(v, (list,dict)): visit(v, str(k), depth+1)
    visit(document)
    return result
