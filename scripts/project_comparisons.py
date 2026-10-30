"""Strict semantic comparison for vector results reloaded from GIS files."""
from datetime import date, datetime

from geopandas.testing import assert_geodataframe_equal
import numpy as np
import pandas as pd


def _single_part(geometry):
    """Undo a driver's single-to-multi promotion, never discard extra parts."""
    if geometry is not None and geometry.geom_type in {'MultiPoint', 'MultiLineString', 'MultiPolygon'}:
        if len(geometry.geoms) == 1:
            return geometry.geoms[0]
    return geometry


def _is_date(value):
    return isinstance(value, date) and not isinstance(value, datetime)


def _naive_midnight_date(value):
    """Recognize temporal objects without parsing text or discarding time."""
    if not isinstance(value, (datetime, np.datetime64)):
        return None
    stamp = pd.Timestamp(value)
    if pd.isna(stamp) or stamp.tzinfo is not None:
        return None
    if any((stamp.hour, stamp.minute, stamp.second, stamp.microsecond, stamp.nanosecond)):
        return None
    return stamp.date()


def _normalize_date_pairs(actual, expected, fields):
    """Normalize native DATE values and their exact midnight counterparts."""
    for field in fields:
        left, right = actual[field].tolist(), expected[field].tolist()
        if not any(_is_date(value) for value in left + right):
            continue
        for row, (before, after) in enumerate(zip(left, right)):
            if _is_date(before):
                normalized = _naive_midnight_date(after)
                if normalized is not None:
                    right[row] = normalized
            elif _is_date(after):
                normalized = _naive_midnight_date(before)
                if normalized is not None:
                    left[row] = normalized
            # DATE columns use None; datetime64 columns use NaT. Normalize
            # only matching missing cells, never a missing/nonmissing pair.
            if (pd.api.types.is_scalar(before) and pd.api.types.is_scalar(after)
                    and pd.isna(before) and pd.isna(after)):
                left[row] = right[row] = None
        actual[field] = pd.Series(left, index=actual.index, dtype=object)
        expected[field] = pd.Series(right, index=expected.index, dtype=object)


def same(left, right):
    """Compare records while normalizing equivalent GIS representations.

    Geometry-column placement and singleton multi-geometries may change in
    GDAL drivers. Attribute order, field names, row order, CRS and attribute
    values must still agree. No numeric tolerance is applied to attributes.
    Coordinate equality retains the existing small reprojection tolerance.
    The index is not compared because GIS output is written with index=False.
    A native DATE may match a naive temporal object at exactly midnight;
    text, nonzero times and timezone-aware timestamps are never coerced.
    """
    assert left.columns.is_unique and right.columns.is_unique, 'Duplicate field names'
    assert left.geometry.name == right.geometry.name, 'Different active geometry'
    geometry = left.geometry.name
    left_fields = [name for name in left.columns if name != geometry]
    right_fields = [name for name in right.columns if name != geometry]
    assert left_fields == right_fields, f'Attribute schema differs: {left_fields!r} != {right_fields!r}'
    fields = left_fields + [geometry]
    actual = left.loc[:, fields].reset_index(drop=True).copy()
    expected = right.loc[:, fields].reset_index(drop=True).copy()
    _normalize_date_pairs(actual, expected, left_fields)
    pd.testing.assert_frame_equal(actual[left_fields], expected[left_fields],
                                  check_dtype=False, check_exact=True)
    actual.geometry = actual.geometry.map(_single_part)
    expected.geometry = expected.geometry.map(_single_part)
    assert_geodataframe_equal(actual, expected, check_dtype=False,
                              check_less_precise=True, normalize=True)
