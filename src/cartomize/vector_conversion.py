"""Convert a selected vector layer and verify the complete reopened delivery.

The four supported output drivers are deliberately explicit. Conversion never
reprojects, repairs, dissolves or drops features. A successful publication has
been reopened and compared cell by cell and geometry by geometry. The default
policy rejects differences; the opt-in report policy records representational
changes without permitting lost features, changed coordinates or a changed CRS.
"""
from dataclasses import dataclass
from datetime import date, datetime
import codecs
import hashlib
from pathlib import Path
import warnings

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
from pyproj import CRS
import shapely

from .imagery import _check_cancel
from .storage import new_directory, save_json
from .vector_io import (FIELD_TYPES, _field_array, _has_standalone_ring,
                        field_kind, is_missing, read_vector, write_geopackage)
from .vector_reprojection import _reject_measured_input


_FORMATS = {'GPKG': '.gpkg', 'GeoJSON': '.geojson',
            'ESRI Shapefile': '.shp', 'FlatGeobuf': '.fgb'}


@dataclass(frozen=True)
class ConvertedVector:
    """Verified delivery, manifest and exhaustive conversion report."""

    manifest: Path
    data: Path
    report: Path
    summary: dict


class VectorConversionError(ValueError):
    """A failed comparison; its report is available without publishing files."""

    def __init__(self, message, report):
        super().__init__(message)
        self.report = report


def vector_conversion_formats():
    """Return the supported drivers and their installed read/write capability."""
    installed = pyogrio.list_drivers()
    return [dict(driver=name, extension=extension,
                 available='r' in installed.get(name, '') and 'w' in installed.get(name, ''),
                 encodings='configurable' if name == 'ESRI Shapefile' else 'UTF-8')
            for name, extension in _FORMATS.items()]


def _format(driver, encoding):
    if not isinstance(driver, str) or driver not in _FORMATS:
        raise ValueError('driver must be one of: ' + ', '.join(_FORMATS))
    capabilities = pyogrio.list_drivers().get(driver, '')
    if 'r' not in capabilities or 'w' not in capabilities:
        raise ValueError(f'The installed GDAL driver {driver!r} must support reading and writing.')
    if not isinstance(encoding, str) or not encoding.strip():
        raise ValueError('encoding must name a character encoding.')
    try:
        codec = codecs.lookup(encoding)
    except LookupError as exc:
        raise ValueError(f'Unknown character encoding: {encoding}') from exc
    if driver != 'ESRI Shapefile' and codec.name != 'utf-8':
        raise ValueError(f'{driver} requires UTF-8 encoding; another encoding cannot be applied silently.')
    return 'UTF-8' if codec.name == 'utf-8' else codec.name


def _layers(source):
    if not isinstance(source, (str, Path)):
        raise ValueError('source must be the path of an existing vector file.')
    path = Path(source).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f'Vector source not found: {path}')
    with _reject_measured_input():
        layers = [dict(name=str(name), geometry_type=None if geometry is None else str(geometry))
                  for name, geometry in pyogrio.list_layers(path)]
    if not layers:
        raise ValueError('The source contains no readable layers.')
    return path, layers


def _selection(layers, layer, *, required):
    names = [item['name'] for item in layers]
    if layer is None:
        if len(layers) != 1:
            if required:
                raise ValueError('Select layer explicitly from this multilayer source: ' + ', '.join(names))
            return None
        layer = names[0]
    if not isinstance(layer, str) or layer not in names:
        raise ValueError('layer must be an existing layer name: ' + ', '.join(names))
    if next(item['geometry_type'] for item in layers if item['name'] == layer) is None:
        raise ValueError('Select a spatial vector layer; a nonspatial table is not a vector delivery.')
    return layer


def _columns(data):
    columns = [name for name in data.columns if name != data.geometry.name]
    if (len(set(data.columns)) != len(data.columns)
            or any(not isinstance(name, str) or not name.strip() or '\x00' in name for name in columns)):
        raise ValueError('Source field names must be distinct, nonempty strings without NUL characters.')
    return columns


def _mapping(data, field_map):
    columns = _columns(data)
    if field_map is None:
        field_map = {}
    if not isinstance(field_map, dict) or set(field_map) - set(columns):
        raise ValueError('field_map must map existing source field names to output field names.')
    mapping = {name: field_map.get(name, name) for name in columns}
    if any(not isinstance(name, str) or not name.strip() or '\x00' in name for name in mapping.values()):
        raise ValueError('Each output field name must be a nonempty string; conversion does not drop fields.')
    if len({name.casefold() for name in mapping.values()}) != len(mapping):
        raise ValueError('Output field names must be distinct without regard to case.')
    return mapping


def _read(path, layer):
    with _reject_measured_input():
        info = pyogrio.read_info(path, layer=layer)
        # A GeoJSON properties.id can be both an OGR attribute and its native
        # FID. Asking Arrow to use FIDs as the dataframe index can consume that
        # business field. Read attributes without an index, then obtain native
        # identifiers independently; never infer attribute fidelity from an
        # already reduced dataframe schema.
        data = read_vector(path, layer=layer, fid_as_index=False)
        _, fids, _, _ = pyogrio.raw.read(path, layer=layer, columns=[],
                                       read_geometry=False, return_fids=True)
    if not isinstance(data, gpd.GeoDataFrame) or data.crs is None:
        raise ValueError('A vector conversion requires a spatial layer with a known source CRS.')
    declared = [str(name) for name in info['fields']]
    actual = _columns(data)
    if actual != declared:
        missing = [name for name in declared if name not in actual]
        raise ValueError('The source reader did not preserve every declared attribute in order'
                         + (': ' + ', '.join(missing) if missing else '.')
                         + ' No conversion may be published.')
    if len(data) != len(fids):
        raise ValueError('The source attribute and native FID reads disagree on feature count.')
    data.index = pd.Index(fids, name='fid')
    if 'M' in str(info.get('geometry_type', '')).replace('Multi', ''):
        raise ValueError('Measured (M) coordinates are not supported by this conversion writer.')
    geometries = data.geometry.to_numpy()
    if hasattr(shapely, 'has_m') and np.any(shapely.has_m(geometries)):
        raise ValueError('Measured (M) coordinates must not be discarded by conversion.')
    for geometry in geometries:
        if _has_standalone_ring(geometry):
            raise ValueError('Standalone LinearRing geometries require an explicit geometry conversion first.')
        if geometry is not None and not geometry.is_empty:
            coords = shapely.get_coordinates(geometry, include_z=bool(geometry.has_z))
            if not np.isfinite(coords).all():
                raise ValueError('All geometry coordinates must be finite before conversion.')
    return data, info


def _kinds(data):
    hints = {**data.attrs.get('_cartomize_declared_fields', {}),
             **data.attrs.get('_cartomize_temporal_fields', {})}
    kinds = {name: field_kind(data[name], hints.get(name)) for name in _columns(data)}
    if any(kind not in FIELD_TYPES for kind in kinds.values()):
        raise ValueError('Mixed, binary or structured fields require explicit preparation before conversion.')
    return kinds


def _scalar(value):
    if is_missing(value):
        return None
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return _scalar(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return repr(value)
    return value


def _profile(data, info, mapping=None):
    kinds = _kinds(data)
    mapping = mapping or {name: name for name in kinds}
    physical = {str(name): dict(ogr_type=str(ogr), ogr_subtype=str(subtype))
                for name, ogr, subtype in zip(info['fields'], info['ogr_types'], info['ogr_subtypes'])}
    return dict(feature_count=len(data), crs=CRS(data.crs).to_string(),
        crs_wkt=CRS(data.crs).to_wkt(),
        fields=[dict(name=name, target=mapping[name], type=kind, dtype=str(data[name].dtype),
                     null_count=sum(is_missing(value) for value in data[name]), **physical.get(name, {}))
                for name, kind in kinds.items()],
        geometry_types={str(key): int(value) for key, value in data.geom_type.value_counts().items()},
        missing_geometries=int(data.geometry.isna().sum()), empty_geometries=int(data.geometry.is_empty.sum()),
        z_features=int(np.sum(shapely.has_z(data.geometry.to_numpy()))))


def _preflight(data, mapping, driver, encoding):
    kinds = _kinds(data)
    issues = []
    for name, target in mapping.items():
        try:
            target.encode(encoding, errors='strict')
            for value in data[name]:
                if isinstance(value, str):
                    if '\x00' in value:
                        raise ValueError('NUL characters cannot be preserved in text fields.')
                    value.encode(encoding, errors='strict')
        except UnicodeEncodeError as exc:
            raise ValueError(f'Field {name!r} or its values cannot be represented in {encoding}.') from exc
        if driver == 'ESRI Shapefile':
            if len(target.encode(encoding)) > 10:
                issues.append(dict(kind='field_name', field=name, target=target,
                    message='The Shapefile DBF field name exceeds ten encoded bytes; supply field_map or report driver renaming.'))
            if kinds[name] in {'datetime', 'datetime_utc'}:
                issues.append(dict(kind='field_type', field=name, target=target,
                    message='Shapefile cannot represent datetime; report policy explicitly stores ISO-8601 text.'))
            if kinds[name] == 'boolean':
                issues.append(dict(kind='field_type', field=name, target=target,
                    message='Shapefile may expose boolean values as integer values after reopening.'))
            if kinds[name] == 'string' and any(isinstance(value, str) and len(value.encode(encoding)) > 254 for value in data[name]):
                issues.append(dict(kind='field_width', field=name, target=target,
                    message='A string exceeds the Shapefile DBF limit of 254 encoded bytes.'))
    return issues


def inspect_vector_conversion(source, *, layer=None, driver='GPKG', encoding='UTF-8', field_map=None):
    """Inspect source layers, fields and known output-format restrictions.

    A multilayer source without ``layer`` returns choices and no selected
    fields. ``convert_vector`` requires an explicit selection in that case.
    Inspection does not write any file and does not replace output verification.
    """
    encoding = _format(driver, encoding)
    path, layers = _layers(source)
    selected = _selection(layers, layer, required=False)
    result = dict(schema='cartomize.vector_conversion_inspection.v1', source=str(path),
                  layers=layers, selected_layer=selected, driver=driver, encoding=encoding,
                  fields=[], feature_count=None, source_crs=None, geometry_types={}, issues=[])
    if selected is None:
        if field_map:
            raise ValueError('Select a layer before supplying a field_map.')
        return result
    data, info = _read(path, selected)
    mapping = _mapping(data, field_map)
    profile = _profile(data, info, mapping)
    result.update(profile)
    result['source_crs'] = profile['crs']
    result['issues'] = _preflight(data, mapping, driver, encoding)
    return result


def _mapped(data, mapping):
    # A business field called "geometry" must never replace the active geometry.
    geometry_name = '_cartomize_geometry'
    targets = {name.casefold() for name in mapping.values()}
    while geometry_name.casefold() in targets:
        geometry_name += '_'
    values = {target: data[name].copy() for name, target in mapping.items()}
    values[geometry_name] = gpd.GeoSeries(data.geometry.to_numpy(), index=data.index, crs=data.crs)
    result = gpd.GeoDataFrame(values, geometry=geometry_name, crs=data.crs)
    result.attrs = {key: {mapping.get(name, name): value for name, value in values.items()}
                    for key, values in data.attrs.items()
                    if key in {'_cartomize_declared_fields', '_cartomize_temporal_fields'}}
    return result


def _write(data, path, driver, encoding, output_layer, loss_policy, cancel):
    if driver == 'GPKG':
        return write_geopackage(data, path, layer=output_layer, cancel=cancel)
    kinds = _kinds(data)
    arrays, masks, offsets = [], [], {}
    for name, kind in kinds.items():
        _check_cancel(cancel)
        values = data[name].tolist()
        if driver == 'ESRI Shapefile' and kind in {'datetime', 'datetime_utc'}:
            if loss_policy != 'report':
                raise ValueError(f'Shapefile cannot preserve datetime field {name!r}; choose GeoPackage or explicit report policy.')
            values = [None if is_missing(value) else value.isoformat() for value in values]
            kind = 'string'
        array, mask = _field_array(values, kind)
        arrays.append(array)
        masks.append(mask)
        if kind == 'datetime_utc':
            offsets[name] = np.full(len(data), 100, dtype=np.int32)
    options = ({'SPATIAL_INDEX': 'NO'} if driver == 'FlatGeobuf' else
               # GDAL's 17-significant-figure "smart" formatting can trim
               # meaningful digits (48.863695000000696 -> 48.863695000001).
               # Eighteen figures avoid this heuristic, while -1 disables a
               # fixed decimal limit that would zero very small coordinates.
               {'RFC7946': 'NO', 'SIGNIFICANT_FIGURES': '18',
                'COORDINATE_PRECISION': '-1', 'WRITE_NAME': 'YES'} if driver == 'GeoJSON' else
               {'RESIZE': 'YES'})
    geometry_types = set(data.geom_type.dropna())
    if driver == 'ESRI Shapefile':
        families = {kind.replace('Multi', '') for kind in geometry_types}
        if len(families) > 1 or families & {'GeometryCollection', 'LinearRing'}:
            raise ValueError('A Shapefile requires one compatible geometry family; use another output format.')
    geometry_type = next(iter(geometry_types)) if len(geometry_types) == 1 else 'Unknown'
    if np.any(shapely.has_z(data.geometry.to_numpy())) and geometry_type != 'Unknown':
        geometry_type += ' Z'
    pyogrio.raw.write(path, shapely.to_wkb(data.geometry.to_numpy()), arrays, list(kinds),
        field_mask=masks, layer=output_layer, driver=driver, geometry_type=geometry_type,
        crs=CRS(data.crs).to_wkt(), promote_to_multi=False, encoding=encoding,
        layer_options=options, gdal_tz_offsets=offsets or None)
    return path


def _same_value(before, after):
    if is_missing(before) or is_missing(after):
        return is_missing(before) and is_missing(after)
    # Python's int/float equality checks large integer precision without an
    # intermediate floating cast. Dates and datetime strings remain distinct.
    # Normalize NumPy scalars first: np.int64 == float would otherwise use
    # NumPy promotion and could hide rounded DBF values above 2**53.
    if isinstance(before, np.generic):
        before = pd.Timestamp(before) if isinstance(before, np.datetime64) else before.item()
    if isinstance(after, np.generic):
        after = pd.Timestamp(after) if isinstance(after, np.datetime64) else after.item()
    try:
        return bool(before == after)
    except (TypeError, ValueError):
        return False


def _verify(before, after, before_info, after_info, mapping, cancel):
    if len(before) != len(after):
        raise ValueError('The output driver changed the feature count; no output may be published.')
    if after.crs is None or not CRS(before.crs).equals(CRS(after.crs), ignore_axis_order=True):
        raise ValueError('The output driver changed or removed the CRS; no output may be published.')
    source_fields, output_fields = _columns(before), _columns(after)
    if len(source_fields) != len(output_fields):
        raise ValueError('The output driver added or removed fields; an unambiguous field comparison is impossible.')
    before_kinds, after_kinds = _kinds(before), _kinds(after)
    differences, fields, rows = [], [], []
    for source_name, actual in zip(source_fields, output_fields):
        expected = mapping[source_name]
        item = dict(source=source_name, requested=expected, actual=actual,
                    source_type=before_kinds[source_name], output_type=after_kinds[actual],
                    changed_values=0, missing_before=0, missing_after=0)
        if expected != actual:
            differences.append(dict(kind='field_name', source_field=source_name,
                                    output_field=actual, before=expected, after=actual))
        if before_kinds[source_name] != after_kinds[actual]:
            differences.append(dict(kind='field_type', source_field=source_name,
                output_field=actual, before=before_kinds[source_name], after=after_kinds[actual]))
        for row, (left, right) in enumerate(zip(before[source_name], after[actual])):
            if row % 1000 == 0:
                _check_cancel(cancel)
            item['missing_before'] += is_missing(left)
            item['missing_after'] += is_missing(right)
            if not _same_value(left, right):
                item['changed_values'] += 1
                differences.append(dict(kind='attribute_value', source_row=row, output_row=row,
                    source_field=source_name, output_field=actual, before=_scalar(left), after=_scalar(right)))
        fields.append(item)
    for row, (left, right) in enumerate(zip(before.geometry, after.geometry)):
        if row % 1000 == 0:
            _check_cancel(cancel)
        same = left is None and right is None or left is not None and right is not None and left.wkb == right.wkb
        if not same:
            if (left is None or right is None or left.geom_type != right.geom_type
                    or shapely.normalize(left).wkb != shapely.normalize(right).wkb):
                raise ValueError(f'The output driver changed geometry coordinates, dimensions, type or null/empty state at row {row}.')
            differences.append(dict(kind='geometry_representation', source_row=row, output_row=row,
                                    before=left.wkb_hex, after=right.wkb_hex))
        rows.append(dict(source_row=row, source_fid=_scalar(before.index[row]),
                         output_row=row, output_fid=_scalar(after.index[row]),
                         geometry_identical=bool(same),
                         source_wkb_sha256=None if left is None else hashlib.sha256(left.wkb).hexdigest(),
                         output_wkb_sha256=None if right is None else hashlib.sha256(right.wkb).hexdigest()))
    return dict(schema='cartomize.vector_conversion_report.v1',
        source=_profile(before, before_info, mapping), output=_profile(after, after_info),
        field_correspondence=fields, rows=rows, differences=differences,
        difference_count=len(differences), checked_features=len(before),
        checked_attribute_values=len(before) * len(source_fields),
        crs_preserved=True, coordinates_preserved=True,
        exact_representation=not differences,
        row_order='Source order preserved; source_row/output_row are zero-based. Native FIDs are recorded separately.')


def convert_vector(source, destination, *, layer=None, driver='GPKG', encoding='UTF-8',
                   output_layer='features', field_map=None, loss_policy='error', progress=None, cancel=None):
    """Publish one converted vector layer and its exhaustive comparison report.

    ``destination`` is a new directory. ``field_map`` renames source fields;
    omitted fields retain their names and no field can be dropped. ``encoding``
    controls Shapefile output; the other formats require UTF-8. GeoJSON keeps
    the source CRS in its legacy CRS member (RFC7946 reprojection is disabled).

    ``loss_policy='error'`` rejects changed names, logical types, attribute
    values or geometry representation. Explicit ``'report'`` permits those
    recorded differences and ISO datetime text for Shapefile. Both policies
    refuse missing features/fields, CRS changes, and geometry-coordinate,
    dimension, type, null or empty changes. Every reopened value is compared.
    """
    _check_cancel(cancel)
    if loss_policy not in {'error', 'report'}:
        raise ValueError('loss_policy must be error or report.')
    encoding = _format(driver, encoding)
    if (not isinstance(output_layer, str) or not output_layer.strip()
            or '\x00' in output_layer or '/' in output_layer or '\\' in output_layer):
        raise ValueError('output_layer must be a nonempty layer name without path separators or NUL.')
    path, layers = _layers(source)
    selected = _selection(layers, layer, required=True)
    destination = Path(destination).expanduser().resolve()
    if destination == path or destination in path.parents:
        raise ValueError('The output directory cannot replace or contain the source file.')
    if destination.exists():
        raise FileExistsError('Choose a new output directory: ' + str(destination))
    if progress:
        progress(0, 4)
    _check_cancel(cancel)
    before, before_info = _read(path, selected)
    mapping = _mapping(before, field_map)
    preflight = _preflight(before, mapping, driver, encoding)
    transformed = _mapped(before, mapping)
    _check_cancel(cancel)
    if progress:
        progress(1, 4)
    filename = 'data' + _FORMATS[driver]
    with new_directory(destination) as work:
        _check_cancel(cancel)
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter('always')
            _write(transformed, work / filename, driver, encoding, output_layer, loss_policy, cancel)
        _check_cancel(cancel)
        if progress:
            progress(2, 4)
        # Shapefile uses the basename as its sole layer name; all formats are
        # reopened from the generated file, never from an in-memory writer.
        _, generated_layers = _layers(work / filename)
        if len(generated_layers) != 1:
            raise ValueError('The output must contain exactly the selected layer.')
        after, after_info = _read(work / filename, generated_layers[0]['name'])
        report = _verify(before, after, before_info, after_info, mapping, cancel)
        report.update(driver=driver, encoding=encoding, loss_policy=loss_policy,
                      preflight_issues=preflight, driver_warnings=[str(item.message) for item in captured])
        if report['difference_count'] and loss_policy == 'error':
            examples = '; '.join(item['kind'] +
                (f" ({item['source_field']})" if 'source_field' in item else f" (row {item['source_row']})")
                for item in report['differences'][:3])
            raise VectorConversionError(
                f"Conversion changed {report['difference_count']} field/value/geometry representations; "
                f'{examples}. No output was published. Inspect exception.report, choose another format, map field names, '
                'or explicitly select loss_policy=report.', report)
        if progress:
            progress(3, 4)
        _check_cancel(cancel)
        files = sorted(str(destination / child.relative_to(work)) for child in work.rglob('*') if child.is_file())
        manifest = dict(schema='cartomize.vector_conversion.v1', status='complete',
            source=str(path), source_layer=selected, output_layer=generated_layers[0]['name'],
            requested_output_layer=output_layer, driver=driver, encoding=encoding, loss_policy=loss_policy,
            field_map=mapping, feature_count=len(before), field_count=len(mapping),
            difference_count=report['difference_count'], exact_representation=report['exact_representation'],
            crs=CRS(before.crs).to_string(), crs_wkt=CRS(before.crs).to_wkt(),
            data=str(destination / filename), report=str(destination / 'report.json'),
            products=dict(data=str(destination / filename), report=str(destination / 'report.json')),
            files=files, verification=dict(features=len(before), attribute_values=report['checked_attribute_values'],
                coordinates_preserved=True, crs_preserved=True),
            environment=dict(geopandas=gpd.__version__, pyogrio=pyogrio.__version__,
                gdal='.'.join(map(str, pyogrio.__gdal_version__))))
        save_json(report, work / 'report.json')
        save_json(manifest, work / 'manifest.json')
        _check_cancel(cancel)
        if progress:
            progress(4, 4)
        _check_cancel(cancel)
    return ConvertedVector(destination / 'manifest.json', destination / filename,
                           destination / 'report.json', manifest)
