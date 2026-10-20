"""Strict semantic comparison for vector results reloaded from GIS files."""
from geopandas.testing import assert_geodataframe_equal
import pandas as pd


def _single_part(geometry):
    """Undo a driver's single-to-multi promotion, never discard extra parts."""
    if geometry is not None and geometry.geom_type in {'MultiPoint', 'MultiLineString', 'MultiPolygon'}:
        if len(geometry.geoms) == 1:
            return geometry.geoms[0]
    return geometry


def same(left, right):
    """Compare records while normalizing two equivalent GIS representations.

    Geometry-column placement and singleton multi-geometries may change in
    GDAL drivers. Attribute order, field names, row order, CRS and attribute
    values must still agree. No numeric tolerance is applied to attributes.
    Coordinate equality retains the existing small reprojection tolerance.
    The index is not compared because GIS output is written with index=False.
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
    pd.testing.assert_frame_equal(actual[left_fields], expected[left_fields],
                                  check_dtype=False, check_exact=True)
    actual.geometry = actual.geometry.map(_single_part)
    expected.geometry = expected.geometry.map(_single_part)
    assert_geodataframe_equal(actual, expected, check_dtype=False,
                              check_less_precise=True, normalize=True)
