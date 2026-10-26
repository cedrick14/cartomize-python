"""Public vector read options preserve the schema of the selected result."""
from datetime import date
from io import BytesIO

import geopandas as gpd
import numpy as np
import pandas as pd
from pyogrio.raw import write as raw_write
from pyproj import CRS
import pytest
import shapely
from shapely.geometry import Point, box, mapping

import cartomize as cm


@pytest.fixture
def source(tmp_path):
    path = tmp_path / 'observations.gpkg'
    raw_write(path, geometry=shapely.to_wkb([Point(i, i) for i in range(4)]),
        field_data=[
            np.array(['A', 'B', 'C', 'D'], dtype=object),
            np.array([2**60 + 3, 0, -7, 42], dtype='int64'),
            np.array(['2024-02-29', 'NaT', '2024-03-02', '2024-03-03'], dtype='datetime64[D]'),
            np.array(['2024-02-29T01:02:03.123', 'NaT', '2024-03-02T03:04:05.678',
                      '2024-03-03T04:05:06.789'], dtype='datetime64[ms]'),
        ], fields=['label', 'identifier', 'survey_date', 'observed_at'],
        field_mask=[None, np.array([False, True, False, False]), None, None],
        layer='observations', driver='GPKG', geometry_type='Point', crs=CRS(4326).to_wkt(),
        layer_options={'SPATIAL_INDEX': 'NO'})
    return path


def test_sql_expression_type_replaces_same_named_physical_datetime(source):
    result = cm.read_file(source,
        sql='SELECT geom, CAST(7 AS INTEGER) AS observed_at FROM observations ORDER BY fid',
        sql_dialect='SQLITE')
    assert pd.api.types.is_integer_dtype(result.observed_at.dtype)
    assert result.observed_at.tolist() == [7, 7, 7, 7]
    assert result.geometry.x.tolist() == [0., 1., 2., 3.]


def test_sql_aliases_keep_date_and_datetime_types_and_nulls(source):
    result = cm.read_file(source,
        sql='SELECT geom, survey_date AS visit_date, observed_at AS sampled_at FROM observations ORDER BY fid',
        sql_dialect='SQLITE')
    assert type(result.visit_date.iloc[0]) is date
    assert result.visit_date.iloc[0] == date(2024, 2, 29)
    assert result.sampled_at.iloc[0] == pd.Timestamp('2024-02-29T01:02:03.123')
    assert result.sampled_at.iloc[0].tzinfo is None
    assert pd.isna(result.visit_date.iloc[1])
    assert pd.isna(result.sampled_at.iloc[1])


def test_sql_business_attribute_geometry_is_distinct_from_active_geometry(source):
    result = cm.read_file(source,
        sql='SELECT geom, label AS geometry, identifier FROM observations ORDER BY fid',
        sql_dialect='SQLITE')
    assert result['geometry'].tolist() == ['A', 'B', 'C', 'D']
    assert result.geometry.name != 'geometry'
    assert result.geometry.x.tolist() == [0., 1., 2., 3.]
    assert result.crs == CRS(4326)
    assert int(result.identifier.iloc[0]) == 2**60 + 3
    assert pd.isna(result.identifier.iloc[1])


@pytest.mark.parametrize('option', ['bbox', 'mask'])
def test_sql_spatial_filter_normalizes_geopandas_mask_and_its_crs(source, option):
    area = gpd.GeoSeries([box(-.1, -.1, 1.1, 1.1)], crs=4326).to_crs(3857)
    result = cm.read_file(source, sql='SELECT * FROM observations ORDER BY fid',
        sql_dialect='SQLITE', **{option: area})
    assert result.label.tolist() == ['A', 'B']
    assert result.geometry.x.tolist() == [0., 1.]


@pytest.mark.parametrize('option,value', [('bbox', box(-.1, -.1, 1.1, 1.1)),
    ('mask', mapping(box(-.1, -.1, 1.1, 1.1)))], ids=['shapely_bbox', 'geojson_mask'])
def test_sql_spatial_filter_accepts_public_geometry_forms(source, option, value):
    result = cm.read_file(source, sql='SELECT * FROM observations ORDER BY fid',
        sql_dialect='SQLITE', **{option: value})
    assert result.label.tolist() == ['A', 'B']


def test_bbox_and_mask_together_are_rejected(source):
    with pytest.raises(ValueError, match='bbox|mask'):
        cm.read_file(source, sql='SELECT * FROM observations', sql_dialect='SQLITE',
            bbox=(-.1, -.1, 1.1, 1.1), mask=box(-.1, -.1, 1.1, 1.1))


@pytest.mark.parametrize('sql', [False, True], ids=['layer', 'sql'])
def test_columns_rows_and_ignore_geometry_keep_pagination_and_null_types(source, sql):
    options = {'sql': 'SELECT * FROM observations ORDER BY fid', 'sql_dialect': 'SQLITE'} if sql else {'layer': 'observations'}
    result = cm.read_file(source, columns=['label', 'identifier'], rows=slice(1, 3),
                          ignore_geometry=True, **options)
    assert list(result.columns) == ['label', 'identifier']
    assert not isinstance(result, gpd.GeoDataFrame)
    assert result.label.tolist() == ['B', 'C']
    assert pd.api.types.is_integer_dtype(result.identifier.dtype)
    assert pd.isna(result.identifier.iloc[0])
    assert int(result.identifier.iloc[1]) == -7


def test_sql_explicit_read_geometry_false_is_preserved(source):
    result = cm.read_file(source, sql='SELECT * FROM observations ORDER BY fid',
        sql_dialect='SQLITE', read_geometry=False)
    assert not isinstance(result, gpd.GeoDataFrame)
    assert 'geometry' not in result.columns and 'geom' not in result.columns
    assert result.label.tolist() == ['A', 'B', 'C', 'D']


@pytest.mark.parametrize('sql', [False, True], ids=['layer', 'sql'])
def test_file_like_source_remains_readable_with_exact_nullable_integers(source, sql):
    options = {'sql': 'SELECT * FROM observations ORDER BY fid', 'sql_dialect': 'SQLITE'} if sql else {'layer': 'observations'}
    result = cm.read_file(BytesIO(source.read_bytes()), **options)
    assert result.label.tolist() == ['A', 'B', 'C', 'D']
    assert int(result.identifier.iloc[0]) == 2**60 + 3
    assert pd.isna(result.identifier.iloc[1])
    assert type(result.survey_date.iloc[0]) is date


def test_sql_explicit_datetime_as_string_keeps_datetime_alias_as_text(source):
    result = cm.read_file(source,
        sql='SELECT geom, survey_date AS visit_date, observed_at AS sampled_at FROM observations ORDER BY fid',
        sql_dialect='SQLITE', datetime_as_string=True)
    # Arrow exposes DATE as datetime.date; this option applies to DATETIME.
    assert result.visit_date.iloc[0] == date(2024, 2, 29)
    assert isinstance(result.sampled_at.iloc[0], str)
    assert pd.Timestamp(result.sampled_at.iloc[0]) == pd.Timestamp('2024-02-29T01:02:03.123')
    assert pd.isna(result.visit_date.iloc[1])
    assert pd.isna(result.sampled_at.iloc[1])
