"""Verified raster delivery without changing the grid or silently losing data.

G06 writes a new directory atomically. A full-resolution, block-by-block
readback checks every valid sample and every band mask. Numeric quantization
is opt-in; overflow, NoData collisions and loss of georeferencing are errors.
The COG driver runs only after the temporary GeoTIFF is complete, and its
output is never reopened for writing.
"""
from dataclasses import dataclass
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import hashlib
import math
from pathlib import Path
from xml.etree import ElementTree as ET

import numpy as np
import rasterio
from rasterio.enums import ColorInterp, MaskFlags, Resampling
from rasterio.io import MemoryFile
from rasterio.shutil import copy as raster_copy
from rasterio.windows import Window

from .imagery import _check_cancel
from .storage import new_directory, save_json


@dataclass(frozen=True)
class ConvertedRaster:
    """The converted raster and its complete readback audit."""

    manifest: Path
    data: Path
    report: Path
    summary: dict


_DTYPES = {'uint8', 'int8', 'uint16', 'int16', 'uint32', 'int32',
           'uint64', 'int64', 'float32', 'float64'}
_COMPRESSIONS = {'none', 'lzw', 'deflate', 'zstd'}
_RESAMPLING = {'nearest', 'bilinear', 'cubic', 'average', 'mode'}
_DERIVED_NAMESPACES = {'IMAGE_STRUCTURE', 'DERIVED_SUBDATASETS', 'SUBDATASETS'}


def _number(value):
    """JSON-safe numbers retain the distinction between absent and NaN."""
    if value is None:
        return None
    if isinstance(value, (float, np.floating)) and not np.isfinite(value):
        return 'nan' if np.isnan(value) else ('inf' if value > 0 else '-inf')
    return value.item() if isinstance(value, np.generic) else value


def _equal_number(left, right):
    if left is None or right is None:
        return left is right
    return bool(left == right or np.isnan(left) and np.isnan(right))


def _nodata(value, dtype):
    if value is None:
        return None
    if isinstance(value, str):
        if value.lower() == 'nan':
            value = float('nan')
        else:
            raise ValueError("NoData must be 'preserve', 'nan', null or a numeric value.")
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.number)):
        raise ValueError('NoData must be a real numeric value, not a boolean.')
    if np.iscomplexobj(value):
        raise ValueError('Complex NoData values are not supported.')
    # Python int/float comparisons retain large integer precision; NumPy's
    # mixed comparison may first round an int64/uint64 to a double.
    if isinstance(value, np.generic):
        value = value.item()
    target = np.dtype(dtype)
    integral = isinstance(value, (int, np.integer))
    if not integral and np.isnan(value):
        if target.kind != 'f':
            raise ValueError('NaN NoData requires a floating-point output type.')
        return float('nan')
    if not integral and not np.isfinite(value):
        raise ValueError('Infinite NoData values are not supported; select a finite value or NaN.')
    if target.kind in 'iu':
        integer = int(value)
        limits = np.iinfo(target)
        if value != integer or not int(limits.min) <= integer <= int(limits.max):
            raise ValueError(f'NoData cannot be represented exactly as {dtype}.')
        # Rasterio exposes the GDAL NoData value through a double. Do not
        # pretend that an ambiguous int64/uint64 sentinel was verified.
        if abs(integer) > 2**53:
            raise ValueError('Integer NoData above 2**53 cannot be verified exactly by this reader.')
        return integer
    try:
        with np.errstate(over='ignore', invalid='ignore'):
            cast = target.type(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f'NoData cannot be represented exactly as {dtype}.') from exc
    if not np.isfinite(cast) or float(cast) != value:
        raise ValueError(f'NoData cannot be represented exactly as {dtype}.')
    return float(cast)


def _auxiliary_metadata(src):
    """Read semantic band metadata and exact int64 NoData through GDAL VRT.

    Rasterio tags do not expose CategoryNames or a raster attribute table,
    and its NoData property rounds 64-bit integer sentinels through double.
    A VRT CreateCopy serializes those GDAL structures without loading pixels
    or modifying the source. No optional osgeo dependency is needed.
    """
    with MemoryFile(ext='.vrt') as probe:
        raster_copy(src, probe.name, driver='VRT')
        root = ET.fromstring(probe.read())
    semantic = {}
    nodata = list(src.nodatavals)
    for node in root.findall('VRTRasterBand'):
        band = int(node.attrib['band'])
        entries = {name: deepcopy(child) for name in ('CategoryNames', 'GDALRasterAttributeTable')
                   if (child := node.find(name)) is not None}
        if entries:
            semantic[band] = entries
        text = node.findtext('NoDataValue')
        if (src.dtypes[band - 1] in {'int64', 'uint64'}
                and nodata[band - 1] is not None and text is not None):
            try:
                number = Decimal(text)
                if not number.is_finite() or number != number.to_integral_value():
                    raise ValueError('Invalid 64-bit integer NoData metadata in the source.')
                nodata[band - 1] = int(number)
            except InvalidOperation as exc:
                raise ValueError('Unparseable 64-bit integer NoData metadata in the source.') from exc
    return semantic, nodata


def _xml_signature(node):
    text = node.text or ''
    if len(node) and not text.strip():
        text = ''
    return (node.tag, tuple(sorted(node.attrib.items())), text,
            tuple(_xml_signature(child) for child in node))


def _semantic_description(semantic):
    result = []
    for band, entries in semantic.items():
        categories = entries.get('CategoryNames')
        table = entries.get('GDALRasterAttributeTable')
        result.append(dict(band=band,
            category_names=None if categories is None else [child.text or '' for child in categories],
            raster_attribute_table=None if table is None else dict(
                rows=len(table.findall('Row')), columns=len(table.findall('FieldDefn')),
                fields=[dict(index=int(field.get('index', '0')), name=field.findtext('Name'),
                             type=field.findtext('Type'), usage=field.findtext('Usage'))
                        for field in table.findall('FieldDefn')],
                sha256=hashlib.sha256(repr(_xml_signature(table)).encode('utf-8')).hexdigest())))
    return result


def _options(src, *, driver, dtype, nodata, compression, source_nodata=None):
    aliases = {'gtiff': 'GTiff', 'geotiff': 'GTiff', 'cog': 'COG'}
    if not isinstance(driver, str) or driver.lower() not in aliases:
        raise ValueError('Raster conversion supports the GTiff and COG drivers.')
    driver = aliases[driver.lower()]
    with rasterio.Env() as env:
        if driver not in env.drivers():
            raise ValueError(f'The {driver} driver is unavailable in this GDAL installation.')
    if src.count < 1 or src.width < 1 or src.height < 1:
        raise ValueError('Choose a raster with bands; select a subdataset explicitly if needed.')
    if len(set(src.dtypes)) != 1 and dtype is None:
        raise ValueError('Different source band types require an explicit common output type.')
    if any(np.dtype(value).kind not in 'iuf' for value in src.dtypes):
        raise ValueError('Complex raster values require a separate, explicit conversion procedure.')
    dtype = src.dtypes[0] if dtype is None else dtype
    try:
        dtype = np.dtype(dtype).name
    except (TypeError, ValueError) as exc:
        raise ValueError('Invalid raster output dtype.') from exc
    if dtype not in _DTYPES:
        raise ValueError('Unsupported raster output dtype: ' + dtype)
    if not isinstance(compression, str) or compression.lower() not in _COMPRESSIONS:
        raise ValueError('compression must be none, lzw, deflate or zstd; lossy compression is not used.')
    if isinstance(nodata, str) and nodata == 'preserve':
        values = src.nodatavals if source_nodata is None else source_nodata
        if not all(_equal_number(values[0], value) for value in values):
            raise ValueError('Different per-band NoData values require one explicit output NoData value.')
        nodata = values[0]
    nodata = _nodata(nodata, dtype)
    gcps, _ = src.gcps
    if gcps or src.tags(ns='GEOLOCATION'):
        raise ValueError('GCP/geolocation-array rasters require an explicit affine-grid preparation before G06.')
    # Palette entries and their transparency depend on dtype and NoData.
    # Keeping their representation unchanged avoids an undocumented remap.
    if ColorInterp.palette in src.colorinterp:
        if dtype != src.dtypes[0] or not _equal_number(nodata, src.nodata):
            raise ValueError('A palette raster must keep its dtype and NoData to preserve the color table.')
    alpha_mask = any(MaskFlags.alpha in flags for flags in src.mask_flag_enums)
    if alpha_mask and (nodata is not None or any(dtype != item for item in src.dtypes)):
        raise ValueError('An active alpha mask requires preserving its dtype and absent NoData.')
    return dict(driver=driver, dtype=dtype, nodata=nodata,
                compression=compression.lower(), alpha_mask=alpha_mask)


def _description(src, source, *, nodata_values=None, semantic=None):
    return dict(path=str(source), width=src.width, height=src.height,
        count=src.count, bands=src.count, dtypes=list(src.dtypes),
        crs=None if src.crs is None else src.crs.to_string(),
        crs_wkt=None if src.crs is None else src.crs.to_wkt(),
        transform=list(src.transform)[:6],
        nodata=[_number(value) for value in (src.nodatavals if nodata_values is None else nodata_values)],
        mask_flags=[[flag.name for flag in flags] for flags in src.mask_flag_enums],
        descriptions=list(src.descriptions), units=list(src.units),
        scales=list(src.scales), offsets=list(src.offsets),
        color_interpretation=[value.name for value in src.colorinterp],
        overviews=[src.overviews(index) for index in src.indexes],
        classification_metadata=_semantic_description(semantic or {}))


def inspect_raster_conversion(source, *, driver='GTiff', dtype=None,
                              nodata='preserve', compression='lzw'):
    """Inspect format options without claiming a full pixel validation.

    ``nodata='nan'`` is the JSON-safe spelling of a floating NaN sentinel.
    An absent source CRS is retained as absent; no projection is guessed.
    """
    with rasterio.open(source) as src:
        semantic, source_nodata = _auxiliary_metadata(src)
        options = _options(src, driver=driver, dtype=dtype, nodata=nodata, compression=compression,
                           source_nodata=source_nodata)
        description = _description(src, source, nodata_values=source_nodata, semantic=semantic)
        requested = {key: _number(value) for key, value in options.items() if key != 'alpha_mask'}
        return dict(schema='cartomize.raster_conversion_inspection.v1', source=description,
            requested=requested, driver=options['driver'], dtype=options['dtype'],
            nodata=_number(options['nodata']), crs=description['crs'],
            width=src.width, height=src.height, count=src.count,
            notes=['Grid and band order are retained.',
                   'All valid samples and per-band masks are checked during conversion.',
                   'Overview resampling affects reduced-resolution previews only.'])


def _windows(width, height, size):
    for top in range(0, height, size):
        for left in range(0, width, size):
            yield Window(left, top, min(size, width - left), min(size, height - top))


def _same_array(left, right):
    equal = left == right
    if left.dtype.kind == 'f' and right.dtype.kind == 'f':
        equal |= np.isnan(left) & np.isnan(right)
    return equal


def _changed_values(original, converted):
    """Avoid NumPy's mixed int/float promotion hiding lost int64 digits."""
    with np.errstate(invalid='ignore', over='ignore'):
        restored = converted.astype(original.dtype)
    return ~_same_array(original, restored)


def _max_error(original, converted, changed):
    if not np.any(changed):
        return 0.0
    before, after = original[changed], converted[changed]
    if original.dtype.kind in 'iu':
        # Python integers also handle uint64->float at the 2**64 boundary.
        return float(max(abs(int(a) - int(b)) for a, b in zip(before, after)))
    with np.errstate(over='ignore', invalid='ignore'):
        values = np.abs(before.astype('float64') - after.astype('float64'))
    if not np.isfinite(values).all():
        raise ValueError('The conversion error is not finite; choose a wider output type.')
    return float(values.max(initial=0.0))


def _convert_samples(values, dtype, loss_policy):
    target = np.dtype(dtype)
    if target.kind in 'iu':
        limits = np.iinfo(target)
        if values.dtype.kind == 'f':
            if not np.isfinite(values).all():
                raise ValueError('Valid NaN or infinite samples cannot be converted to an integer type.')
            rounded = np.rint(values)
            if loss_policy == 'error' and np.any(rounded != values):
                raise ValueError("Fractional samples would be rounded; choose a float dtype or loss_policy='report'.")
            # Exclusive powers of two remain exact even when int64.max does
            # not fit in a floating-point comparison operand.
            upper = 2**(target.itemsize * 8 - (target.kind == 'i'))
            lower = -upper if target.kind == 'i' else 0
            if np.any(rounded < lower) or np.any(rounded >= upper):
                raise ValueError('Raster values overflow the requested integer dtype; clipping is never implicit.')
            cast_from = rounded
        else:
            if values.size and (int(values.min()) < int(limits.min) or int(values.max()) > int(limits.max)):
                raise ValueError('Raster values overflow the requested integer dtype; clipping is never implicit.')
            cast_from = values
    else:
        cast_from = values
    with np.errstate(over='ignore', invalid='ignore'):
        result = cast_from.astype(target)
    if target.kind == 'f':
        if np.any(np.isfinite(values) & ~np.isfinite(result)):
            raise ValueError('Raster values overflow the requested floating-point dtype.')
    changed = _changed_values(values, result)
    if loss_policy == 'error' and np.any(changed):
        raise ValueError("Raster precision would be lost; choose a wider dtype or loss_policy='report'.")
    return result


def _metadata(src, *, remove_statistics=False):
    result = {}
    discarded = []
    for band in (0, *src.indexes):
        domains = {}
        for namespace in (None, *src.tag_namespaces(band)):
            if namespace in _DERIVED_NAMESPACES:
                continue
            tags = src.tags(band, ns=namespace)
            if remove_statistics:
                for key in list(tags):
                    if key.upper().startswith('STATISTICS_'):
                        discarded.append(dict(band=band, namespace=namespace, key=key))
                        tags.pop(key)
            if tags:
                domains[namespace] = tags
        result[band] = domains
    return result, discarded


def _write_band_layout(src, dst):
    dst.descriptions = src.descriptions
    dst.scales = src.scales
    dst.offsets = src.offsets
    for band in src.indexes:
        if src.units[band - 1] is not None:
            dst.set_band_unit(band, src.units[band - 1])
        if src.colorinterp[band - 1] == ColorInterp.palette:
            dst.write_colormap(band, src.colormap(band))
    dst.colorinterp = src.colorinterp


def _write_metadata(src, dst, tags):
    for band, domains in tags.items():
        for namespace, values in domains.items():
            dst.update_tags(band, ns=namespace, **values)


def _complete_pam_metadata(path, tags, semantic):
    """Attach semantic/missing metadata through PAM without changing TIFF bytes.

    GDAL's COPY_SRC_MDD=YES path can omit the default band domain, whereas
    AUTO omits custom dataset domains (GTiff WriteMetadata). Keep YES, then
    supply any missing exposed tags in the standard companion .aux.xml.
    Category names and GDAL raster attribute tables use that same standard
    band structure for both GeoTIFF and COG, since Rasterio has no setter.
    The delivery is consequently a TIFF plus its metadata sidecar whenever
    that driver limitation occurs; the manifest lists both files.
    """
    missing = {}
    with rasterio.open(path) as check:
        for band, domains in tags.items():
            for namespace, values in domains.items():
                actual = check.tags(band, ns=namespace)
                absent = {key: value for key, value in values.items() if actual.get(key) != value}
                if absent:
                    missing.setdefault(band, {})[namespace] = absent
    if not missing and not semantic:
        return
    sidecar = Path(str(path) + '.aux.xml')
    root = ET.parse(sidecar).getroot() if sidecar.exists() else ET.Element('PAMDataset')
    for band, domains in missing.items():
        parent = root
        if band:
            parent = root.find(f"PAMRasterBand[@band='{band}']")
            if parent is None:
                parent = ET.SubElement(root, 'PAMRasterBand', band=str(band))
        for namespace, values in domains.items():
            node = next((item for item in parent.findall('Metadata')
                         if item.get('domain') == namespace), None)
            if node is None:
                node = ET.SubElement(parent, 'Metadata', {} if namespace is None else {'domain': namespace})
            for key, value in values.items():
                item = next((item for item in node.findall('MDI') if item.get('key') == key), None)
                if item is None:
                    item = ET.SubElement(node, 'MDI', key=key)
                item.text = value
    for band, entries in semantic.items():
        parent = root.find(f"PAMRasterBand[@band='{band}']")
        if parent is None:
            parent = ET.SubElement(root, 'PAMRasterBand', band=str(band))
        for name, node in entries.items():
            for existing in parent.findall(name):
                parent.remove(existing)
            parent.append(deepcopy(node))
    # GDAL PAM expects PAMDataset as the first XML node; an XML declaration
    # can be accepted as a file yet cause the metadata content to be ignored.
    ET.ElementTree(root).write(sidecar, encoding='utf-8', xml_declaration=False)


def _overview_factors(src, overviews):
    if overviews is None:
        factors = src.overviews(1)
        if any(src.overviews(band) != factors for band in src.indexes):
            raise ValueError('Different per-band overview levels require an explicit common overview list.')
    else:
        if not isinstance(overviews, (list, tuple)):
            raise ValueError('overviews must be null or a list of integer reduction factors.')
        factors = list(overviews)
    if (any(isinstance(value, bool) or not isinstance(value, (int, np.integer)) or value < 2
            or value > max(src.width, src.height) for value in factors)
            or len(set(factors)) != len(factors) or factors != sorted(factors)):
        raise ValueError('Overview factors must be distinct increasing integers from 2 to the largest image dimension.')
    shapes = [(math.ceil(src.width / value), math.ceil(src.height / value)) for value in factors]
    if len(set(shapes)) != len(shapes):
        raise ValueError('Two overview factors would produce the same reduced raster dimensions.')
    return [int(value) for value in factors]


def _verify_metadata(src, check, options, tags, expected_overviews, semantic):
    if ((src.width, src.height, src.count) != (check.width, check.height, check.count)
            or src.crs != check.crs or src.transform != check.transform):
        raise ValueError('Raster readback changed the dimensions, band count, CRS or affine grid.')
    if any(value != options['dtype'] for value in check.dtypes):
        raise ValueError('Raster readback does not have the requested numeric type.')
    if not all(_equal_number(value, options['nodata']) for value in check.nodatavals):
        raise ValueError('Raster readback changed the requested NoData value.')
    for name in ('descriptions', 'scales', 'offsets', 'units', 'colorinterp'):
        if getattr(src, name) != getattr(check, name):
            raise ValueError('Raster readback changed band metadata: ' + name)
    for band in src.indexes:
        if src.colorinterp[band - 1] == ColorInterp.palette and src.colormap(band) != check.colormap(band):
            raise ValueError('Raster readback changed the color table.')
        if check.overviews(band) != expected_overviews:
            raise ValueError('Raster readback changed the requested overview levels.')
    for band, domains in tags.items():
        for namespace, values in domains.items():
            actual = check.tags(band, ns=namespace)
            if any(actual.get(key) != value for key, value in values.items()):
                raise ValueError(f'Raster readback changed metadata in band {band}, domain {namespace!r}.')
    actual_compression = 'none' if check.compression is None else check.compression.name.lower()
    if actual_compression != options['compression']:
        raise ValueError('The raster driver did not apply the selected compression.')
    if options['driver'] == 'COG' and check.tags(ns='IMAGE_STRUCTURE').get('LAYOUT') != 'COG':
        raise ValueError('The final file is not marked as a cloud-optimized GeoTIFF by GDAL.')
    restored, exact_nodata = _auxiliary_metadata(check)
    if not all(_equal_number(value, options['nodata']) for value in exact_nodata):
        raise ValueError('The exact GDAL NoData metadata differs after raster conversion.')
    if set(semantic) != set(restored):
        raise ValueError('Raster readback changed category names or raster attribute tables.')
    for band, entries in semantic.items():
        if (set(entries) != set(restored[band])
                or any(_xml_signature(node) != _xml_signature(restored[band][name])
                       for name, node in entries.items())):
            raise ValueError(f'Raster readback changed category names or raster attribute table in band {band}.')
    return restored, exact_nodata


def convert_raster(source, destination, *, driver='GTiff', dtype=None,
                   nodata='preserve', compression='lzw', block_size=512,
                   overviews=None, resampling='nearest', loss_policy='error',
                   progress=None, cancel=None):
    """Convert one raster to a verified GeoTIFF or COG in a new directory.

    The source grid and band order never change. ``dtype=None`` and
    ``nodata='preserve'`` retain the original representation. ``nodata=None``
    removes the sentinel while retaining validity in a common internal mask
    or an existing alpha band; differing band masks need a numeric sentinel.
    ``nodata='nan'`` is suitable for JSON plans.

    ``loss_policy='report'`` permits finite numeric quantization, with
    round-to-nearest, ties-to-even for integer outputs. It never permits
    overflow, a valid sample colliding with NoData, or a different mask/grid.
    Bands with category names or a GDAL raster attribute table retain all
    stored class codes, including masked ones; their quantization is refused.
    Those classification structures are preserved in a listed PAM companion.
    Reduced-resolution previews use ``overviews`` (None preserves source
    factors, [] removes them); their resampling does not affect base pixels.
    """
    if loss_policy not in {'error', 'report'}:
        raise ValueError("loss_policy must be 'error' or 'report'.")
    if (isinstance(block_size, bool) or not isinstance(block_size, int)
            or block_size < 128 or block_size > 4096 or block_size % 16):
        raise ValueError('block_size must be a multiple of 16 between 128 and 4096.')
    if resampling not in _RESAMPLING:
        raise ValueError('Unsupported overview resampling method.')
    _check_cancel(cancel)
    destination = Path(destination).expanduser().resolve()
    source_label = str(source)
    with rasterio.open(source) as src:
        semantic, source_nodata = _auxiliary_metadata(src)
        options = _options(src, driver=driver, dtype=dtype, nodata=nodata, compression=compression,
                           source_nodata=source_nodata)
        source_description = _description(src, source_label, nodata_values=source_nodata, semantic=semantic)
        factors = _overview_factors(src, overviews)
        common_mask = options['nodata'] is None and not options['alpha_mask']
        blocks = math.ceil(src.width / block_size) * math.ceil(src.height / block_size)
        total = blocks * 2
        if progress:
            progress(0, total)
        losses = [dict(band=band, valid_samples=0, invalid_samples=0,
                       changed_samples=0, max_absolute_error=0.0, nonfinite_valid_samples=0)
                  for band in src.indexes]
        with new_directory(destination) as work:
            data_path = work / 'data.tif'
            stage = work / '_staging.tif' if options['driver'] == 'COG' else data_path
            profile = dict(driver='GTiff', width=src.width, height=src.height,
                count=src.count, crs=src.crs, transform=src.transform,
                dtype=options['dtype'], nodata=options['nodata'], tiled=True,
                blockxsize=block_size, blockysize=block_size, BIGTIFF='IF_SAFER')
            if options['compression'] != 'none':
                profile['compress'] = options['compression']
            any_changed = False
            with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=True):
                with rasterio.open(stage, 'w', **profile) as dst:
                    _write_band_layout(src, dst)
                    for index, window in enumerate(_windows(src.width, src.height, block_size), 1):
                        _check_cancel(cancel)
                        masks = src.read_masks(window=window)
                        if common_mask:
                            if any(not np.array_equal(masks[0], mask) for mask in masks[1:]):
                                raise ValueError('Different per-band validity masks need a numeric NoData sentinel; '
                                                 'removing it cannot use a common internal mask.')
                            if np.any((masks[0] != 0) & (masks[0] != 255)):
                                raise ValueError('Nonbinary masks require a preserved alpha band.')
                            dst.write_mask(masks[0], window=window)
                        for band in src.indexes:
                            values = src.read(band, window=window)
                            valid = masks[band - 1] != 0
                            converted = _convert_samples(values[valid], options['dtype'], loss_policy)
                            sentinel = options['nodata']
                            if sentinel is not None:
                                collision = np.isnan(converted) if np.isnan(sentinel) else converted == sentinel
                                if np.any(collision):
                                    raise ValueError('The requested NoData collides with valid samples after conversion; '
                                                     'choose another sentinel or retain a mask.')
                            any_changed |= bool(np.any(_changed_values(values[valid], converted)))
                            # Values beneath an invalid mask have no data meaning.
                            # Their storage is normalized to NoData (or zero).
                            output = np.full(values.shape, 0 if sentinel is None else sentinel,
                                             dtype=options['dtype'])
                            output[valid] = converted
                            if band in semantic:
                                # Category labels and RAT rows refer to stored
                                # codes. Preserve even masked codes, and never
                                # authorize their quantization through report.
                                try:
                                    output = _convert_samples(values, options['dtype'], 'error')
                                except ValueError as exc:
                                    raise ValueError('Category names/raster attribute tables require unchanged '
                                                     'class values, including masked values; quantization is refused.') from exc
                                if sentinel is not None and np.any(~valid):
                                    invalid_values = output[~valid]
                                    matches = (np.isnan(invalid_values) if np.isnan(sentinel)
                                               else invalid_values == sentinel)
                                    if not np.all(matches):
                                        raise ValueError('Changing NoData would change stored class codes referenced '
                                                         'by category names or a raster attribute table.')
                            dst.write(output, band, window=window)
                        if progress:
                            progress(index, total)
                    tags, discarded = _metadata(src, remove_statistics=any_changed)
                    _write_metadata(src, dst, tags)
                    _check_cancel(cancel)
                    if factors:
                        dst.build_overviews(factors, Resampling[resampling])
                    expected_overviews = dst.overviews(1)
                _check_cancel(cancel)
                if options['driver'] == 'COG':
                    raster_copy(stage, data_path, driver='COG',
                        COMPRESS=options['compression'].upper(), BLOCKSIZE=block_size,
                        BIGTIFF='IF_SAFER', RESAMPLING=resampling.upper(),
                        COPY_SRC_MDD='YES',
                        OVERVIEWS='FORCE_USE_EXISTING' if factors else 'NONE')
                    _check_cancel(cancel)
            _complete_pam_metadata(data_path, tags, semantic)
            # Independent reads of the published representation, including
            # COG rather than only its staging input, are mandatory.
            with rasterio.open(data_path) as check:
                restored_semantic, exact_output_nodata = _verify_metadata(
                    src, check, options, tags, expected_overviews, semantic)
                for index, window in enumerate(_windows(src.width, src.height, block_size), 1):
                    _check_cancel(cancel)
                    before_masks = src.read_masks(window=window)
                    after_masks = check.read_masks(window=window)
                    if not np.array_equal(before_masks, after_masks):
                        raise ValueError('Raster readback changed a per-band validity/alpha mask.')
                    for band in src.indexes:
                        valid = before_masks[band - 1] != 0
                        source_values = src.read(band, window=window)
                        output_values = check.read(band, window=window)
                        if band in semantic:
                            all_expected = _convert_samples(source_values, options['dtype'], 'error')
                            if not np.all(_same_array(all_expected, output_values)):
                                raise ValueError('Raster readback changed a stored code referenced by classification metadata.')
                        original = source_values[valid]
                        actual = output_values[valid]
                        expected = _convert_samples(original, options['dtype'], loss_policy)
                        if not np.all(_same_array(expected, actual)):
                            raise ValueError(f'Raster readback changed pixel values in band {band}.')
                        changed = _changed_values(original, actual)
                        stats = losses[band - 1]
                        stats['valid_samples'] += int(valid.sum())
                        stats['invalid_samples'] += int(valid.size - valid.sum())
                        stats['changed_samples'] += int(changed.sum())
                        stats['max_absolute_error'] = max(stats['max_absolute_error'],
                                                         _max_error(original, actual, changed))
                        stats['nonfinite_valid_samples'] += int((~np.isfinite(original)).sum())
                    if progress:
                        progress(blocks + index, total)
                output_description = _description(check, destination / 'data.tif',
                    nodata_values=exact_output_nodata, semantic=restored_semantic)
                layout = check.tags(ns='IMAGE_STRUCTURE').get('LAYOUT', 'tiled GeoTIFF')
                sidecars = [Path(name).name for name in check.files if Path(name) != data_path]
            if options['driver'] == 'COG':
                for suffix in ('', '.msk', '.aux.xml', '.ovr'):
                    Path(str(stage) + suffix).unlink(missing_ok=True)
            changed_count = sum(item['changed_samples'] for item in losses)
            summary = dict(schema='cartomize.raster_conversion.v1', verified=True,
                driver=options['driver'], dtype=options['dtype'], nodata=_number(options['nodata']),
                compression=options['compression'], width=src.width, height=src.height,
                bands=src.count, changed_samples=changed_count,
                valid_samples=sum(item['valid_samples'] for item in losses),
                invalid_samples=sum(item['invalid_samples'] for item in losses),
                loss_policy=loss_policy, lossless=changed_count == 0,
                max_absolute_error=max((item['max_absolute_error'] for item in losses), default=0.0),
                layout=layout, overview_factors=expected_overviews,
                auxiliary_files=sidecars, self_contained=not sidecars,
                classification_metadata_verified=True,
                classification_metadata=_semantic_description(semantic),
                metadata_verified=True, masks_verified=True, grid_verified=True)
            report = dict(schema='cartomize.raster_conversion_report.v1', source=source_description,
                output=output_description, summary=summary, bands=losses,
                requested=dict(driver=options['driver'], dtype=options['dtype'],
                    nodata=_number(options['nodata']), compression=options['compression'],
                    block_size=block_size, overviews=factors, overview_resampling=resampling,
                    loss_policy=loss_policy),
                changes=dict(numeric_quantization=changed_count, discarded_stale_statistics=discarded,
                             invalid_sample_storage=('Original codes retained in bands with categories/RAT; '
                                 + ('NoData sentinel' if options['nodata'] is not None else 'zero beneath mask')
                                 + ' in other bands.'),
                             overview_pixels='Rebuilt from full-resolution values using the requested resampling.'),
                sidecars=sidecars,
                verification=dict(full_resolution_samples='all', per_band_masks='all',
                                  metadata='CRS, affine grid, band count/order, dtype, NoData, labels, units, '
                                           'scales, offsets, color interpretation, palettes, category names, '
                                           'raster attribute tables and exposed GDAL tags',
                                  gdal_version=rasterio.__gdal_version__, rasterio_version=rasterio.__version__))
            _check_cancel(cancel)
            save_json(report, work / 'report.json')
            save_json(dict(schema='cartomize.raster_conversion.v1', summary=summary,
                products=dict(data=str(destination / 'data.tif'), report=str(destination / 'report.json')),
                files=[str(destination / 'data.tif'),
                       *[str(destination / name) for name in sidecars],
                       str(destination / 'report.json'), str(destination / 'manifest.json')],
                source=source_label), work / 'manifest.json')
            _check_cancel(cancel)
    return ConvertedRaster(destination / 'manifest.json', destination / 'data.tif',
                           destination / 'report.json', summary)
