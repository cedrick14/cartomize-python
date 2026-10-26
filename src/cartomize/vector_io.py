"""Typed vector I/O without nullable-integer or timestamp coercion.

Arrow must use pandas nullable integer/boolean types: the default NumPy
reader, and Arrow's default pandas conversion, both turn nullable int64
columns into doubles. Datetimes are read as text before parsing so that
sub-millisecond precision and the distinction between naive and aware values
remain available for validation.
"""
from datetime import date, datetime
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyarrow as pa
import pyogrio
from pyproj import CRS
import shapely
from shapely.geometry import shape


FIELD_TYPES = ('string', 'int64', 'float64', 'boolean', 'date', 'datetime', 'datetime_utc')


def is_missing(value):
    if value is None or value is pd.NA or value is pd.NaT:
        return True
    if not pd.api.types.is_scalar(value):
        return False
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _nullable_type(arrow_type):
    return {
        pa.int8(): pd.Int8Dtype(), pa.int16(): pd.Int16Dtype(),
        pa.int32(): pd.Int32Dtype(), pa.int64(): pd.Int64Dtype(),
        pa.uint8(): pd.UInt8Dtype(), pa.uint16(): pd.UInt16Dtype(),
        pa.uint32(): pd.UInt32Dtype(), pa.uint64(): pd.UInt64Dtype(),
        pa.bool_(): pd.BooleanDtype(), pa.string(): pd.StringDtype(),
        pa.large_string(): pd.StringDtype(),
    }.get(arrow_type)


def read_vector(path, **kwargs):
    """Read with nullable integers and exact, individually parsed datetimes.

    Explicit engine, Arrow or datetime options remain caller choices. The
    lossless defaults are used by Cartomize's file-based vector operations.
    """
    if kwargs.get('engine', 'pyogrio') != 'pyogrio' or kwargs.get('use_arrow') is False:
        return gpd.read_file(path, **kwargs)
    options = dict(kwargs)
    options.setdefault('engine', 'pyogrio')
    options.setdefault('use_arrow', True)
    arrow_options = dict(options.get('arrow_to_pandas_kwargs') or {})
    arrow_options.setdefault('types_mapper', _nullable_type)
    options['arrow_to_pandas_kwargs'] = arrow_options
    restore_temporal = 'datetime_as_string' not in options
    options.setdefault('datetime_as_string', True)
    info = pyogrio.read_info(path, layer=options.get('layer'))
    if 'geometry' in info['fields'] or options.get('sql') is not None:
        # The standard adapter assigns df['geometry'], overwriting a
        # business field with that name. SQL also needs its own result
        # metadata: a query may rename a date or replace it with an integer.
        raw = dict(options)
        for name in ('engine', 'use_arrow', 'arrow_to_pandas_kwargs', 'mixed_offsets_as_utc'):
            raw.pop(name, None)
        invalid = raw.pop('on_invalid', 'raise')
        raw['return_fids'] = raw.pop('fid_as_index', False)
        if raw.pop('ignore_geometry', False):
            raw['read_geometry'] = False
        else:
            raw.setdefault('read_geometry', True)
        rows = raw.pop('rows', None)
        if rows is not None:
            if isinstance(rows, int):
                raw['max_features'] = rows
            elif isinstance(rows, slice) and rows.step in (None, 1):
                if rows.start is not None and rows.start < 0:
                    raise ValueError('Negative row slices are not supported.')
                raw['skip_features'] = rows.start or 0
                raw['max_features'] = None if rows.stop is None else rows.stop - raw['skip_features']
            else:
                raise ValueError('rows must be an integer or a forward slice with step 1.')
        bbox, mask = raw.get('bbox'), raw.get('mask')
        if bbox is not None and mask is not None:
            raise ValueError('mask and bbox cannot be set together.')
        if bbox is not None:
            if isinstance(bbox, (gpd.GeoDataFrame, gpd.GeoSeries)):
                bbox = tuple(bbox.to_crs(info['crs']).total_bounds)
            elif isinstance(bbox, shapely.Geometry):
                bbox = bbox.bounds
            if len(bbox) != 4:
                raise ValueError('bbox must contain four bounds.')
            raw['bbox'] = bbox
        if mask is not None:
            if isinstance(mask, (gpd.GeoDataFrame, gpd.GeoSeries)):
                if info['crs'] is not None and mask.crs is not None:
                    mask = mask.to_crs(info['crs'])
                mask = shapely.union_all(mask.geometry.to_numpy())
            elif isinstance(mask, dict) or hasattr(mask, '__geo_interface__'):
                mask = shape(mask)
            raw['mask'] = mask
        if 'ignore_fields' in raw and 'include_fields' in raw:
            raise ValueError('Cannot specify both ignore_fields and include_fields.')
        for alias in ('ignore_fields', 'include_fields'):
            if alias in raw:
                if raw.get('columns') is not None:
                    raise ValueError('Cannot combine columns with ' + alias + '.')
                selected = raw.pop(alias)
                raw['columns'] = ([name for name in info['fields'] if name not in selected]
                                  if alias == 'ignore_fields' else selected)
        info, table = pyogrio.read_arrow(path, **raw)
        result = table.to_pandas(**arrow_options)
        if raw['return_fids']:
            result = result.set_index(info['fid_column'])
            result.index.name = 'fid'
        name = info['geometry_name'] or 'wkb_geometry'
        if raw['read_geometry'] and name in result:
            values = shapely.from_wkb(result.pop(name).to_numpy(), on_invalid=invalid)
            active = 'geometry' if 'geometry' not in result else '_cartomize_geometry'
            while active.casefold() in {column.casefold() for column in result.columns}:
                active += '_'
            result[active] = values
            result = gpd.GeoDataFrame(result, geometry=active, crs=info['crs'])
    else:
        result = gpd.read_file(path, **options)
    declared = {}
    for name, ogr_type, subtype in zip(info['fields'], info['ogr_types'], info['ogr_subtypes']):
        declared[str(name)] = ('boolean' if subtype == 'OFSTBoolean' else {
            'OFTInteger': 'int64', 'OFTInteger64': 'int64', 'OFTReal': 'float64',
            'OFTString': 'string', 'OFTDate': 'date', 'OFTDateTime': 'datetime',
        }.get(ogr_type))
    result.attrs['_cartomize_declared_fields'] = declared
    if not restore_temporal:
        return result
    hints = {}
    for name, dtype in zip(info['fields'], info['dtypes']):
        if name not in result or not str(dtype).startswith('datetime64'):
            continue
        kind = 'date' if str(dtype) == 'datetime64[D]' else 'datetime'
        hints[str(name)] = kind
        values = []
        for value in result[name]:
            if is_missing(value):
                values.append(None)
            elif kind == 'date':
                values.append(date.fromisoformat(str(value)) if isinstance(value, str) else value)
            else:
                values.append(pd.Timestamp(value))
        # Object keeps mixed offsets and naive/aware values distinct. In
        # particular, it never silently interprets a naive timestamp as UTC.
        result[name] = pd.Series(values, index=result.index, dtype=object)
    if hints:
        result.attrs['_cartomize_temporal_fields'] = hints
    return result


def value_kind(value):
    if is_missing(value):
        return None
    if isinstance(value, (bool, np.bool_)):
        return 'boolean'
    if isinstance(value, (int, np.integer)):
        return 'int64'
    if isinstance(value, (float, np.floating)):
        return 'float64'
    if isinstance(value, (datetime, pd.Timestamp, np.datetime64)):
        stamp = pd.Timestamp(value)
        return 'datetime_utc' if stamp.tzinfo is not None else 'datetime'
    if isinstance(value, date):
        return 'date'
    if isinstance(value, str):
        return 'string'
    return 'unsupported'


def field_kind(series, hint=None):
    kinds = {value_kind(value) for value in series if not is_missing(value)}
    if kinds:
        if kinds <= {'int64', 'float64'}:
            return 'float64' if 'float64' in kinds else 'int64'
        return next(iter(kinds)) if len(kinds) == 1 and 'unsupported' not in kinds else None
    dtype = series.dtype
    if hint in FIELD_TYPES:
        return hint
    if pd.api.types.is_bool_dtype(dtype):
        return 'boolean'
    if pd.api.types.is_integer_dtype(dtype):
        return 'int64'
    if pd.api.types.is_float_dtype(dtype):
        return 'float64'
    if isinstance(dtype, pd.DatetimeTZDtype):
        return 'datetime_utc'
    if pd.api.types.is_datetime64_any_dtype(dtype):
        return 'datetime'
    return 'string'


def timestamp(value, *, utc=False):
    stamp = pd.Timestamp(value)
    if is_missing(stamp) or not 1 <= stamp.year <= 9999:
        raise ValueError('A timestamp must have a valid year between 1 and 9999.')
    if stamp.microsecond % 1000 or stamp.nanosecond:
        raise ValueError('GeoPackage datetime precision is milliseconds; sub-millisecond values must be normalized explicitly.')
    if utc:
        if stamp.tzinfo is None:
            raise ValueError('datetime_utc requires an explicit timezone; naive times are not assumed to be UTC.')
        return stamp.tz_convert('UTC')
    if stamp.tzinfo is not None:
        raise ValueError('datetime requires a naive timestamp; use datetime_utc for timezone-aware values.')
    return stamp


def _field_array(values, kind):
    mask = np.asarray([is_missing(value) for value in values], dtype=bool)
    filled = []
    for value, absent in zip(values, mask):
        if absent:
            filled.append({'string': None, 'int64': 0, 'float64': 0., 'boolean': False,
                           'date': '1970-01-01', 'datetime': '1970-01-01',
                           'datetime_utc': '1970-01-01'}[kind])
        elif kind == 'string':
            if not isinstance(value, str):
                raise ValueError('String fields must contain strings; request an explicit conversion first.')
            if '\x00' in value:
                raise ValueError('NUL characters cannot be preserved in a GeoPackage text field.')
            filled.append(value)
        elif kind == 'int64':
            if not isinstance(value, (int, np.integer)) or isinstance(value, (bool, np.bool_)):
                raise ValueError('Integer fields require exact integer values.')
            if not -(2**63) <= int(value) <= 2**63 - 1:
                raise ValueError('An integer is outside the signed int64 range.')
            filled.append(int(value))
        elif kind == 'float64':
            number = float(value)
            if not np.isfinite(number):
                raise ValueError('Real fields require finite numbers.')
            if isinstance(value, (int, np.integer)) and int(number) != int(value):
                raise ValueError('An integer cannot be represented exactly as float64.')
            filled.append(number)
        elif kind == 'boolean':
            if not isinstance(value, (bool, np.bool_)):
                raise ValueError('Boolean fields require boolean values.')
            filled.append(bool(value))
        elif kind == 'date':
            if not isinstance(value, date) or isinstance(value, datetime):
                raise ValueError('Date fields require dates without a time.')
            filled.append(value.isoformat())
        else:
            stamp = timestamp(value, utc=kind == 'datetime_utc')
            if stamp.tzinfo is not None:
                stamp = stamp.tz_localize(None)
            filled.append(stamp.to_datetime64())
    dtype = {'string': object, 'int64': np.int64, 'float64': np.float64,
             'boolean': np.bool_, 'date': 'datetime64[D]',
             'datetime': 'datetime64[ms]', 'datetime_utc': 'datetime64[ms]'}[kind]
    return np.asarray(filled, dtype=dtype), mask


def write_geopackage(data, path, *, types=None, layer='features', cancel=None):
    """Write typed scalar attributes and verify every value and geometry.

    The caller supplies an atomic destination directory. No field is routed
    through a floating intermediate and no datetime is silently rounded.
    """
    from .imagery import _check_cancel
    path = Path(path)
    if path.exists():
        raise FileExistsError(path)
    columns = [name for name in data.columns if name != data.geometry.name]
    folded = [str(name).casefold() for name in data.columns]
    if (len(set(folded)) != len(folded)
            or any(not isinstance(name, str) or not name.strip() or '\x00' in name for name in data.columns)
            or any(name.casefold() == 'geometry' for name in columns)):
        raise ValueError('GeoPackage attribute names must be nonempty, case-insensitively unique and distinct from geometry.')
    hints = {**data.attrs.get('_cartomize_declared_fields', {}),
             **data.attrs.get('_cartomize_temporal_fields', {})}
    kinds = {name: (types[name] if types is not None else field_kind(data[name], hints.get(name))) for name in columns}
    if any(kind not in FIELD_TYPES for kind in kinds.values()):
        raise ValueError('Mixed or structured attributes require an explicit scalar schema.')
    arrays, masks, offsets = [], [], {}
    for name in columns:
        _check_cancel(cancel)
        array, mask = _field_array(data[name].tolist(), kinds[name])
        arrays.append(array)
        masks.append(mask)
        if kinds[name] == 'datetime_utc':
            offsets[name] = np.full(len(data), 100, dtype=np.int32)
    fid = '_cartomize_fid'
    while fid.casefold() in folded:
        fid += '_'
    geometry_name = '_cartomize_geom'
    while geometry_name.casefold() in folded:
        geometry_name += '_'
    _check_cancel(cancel)
    geometries = data.geometry.to_numpy()
    pyogrio.raw.write(path, shapely.to_wkb(geometries), arrays, columns,
        field_mask=masks, layer=layer, driver='GPKG', geometry_type='Unknown',
        crs=CRS(data.crs).to_wkt(), promote_to_multi=False,
        layer_options={'FID': fid, 'GEOMETRY_NAME': geometry_name}, gdal_tz_offsets=offsets or None)
    _check_cancel(cancel)
    check = read_vector(path, layer=layer)
    if len(check) != len(data) or CRS(check.crs) != CRS(data.crs):
        raise ValueError('The written GeoPackage failed feature-count/CRS verification.')
    if [name for name in check.columns if name != check.geometry.name] != columns:
        raise ValueError('The output driver changed the attribute schema.')
    for before, after in zip(data.geometry, check.geometry):
        if ((before is None) != (after is None)
                or before is not None and (before.geom_type != after.geom_type or before.wkb != after.wkb)):
            raise ValueError('The output driver changed geometry types, dimensions or coordinates.')
    for name in columns:
        for before, after in zip(data[name], check[name]):
            if is_missing(before):
                equal = is_missing(after)
            else:
                equal = not is_missing(after) and before == after
            if not equal:
                raise ValueError(f'The output driver changed attribute {name!r}; no output may be published.')
    return path
