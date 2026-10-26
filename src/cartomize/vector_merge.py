"""Harmonize scalar schemas and concatenate vector features with provenance.

Field correspondences, conversions, missing values and dropped attributes are
explicit. Geometries are never dissolved, repaired or deduplicated. A requested
CRS transformation delegates to the audited M09 workflow before publication.
"""
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import CRS
import pyogrio
import shapely

from .imagery import _check_cancel
from .storage import new_directory, relocate_products, save_json
from .vector_io import FIELD_TYPES, field_kind, is_missing, timestamp, value_kind, read_vector, write_geopackage
from .vector_reprojection import _discover, _public, _read, _horizontal_crs, reproject_batch


@dataclass(frozen=True)
class MergedVectors:
    """The merged layer, schema audit and detailed conversion issues."""

    manifest: Path
    data: Path
    report: Path
    issues: Path
    summary: dict


def _field_name(name):
    if not isinstance(name, str) or not name.strip() or '\x00' in name:
        raise ValueError('Field names must be nonempty strings without NUL characters.')
    if name.casefold() == 'geometry':
        raise ValueError('The target field name geometry is reserved; map that attribute to another name.')
    return name


def _columns(data):
    columns = [name for name in data.columns if name != data.geometry.name]
    if len(set(data.columns)) != len(data.columns):
        raise ValueError('Source columns must have distinct names before harmonization.')
    if any(not isinstance(name, str) or not name or '\x00' in name for name in columns):
        raise ValueError('Source attribute names must be nonempty strings without NUL characters.')
    return columns


def _maps(layers, field_maps):
    if field_maps is None:
        return {}
    if not isinstance(field_maps, dict) or any(not isinstance(key, str) for key in field_maps):
        raise ValueError('field_maps must map source layer IDs to field dictionaries.')
    unknown = set(field_maps) - {layer['id'] for layer in layers}
    if unknown:
        raise ValueError('Unknown layer IDs in field_maps: ' + ', '.join(sorted(unknown)))
    for mapping in field_maps.values():
        if (not isinstance(mapping, dict)
                or any(not isinstance(source, str) or target is not None and not isinstance(target, str)
                       for source, target in mapping.items())):
            raise ValueError('A field map must map source field names to target names or null for an explicit drop.')
    return field_maps


def _mapping(data, mapping, *, validate_targets=True):
    columns = _columns(data)
    unknown = set(mapping) - set(columns)
    if unknown:
        raise ValueError('Unknown source fields in field map: ' + ', '.join(sorted(unknown)))
    result = {name: mapping.get(name, name) for name in columns}
    targets = [target for target in result.values() if target is not None]
    if validate_targets:
        for target in targets:
            _field_name(target)
    if validate_targets and len({name.casefold() for name in targets}) != len(targets):
        raise ValueError('Several fields in one source map to the same target; select one source field explicitly.')
    return result


def _json_scalar(value):
    if is_missing(value):
        return None
    if isinstance(value, (date, datetime, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return _json_scalar(value.item())
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (str, int, float, bool)):
        return str(value) if isinstance(value, float) and not np.isfinite(value) else value
    return repr(value)


def _profile(record, data, mapping):
    declared = data.attrs.get('_cartomize_declared_fields', {})
    hints = {**declared, **data.attrs.get('_cartomize_temporal_fields', {})}
    fields = []
    for name in _columns(data):
        values = data[name]
        nulls = sum(is_missing(value) for value in values)
        untyped_null = nulls == len(values) and values.dtype == object and name not in hints
        kind = None if nulls == len(values) and name in declared and declared[name] is None else field_kind(values, hints.get(name))
        fields.append(dict(name=name, dtype=str(values.dtype), type=kind,
            nullable=bool(nulls), null_count=nulls, target=mapping[name],
            untyped_null=bool(untyped_null),
            examples=[_json_scalar(value) for value in values if not is_missing(value)][:3]))
    geometries = data.geometry.to_numpy()
    return dict(**_public(record), fields=fields,
        geometry_types={str(key): int(value) for key, value in data.geom_type.value_counts().items()},
        missing_geometries=int(data.geometry.isna().sum()), empty_geometries=int(data.geometry.is_empty.sum()),
        invalid_geometries=int((~data.geometry.isna() & ~data.geometry.is_empty & ~data.geometry.is_valid).sum()),
        z_features=int(np.sum(shapely.has_z(geometries))))


def _suggest(profiles):
    groups, conflicts = {}, []
    for profile in profiles:
        seen = set()
        for field in profile['fields']:
            if field['target'] is not None:
                groups.setdefault(field['target'], []).append(field)
                if field['target'].casefold() in seen:
                    conflicts.append(dict(field=field['target'], types=[],
                        reason='Several fields in one source map to the same target; choose a correspondence.'))
                seen.add(field['target'].casefold())
    folded = {}
    for name in groups:
        try:
            _field_name(name)
        except ValueError as exc:
            conflicts.append(dict(field=name, types=[], reason=str(exc)))
        if name.casefold() in folded:
            conflicts.append(dict(field=name, types=[],
                reason='Target names differ only by case; supply explicit field correspondences.'))
        folded[name.casefold()] = name
    schema = {}
    for name, fields in groups.items():
        distinct = {field['type'] for field in fields if not field['untyped_null']} or {'string'}
        if distinct <= {'int64', 'float64'}:
            kind = 'float64' if 'float64' in distinct else 'int64'
        else:
            kind = next(iter(distinct)) if len(distinct) == 1 else None
        schema[name] = {'type': kind, 'nullable': True}
        if kind is None:
            conflicts.append(dict(field=name, types=sorted(str(value) for value in distinct),
                                  reason='Choose an explicit target type and conversion policy.'))
    return schema, conflicts


def inspect_merge(sources, *, recursive=False, field_maps=None, progress=None, cancel=None):
    """Describe every source field and propose a compatible union schema.

    A null type in ``suggested_schema`` is a conflict, never a silently chosen
    coercion. IDs are shared with discover_vector_layers. Inspection reads
    complete fields so null counts and mixed-value types are not sampled.
    """
    _check_cancel(cancel)
    layers = _discover(sources, recursive)
    mappings = _maps(layers, field_maps)
    profiles = []
    if progress:
        progress(0, len(layers))
    for index, record in enumerate(layers, 1):
        _check_cancel(cancel)
        data = _read(record)
        mapping = _mapping(data, mappings.get(record['id'], {}), validate_targets=False)
        profiles.append(_profile(record, data, mapping))
        if progress:
            progress(index, len(layers))
    _check_cancel(cancel)
    schema, conflicts = _suggest(profiles)
    crs = CRS(layers[0]['source_crs'])
    common = crs.to_string() if all(CRS(layer['source_crs']) == crs for layer in layers) else None
    return dict(schema='cartomize.vector_merge_inspection.v1', layer_count=len(layers),
        feature_count=sum(layer['features'] for layer in layers), common_crs=common,
        layers=profiles, suggested_schema=schema, conflicts=conflicts)


def _convert(value, kind):
    if is_missing(value):
        return None
    if not pd.api.types.is_scalar(value) or isinstance(value, (bytes, bytearray, complex)):
        raise ValueError('Structured or binary values require explicit preparation before a scalar conversion.')
    if kind == 'string':
        text = str(value)
        if '\x00' in text:
            raise ValueError('NUL characters cannot be preserved in a GeoPackage text field.')
        return text
    if kind == 'int64':
        if isinstance(value, (int, np.integer, bool, np.bool_)):
            number = int(value)
        elif isinstance(value, (float, np.floating)):
            if not np.isfinite(value) or value != int(value):
                raise ValueError('Expected an integral, finite number without rounding.')
            number = int(value)
        else:
            try:
                decimal = Decimal(str(value).strip())
            except InvalidOperation as exc:
                raise ValueError('Expected a decimal integer.') from exc
            if not decimal.is_finite() or decimal != decimal.to_integral_value():
                raise ValueError('Expected an integral, finite decimal without rounding.')
            number = int(decimal)
        if not -(2**63) <= number <= 2**63 - 1:
            raise ValueError('Integer is outside the signed int64 range.')
        return number
    if kind == 'float64':
        try:
            number = float(value)
            exact = Decimal(str(value).strip()) if isinstance(value, (str, Decimal, int, np.integer)) else None
        except (TypeError, ValueError, InvalidOperation, OverflowError) as exc:
            raise ValueError('Expected a finite real number.') from exc
        if not np.isfinite(number):
            raise ValueError('Expected a finite real number.')
        if exact is not None and exact == exact.to_integral_value() and int(number) != int(exact):
            raise ValueError('Integer precision would be lost in float64.')
        return number
    if kind == 'boolean':
        if isinstance(value, (bool, np.bool_)):
            return bool(value)
        if isinstance(value, str):
            token = value.strip().casefold()
            if token in {'true', '1'}:
                return True
            if token in {'false', '0'}:
                return False
        elif isinstance(value, (int, float, np.integer, np.floating)) and value in (0, 1):
            return bool(value)
        raise ValueError('Boolean conversion accepts only true/false or 1/0.')
    if kind == 'date':
        if isinstance(value, (datetime, pd.Timestamp, np.datetime64)):
            stamp = pd.Timestamp(value)
            if stamp.tzinfo is not None or stamp != stamp.normalize():
                raise ValueError('A date conversion must not discard a time or timezone.')
            return stamp.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            return date.fromisoformat(value)
        raise ValueError('Dates require ISO YYYY-MM-DD values without an ambiguous format.')
    if kind in {'datetime', 'datetime_utc'}:
        if isinstance(value, str):
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}(?:[Tt ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:[Zz]|[+-]\d{2}:\d{2})?)?', value):
                raise ValueError('Datetimes require an explicit ISO 8601 date and time.')
        elif not isinstance(value, (date, datetime, pd.Timestamp, np.datetime64)):
            raise ValueError('Numeric timestamps require explicit preparation; an epoch is not guessed.')
        return timestamp(value, utc=kind == 'datetime_utc')
    raise ValueError('Unknown target type: ' + str(kind))


def _schema(supplied, profiles):
    if supplied is None:
        supplied, conflicts = _suggest(profiles)
        if conflicts:
            raise ValueError('Incompatible field types require an explicit schema: ' +
                             ', '.join(record['field'] for record in conflicts))
    if not isinstance(supplied, dict):
        raise ValueError('schema must map target field names to types or field specifications.')
    result = {}
    for name, value in supplied.items():
        _field_name(name)
        spec = {'type': value} if isinstance(value, str) else value
        if not isinstance(spec, dict) or set(spec) - {'type', 'nullable', 'default'}:
            raise ValueError('A schema field accepts only type, nullable and default.')
        if spec.get('type') not in FIELD_TYPES:
            raise ValueError(f'{name}: choose a supported scalar type: ' + ', '.join(FIELD_TYPES))
        nullable = spec.get('nullable', True)
        if not isinstance(nullable, bool):
            raise ValueError('nullable must be a boolean.')
        result[name] = {'type': spec['type'], 'nullable': nullable}
        if 'default' in spec:
            try:
                result[name]['default'] = _convert(spec['default'], spec['type'])
            except (ValueError, TypeError, OverflowError) as exc:
                raise ValueError(f'{name}: invalid default value: {exc}') from exc
    if len({name.casefold() for name in result}) != len(result):
        raise ValueError('Target schema names must be distinct without regard to case.')
    return result


def _provenance_names(schema):
    used = {name.casefold() for name in schema}
    result = {}
    for semantic in ('source_id', 'source_name', 'source_path', 'source_layer', 'source_row'):
        name = 'cm_' + semantic
        while name.casefold() in used:
            name += '_'
        used.add(name.casefold())
        result[semantic] = name
    return result


def _convert_layer(record, data, mapping, schema, policies, reports, issues, cancel):
    targets = {target: source for source, target in mapping.items() if target is not None}
    extras = set(targets) - set(schema)
    if extras and policies['extra_fields'] == 'error':
        raise ValueError(f'{record["name"]}: fields are absent from the target schema: ' + ', '.join(sorted(extras)))
    result = {}
    for source, target in mapping.items():
        if target is None or target in extras:
            reports.append(dict(source_id=record['id'], source_name=record['name'], source_field=source,
                target_field=target, target_type=None, action='drop', rows=len(data),
                missing_values=0, converted_values=0, defaulted_values=0, conversion_errors=0, output_nulls=0))
    for target, spec in schema.items():
        _check_cancel(cancel)
        source = targets.get(target)
        if source is None and policies['missing_fields'] == 'error':
            raise ValueError(f'{record["name"]}: missing source field for target {target!r}.')
        values = data[source].tolist() if source is not None else [None] * len(data)
        converted, missing, changed, defaulted, errors = [], 0, 0, 0, 0
        for row, value in enumerate(values):
            if row % 1000 == 0:
                _check_cancel(cancel)
            absent = is_missing(value)
            missing += absent
            try:
                output = _convert(value, spec['type'])
                changed += not absent and (value_kind(value) != spec['type'] or output != value)
            except (ValueError, TypeError, OverflowError) as exc:
                if policies['conversion_errors'] == 'error':
                    raise ValueError(f'{record["name"]}, row {row}, field {source!r} -> {target!r}: {exc}') from exc
                output = None
                errors += 1
                issues.append(dict(source_id=record['id'], source_row=row, source_field=source,
                    target_field=target, value=json.dumps(_json_scalar(value), ensure_ascii=False, default=str),
                    reason=str(exc), action='null'))
            if output is None and 'default' in spec:
                output = spec['default']
                defaulted += output is not None
            if output is None and not spec['nullable']:
                raise ValueError(f'{record["name"]}, row {row}: target field {target!r} is not nullable.')
            converted.append(output)
        result[target] = converted
        reports.append(dict(source_id=record['id'], source_name=record['name'], source_field=source,
            target_field=target, target_type=spec['type'], action='convert' if source is not None else 'missing',
            rows=len(data), missing_values=int(missing), converted_values=int(changed),
            defaulted_values=int(defaulted), conversion_errors=errors,
            output_nulls=sum(value is None for value in converted)))
    return result


def _aligned_geometries(layers, frames, target, options, work, cancel):
    if target is None:
        first = CRS(layers[0]['source_crs'])
        if any(CRS(record['source_crs']) != first for record in layers):
            raise ValueError('Sources have different CRSs. Specify target_crs or reproject the layers explicitly first.')
        if options:
            raise ValueError('reprojection_options requires an explicit target_crs.')
        return [frame.geometry.to_list() for frame in frames], first, None
    target = _horizontal_crs(target, 'Target CRS')
    if options is None:
        options = {}
    if not isinstance(options, dict) or set(options) - {
            'operations', 'area_of_interest', 'accuracy', 'allow_ballpark', 'require_best', 'area_policy'}:
        raise ValueError('reprojection_options accepts only the documented M09 geodetic options.')
    # Reproject geometry-only frames. Attribute conversions are independent
    # of temporary vector storage, including fields intentionally dropped.
    sources = [{'data': gpd.GeoDataFrame(geometry=frame.geometry.copy(), crs=frame.crs),
                'name': record['id']} for record, frame in zip(layers, frames)]
    internal = _discover(sources)
    supplied = dict(options)
    if 'operations' in supplied:
        selection = supplied['operations']
        if not isinstance(selection, dict) or set(selection) - {record['id'] for record in layers}:
            raise ValueError('Unknown source layer IDs in reprojection operation selection.')
        supplied['operations'] = {inside['id']: selection[record['id']] for record, inside in zip(layers, internal)
                                  if record['id'] in selection}
    batch = reproject_batch(sources, work / 'reprojection', target, cancel=cancel, **supplied)
    geometry = [read_vector(batch.layers[record['id']]).geometry.to_list() for record in internal]
    return geometry, target, batch


def merge_layers(sources, destination, *, schema=None, field_maps=None, recursive=False,
                 target_crs=None, reprojection_options=None, conversion_errors='error',
                 missing_fields='null', extra_fields='error', progress=None, cancel=None):
    """Harmonize fields and publish a new merged GeoPackage atomically.

    ``field_maps`` uses source-layer IDs and source-to-target names; a null
    target explicitly drops that source field. Unspecified fields keep their
    names. ``schema`` is the exact target schema, or a compatible inferred
    union when omitted. A field specification has type, nullable and optional
    default. Conversion errors stop by default; the explicit null policy
    records every failed cell. Defaults fill missing values, then nullable
    constraints apply. Missing/extra fields have independent error policies.

    Without target_crs all input CRSs must match. With it, the M09 geodetic
    audit is retained and reprojection_options controls its strict policies.
    Source order and rows are preserved, with five unambiguous provenance
    fields. No geometry union, repair or deduplication is performed.
    """
    _check_cancel(cancel)
    for name, value, choices in [('conversion_errors', conversion_errors, {'error', 'null'}),
                                 ('missing_fields', missing_fields, {'null', 'error'}),
                                 ('extra_fields', extra_fields, {'error', 'drop'})]:
        if value not in choices:
            raise ValueError(name + ' must be one of: ' + ', '.join(sorted(choices)))
    policies = dict(conversion_errors=conversion_errors, missing_fields=missing_fields, extra_fields=extra_fields)
    layers = _discover(sources, recursive)
    mappings = _maps(layers, field_maps)
    destination = Path(destination).expanduser().resolve()
    if destination.exists():
        raise FileExistsError('Choose a new output directory: ' + str(destination))
    for record in layers:
        if record['path'] and (Path(record['path']) == destination or destination in Path(record['path']).parents):
            raise ValueError('The destination contains or replaces a source file.')
    frames, profiles, resolved_maps = [], [], []
    total = len(layers) + 2
    if progress:
        progress(0, total)
    for index, record in enumerate(layers, 1):
        _check_cancel(cancel)
        data = _read(record)
        mapping = _mapping(data, mappings.get(record['id'], {}))
        frames.append(data)
        profiles.append(_profile(record, data, mapping))
        resolved_maps.append(mapping)
        if progress:
            progress(index, total)
    resolved_schema = _schema(schema, profiles)
    provenance = _provenance_names(resolved_schema)
    attributes = {name: [] for name in (*resolved_schema, *provenance.values())}
    reports, issues = [], []
    for record, data, mapping in zip(layers, frames, resolved_maps):
        _check_cancel(cancel)
        converted = _convert_layer(record, data, mapping, resolved_schema, policies, reports, issues, cancel)
        for name, values in converted.items():
            attributes[name].extend(values)
        for semantic, name in provenance.items():
            if semantic == 'source_row':
                attributes[name].extend(range(len(data)))
            else:
                source_key = semantic.removeprefix('source_')
                attributes[name].extend([record[source_key]] * len(data))
    with new_directory(destination) as work:
        geometries, crs, reprojection = _aligned_geometries(layers, frames, target_crs, reprojection_options, work, cancel)
        _check_cancel(cancel)
        if progress:
            progress(len(layers) + 1, total)
        merged = gpd.GeoDataFrame({name: pd.Series(values, dtype=object) for name, values in attributes.items()},
            geometry=[geometry for layer in geometries for geometry in layer], crs=crs)
        kinds = {name: spec['type'] for name, spec in resolved_schema.items()}
        kinds.update({name: 'int64' if semantic == 'source_row' else 'string' for semantic, name in provenance.items()})
        write_geopackage(merged, work / 'merged.gpkg', types=kinds, cancel=cancel)
        report_columns = ['source_id', 'source_name', 'source_field', 'target_field', 'target_type', 'action',
                          'rows', 'missing_values', 'converted_values', 'defaulted_values', 'conversion_errors', 'output_nulls']
        pd.DataFrame(reports, columns=report_columns).to_csv(work / 'fields.csv', index=False)
        pd.DataFrame(issues, columns=['source_id', 'source_row', 'source_field', 'target_field', 'value', 'reason', 'action']).to_csv(work / 'issues.csv', index=False)
        manifest = dict(schema='cartomize.vector_merge.v1', status='complete',
            source_count=len(layers), feature_count=len(merged), target_crs=crs.to_string(), target_crs_wkt=crs.to_wkt(),
            target_schema={name: {key: _json_scalar(value) for key, value in spec.items()} for name, spec in resolved_schema.items()},
            settings=dict(**policies, recursive=recursive, schema_mode='inferred' if schema is None else 'explicit'),
            provenance_columns=provenance, sources=profiles,
            field_maps={record['id']: mapping for record, mapping in zip(layers, resolved_maps)},
            conversion_error_count=len(issues), dropped_field_count=sum(row['action'] == 'drop' for row in reports),
            row_order='source discovery order, then zero-based source row order; no deduplication or geometric union',
            data=str(destination / 'merged.gpkg'), report=str(destination / 'fields.csv'), issues=str(destination / 'issues.csv'),
            reprojection_manifest=str(destination / reprojection.manifest.relative_to(work)) if reprojection is not None else None,
            environment=dict(geopandas=gpd.__version__, pandas=pd.__version__, pyogrio=pyogrio.__version__,
                             gdal='.'.join(map(str, pyogrio.__gdal_version__))))
        save_json(manifest, work / 'manifest.json')
        relocate_products(work, destination)
        _check_cancel(cancel)
        if progress:
            progress(total, total)
        _check_cancel(cancel)
    return MergedVectors(destination / 'manifest.json', destination / 'merged.gpkg', destination / 'fields.csv',
                         destination / 'issues.csv', manifest)
