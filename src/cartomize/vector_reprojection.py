"""Discover and reproject vector layers with an explicit geodetic audit.

This is a horizontal, static-CRS workflow. Coordinates use GIS x/y order;
existing Z ordinates are carried unchanged, not treated as surveyed heights.
One selected PROJ operation is used for every feature of a layer. The whole
batch is published atomically, with no implicit repair or dropped features.
"""
from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import warnings

import geopandas as gpd
import numpy as np
import pandas as pd
import pyproj
from pyproj import CRS, Transformer
from pyproj.aoi import AreaOfInterest
from pyproj.transformer import TransformerGroup
import pyogrio
import shapely

from .imagery import _check_cancel
from .storage import new_directory, save_json
from .vector_quality import _finite_geometry
from .vector_io import read_vector


@dataclass(frozen=True)
class ReprojectedBatch:
    """Reopenable files and the complete per-layer transformation manifest."""

    manifest: Path
    report: Path
    layers: dict[str, Path]
    summary: dict


_EXTENSIONS = {'.gpkg', '.shp', '.geojson', '.fgb', '.gml', '.kml', '.sqlite'}


@contextmanager
def _reject_measured_input():
    # GDAL can expose M geometries that pyogrio converts to XY/XYZ before
    # Shapely receives them. Reject that conversion at the reader boundary.
    with warnings.catch_warnings():
        warnings.filterwarnings('error', message=r'.*[Mm]easured.*geometry types.*')
        try:
            yield
        except UserWarning as exc:
            raise ValueError('Measured M ordinates in this input are unsupported and must not be discarded.') from exc


def _horizontal_crs(value, label):
    if value is None:
        raise ValueError(f'{label} has no CRS. Declare its actual source CRS before processing.')
    crs = CRS.from_user_input(value)
    horizontal = crs.source_crs if crs.is_bound else crs
    if (horizontal.is_compound or len(horizontal.axis_info) != 2
            or not (horizontal.is_geographic or horizontal.is_projected)):
        raise ValueError(f'{label}: only horizontal 2D geographic/projected CRSs are supported; '
                         'vertical, compound, geocentric and 3D CRSs require a separate workflow.')
    if horizontal.datum and 'dynamic' in horizontal.datum.type_name.lower():
        raise ValueError(f'{label}: a dynamic CRS requires coordinate epochs and is not supported here.')
    return crs


def _bounds(data):
    coordinates = shapely.get_coordinates(data.geometry.to_numpy())
    if not len(coordinates):
        return None
    if not np.isfinite(coordinates).all():
        raise ValueError('Geometry coordinates must be finite before reprojection.')
    return [float(coordinates[:, 0].min()), float(coordinates[:, 1].min()),
            float(coordinates[:, 0].max()), float(coordinates[:, 1].max())]


def _layer_id(token, name):
    slug = re.sub(r'[^a-zA-Z0-9_]+', '_', str(name)).strip('_')[:36] or 'layer'
    if not slug[0].isalpha():
        slug = 'layer_' + slug
    return slug + '_' + hashlib.sha256(token.encode('utf-8')).hexdigest()[:12]


def _entries(sources, recursive):
    if isinstance(sources, (str, Path, dict, gpd.GeoDataFrame, gpd.GeoSeries)):
        sources = [sources]
    if not isinstance(sources, (list, tuple)) or not sources:
        raise ValueError('sources must contain at least one vector file, directory or layer.')
    for number, item in enumerate(sources, 1):
        if isinstance(item, (gpd.GeoDataFrame, gpd.GeoSeries)):
            yield {'data': item, 'name': f'memory_{number}'}
            continue
        if isinstance(item, dict):
            extra = set(item) - {'path', 'layer', 'name', 'data'}
            if extra or ('path' in item) == ('data' in item):
                raise ValueError('A layer descriptor requires path or data, with optional layer/name.')
            if 'data' in item:
                if not isinstance(item['data'], (gpd.GeoDataFrame, gpd.GeoSeries)):
                    raise ValueError('In-memory data must be a GeoDataFrame or GeoSeries.')
                yield {**item, 'name': item.get('name', f'memory_{number}')}
                continue
            record = dict(item)
        elif isinstance(item, (str, Path)):
            record = {'path': item}
        else:
            raise ValueError('Each source must be a local path, a layer descriptor or geospatial data.')
        path = Path(record['path']).expanduser().resolve()
        if path.is_dir():
            if record.get('layer') is not None:
                raise ValueError('A layer name can only select a layer in one file.')
            paths = path.rglob('*') if recursive else path.iterdir()
            for child in sorted(paths, key=lambda p: str(p).casefold()):
                if child.is_file() and child.suffix.lower() in _EXTENSIONS:
                    yield {'path': child.resolve()}
        else:
            if not path.is_file():
                raise FileNotFoundError(f'Vector source not found: {path}')
            if path.suffix.lower() not in _EXTENSIONS | {'.json'}:
                raise ValueError(f'Unsupported vector input format: {path.suffix}')
            yield {**record, 'path': path}


def _discover(sources, recursive=False):
    if not isinstance(recursive, bool):
        raise ValueError('recursive must be a boolean.')
    layers, seen, ids = [], set(), set()
    for number, item in enumerate(_entries(sources, recursive), 1):
        if 'data' in item:
            data = item['data']
            if isinstance(data, gpd.GeoSeries):
                data = gpd.GeoDataFrame(geometry=data)
            crs = _horizontal_crs(data.crs, item['name'])
            token = f'memory:{number}:{item["name"]}'
            record = dict(id=_layer_id(token, item['name']), name=str(item['name']),
                          path=None, layer=None, source_crs=crs.to_string(),
                          features=len(data), bounds=_bounds(data), _data=data.copy())
            layers.append(record)
            continue
        path = item['path']
        with warnings.catch_warnings():
            # read_info below checks each selected spatial layer separately;
            # an unselected M layer must not block a selected ordinary layer.
            warnings.filterwarnings('ignore', message=r'.*[Mm]easured.*geometry types.*')
            available = pyogrio.list_layers(path)
        selected = item.get('layer')
        if selected is not None and not isinstance(selected, str):
            raise ValueError('layer must be a layer name, not a numeric index.')
        found = False
        for name, geometry_type in available:
            if selected is not None and str(name) != selected:
                continue
            if geometry_type is None:
                if selected is not None:
                    raise ValueError(f'{path}: {selected} is an attribute table, not a spatial layer.')
                continue
            found = True
            token = str(path) + '\n' + str(name)
            if token in seen:
                continue
            seen.add(token)
            with _reject_measured_input():
                info = pyogrio.read_info(path, layer=str(name), force_feature_count=True,
                                         force_total_bounds=True)
            crs = _horizontal_crs(info['crs'], f'{path} / {name}')
            title = str(item.get('name') or name)
            ident = _layer_id(token, title)
            if ident in ids:
                raise ValueError('Vector layer identifiers collide; choose distinct names.')
            ids.add(ident)
            extent = info.get('total_bounds')
            bounds = list(map(float, extent)) if extent is not None and np.isfinite(extent).all() else None
            layers.append(dict(id=ident, name=title, path=str(path), layer=str(name),
                               source_crs=crs.to_string(), features=int(info['features']), bounds=bounds))
        if selected is not None and not found:
            raise ValueError(f'Unknown spatial layer {selected!r} in {path}.')
    if not layers:
        raise ValueError('No spatial vector layers were discovered in the supplied sources.')
    return layers


def _public(record):
    return {key: value for key, value in record.items() if not key.startswith('_')}


def discover_vector_layers(sources, *, recursive=False):
    """Discover every spatial layer, including all layers in a GeoPackage.

    ``sources`` accepts local files/directories, lists, ``{path, layer}``
    selectors, GeoDataFrames/GeoSeries or ``{data, name}`` descriptors.
    Directories include common vector extensions, not arbitrary JSON files;
    a GeoJSON named .json can be supplied explicitly. Nonspatial tables and
    repeated file/layer inputs are omitted. No CRS is guessed or assigned.
    IDs are stable for the same file path and layer; in-memory IDs also depend
    on input order. The returned dictionaries contain no in-memory data.
    """
    return [_public(record) for record in _discover(sources, recursive)]


def _read(record):
    with _reject_measured_input():
        data = (record['_data'].copy() if '_data' in record else
                read_vector(record['path'], layer=record['layer']))
    _horizontal_crs(data.crs, record['name'])
    if CRS(data.crs) != CRS(record['source_crs']) or len(data) != record['features']:
        raise ValueError(f'{record["name"]}: the source CRS or feature count changed during discovery; inspect it again.')
    if hasattr(shapely, 'has_m') and np.any(shapely.has_m(data.geometry.to_numpy())):
        raise ValueError(f'{record["name"]}: measured M ordinates are not supported; they must not be discarded.')
    for position, geometry in enumerate(data.geometry):
        if _has_standalone_ring(geometry):
            raise ValueError(f'{record["name"]}: standalone LinearRing features cannot be stored safely; '
                             'construct a LineString or Polygon explicitly.')
        if not _finite_geometry(geometry):
            raise ValueError(f'{record["name"]}: non-finite geometry coordinates at source row {position}.')
    return data


def _has_standalone_ring(geometry):
    if geometry is None:
        return False
    if geometry.geom_type == 'LinearRing':
        return True
    if hasattr(geometry, 'geoms'):
        return any(_has_standalone_ring(part) for part in geometry.geoms)
    return False


def _geographic_xy(data):
    """Approximate geographic position without selecting a datum shift.

    Invert the source projection, then normalize source angular units and its
    prime meridian. These coordinates use the source datum, not transformed
    WGS84 coordinates; this is explicitly recorded for domain/AOI screening.
    """
    coordinates = shapely.get_coordinates(data.geometry.to_numpy())
    if not len(coordinates):
        return np.empty((0, 2))
    source = CRS(data.crs)
    horizontal = source.source_crs if source.is_bound else source
    geographic = horizontal.geodetic_crs
    converter = Transformer.from_crs(horizontal, geographic, always_xy=True)
    lon, lat = converter.transform(coordinates[:, 0], coordinates[:, 1], errcheck=True)
    factors = {axis.direction: axis.unit_conversion_factor * 180. / np.pi
               for axis in geographic.axis_info}
    if 'east' not in factors or 'north' not in factors:
        raise ValueError('Geographic CRS axes must have east/north directions for area screening.')
    lon, lat = np.asarray(lon) * factors['east'], np.asarray(lat) * factors['north']
    if not np.isfinite([lon, lat]).all() or np.any(np.abs(lat) > 90. + 1e-9):
        raise ValueError('Source coordinates lie outside the finite geographic latitude domain.')
    if np.any(np.abs(lon) > 180. + 1e-9):
        raise ValueError('Source longitudes lie outside [-180, 180] degrees; normalize them explicitly.')
    meridian = geographic.prime_meridian
    lon = lon + meridian.longitude * meridian.unit_conversion_factor * 180. / np.pi
    normalized = (lon + 180.) % 360. - 180.
    # Keep the eastern endpoint on its original side of the cut. Turning
    # +180 into -180 would invent a discontinuity in a 179 -> 180 segment.
    lon = np.where((np.abs(normalized + 180.) < 1e-10) & (lon > 0), 180., normalized)
    return np.column_stack([lon, np.clip(lat, -90., 90.)])


def _geographic_bounds(coordinates):
    if not len(coordinates):
        return None
    return [float(coordinates[:, 0].min()), float(coordinates[:, 1].min()),
            float(coordinates[:, 0].max()), float(coordinates[:, 1].max())]


def _aoi(value):
    if value is None:
        return None
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError('area_of_interest must be [west, south, east, north] in geographic degrees.')
    if any(isinstance(number, bool) for number in value):
        raise ValueError('area_of_interest requires four finite numbers.')
    west, south, east, north = map(float, value)
    if (not np.isfinite([west, south, east, north]).all()
            or not (-180 <= west <= 180 and -180 <= east <= 180
                    and -90 <= south <= north <= 90)):
        raise ValueError('area_of_interest is outside the geographic longitude/latitude domain.')
    # PROJ spatial ranking needs an extent, including for point-only layers.
    epsilon = 1e-8
    if west == east:
        west, east = max(-180., west - epsilon), min(180., east + epsilon)
    if south == north:
        south, north = max(-90., south - epsilon), min(90., north + epsilon)
    return AreaOfInterest(west, south, east, north)


def _area(area):
    if area is None:
        return None
    return dict(name=area.name, west=float(area.west), south=float(area.south),
                east=float(area.east), north=float(area.north))


def _grids(operations):
    result, seen = [], set()
    for operation in operations:
        for grid in operation.grids:
            token = (grid.short_name, grid.url)
            if token in seen:
                continue
            seen.add(token)
            result.append(dict(name=grid.short_name, full_name=grid.full_name,
                               available=bool(grid.available), url=grid.url,
                               direct_download=bool(grid.direct_download),
                               open_license=bool(grid.open_license)))
    return result


def _operation(transformer):
    definition = transformer.definition
    operations = transformer.operations
    description = transformer.description
    ballpark = ('ballpark' in description.lower()
                or any(op.has_ballpark_transformation for op in operations))
    identity = json.dumps([definition, description], ensure_ascii=False)
    return dict(id='op_' + hashlib.sha256(identity.encode('utf-8')).hexdigest()[:20],
                description=description, definition=definition,
                accuracy=None if transformer.accuracy < 0 else float(transformer.accuracy),
                ballpark=bool(ballpark), area_of_use=_area(transformer.area_of_use),
                grids=_grids(operations),
                steps=[dict(name=op.name, type=op.type_name,
                            accuracy=None if op.accuracy < 0 else float(op.accuracy),
                            ballpark=bool(op.has_ballpark_transformation)) for op in operations])


def _options(source, target, area_of_interest, accuracy, allow_ballpark):
    if not isinstance(allow_ballpark, bool):
        raise ValueError('allow_ballpark must be a boolean.')
    if accuracy is not None and (isinstance(accuracy, bool) or not np.isfinite(float(accuracy)) or float(accuracy) <= 0):
        raise ValueError('accuracy must be a finite positive number of metres, or None for no filter.')
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always', UserWarning)
        group = TransformerGroup(source, target, always_xy=True,
                                 area_of_interest=_aoi(area_of_interest),
                                 accuracy=accuracy, allow_ballpark=allow_ballpark,
                                 allow_superseded=False)
    catalogue = dict(best_available=bool(group.best_available),
                     operations=[_operation(item) for item in group.transformers],
                     unavailable_operations=[dict(name=op.name,
                         accuracy=None if op.accuracy < 0 else float(op.accuracy),
                         area_of_use=_area(op.area_of_use), grids=_grids([op]))
                         for op in group.unavailable_operations],
                     warnings=list(dict.fromkeys(str(item.message) for item in caught)))
    return group, catalogue


def inspect_reprojection(sources, target_crs, *, recursive=False, area_of_interest=None,
                         accuracy=None, allow_ballpark=False, progress=None, cancel=None):
    """Inspect layer metadata and locally available candidate operations.

    IDs refer to operation definitions, not list positions. Pass selections as
    ``operations={layer_id: operation_id}`` to :func:`reproject_batch`. No
    Transformer objects cross threads or enter a serialized plan. AOI is a
    ranking hint, not a geometry clip or proof that an operation covers data.
    No grid download is requested; existing PROJ network settings are retained.
    """
    target = _horizontal_crs(target_crs, 'Target CRS')
    _aoi(area_of_interest)
    _check_cancel(cancel)
    layers = []
    discovered = _discover(sources, recursive)
    if progress:
        progress(0, len(discovered))
    for number, record in enumerate(discovered, 1):
        _check_cancel(cancel)
        data = _read(record)
        geographic_bounds = _geographic_bounds(_geographic_xy(data))
        _, catalogue = _options(data.crs, target, area_of_interest or geographic_bounds,
                                accuracy, allow_ballpark)
        layers.append(dict(_public(record), bounds=_bounds(data), features=len(data),
                           geographic_bounds=geographic_bounds, catalogue=catalogue))
        if progress:
            progress(number, len(discovered))
    _check_cancel(cancel)
    return dict(target_crs=target.to_string(), target_crs_wkt=target.to_wkt(), layers=layers)


def _outside(coordinates, area):
    if not len(coordinates) or area is None:
        return 0
    lon, lat = coordinates.T
    epsilon = 1e-8
    latitude = (lat >= area['south'] - epsilon) & (lat <= area['north'] + epsilon)
    if area['west'] <= area['east']:
        longitude = np.zeros(len(lon), dtype=bool)
        for equivalent in (lon, lon - 360., lon + 360.):
            longitude |= (equivalent >= area['west'] - epsilon) & (equivalent <= area['east'] + epsilon)
    else:
        longitude = (lon >= area['west'] - epsilon) | (lon <= area['east'] + epsilon)
    return int(np.count_nonzero(~(latitude & longitude)))


def _coordinate_sequences(geometry):
    if geometry is None or geometry.is_empty:
        return
    if geometry.geom_type == 'Polygon':
        yield np.asarray(geometry.exterior.coords)
        for ring in geometry.interiors:
            yield np.asarray(ring.coords)
    elif hasattr(geometry, 'geoms'):
        for part in geometry.geoms:
            yield from _coordinate_sequences(part)
    else:
        yield np.asarray(geometry.coords)


def _check_antimeridian(data, geographic):
    offset = 0
    for geometry in data.geometry:
        for sequence in _coordinate_sequences(geometry):
            longitude = geographic[offset:offset + len(sequence), 0]
            offset += len(sequence)
            if len(longitude) > 1 and np.any(np.abs(np.diff(longitude)) > 180. + 1e-8):
                raise ValueError('A geometry segment crosses the antimeridian. Split it explicitly '
                                 'before reprojection; vertices are not geodesically densified here.')


def _write_layer(data, path, *, cancel=None):
    folded = [str(column).casefold() for column in data.columns]
    if (len(set(folded)) != len(folded) or any(not isinstance(column, str) or not column
                                             for column in data.columns)):
        raise ValueError('GeoPackage requires nonempty field names distinct without regard to case.')
    fid = '_cartomize_fid'
    while fid.casefold() in folded:
        fid += '_'
    _check_cancel(cancel)
    data.to_file(path, layer='features', driver='GPKG', index=False,
                 promote_to_multi=False, layer_options={'FID': fid})
    _check_cancel(cancel)
    check = read_vector(path, layer='features')
    if len(check) != len(data) or CRS(check.crs) != CRS(data.crs):
        raise ValueError('The written layer failed feature-count/CRS verification.')
    for before, after in zip(data.geometry, check.geometry):
        if ((before is None) != (after is None)
                or before is not None and (before.geom_type != after.geom_type or before.wkb != after.wkb)):
            raise ValueError('The GeoPackage driver changed geometry types, dimensions or coordinates; '
                             'no batch was published. Normalize mixed geometry dimensions explicitly.')
    original = data.drop(columns=data.geometry.name).reset_index(drop=True)
    reopened = check.drop(columns=check.geometry.name).reset_index(drop=True)
    if list(original.columns) != list(reopened.columns):
        raise ValueError('The output driver changed the attribute schema.')
    for column in original:
        for before, after in zip(original[column], reopened[column]):
            if not pd.api.types.is_scalar(before):
                raise ValueError(f'Attribute {column!r} cannot be preserved as a scalar GeoPackage field.')
            if pd.isna(before):
                equal = pd.isna(after)
            elif isinstance(before, (int, np.integer)) and not isinstance(before, (bool, np.bool_)):
                equal = (isinstance(after, (int, float, np.integer, np.floating))
                         and np.isfinite(after) and int(after) == int(before) and after == int(after))
            else:
                equal = not pd.isna(after) and before == after
            if not equal:
                raise ValueError(f'The output driver cannot preserve attribute {column!r}; no batch was published.')


def reproject_batch(sources, destination, target_crs, *, recursive=False, operations=None,
                    area_of_interest=None, accuracy=None, allow_ballpark=False,
                    require_best=True, area_policy='error', progress=None, cancel=None):
    """Reproject discovered layers into one new, atomic output directory.

    Each layer gets a GeoPackage, an actual-vertex extent and a full operation
    audit. ``require_best`` refuses a missing preferred operation/grid; set it
    to False explicitly to permit selection among available alternatives.
    ``allow_ballpark`` separately controls approximate datum transformations.
    An explicit unavailable/unknown operation ID always fails without fallback.
    ``accuracy`` is PROJ's metre accuracy filter; unknown precision is reported
    as null (pure conversions can have no advertised transformation precision).

    ``area_policy`` is error or warn for vertices outside source/target CRS or
    selected-operation domains. Geographic screening uses the source geodetic
    datum, normalized to Greenwich degrees, without claiming a WGS84 datum
    transformation. These rectangular checks are not grid coverage guarantees.
    Nonfinite values, unsupported dimensions and antimeridian-crossing segments
    always fail. Missing/empty/invalid geometries and attributes are retained;
    geometry validity counts are reported. Z is preserved without vertical
    transformation; M and dynamic/3D CRSs require a separate workflow.
    """
    _check_cancel(cancel)
    target = _horizontal_crs(target_crs, 'Target CRS')
    _aoi(area_of_interest)
    if not isinstance(require_best, bool):
        raise ValueError('require_best must be a boolean.')
    if area_policy not in {'error', 'warn'}:
        raise ValueError('area_policy must be error or warn.')
    if operations is not None and (not isinstance(operations, dict)
            or any(not isinstance(k, str) or not isinstance(v, str) for k, v in operations.items())):
        raise ValueError('operations must map layer IDs to explicit operation IDs.')
    selections = operations or {}
    layers = _discover(sources, recursive)
    unknown = set(selections) - {record['id'] for record in layers}
    if unknown:
        raise ValueError('Unknown layer IDs in operations: ' + ', '.join(sorted(unknown)))
    destination = Path(destination).expanduser().resolve()
    for record in layers:
        if record['path']:
            path = Path(record['path'])
            if path == destination or destination in path.parents:
                raise ValueError('The destination contains or replaces a source file.')
    total = sum(record['features'] for record in layers)
    completed, reports, products = 0, [], {}
    if progress:
        progress(0, total)
    with new_directory(destination) as work:
        for record in layers:
            _check_cancel(cancel)
            data = _read(record)
            geographic = _geographic_xy(data)
            geographic_bounds = _geographic_bounds(geographic)
            chosen_aoi = area_of_interest or geographic_bounds
            group, catalogue = _options(data.crs, target, chosen_aoi, accuracy, allow_ballpark)
            if require_best and not catalogue['best_available']:
                missing = sorted({grid['name'] for op in catalogue['unavailable_operations']
                                  for grid in op['grids'] if not grid['available']})
                raise ValueError(f'{record["name"]}: the best transformation is unavailable; missing grids: '
                                 + (', '.join(missing) or 'see inspect_reprojection')
                                 + '. Install the required grids or explicitly set require_best=False.')
            if not catalogue['operations']:
                raise ValueError(f'{record["name"]}: no available transformation meets the requested '
                                 'accuracy/ballpark policy. Inspect the unavailable operations and grids.')
            requested = selections.get(record['id'])
            index = 0
            if requested is not None:
                matches = [i for i, candidate in enumerate(catalogue['operations']) if candidate['id'] == requested]
                if not matches:
                    raise ValueError(f'{record["name"]}: selected operation {requested!r} is unavailable or unknown; '
                                     'refresh the transformation catalogue. No fallback was used.')
                index = matches[0]
            operation = catalogue['operations'][index]
            transformer = group.transformers[index]
            messages = list(catalogue['warnings'])
            if not catalogue['best_available']:
                messages.append('A preferred operation is unavailable; require_best=False explicitly permits this alternative.')
            if operation['ballpark']:
                if not allow_ballpark:
                    raise ValueError('The selected operation is ballpark and allow_ballpark=False.')
                messages.append('An approximate ballpark datum transformation was explicitly allowed.')
            for label, area in [('source CRS', _area(CRS(data.crs).area_of_use)),
                                ('target CRS', _area(target.area_of_use)),
                                ('selected operation', operation['area_of_use'])]:
                outside = _outside(geographic, area)
                if outside:
                    message = f'{record["name"]}: {outside} vertices lie outside the {label} area of use.'
                    if area_policy == 'error':
                        raise ValueError(message + ' Choose an appropriate CRS/operation or explicitly set area_policy="warn".')
                    messages.append(message)
            if CRS(data.crs) != target:
                _check_antimeridian(data, geographic)
            geometries = []
            def project(coordinates):
                projected = coordinates.copy()
                xx, yy = transformer.transform(coordinates[:, 0], coordinates[:, 1], errcheck=True)
                if not np.isfinite([xx, yy]).all():
                    raise ValueError('The selected transformation produced non-finite coordinates.')
                projected[:, 0], projected[:, 1] = xx, yy
                return projected
            for position, geometry in enumerate(data.geometry):
                _check_cancel(cancel)
                try:
                    transformed = (geometry if geometry is None or geometry.is_empty else
                                   shapely.transform(geometry, project, include_z=bool(shapely.has_z(geometry))))
                except (ValueError, pyproj.exceptions.ProjError) as exc:
                    raise ValueError(f'{record["name"]}: transformation failed at source row {position}: {exc}') from exc
                if not _finite_geometry(transformed):
                    raise ValueError(f'{record["name"]}: non-finite result at source row {position}.')
                geometries.append(transformed)
                completed += 1
                if progress:
                    progress(completed, total)
            result = data.copy()
            result = result.set_geometry(gpd.GeoSeries(geometries, index=data.index,
                                                       name=data.geometry.name, crs=target))
            output = work / (record['id'] + '.gpkg')
            _write_layer(result, output, cancel=cancel)
            final = destination / output.name
            products[record['id']] = final
            reports.append(dict(_public(record), features=len(data), bounds=_bounds(data),
                source_crs_wkt=CRS(data.crs).to_wkt(), target_crs=target.to_string(),
                target_bounds=_bounds(result), geographic_bounds=geographic_bounds,
                area_of_interest=chosen_aoi, output=str(final), output_layer='features',
                operation=operation, selection='explicit' if requested else 'automatic',
                best_available=catalogue['best_available'],
                unavailable_operations=catalogue['unavailable_operations'], warnings=messages,
                missing_geometries=int(data.geometry.isna().sum()),
                empty_geometries=int(data.geometry.is_empty.sum()),
                invalid_before=int((~data.geometry.isna() & ~data.geometry.is_empty & ~data.geometry.is_valid).sum()),
                invalid_after=int((~result.geometry.isna() & ~result.geometry.is_empty & ~result.geometry.is_valid).sum()),
                z_features=int(np.count_nonzero(shapely.has_z(data.geometry.to_numpy())))))
        summary = dict(schema='cartomize.vector_reprojection.v1', status='complete',
            target_crs=target.to_string(), target_crs_wkt=target.to_wkt(),
            layer_count=len(reports), feature_count=sum(row['features'] for row in reports),
            settings=dict(recursive=recursive, area_of_interest=area_of_interest,
                          accuracy=accuracy, allow_ballpark=allow_ballpark,
                          require_best=require_best, area_policy=area_policy),
            coordinate_policy='GIS x/y order; static horizontal 2D transformation; Z preserved unchanged; M refused.',
            geometry_policy='All features retained; no repair, clipping, geodesic densification or antimeridian splitting.',
            extent_policy='Bounds of actual stored vertices, in each stated CRS; no interpolated envelope.',
            geographic_screening='Source geodetic datum in Greenwich degrees; approximate AOI/domain screening, not a WGS84 datum shift or grid-coverage proof.',
            environment=dict(pyproj=pyproj.__version__, proj=pyproj.proj_version_str,
                             geopandas=gpd.__version__, shapely=shapely.__version__,
                             proj_network_enabled=pyproj.network.is_network_enabled()),
            layers=reports, report=str(destination / 'report.csv'))
        rows = []
        for record in reports:
            rows.append({key: record[key] for key in
                         ('id', 'name', 'path', 'layer', 'features', 'source_crs', 'target_crs', 'output',
                          'missing_geometries', 'empty_geometries', 'invalid_before', 'invalid_after', 'z_features', 'selection', 'best_available')}
                        | dict(source_bounds=json.dumps(record['bounds']),
                               target_bounds=json.dumps(record['target_bounds']),
                               operation_id=record['operation']['id'],
                               operation=record['operation']['description'],
                               accuracy_m=record['operation']['accuracy'],
                               ballpark=record['operation']['ballpark'],
                               warnings='; '.join(record['warnings'])))
        pd.DataFrame(rows).to_csv(work / 'report.csv', index=False, encoding='utf-8-sig')
        save_json(summary, work / 'manifest.json')
        _check_cancel(cancel)
    return ReprojectedBatch(destination / 'manifest.json', destination / 'report.csv', products, summary)
