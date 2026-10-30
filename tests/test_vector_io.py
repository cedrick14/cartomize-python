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


@pytest.fixture
def flatgeobuf_null_source(tmp_path):
    path = tmp_path / 'null_geometry.fgb'
    raw_write(path, geometry=shapely.to_wkb([Point(0, 0), None, Point(2, 2), Point(3, 3)]),
        field_data=[np.array([2**60 + 3, 0, 2**60 + 5, 2**60 + 7], dtype='int64'),
                    np.array(['001', 'NA', '003', '004'], dtype=object),
                    np.array(['2024-02-29T01:02:03.123', 'NaT', '2024-03-02T03:04:05.678',
                              '2024-03-03T04:05:06.789'], dtype='datetime64[ms]')],
        fields=['identifier', 'geometry', 'observed_at'],
        field_mask=[np.array([False, True, False, False]), None, None],
        layer='features', driver='FlatGeobuf', geometry_type='Point',
        crs=CRS(4326).to_wkt(), layer_options={'SPATIAL_INDEX': 'NO'})
    return path


def test_flatgeobuf_null_geometry_keeps_arrow_nullable_int64_and_business_geometry(flatgeobuf_null_source):
    result = cm.read_file(flatgeobuf_null_source)
    assert result.index.tolist() == [0, 1, 2, 3]
    assert int(result.identifier.iloc[0]) == 2**60 + 3
    assert pd.isna(result.identifier.iloc[1])
    assert int(result.identifier.iloc[2]) == 2**60 + 5
    assert result.geometry.iloc[1] is None
    assert result['geometry'].tolist() == ['001', 'NA', '003', '004']
    assert result.geometry.name != 'geometry'
    assert result.observed_at.iloc[0] == pd.Timestamp('2024-02-29T01:02:03.123')


def test_flatgeobuf_rows_columns_layer_and_fid_index_agree(flatgeobuf_null_source):
    result = cm.read_file(flatgeobuf_null_source, layer='features', columns=['identifier'],
                          rows=slice(1, 3), fid_as_index=True)
    assert result.index.tolist() == [1, 2]
    assert result.index.name == 'fid'
    assert list(result.columns) == ['identifier', result.geometry.name]
    assert pd.isna(result.identifier.iloc[0])
    assert int(result.identifier.iloc[1]) == 2**60 + 5
    assert result.geometry.iloc[0] is None
    assert result.geometry.iloc[1].wkb == Point(2, 2).wkb


@pytest.mark.parametrize('option', ['bbox', 'mask'])
def test_flatgeobuf_spatial_filters_use_matching_ids_and_normalize_crs(flatgeobuf_null_source, option):
    area = gpd.GeoSeries([box(1.5, 1.5, 2.5, 2.5)], crs=4326).to_crs(3857)
    result = cm.read_file(flatgeobuf_null_source, **{option: area}, fid_as_index=True)
    assert result.index.tolist() == [2]
    assert int(result.identifier.iloc[0]) == 2**60 + 5
    assert result.geometry.iloc[0].wkb == Point(2, 2).wkb


def test_flatgeobuf_where_filter_preserves_null_geometry_and_exact_schema(flatgeobuf_null_source):
    result = cm.read_file(flatgeobuf_null_source, where="geometry IN ('NA', '003')", fid_as_index=True)
    assert result.index.tolist() == [1, 2]
    assert result['geometry'].tolist() == ['NA', '003']
    assert result.geometry.iloc[0] is None
    assert int(result.identifier.iloc[1]) == 2**60 + 5


def test_flatgeobuf_sql_aliases_keep_result_types_and_nulls(flatgeobuf_null_source):
    result = cm.read_file(flatgeobuf_null_source,
        sql='SELECT identifier, geometry AS code, observed_at AS sampled_at FROM features ORDER BY FID',
        sql_dialect='OGRSQL', fid_as_index=True)
    assert result.code.tolist() == ['001', 'NA', '003', '004']
    assert int(result.identifier.iloc[0]) == 2**60 + 3
    assert pd.isna(result.identifier.iloc[1])
    assert result.sampled_at.iloc[0] == pd.Timestamp('2024-02-29T01:02:03.123')
    assert result.geometry.iloc[1] is None


@pytest.mark.parametrize('options', [{'ignore_geometry': True}, {'read_geometry': False}])
def test_flatgeobuf_explicit_attribute_only_read_is_preserved(flatgeobuf_null_source, options):
    result = cm.read_file(flatgeobuf_null_source, **options)
    assert not isinstance(result, gpd.GeoDataFrame)
    assert result['geometry'].tolist() == ['001', 'NA', '003', '004']
    assert int(result.identifier.iloc[0]) == 2**60 + 3
    assert pd.isna(result.identifier.iloc[1])


def test_flatgeobuf_datetime_as_string_remains_explicit(flatgeobuf_null_source):
    result = cm.read_file(flatgeobuf_null_source, datetime_as_string=True)
    assert isinstance(result.observed_at.iloc[0], str)
    assert pd.Timestamp(result.observed_at.iloc[0]) == pd.Timestamp('2024-02-29T01:02:03.123')


def test_flatgeobuf_fid_selection_keeps_geometry_attribute_identity(flatgeobuf_null_source):
    result = cm.read_file(flatgeobuf_null_source, fids=[2, 0], fid_as_index=True)
    for fid, row in result.iterrows():
        assert row[result.geometry.name].wkb == Point(fid, fid).wkb
        assert int(row['identifier']) == {0: 2**60 + 3, 2: 2**60 + 5}[fid]


def test_flatgeobuf_spatial_filter_then_pagination_selects_matching_attributes(flatgeobuf_null_source):
    result = cm.read_file(flatgeobuf_null_source, bbox=(1.5, 1.5, 3.5, 3.5), rows=slice(1, 2),
                          columns=['identifier'], fid_as_index=True)
    assert result.index.tolist() == [3]
    assert int(result.identifier.iloc[0]) == 2**60 + 7
    assert result.geometry.iloc[0].wkb == Point(3, 3).wkb


@pytest.mark.parametrize('rows', [0, slice(1, 1), slice(3, 2), slice(0, 0)])
def test_flatgeobuf_empty_row_selection_is_empty_with_original_types(flatgeobuf_null_source, rows):
    result = cm.read_file(flatgeobuf_null_source, rows=rows, columns=['identifier'])
    assert result.empty
    assert isinstance(result, gpd.GeoDataFrame)
    assert str(result.identifier.dtype) == 'Int64'
    assert result.crs == CRS(4326)
