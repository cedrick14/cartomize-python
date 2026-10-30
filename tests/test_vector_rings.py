"""Distance-band geometry, analytic areas, identities and guarded execution."""
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
import json
import math
from threading import Event

import geopandas as gpd
from geopandas.testing import assert_geodataframe_equal
import numpy as np
import pandas as pd
import pytest
import shapely
from shapely.geometry import (GeometryCollection, LinearRing, LineString,
                              MultiLineString, MultiPoint, MultiPolygon,
                              Point, Polygon, box)

from cartomize.algebra import ProcessingCancelled
from cartomize.vector_io import write_geopackage
from cartomize.vector_rings import BufferRingsResult, buffer_rings


def layer(geometries, *, values=None, crs=32733):
    fields = {} if values is None else {'key': pd.Series(values, dtype=object)}
    return gpd.GeoDataFrame(fields, geometry=geometries, crs=crs)


def run(data, distances=(10, 20, 50), **kwargs):
    return buffer_rings(data, distances, area_unit=kwargs.pop('area_unit', 'm2'), **kwargs)


def circle_coefficient(quad_segs):
    # Shoelace area of the regular 4q-gon inscribed in a unit circle.
    return 2 * quad_segs * math.sin(math.pi / (2 * quad_segs))


def assert_partition(result):
    assert isinstance(result, BufferRingsResult)
    json.dumps(result.summary, allow_nan=False)
    assert result.table.columns.tolist() == ['ring_id', 'group_id', 'band_index',
                                             'lower_m', 'upper_m', 'area']
    assert len(result.table) == result.summary['group_count'] * result.summary['band_count']
    assert result.data.ring_id.tolist() == result.table[result.table.area > 0].ring_id.tolist()
    assert result.table.ring_id.is_unique
    divisor = {'m2': 1, 'ha': 10000, 'km2': 1000000}[result.summary['area_unit']]
    factor = result.summary['metres_per_coordinate_unit']
    for row in result.balances.itertuples():
        allowed = 1e-6 / divisor + 1e-8 * row.expected_area
        cells = result.table[result.table.group_id == row.group_id]
        assert cells.area.sum() == pytest.approx(row.sum_ring_area)
        assert row.expected_area - row.sum_ring_area == pytest.approx(row.closure_error)
        assert row.sum_ring_area - row.union_ring_area == pytest.approx(row.raw_excess_area)
        assert abs(row.closure_error) <= allowed
        assert abs(row.raw_excess_area) <= allowed
        assert row.overlap_area <= allowed
        assert row.uncovered_area <= allowed
        assert row.outside_area <= allowed
        rings = result.data[result.data.group_id == row.group_id]
        for position, geometry in enumerate(rings.geometry):
            for other in rings.geometry.iloc[position + 1:]:
                assert geometry.intersection(other).area * factor ** 2 / divisor <= allowed
    assert result.data.crs == result.sources.crs
    assert result.data.geometry.is_valid.all()
    assert all(geometry.geom_type in {'Polygon', 'MultiPolygon'} for geometry in result.data.geometry)
    assert all(geometry.area > 0 for geometry in result.data.geometry)
    assert not shapely.has_z(result.data.geometry).any()
    assert not shapely.has_z(result.sources.geometry).any()
    assert result.summary['totals']['excess_area'] == max(0, result.summary['totals']['raw_excess_area'])
    for frame in (result.data, result.table, result.sources, result.balances):
        assert frame.attrs['area_unit'] == result.summary['area_unit']
        assert frame.attrs['measurement_crs'] == result.summary['measurement_crs']


@pytest.mark.parametrize('quad_segs', [1, 2, 16, 64])
@pytest.mark.parametrize('mode', ['dissolved', 'independent'])
def test_point_rings_have_closed_form_regular_polygon_area(quad_segs, mode):
    result = run(layer([Point(0, 0)]), quad_segs=quad_segs, mode=mode)
    coefficient = circle_coefficient(quad_segs)
    assert result.table.area.tolist() == pytest.approx(
        [coefficient * 100, coefficient * 300, coefficient * 2100], rel=1e-12)
    assert result.table.lower_m.tolist() == [0, 10, 20]
    assert result.table.upper_m.tolist() == [10, 20, 50]
    assert result.table.band_index.tolist() == [1, 2, 3]
    assert result.sources.id_type.tolist() == ['integer']
    assert result.sources.id_value.tolist() == ['0']
    assert result.sources.source_area.tolist() == [0]
    assert result.balances.base_area.tolist() == [0]
    assert_partition(result)


@pytest.mark.parametrize('include_input', [False, True])
def test_straight_line_uses_two_round_caps_and_keeps_zero_area_source(include_input):
    result = run(layer([LineString([(0, 0), (100, 0)])]), include_input=include_input)
    coefficient = circle_coefficient(16)
    cumulative = [200 * distance + coefficient * distance ** 2 for distance in (10, 20, 50)]
    assert result.table.area.tolist() == pytest.approx(
        [cumulative[0], cumulative[1] - cumulative[0], cumulative[2] - cumulative[1]])
    assert result.balances.base_area.iloc[0] == 0
    assert result.sources.source_area.iloc[0] == 0
    assert_partition(result)


@pytest.mark.parametrize('include_input', [False, True])
@pytest.mark.parametrize('quad_segs', [1, 16])
def test_rectangle_exterior_bands_and_explicit_interior_have_analytic_balance(include_input, quad_segs):
    result = run(layer([box(0, 0, 100, 50)]), include_input=include_input,
                 quad_segs=quad_segs)
    coefficient = circle_coefficient(quad_segs)
    cumulative = [5000 + 300 * distance + coefficient * distance ** 2
                  for distance in (10, 20, 50)]
    expected = [cumulative[0] - (0 if include_input else 5000),
                cumulative[1] - cumulative[0], cumulative[2] - cumulative[1]]
    assert result.table.area.tolist() == pytest.approx(expected)
    assert result.balances.base_area.tolist() == [0 if include_input else 5000]
    assert result.balances.outer_area.iloc[0] == pytest.approx(cumulative[-1])
    assert result.sources.source_area.tolist() == [5000]
    assert result.data.geometry.iloc[0].covers(Point(50, 25)) is include_input
    assert_partition(result)


def test_polygon_holes_receive_their_own_outward_strips_and_source_is_excluded():
    polygon = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)],
                      [[(30, 30), (70, 30), (70, 70), (30, 70)]])
    result = run(layer([polygon]), distances=[5, 10])
    first, second = result.data.geometry
    assert first.covers(Point(32, 50))
    assert second.covers(Point(37, 50))
    assert not shapely.union_all(result.data.geometry).covers(Point(50, 50))
    assert shapely.union_all(result.data.geometry).intersection(polygon).area == 0
    coefficient = circle_coefficient(16)
    # Exterior expansion + inner square strips; the hole's inward corners stay square.
    expected_total = 400 * 10 + coefficient * 100 + 1600 - 20 ** 2
    assert result.table.area.sum() == pytest.approx(expected_total)
    assert_partition(result)


@pytest.mark.parametrize('geometry,expected', [
    (MultiPoint([(0, 0), (1000, 0)]), 2 * circle_coefficient(16) * 100),
    (MultiLineString([[(0, 0), (100, 0)], [(1000, 0), (1100, 0)]]),
     2 * (2000 + circle_coefficient(16) * 100)),
    (MultiPolygon([box(0, 0, 100, 100), box(1000, 0, 1100, 100)]),
     2 * (4000 + circle_coefficient(16) * 100)),
])
def test_multipart_feature_remains_one_independent_source_group(geometry, expected):
    result = run(layer([geometry]), distances=[10], mode='independent')
    assert result.table.area.tolist() == pytest.approx([expected])
    assert result.summary['groups'] == [{'group_id': 'g000001',
                                         'source_ids': ['s000001'], 'source_rows': [0]}]
    assert result.sources.geometry_type.tolist() == [geometry.geom_type]
    assert_partition(result)


def test_dissolved_bands_partition_distance_to_nearest_source_without_feature_double_counting():
    source = layer([Point(0, 0), Point(15, 0)], values=['same', 'same'])
    result = run(source, distances=[10, 20, 30], id_field='key')
    independent = run(source, distances=[10, 20, 30], id_field='key', mode='independent')
    assert result.summary['group_count'] == 1
    assert result.summary['groups'][0]['source_rows'] == [0, 1]
    assert result.balances.source_count.tolist() == [2]
    assert len(result.data) == 3
    assert len(independent.data) == 6
    assert result.table.area.sum() < independent.table.area.sum()
    assert result.summary['totals']['union_ring_area'] == pytest.approx(
        independent.summary['totals']['union_ring_area'])
    assert independent.summary['totals']['overlap_area'] > 0
    assert independent.summary['totals']['excess_area'] > 0
    for row in result.data.itertuples():
        point = Point(-((row.lower_m + row.upper_m) / 2), 0)
        assert row.geometry.covers(point)
    assert_partition(result)
    assert_partition(independent)


def test_three_identical_independent_sources_distinguish_unique_overlap_from_excess():
    source = layer([Point(0, 0)] * 3, values=['mine', 'mine', 'mine'])
    result = run(source, id_field='key', mode='independent', quad_segs=1)
    assert result.sources.id_value.tolist() == ['mine'] * 3
    assert result.summary['group_count'] == 3
    assert result.summary['totals']['union_ring_area'] == 5000
    assert result.summary['totals']['overlap_area'] == 5000
    assert result.summary['totals']['sum_ring_area'] == 15000
    assert result.summary['totals']['excess_area'] == 10000
    assert result.balances.overlap_area.tolist() == [0, 0, 0]
    assert_partition(result)


def test_overlapping_polygons_exclude_union_base_and_mixed_lines_do_not_restore_it():
    source = layer([box(0, 0, 100, 100), box(50, 0, 150, 100),
                    LineString([(-30, 50), (180, 50)]), Point(75, 50)])
    result = run(source, distances=[10, 30])
    included = run(source, distances=[10, 30], include_input=True)
    assert result.balances.base_area.tolist() == [15000]
    assert result.sources.source_area.tolist() == [10000, 10000, 0, 0]
    assert result.table.area.sum() + 15000 == pytest.approx(included.table.area.sum())
    base = box(0, 0, 150, 100)
    assert all(geometry.intersection(base).area == 0 for geometry in result.data.geometry)
    assert_partition(result)
    assert_partition(included)


def test_exact_typed_labels_and_positional_ids_ignore_duplicates_and_dataframe_index():
    values = ['001', 'NA', '', '1', 1, True, 2**64 - 1, date(2026, 10, 30),
              datetime(2026, 10, 30, 12, tzinfo=timezone(timedelta(hours=1))),
              Decimal('1234567890123456789012345678901234567890.00'), '001']
    source = layer([Point(0, 0)] * len(values), values=values)
    source['group_id'] = 'existing source attribute'
    source['area'] = -123
    source.index = ['duplicate index'] * len(source)
    before = source.copy(deep=True)
    result = run(source, distances=[1], id_field='key', mode='independent')
    assert result.sources.id_type.tolist() == ['string'] * 4 + [
        'integer', 'boolean', 'integer', 'date', 'datetime_utc', 'decimal', 'string']
    assert result.sources.id_value.tolist() == [
        '001', 'NA', '', '1', '1', 'true', str(2**64 - 1), '2026-10-30',
        '2026-10-30T11:00:00+00:00', '1.23456789012345678901234567890123456789E+39', '001']
    assert result.sources.source_row.tolist() == list(range(len(values)))
    assert len(result.summary['groups']) == len(values)
    assert result.sources.source_id.is_unique
    assert_geodataframe_equal(source, before)
    assert result.data.area.min() > 0
    assert_partition(result)


@pytest.mark.parametrize('unit,divisor', [('m2', 1), ('ha', 10000), ('km2', 1000000)])
def test_area_unit_changes_all_measures_but_not_geometry_or_distance_bounds(unit, divisor):
    source = layer([Point(0, 0)])
    result = run(source, area_unit=unit, quad_segs=1)
    assert result.table.area.tolist() == pytest.approx([200 / divisor, 600 / divisor, 4200 / divisor])
    assert result.balances.outer_area.tolist() == pytest.approx([5000 / divisor])
    assert result.summary['totals']['union_ring_area'] == pytest.approx(5000 / divisor)
    assert result.data.geometry.iloc[0].area == 200
    assert result.table.upper_m.tolist() == [10, 20, 50]
    assert_partition(result)


def test_geographic_source_requires_explicit_projection_and_remains_unchanged():
    source = layer([Point(15, -4)], values=['village'], crs=4326)
    before = source.copy()
    with pytest.raises(ValueError, match='projected'):
        run(source)
    result = run(source, metric_crs=32733, id_field='key', quad_segs=1)
    assert result.data.crs.to_epsg() == 32733
    assert result.sources.crs.to_epsg() == 32733
    assert result.sources.geometry.iloc[0].equals(source.to_crs(32733).geometry.iloc[0])
    assert result.summary['source_crs'] == 'EPSG:4326'
    assert result.table.area.tolist() == pytest.approx([200, 600, 4200], abs=1e-6)
    assert_geodataframe_equal(source, before)
    assert_partition(result)


def test_projected_feet_distances_and_areas_are_converted_without_return_to_source_units():
    source = layer([Point(1000000, 200000)], crs=2263)
    result = run(source, distances=[30.48, 60.96], quad_segs=1)
    factor = source.crs.axis_info[0].unit_conversion_factor
    assert result.data.crs == source.crs
    assert result.summary['metres_per_coordinate_unit'] == factor
    assert result.table.area.tolist() == pytest.approx([2 * 30.48 ** 2, 6 * 30.48 ** 2])
    assert result.data.total_bounds[2] - 1000000 == pytest.approx(60.96 / factor)
    assert result.table.upper_m.tolist() == [30.48, 60.96]
    assert_partition(result)


@pytest.mark.parametrize('mode', ['dissolved', 'independent'])
def test_empty_layer_has_typed_empty_products_and_no_invented_source_group(mode):
    source = layer([], values=[])
    result = run(source, mode=mode, id_field='key')
    for frame in (result.data, result.table, result.sources, result.balances):
        assert frame.empty and len(frame.columns)
    assert result.summary['input_features'] == result.summary['group_count'] == 0
    assert result.summary['band_count'] == 3
    assert result.summary['groups'] == []
    assert set(result.summary['totals'].values()) == {0}
    assert_partition(result)


def test_positive_slivers_smaller_than_absolute_check_tolerance_are_retained():
    result = run(layer([Point(0, 0)]), distances=[1e-4, 2e-4], quad_segs=1)
    assert len(result.data) == 2
    assert result.table.area.tolist() == pytest.approx([2e-8, 6e-8], rel=1e-12, abs=1e-20)
    assert result.summary['empty_intervals'] == 0
    assert_partition(result)


def test_numerically_empty_interval_stays_in_dense_table_with_stable_ring_ids():
    result = run(layer([Point(1e12, 1e12)]), distances=[1, 1 + 1e-12, 2], quad_segs=1)
    assert result.table.area.tolist() == [2, 0, 6]
    assert result.table.ring_id.tolist() == ['r000001', 'r000002', 'r000003']
    assert result.data.ring_id.tolist() == ['r000001', 'r000003']
    assert result.summary['empty_intervals'] == 1
    assert_partition(result)


@pytest.mark.parametrize('distances', [
    None, 1, 1.5, '10,20', b'10', {'x': 10}, {10, 20}, frozenset([10]), [],
    [0], [-1], [True], [np.bool_(True)], ['10'], [None], [float('nan')],
    [float('inf')], [float('-inf')], [10, 10], [20, 10], [[10]],
    np.array([[10, 20]]), [10**1000], [1, float('nan')], [Decimal('10')],
])
def test_invalid_distance_sequences_are_refused_without_coercion(distances):
    with pytest.raises(ValueError, match='distance|Distances'):
        run(layer([Point(0, 0)]), distances=distances)


def test_ordered_numpy_and_generator_distances_are_supported():
    source = layer([Point(0, 0)])
    for values in (np.array([1, 2, 3], dtype=np.int64), (value for value in [1., 2., 3.])):
        result = run(source, distances=values, quad_segs=1)
        assert result.table.area.tolist() == [2, 6, 10]


@pytest.mark.parametrize('quad_segs', [0, -1, 1025, True, np.bool_(False), 1.0, 1.5, '16', None])
def test_invalid_arc_resolution_is_refused(quad_segs):
    with pytest.raises(ValueError, match='quad_segs'):
        run(layer([Point(0, 0)]), quad_segs=quad_segs)


@pytest.mark.parametrize('key,value,message', [
    ('mode', 'all', 'mode'), ('mode', None, 'mode'), ('mode', [], 'mode'),
    ('area_unit', 'm', 'area_unit'), ('area_unit', None, 'area_unit'),
    ('include_input', 'false', 'include_input'), ('include_input', 0, 'include_input'),
    ('include_input', None, 'include_input'), ('progress', 1, 'progress'),
])
def test_invalid_options_fail_before_geometry_work(key, value, message):
    with pytest.raises(ValueError, match=message):
        run(layer([Point(0, 0)]), **{key: value})


@pytest.mark.parametrize('geometry', [None, Point(), LineString(), Polygon(),
    Point(float('inf'), 0), Point(float('nan'), 1),
    shapely.from_wkt('POINT Z (0 0 NaN)'),
    Polygon([(0, 0), (2, 2), (0, 2), (2, 0), (0, 0)]),
    GeometryCollection([Point(0, 0)]), LinearRing([(0, 0), (1, 0), (0, 1)]),
    MultiPolygon([box(0, 0, 2, 2), box(1, 0, 3, 2)]),
])
def test_unusable_geometries_are_refused_without_implicit_repairs(geometry):
    source = layer([geometry])
    before = source.geometry.to_wkb().tolist()
    with pytest.raises(ValueError, match='geometry|coordinates|Polygon|polygon'):
        run(source)
    assert source.geometry.to_wkb().tolist() == before


def test_invalid_geometry_created_by_projection_is_refused():
    source = layer([Point(0, 100)], crs=4326)
    with pytest.raises(ValueError, match='after reprojection.*nonfinite'):
        run(source, metric_crs=3857)


def test_unknown_crs_and_geographic_analysis_crs_are_refused():
    source = layer([Point(0, 0)], crs=None)
    with pytest.raises(ValueError, match='no CRS'):
        run(source)
    with pytest.raises(ValueError, match='projected'):
        run(layer([Point(0, 0)]), metric_crs=4326)


@pytest.mark.parametrize('bad', [None, pd.NA, float('nan')])
def test_missing_selected_label_is_refused(bad):
    with pytest.raises(ValueError, match='missing label'):
        run(layer([Point(0, 0)], values=[bad]), id_field='key')


@pytest.mark.parametrize('id_field', ['', 7, 'missing', 'geometry'])
def test_invalid_selected_field_is_refused(id_field):
    with pytest.raises(ValueError, match='id_field'):
        run(layer([Point(0, 0)], values=['one']), id_field=id_field)


@pytest.mark.parametrize('value', [[1, 2], {'a': 1}, complex(1, 2), float('inf'), 'a\x00b'])
def test_unsupported_selected_label_cannot_be_silently_stringified(value):
    with pytest.raises(ValueError, match='id_field'):
        run(layer([Point(0, 0)], values=[value]), id_field='key')


def test_duplicate_columns_are_refused_even_without_selected_label():
    source = layer([Point(0, 0)])
    source.insert(0, 'duplicate', 1)
    source.insert(0, 'duplicate', 2, allow_duplicates=True)
    with pytest.raises(ValueError, match='field names must be unique'):
        run(source)


def test_z_and_m_are_audited_before_explicit_2d_work_and_source_stays_exact():
    geometries = [shapely.from_wkt('POINT Z (0 0 7)')]
    if hasattr(shapely, 'has_m') and tuple(shapely.geos_version) >= (3, 12, 0):
        geometries.extend([shapely.from_wkt('POINT M (100 0 8)'),
                           shapely.from_wkt('LINESTRING ZM (200 0 3 9, 210 0 4 10)')])
    source = layer(geometries)
    before = source.geometry.to_wkb().tolist()
    result = run(source, distances=[1, 2])
    assert result.summary['dimensionality']['z_features'] == (2 if len(geometries) == 3 else 1)
    assert result.summary['dimensionality']['m_features'] == (2 if len(geometries) == 3 else 0)
    assert source.geometry.to_wkb().tolist() == before
    assert all(len(geometry.coords[0]) == 2 for geometry in result.sources.geometry)
    assert_partition(result)


def test_nonfinite_m_is_refused_before_dimension_drop():
    if not hasattr(shapely, 'has_m') or tuple(shapely.geos_version) < (3, 12, 0):
        pytest.skip('Measured geometries require GEOS 3.12 and Shapely 2.1.')
    source = layer([shapely.from_wkt('POINT M (0 0 NaN)')])
    with pytest.raises(ValueError, match='nonfinite'):
        run(source)


def test_file_layers_are_explicit_and_numeric_looking_names_are_preserved(tmp_path):
    source = layer([Point(0, 0)], values=['001'])
    path = tmp_path / 'sources.gpkg'
    write_geopackage(source, path, layer='007')
    source.to_file(path, layer='008', driver='GPKG')
    original = path.read_bytes()
    with pytest.raises(ValueError, match='multiple layers'):
        run(path)
    with pytest.raises(ValueError, match='Unknown vector layer'):
        run(path, layer='009')
    result = run(path, layer='007', id_field='key')
    assert result.summary['parameters']['layer'] == '007'
    assert result.sources.id_value.tolist() == ['001']
    assert path.read_bytes() == original
    with pytest.raises(ValueError, match='file input'):
        run(source, layer='007')


def test_geoseries_input_is_an_independent_copy():
    source = gpd.GeoSeries([Point(0, 0)], index=['label'], crs=32733)
    before = source.copy()
    result = run(source)
    assert source.equals(before)
    assert result.sources.source_row.tolist() == [0]
    assert_partition(result)


def test_progress_is_monotonic_and_ends_at_the_documented_total():
    progress = []
    result = run(layer([Point(0, 0), Point(15, 0)]), mode='independent',
                 progress=lambda done, total: progress.append((done, total)))
    assert progress[0] == (0, 10000) and progress[-1] == (10000, 10000)
    assert all(left[0] < right[0] for left, right in zip(progress, progress[1:]))
    assert all(total == 10000 for _, total in progress)
    assert_partition(result)


@pytest.mark.parametrize('threshold', [0, 600, 1200, 2000, 7900, 8400, 9400, 10000])
def test_cancellation_at_stages_returns_no_partial_result_or_source_mutation(threshold):
    source = layer([Point(0, 0), Point(15, 0)], values=['A', 'B'])
    before = source.copy()
    event = Event()
    def progress(done, total):
        if done >= threshold:
            event.set()
    with pytest.raises(ProcessingCancelled):
        run(source, mode='independent', progress=progress, cancel=event)
    assert_geodataframe_equal(source, before)


def test_already_cancelled_call_does_not_read_the_source():
    event = Event()
    event.set()
    with pytest.raises(ProcessingCancelled):
        run('/a/path/that/does/not/exist.gpkg', cancel=event)


def test_positive_buffer_that_collapses_in_coordinate_precision_is_refused():
    with pytest.raises(ValueError, match='collapsed to an empty'):
        run(layer([Point(1e12, 1e12)]), distances=[1e-10])


def test_nonnested_buffer_cannot_be_published_as_an_area_partition(monkeypatch):
    import cartomize.vector_rings as rings
    real_buffer = rings.shapely.buffer
    def unexpected_shrink(geometry, distance, **kwargs):
        return real_buffer(geometry, 1 if distance == 20 else distance, **kwargs)
    monkeypatch.setattr(rings.shapely, 'buffer', unexpected_shrink)
    with pytest.raises(ValueError, match='not nested'):
        run(layer([Point(0, 0)]), distances=[10, 20])


def test_invalid_generated_polygon_is_refused_instead_of_repaired(monkeypatch):
    import cartomize.vector_rings as rings
    invalid = Polygon([(0, 0), (2, 2), (0, 2), (2, 0), (0, 0)])
    monkeypatch.setattr(rings.shapely, 'buffer', lambda *args, **kwargs: invalid)
    with pytest.raises(ValueError, match='invalid or nonfinite'):
        run(layer([Point(0, 0)]))
