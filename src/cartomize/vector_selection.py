"""Auditable extraction of unchanged source records by explicit criteria.

Selection is a partition, never a geometric clipping operation. The two output
layers retain the original schema; decisions and source positions belong to a
separate report so no attribute is overwritten by a diagnostic field.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

from .imagery import _check_cancel
from .vector_io import field_kind, is_missing
from .vector_quality import _quality_source
from .vector_workflows import _attribute_mask


@dataclass
class VectorSelectionResult:
    """Selected/rejected source records and an exhaustive positional audit."""

    data: gpd.GeoDataFrame
    rejected: gpd.GeoDataFrame
    report: pd.DataFrame
    summary: dict


_PREDICATES = {'intersects', 'within', 'contains', 'covers', 'covered_by',
               'touches', 'overlaps', 'crosses', 'disjoint'}


def _parameter_value(value):
    """Represent filter parameters in JSON without losing their literal type."""
    if is_missing(value):
        return None
    if isinstance(value, (datetime, pd.Timestamp, np.datetime64)):
        return {'type': 'datetime', 'value': pd.Timestamp(value).isoformat()}
    if isinstance(value, date):
        return {'type': 'date', 'value': value.isoformat()}
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError('Filter parameters must be finite.')
        return {'type': 'decimal', 'value': str(value)}
    if isinstance(value, np.generic):
        return _parameter_value(value.item())
    if isinstance(value, (list, tuple, set)):
        values = list(value)
        if isinstance(value, set):
            values.sort(key=lambda item: (type(item).__name__, repr(item)))
        return [_parameter_value(item) for item in values]
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float) and np.isfinite(value):
        return value
    raise ValueError('Filter parameters must be scalar values or membership lists.')


def _finite_geometry(geometry, cancel):
    """Inspect present ordinates, including Z/M, without manufacturing NaNs."""
    _check_cancel(cancel)
    if geometry.is_empty:
        return True
    if geometry.geom_type == 'Polygon':
        return (_finite_geometry(geometry.exterior, cancel)
                and all(_finite_geometry(ring, cancel) for ring in geometry.interiors))
    if hasattr(geometry, 'geoms'):
        return all(_finite_geometry(part, cancel) for part in geometry.geoms)
    return bool(np.isfinite(np.asarray(geometry.coords, dtype=float)).all())


def _validate_geometries(data, label, cancel, advance=None):
    total = len(data)
    for row, geometry in enumerate(data.geometry):
        _check_cancel(cancel)
        if geometry is not None and not geometry.is_empty:
            if not _finite_geometry(geometry, cancel):
                raise ValueError(f'{label} geometry at source row {row} contains nonfinite coordinates.')
            if not geometry.is_valid:
                raise ValueError(f'{label} geometry at source row {row} is invalid: '
                                 + shapely.is_valid_reason(geometry))
        if advance is not None and (row % 256 == 0 or row + 1 == total):
            advance((row + 1) / max(total, 1))


def _identifiers(source, id_field):
    if id_field is None:
        return pd.Series(np.arange(len(source), dtype=np.int64))
    if (not isinstance(id_field, str) or not id_field or id_field not in source
            or isinstance(source[id_field].dtype, gpd.array.GeometryDtype)):
        raise ValueError('id_field must name one existing attribute field.')
    values = source[id_field]
    if any(not pd.api.types.is_scalar(value) for value in values):
        raise ValueError('id_field must contain scalar identifiers.')
    if values.isna().any() or values.duplicated().any():
        raise ValueError('id_field must contain unique, nonmissing identifiers.')
    return values.reset_index(drop=True).copy()


def extract_features(data, *, filters=None, attribute_match='all', mask=None,
                     predicate='intersects', combination='and', invert=False,
                     layer=None, mask_layer=None, id_field=None,
                     progress=None, cancel=None):
    """Partition features using attribute and/or spatial criteria, with reasons.

    ``filters`` is a list of ``{field, comparison, value}`` dictionaries using
    the comparators accepted by :func:`select_attributes`; ``value`` may be
    omitted only for ``is_null``/``not_null``. ``attribute_match='all'`` means
    every attribute criterion must match; ``'any'`` means at least one. If a
    spatial mask is also supplied, ``combination='and'``/``'or'`` combines the
    two blocks. With one active block its result is used directly. ``invert``
    complements the final decision across **every** source record. At least
    one attribute criterion or a spatial mask is required. No expression is
    evaluated as Python, SQL or regular expression syntax.

    Spatial predicates are planar ``source.predicate(union(mask))`` after
    reprojecting the mask into the source CRS. Overlapping mask geometries do
    not duplicate records. Source null/empty geometries do not match spatial
    predicates, including ``disjoint``; inversion can explicitly select them.
    Null/empty mask geometries are ignored. An empty mask therefore matches
    all present, nonempty source geometries with ``disjoint`` and none with
    the other predicates. Invalid geometries or nonfinite coordinates are
    refused when spatial selection is requested; attribute-only extraction
    does not validate or change geometries. Z/M are retained unchanged but
    ignored by the planar predicate. Inputs require known CRSs; multi-layer
    files require explicit ``layer``/``mask_layer`` selection.

    ``data`` and ``rejected`` on the returned :class:`VectorSelectionResult`
    are disjoint, exhaustive copies of complete source records in source
    order, with identical attributes, dtypes, geometry WKB, indices and CRS.
    ``report`` contains every source row, its source label and optional exact
    unique ``id_field``, zero-based output/rejected row positions, criterion
    and block matches, the pre-inversion decision, final selection and reason.
    Disabled blocks have missing Boolean report values, not invented matches.
    ``summary`` provides counts, the four attribute/spatial combinations and
    JSON-serializable parameters; native temporal/Decimal values are tagged.

    ``progress(done, total)`` uses total 10000. ``cancel`` accepts an
    Event-compatible object and raises ProcessingCancelled without a result.
    """
    _check_cancel(cancel)
    if not isinstance(attribute_match, str) or attribute_match not in {'all', 'any'}:
        raise ValueError("attribute_match must be 'all' or 'any'.")
    if not isinstance(combination, str) or combination not in {'and', 'or'}:
        raise ValueError("combination must be 'and' or 'or'.")
    if not isinstance(predicate, str) or predicate not in _PREDICATES:
        raise ValueError('Unsupported spatial predicate.')
    if not isinstance(invert, (bool, np.bool_)):
        raise ValueError('invert must be a boolean.')
    if progress is not None and not callable(progress):
        raise ValueError('progress must be callable.')
    if filters is None:
        filters = []
    if not isinstance(filters, (list, tuple)):
        raise ValueError('filters must be a list of attribute criterion dictionaries.')
    filters = list(filters)
    if not filters and mask is None:
        raise ValueError('Specify at least one attribute filter or a spatial mask.')
    if mask is None and mask_layer is not None:
        raise ValueError('mask_layer requires a spatial mask.')
    normalized_filters = []
    for number, criterion in enumerate(filters, 1):
        if not isinstance(criterion, dict) or set(criterion) - {'field', 'comparison', 'value'}:
            raise ValueError(f'Attribute criterion {number} must contain only field, comparison and value.')
        if 'field' not in criterion or 'comparison' not in criterion:
            raise ValueError(f'Attribute criterion {number} requires field and comparison.')
        if not isinstance(criterion['field'], str) or not isinstance(criterion['comparison'], str):
            raise ValueError(f'Attribute criterion {number} requires a field name and comparison name.')
        if (criterion['comparison'] not in {'is_null', 'not_null'}
                and 'value' not in criterion):
            raise ValueError(f'Attribute criterion {number} requires a value.')
        normalized_filters.append({'field': criterion['field'],
                                   'comparison': criterion['comparison'],
                                   'value': _parameter_value(criterion.get('value'))})

    def advance(value):
        _check_cancel(cancel)
        if progress is not None:
            progress(int(value), 10000)
        _check_cancel(cancel)

    advance(0)
    source, source_layer = _quality_source(data, layer)
    if not source.columns.is_unique:
        raise ValueError('Input field names must be unique.')
    identifiers = _identifiers(source, id_field)
    # Infer on the complete source: one partition may contain only nulls or
    # no rows, which must not turn an otherwise native DATE/Boolean into TEXT.
    hints = dict(source.attrs.get('_cartomize_declared_fields', {}))
    hints.update(source.attrs.get('_cartomize_temporal_fields', {}))
    source_attribute_types = {name: field_kind(source[name], hints.get(name))
                              for name in source.columns if name != source.geometry.name}
    count = len(source)
    missing_geometry = source.geometry.isna().to_numpy(dtype=bool)
    empty_geometry = source.geometry.is_empty.to_numpy(dtype=bool) & ~missing_geometry
    present_geometry = ~(missing_geometry | empty_geometry)
    geometry_status = np.full(count, 'not_evaluated', dtype=object)
    geometry_status[missing_geometry] = 'missing'
    geometry_status[empty_geometry] = 'empty'
    advance(500)

    report = pd.DataFrame({'source_row': np.arange(count, dtype=np.int64),
                           'source_index': pd.Series(list(source.index), dtype=object),
                           'source_id': identifiers})
    criteria = []
    attributes = None
    for number, criterion in enumerate(filters, 1):
        _check_cancel(cancel)
        matched = _attribute_mask(source, criterion['field'], criterion['comparison'],
                                  criterion.get('value'))
        missing = source[criterion['field']].isna().to_numpy(dtype=bool)
        key = f'attribute_{number}'
        report[key + '_match'] = matched
        report[key + '_reason'] = pd.Series(np.where(matched, 'matched',
                                           np.where(missing, 'missing_value', 'no_match')),
                                            dtype='string')
        criteria.append({'id': key, **normalized_filters[number - 1],
                         'matched': int(matched.sum()), 'unmatched': int((~matched).sum()),
                         'missing_values': int(missing.sum())})
        if attributes is None:
            attributes = matched.copy()
        elif attribute_match == 'all':
            attributes &= matched
        else:
            attributes |= matched
        advance(500 + 2500 * number / len(filters))
    advance(3000)

    spatial = None
    mask_metadata = None
    selected_mask_layer = None
    if mask is not None:
        mask_data, selected_mask_layer = _quality_source(mask, mask_layer)
        _validate_geometries(source, 'Source', cancel,
                             lambda fraction: advance(3000 + 750 * fraction))
        _validate_geometries(mask_data, 'Mask', cancel,
                             lambda fraction: advance(3750 + 750 * fraction))
        original_mask_crs = str(mask_data.crs)
        mask_data = mask_data.to_crs(source.crs)
        _validate_geometries(mask_data, 'Reprojected mask', cancel,
                             lambda fraction: advance(4500 + 500 * fraction))
        mask_missing = mask_data.geometry.isna().to_numpy(dtype=bool)
        mask_empty = mask_data.geometry.is_empty.to_numpy(dtype=bool) & ~mask_missing
        usable_mask = ~(mask_missing | mask_empty)
        advance(5000)
        union = mask_data.iloc[usable_mask].geometry.union_all()
        advance(5500)
        spatial = np.zeros(count, dtype=bool)
        for start in range(0, count, 4096):
            _check_cancel(cancel)
            stop = min(start + 4096, count)
            spatial[start:stop] = (getattr(source.geometry.iloc[start:stop], predicate)(union)
                                   .to_numpy(dtype=bool) & present_geometry[start:stop])
            advance(5500 + 2500 * stop / max(count, 1))
        geometry_status[present_geometry] = 'valid'
        mask_metadata = {'features': len(mask_data), 'usable_features': int(usable_mask.sum()),
                         'missing_geometries': int(mask_missing.sum()),
                         'empty_geometries': int(mask_empty.sum()),
                         'original_crs': original_mask_crs, 'aligned_crs': str(source.crs),
                         'union_empty': bool(union.is_empty),
                         'predicate_direction': 'source.predicate(mask_union)',
                         'dimensions': 'planar XY; source Z/M retained'}
    advance(8000)

    if attributes is not None and spatial is not None:
        combined = attributes & spatial if combination == 'and' else attributes | spatial
        combinations = {'both': int((attributes & spatial).sum()),
                        'attributes_only': int((attributes & ~spatial).sum()),
                        'spatial_only': int((~attributes & spatial).sum()),
                        'neither': int((~attributes & ~spatial).sum())}
    else:
        combined = (attributes if attributes is not None else spatial).copy()
        combinations = None
    selected = ~combined if invert else combined.copy()
    rejected = ~selected
    reasons = np.full(count, 'selected_by_inversion' if invert else 'selected', dtype=object)
    if invert:
        reasons[rejected] = 'excluded_by_inversion'
    else:
        if attributes is not None:
            reasons[rejected & ~attributes] = 'attribute_no_match'
        if spatial is not None:
            failed_spatial = rejected & ~spatial
            reasons[failed_spatial] = 'spatial_no_match'
            reasons[failed_spatial & missing_geometry] = 'missing_geometry'
            reasons[failed_spatial & empty_geometry] = 'empty_geometry'
            if attributes is not None:
                reasons[rejected & ~attributes & ~spatial] = 'attribute_and_spatial_no_match'
    output_rows = pd.array([pd.NA] * count, dtype='Int64')
    rejected_rows = pd.array([pd.NA] * count, dtype='Int64')
    output_rows[selected] = np.arange(int(selected.sum()), dtype=np.int64)
    rejected_rows[rejected] = np.arange(int(rejected.sum()), dtype=np.int64)
    report['output_row'] = output_rows
    report['rejected_row'] = rejected_rows
    for name, values in [('attribute_match', attributes), ('spatial_match', spatial)]:
        report[name] = pd.array([pd.NA] * count if values is None else values, dtype='boolean')
    report['combined_match'] = combined
    report['selected'] = selected
    report['geometry_status'] = pd.Series(geometry_status, dtype='string')
    report['reason'] = pd.Series(reasons, dtype='string')
    output = source.iloc[selected].copy()
    excluded = source.iloc[rejected].copy()

    def block(values):
        return {'enabled': values is not None,
                'matched': int(values.sum()) if values is not None else None,
                'unmatched': int((~values).sum()) if values is not None else None}

    summary = {
        'schema': 'cartomize.vector.selection.v1', 'procedure': 'extract_features',
        'crs': str(source.crs), 'input_features': count,
        'source_attribute_types': source_attribute_types,
        'output_features': len(output), 'rejected_features': len(excluded),
        'parameters': {'filters': normalized_filters, 'attribute_match': attribute_match,
                       'predicate': predicate if mask is not None else None,
                       'combination': combination, 'invert': bool(invert),
                       'layer': source_layer, 'mask_layer': selected_mask_layer,
                       'id_field': id_field},
        'criteria': criteria,
        'blocks': {'attributes': block(attributes), 'spatial': block(spatial)},
        'combinations': combinations, 'mask': mask_metadata,
        'source_row_base': 0, 'output_order': 'source', 'partition_complete': True,
        'missing_geometries': int(missing_geometry.sum()),
        'empty_geometries': int(empty_geometry.sum()),
        'geometry_policy': 'invalid/nonfinite refused for spatial selection; unchanged for attribute-only selection',
        'missing_attribute_policy': 'is_null or explicit in membership matches missing; other comparisons exclude missing',
        'reason_counts': {str(reason): int(amount) for reason, amount in report['reason'].value_counts().items()},
    }
    advance(10000)
    return VectorSelectionResult(data=output, rejected=excluded, report=report, summary=summary)
