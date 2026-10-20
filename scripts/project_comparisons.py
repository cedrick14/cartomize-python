"""Strict semantic comparison for vector results reloaded from GIS files."""
from geopandas.testing import assert_geodataframe_equal
import pandas as pd


def same(left, right):
    """Compare records in order while allowing only the geometry column to move.

    GDAL vector drivers expose geometry separately from attribute fields and
    GeoPandas normally appends it when reading a file. Attribute order, field
    names, row order, active geometry, CRS and values must still agree. The
    row index is intentionally not compared because GIS output uses index=False.
    Driver-dependent integer widths and nullable dtypes are not significant.
    """
    assert left.columns.is_unique and right.columns.is_unique, 'Duplicate field names'
    assert left.geometry.name == right.geometry.name, 'Different active geometry'
    geometry = left.geometry.name
    left_fields = [name for name in left.columns if name != geometry]
    right_fields = [name for name in right.columns if name != geometry]
    assert left_fields == right_fields, f'Attribute schema differs: {left_fields!r} != {right_fields!r}'
    fields = left_fields + [geometry]
    actual = left.loc[:, fields].reset_index(drop=True)
    expected = right.loc[:, fields].reset_index(drop=True)
    # Attribute equality remains exact. Geometry coordinates may have the
    # original comparator's small round-trip projection tolerance.
    pd.testing.assert_frame_equal(actual[left_fields], expected[left_fields],
                                  check_dtype=False, check_exact=True)
    assert_geodataframe_equal(actual, expected, check_dtype=False,
                              check_less_precise=True, normalize=True)
