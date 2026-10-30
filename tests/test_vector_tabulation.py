"""Analytic area partitions, exact identities and explicit G09 topology rules."""
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal, localcontext
import json
import threading

import geopandas as gpd
from geopandas.testing import assert_geodataframe_equal
import numpy as np
import pandas as pd
import pytest
from pyproj import CRS
import shapely
from shapely.geometry import GeometryCollection, LineString, MultiPolygon, Point, Polygon, box

from cartomize.algebra import ProcessingCancelled
from cartomize.vector_io import read_vector, write_geopackage
from cartomize.vector_tabulation import AreaTabulationResult, tabulate_area


def layer(values, geometries, *, field='key', crs=3857):
    return gpd.GeoDataFrame({field: pd.Series(values, dtype=object)},
                            geometry=geometries, crs=crs)


def run(zones, classes, **kwargs):
    return tabulate_area(zones, classes, zone_field='key', class_field='key',
                         area_unit=kwargs.pop('area_unit', 'm2'), **kwargs)


def simple():
    zones = layer(['west', 'east'], [box(0, 0, 10, 10), box(10, 0, 20, 10)])
    classes = layer(['forest', 'water', 'outside'], [box(0, 0, 5, 10),
                        box(5, 0, 15, 10), box(30, 0, 40, 10)])
    return zones, classes


def assert_balances(result):
    json.dumps(result.summary, allow_nan=False)
    unit = {'m2': 1, 'ha': 10000, 'km2': 1000000}[result.summary['area_unit']]
    for zone in result.zones.itertuples():
        cells = result.table[result.table.zone_id == zone.zone_id]
        assert cells.area.sum() == pytest.approx(zone.summed_class_area)
        assert zone.covered_area + zone.uncovered_area == pytest.approx(zone.zone_area)
        assert zone.unclassified_area + zone.no_coverage_area == pytest.approx(zone.uncovered_area)
        assert zone.covered_area + zone.raw_excess_area == pytest.approx(zone.summed_class_area)
        assert abs(zone.closure_error) <= 1e-6 / unit + 1e-8 * zone.zone_area
        assert cells.percentage.sum() == pytest.approx(zone.summed_class_percentage)
    assert result.table.columns.tolist() == ['zone_id', 'zone_type', 'zone_value',
            'class_id', 'class_type', 'class_value', 'area', 'percentage']
    assert result.table.index.tolist() == list(range(len(result.table)))
    assert len(result.table) == len(result.zones) * len(result.categories)
    assert result.data.zone_id.tolist() == result.table[result.table.area > 0].zone_id.tolist()
    assert result.data.class_id.tolist() == result.table[result.table.area > 0].class_id.tolist()
    for frame in [result.data, result.zones, result.gaps, result.overlaps]:
        assert frame.crs == result.zones.crs
        assert frame.geometry.is_valid.all()
        assert all(geom.geom_type in {'Polygon', 'MultiPolygon'} for geom in frame.geometry)
        assert all(geom.area > 0 for geom in frame.geometry)
        assert not shapely.has_z(frame.geometry).any()
    for frame in [result.data, result.table, result.matrix, result.zones,
                  result.categories, result.gaps, result.overlaps]:
        assert frame.attrs['area_unit'] == result.summary['area_unit']
        assert frame.attrs['measurement_crs'] == result.summary['measurement_crs']


def test_closed_form_rectangles_complete_zero_cells_and_uncovered_geometry():
    zones, classes = simple()
    result = run(zones, classes)
    assert isinstance(result, AreaTabulationResult)
    assert result.table.area.tolist() == [50, 50, 0, 0, 50, 0]
    assert result.table.percentage.tolist() == [50, 50, 0, 0, 50, 0]
    assert result.table.zone_value.tolist() == ['west'] * 3 + ['east'] * 3
    assert result.matrix.columns.tolist() == ['zone_id', 'zone_type', 'zone_value',
                                             'c000001', 'c000002', 'c000003']
    assert result.matrix.iloc[:, 3:].to_numpy().tolist() == [[50, 50, 0], [0, 50, 0]]
    assert result.zones.covered_area.tolist() == [100, 50]
    assert result.zones.uncovered_area.tolist() == [0, 50]
    assert result.categories.outside_area.tolist() == [0, 0, 100]
    assert result.categories.covered_domain_area.tolist() == [50, 100, 0]
    assert len(result.gaps) == 1
    assert result.gaps.iloc[0].kind == 'no_coverage'
    assert result.gaps.iloc[0].geometry.equals(box(15, 0, 20, 10))
    assert result.overlaps.empty
    assert result.summary['totals']['domain']['zone_area'] == 200
    assert result.summary['totals']['domain']['covered_area'] == 150
    assert result.summary['table_cells'] == 6
    assert result.summary['intersection_features'] == 3
    assert_balances(result)


@pytest.mark.parametrize('unit,divisor', [('m2', 1), ('ha', 10000), ('km2', 1e6)])
def test_area_units_change_measures_but_not_percentages_or_geometry(unit, divisor):
    zones, classes = simple()
    result = run(zones, classes, area_unit=unit)
    assert result.table.area.tolist() == pytest.approx([50 / divisor, 50 / divisor, 0,
                                                       0, 50 / divisor, 0])
    assert result.zones.zone_area.tolist() == pytest.approx([100 / divisor, 100 / divisor])
    assert result.table.percentage.tolist() == [50, 50, 0, 0, 50, 0]
    assert result.data.geometry.iloc[0].equals(box(0, 0, 5, 10))
    assert_balances(result)


def test_repeated_zone_and_class_identities_dissolve_and_audit_duplicate_coverage():
    zones = layer(['district', 'district'], [box(0, 0, 6, 10), box(4, 0, 10, 10)])
    classes = layer(['forest', 'forest'], [box(0, 0, 7, 10), box(3, 0, 10, 10)])
    result = run(zones, classes)
    assert result.table.area.tolist() == [100]
    zone = result.zones.iloc[0]
    category = result.categories.iloc[0]
    assert zone.source_count == 2
    assert zone.source_area == 120
    assert zone.zone_area == 100
    assert zone.same_zone_excess_area == 20
    assert category.source_count == 2
    assert category.source_area == 140
    assert category.dissolved_area == 100
    assert category.same_class_excess_area == 40
    assert result.summary['registries']['zones'][0]['source_rows'] == [0, 1]
    assert result.summary['registries']['classes'][0]['source_rows'] == [0, 1]
    areas = dict(zip(result.overlaps.kind, result.overlaps.area))
    assert areas == {'same_class_overlap': 40, 'same_zone_overlap': 20}
    assert result.zones.overlap_area.tolist() == [0]
    assert result.zones.excess_area.tolist() == [0]
    assert_balances(result)


def test_thirty_identical_source_features_do_not_create_pairwise_duplicate_rows():
    zones = layer(['zone'] * 30, [box(0, 0, 10, 10)] * 30)
    classes = layer(['forest'] * 30, [box(0, 0, 10, 10)] * 30)
    result = run(zones, classes)
    assert result.zones.same_zone_excess_area.tolist() == [2900]
    assert result.categories.same_class_excess_area.tolist() == [2900]
    assert result.overlaps.area.tolist() == [100, 100]
    assert len(result.overlaps) == 2
    assert result.table.area.tolist() == [100]
    assert_balances(result)


def test_cross_category_overlap_is_rejected_by_default_inside_analysis_domain():
    zones = layer(['zone'], [box(0, 0, 10, 10)])
    classes = layer(['forest', 'agriculture'], [box(0, 0, 8, 10), box(2, 0, 10, 10)])
    with pytest.raises(ValueError, match='Distinct classes overlap.*c000001, c000002'):
        run(zones, classes)


def test_triple_overlap_separates_unique_ambiguous_area_additive_excess_and_pair_sums():
    zones = layer(['zone'], [box(0, 0, 10, 10)])
    classes = layer(['A', 'B', 'C'], [box(0, 0, 8, 10), box(2, 0, 10, 10), box(4, 0, 6, 10)])
    result = run(zones, classes, overlap_policy='report')
    assert result.table.area.tolist() == [80, 80, 20]
    zone = result.zones.iloc[0]
    assert zone.zone_area == zone.covered_area == 100
    assert zone.overlap_area == 60
    assert zone.excess_area == zone.raw_excess_area == 80
    assert zone.summed_class_area == zone.summed_class_percentage == 180
    assert sorted(result.overlaps.area) == [20, 20, 60]
    assert result.overlaps.area.sum() == 100
    assert result.summary['totals']['domain']['overlap_area'] == 60
    assert result.summary['totals']['domain']['excess_area'] == 80
    assert result.gaps.empty
    assert_balances(result)


def test_overlap_outside_union_of_zones_does_not_block_and_outside_categories_remain():
    zones = layer(['zone'], [box(0, 0, 10, 10)])
    classes = layer(['A', 'B', 'C'], [box(0, 0, 20, 10), box(11, 0, 20, 10), box(12, 0, 15, 10)])
    result = run(zones, classes)
    assert result.table.area.tolist() == [100, 0, 0]
    assert result.categories.outside_area.tolist() == [100, 90, 30]
    assert result.overlaps.empty
    assert result.summary['policies']['class_overlap_scope'] == 'union_of_zones'
    assert_balances(result)


def test_distinct_overlapping_zones_are_independent_and_global_totals_use_union():
    zones = layer(['A', 'B', 'C'], [box(0, 0, 8, 10), box(2, 0, 10, 10), box(4, 0, 6, 10)])
    classes = layer(['forest'], [box(0, 0, 10, 10)])
    result = run(zones, classes)
    assert result.table.area.tolist() == [80, 80, 20]
    assert result.table.percentage.tolist() == [100, 100, 100]
    domain = result.summary['totals']['domain']
    sums = result.summary['totals']['zone_sums']
    assert domain['zone_area'] == domain['covered_area'] == 100
    assert domain['zone_overlap_area'] == 60
    assert sums['zone_area'] == sums['covered_area'] == 180
    assert sums['zone_excess_area'] == sums['raw_zone_excess_area'] == 80
    assert sorted(result.overlaps.area) == [20, 20, 60]
    with pytest.raises(ValueError, match='Distinct zones overlap'):
        run(zones, classes, zone_overlap_policy='error')
    assert_balances(result)


def test_zone_overlap_error_still_allows_same_zone_dissolution_and_touching_boundaries():
    zones = layer(['A', 'A', 'B'], [box(0, 0, 8, 10), box(2, 0, 10, 10), box(10, 0, 20, 10)])
    classes = layer(['forest'], [box(0, 0, 20, 10)])
    result = run(zones, classes, zone_overlap_policy='error')
    assert result.table.area.tolist() == [100, 100]
    assert result.overlaps.kind.tolist() == ['same_zone_overlap']
    assert result.zones.same_zone_excess_area.tolist() == [60, 0]
    assert_balances(result)


def test_holes_multipolygons_and_polygon_line_collections_preserve_only_real_area():
    donut = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)],
                    [[(3, 3), (7, 3), (7, 7), (3, 7)]])
    zones = layer(['donut', 'parts'], [donut, MultiPolygon([box(20, 0, 22, 2), box(24, 0, 26, 2)])])
    classes = layer(['forest', 'hole', 'parts'], [box(0, 0, 10, 10), box(3, 3, 7, 7),
                            MultiPolygon([box(20, 0, 22, 2), box(23, 0, 24, 2)])])
    result = run(zones, classes)
    assert result.table.area.tolist() == [84, 0, 0, 0, 0, 4]
    assert result.zones.zone_area.tolist() == [84, 8]
    assert result.zones.uncovered_area.tolist() == [0, 4]
    assert result.categories.outside_area.tolist() == [16, 16, 2]
    assert len(result.data) == 2
    assert result.data.geometry.iloc[0].equals(donut)
    assert result.gaps.geometry.iloc[0].equals(box(24, 0, 26, 2))
    assert_balances(result)


@pytest.mark.parametrize('shift', [0.0, 1e6])
def test_no_positive_sliver_is_suppressed_by_closure_tolerance(shift):
    zones = layer(['zone'], [box(shift, 0, shift + 10, 10)])
    epsilon = 1e-8
    classes = layer(['A', 'B'], [box(shift, 0, shift + 5 + epsilon, 10),
                               box(shift + 5, 0, shift + 10, 10)])
    with pytest.raises(ValueError, match='Distinct classes overlap'):
        run(zones, classes)
    result = run(zones, classes, overlap_policy='report')
    assert 0 < result.overlaps.area.iloc[0] < 1e-6
    assert result.zones.overlap_area.iloc[0] > 0
    assert len(result.data) == 2
    assert result.summary['closure_tolerance']['absolute_m2'] == 1e-6
    assert_balances(result)


def test_tiny_positive_category_cell_and_gap_are_retained():
    zones = layer(['zone'], [box(0, 0, 1, 1)])
    classes = layer(['tiny', 'large'], [box(0, 0, 1e-9, 1), box(1e-9, 0, 1 - 1e-9, 1)])
    result = run(zones, classes)
    assert result.table.area.iloc[0] == pytest.approx(1e-9, abs=1e-15)
    assert result.gaps.area.iloc[0] == pytest.approx(1e-9, abs=1e-15)
    assert len(result.data) == 2
    assert len(result.gaps) == 1
    assert_balances(result)


def test_null_class_footprint_is_separate_from_absence_and_known_coverage_takes_precedence():
    zones = layer(['zone'], [box(0, 0, 10, 10)])
    classes = layer(['forest', None], [box(0, 0, 4, 10), box(3, 0, 8, 10)])
    with pytest.raises(ValueError, match='class_field has a missing value'):
        run(zones, classes)
    result = run(zones, classes, null_classes='unclassified')
    assert result.table.area.tolist() == [40]
    zone = result.zones.iloc[0]
    assert zone.covered_area == 40
    assert zone.uncovered_area == 60
    assert zone.unclassified_area == 40
    assert zone.no_coverage_area == 20
    assert result.gaps.kind.tolist() == ['unclassified', 'no_coverage']
    assert result.gaps.area.tolist() == [40, 20]
    assert result.summary['null_class_features'] == 1
    assert result.summary['registries']['unclassified_source_rows'] == [1]
    assert result.summary['unclassified']['already_classified_area'] == 10
    assert result.summary['unclassified']['dissolved_area'] == 50
    assert result.overlaps.empty
    assert_balances(result)


def test_all_null_classes_are_not_invented_categories_and_null_duplicates_are_unioned():
    zones = layer(['zone'], [box(0, 0, 10, 10)])
    classes = layer([None, pd.NA], [box(0, 0, 8, 10), box(2, 0, 10, 10)])
    result = run(zones, classes, null_classes='unclassified')
    assert result.categories.empty and result.table.empty and result.data.empty
    assert result.matrix.columns.tolist() == ['zone_id', 'zone_type', 'zone_value']
    assert result.zones.unclassified_area.tolist() == [100]
    assert result.zones.no_coverage_area.tolist() == [0]
    assert result.gaps.area.tolist() == [100]
    assert result.summary['unclassified']['source_area'] == 160
    assert result.summary['unclassified']['dissolved_area'] == 100
    assert_balances(result)


@pytest.mark.parametrize('empty_zones,empty_classes', [(True, False), (False, True), (True, True)])
def test_empty_layers_have_typed_schemas_zero_balances_and_complete_nonempty_side(empty_zones, empty_classes):
    zones, classes = simple()
    if empty_zones:
        zones = zones.iloc[:0]
    if empty_classes:
        classes = classes.iloc[:0]
    result = run(zones, classes)
    assert result.table.empty
    assert len(result.zones) == len(zones)
    assert len(result.categories) == len(classes)
    assert result.data.crs == zones.crs
    assert result.data.area.dtype == np.dtype('float64')
    assert result.zones.source_count.dtype == pd.Int64Dtype()
    assert isinstance(result.categories.class_id.dtype, pd.StringDtype)
    assert result.summary['totals']['domain']['zone_area'] == (0 if empty_zones else 200)
    if empty_classes and not empty_zones:
        assert result.gaps.area.tolist() == [100, 100]
    if empty_zones and not empty_classes:
        assert result.categories.outside_area.tolist() == [50, 100, 100]
    assert_balances(result)


def test_typed_identities_large_unsigned_values_text_numbers_booleans_and_native_dates():
    values = ['001', 'NA', '', '1', 1, True, 1.0, 2**63 + 1, 2**63 + 2,
              date(2026, 1, 1), pd.Timestamp('2026-01-01'),
              pd.Timestamp('2026-01-01T00:00:00.123456789+01:00')]
    geoms = [box(i, 0, i + 1, 1) for i in range(len(values))]
    zones, classes = layer(values, geoms), layer(values, geoms)
    result = run(zones, classes)
    assert len(result.zones) == len(values) == len(result.categories)
    assert result.zones.zone_value.tolist() == ['001', 'NA', '', '1', '1', 'true', '1.0',
            str(2**63 + 1), str(2**63 + 2), '2026-01-01', '2026-01-01T00:00:00',
            '2025-12-31T23:00:00.123456789+00:00']
    assert result.zones.zone_type.tolist() == ['string'] * 4 + ['integer', 'boolean', 'float',
            'integer', 'integer', 'date', 'datetime', 'datetime_utc']
    assert result.data.area.tolist() == [1] * len(values)
    assert result.table.area.sum() == len(values)
    assert result.summary['registries']['zones'][7]['zone_value'] == str(2**63 + 1)
    assert_balances(result)


def test_decimal_identity_is_exact_even_under_small_decimal_context_precision():
    a = Decimal('123456789012345678901234567890.123456789')
    b = Decimal('123456789012345678901234567890.123456788')
    zones = layer([a, b, Decimal('1.00'), Decimal('1.0')],
                  [box(0, 0, 1, 1), box(1, 0, 2, 1), box(2, 0, 3, 1), box(3, 0, 4, 1)])
    classes = layer(['one'], [box(0, 0, 4, 1)])
    with localcontext() as context:
        context.prec = 5
        result = run(zones, classes)
    assert result.zones.zone_value.tolist() == [str(a), str(b), '1']
    assert result.zones.zone_type.tolist() == ['decimal'] * 3
    assert result.zones.source_count.tolist() == [1, 1, 2]
    assert result.table.area.tolist() == [1, 1, 2]
    assert_balances(result)


def test_categorical_unused_levels_do_not_invent_rows_and_order_is_first_seen():
    zones, classes = simple()
    zones['key'] = pd.Categorical(['west', 'east'], categories=['unused', 'east', 'west'])
    classes['key'] = pd.Categorical(['forest', 'water', 'outside'],
                                    categories=['unused', 'outside', 'water', 'forest'])
    result = run(zones, classes)
    assert result.zones.zone_value.tolist() == ['west', 'east']
    assert result.categories.class_value.tolist() == ['forest', 'water', 'outside']
    assert_balances(result)


def test_inputs_geometry_attributes_crs_duplicate_indexes_and_metadata_are_unchanged():
    zones, classes = simple()
    zones = zones.rename_geometry('shape')
    classes = classes.rename_geometry('footprint')
    zones.index = pd.MultiIndex.from_tuples([('A', 1), ('A', 1)])
    classes.index = [7, 7, 7]
    zones['keep'] = pd.array([2**63 + 1, 2**63 + 2], dtype='UInt64')
    classes['keep'] = ['x', 'y', 'z']
    zones.attrs = {'source_note': {'value': 'unchanged'}}
    classes.attrs = {'source_note': {'value': 'unchanged'}}
    z_before, c_before = zones.copy(deep=True), classes.copy(deep=True)
    result = run(zones, classes)
    assert_geodataframe_equal(zones, z_before)
    assert_geodataframe_equal(classes, c_before)
    assert zones.attrs == z_before.attrs and classes.attrs == c_before.attrs
    assert zones.geometry.to_wkb().tolist() == z_before.geometry.to_wkb().tolist()
    assert classes.geometry.to_wkb().tolist() == c_before.geometry.to_wkb().tolist()
    assert result.summary['registries']['zones'][1]['source_rows'] == [1]
    assert 'keep' not in result.data
    assert_balances(result)


def test_geographic_source_requires_explicit_projected_crs_and_outputs_analysis_crs():
    zones, classes = simple()
    z_geo, c_geo = zones.to_crs(4326), classes.to_crs(4326)
    with pytest.raises(ValueError, match='projected CRS'):
        run(z_geo, c_geo)
    result = run(z_geo, c_geo, metric_crs=3857)
    assert result.zones.crs == CRS.from_epsg(3857)
    assert result.table.area.tolist() == pytest.approx([50, 50, 0, 0, 50, 0])
    assert result.summary['source_crs'] == {'zones': 'EPSG:4326', 'classes': 'EPSG:4326'}
    with pytest.raises(ValueError, match='projected CRS'):
        run(zones, classes, metric_crs=4326)
    assert_balances(result)


def test_class_crs_is_explicitly_aligned_without_mutating_source():
    zones, classes = simple()
    classes = classes.to_crs(4326)
    before = classes.copy()
    result = run(zones, classes)
    assert result.table.area.tolist() == pytest.approx([50, 50, 0, 0, 50, 0])
    assert_geodataframe_equal(classes, before)
    assert_balances(result)


def test_projected_us_survey_feet_are_converted_to_square_metres():
    crs = CRS.from_epsg(2263)
    zones = layer(['zone'], [box(1000000, 200000, 1000010, 200010)], crs=crs)
    classes = layer(['forest'], [box(1000000, 200000, 1000005, 200010)], crs=crs)
    result = run(zones, classes)
    metres_per_foot = 1200 / 3937
    assert result.zones.zone_area.iloc[0] == pytest.approx(100 * metres_per_foot**2, rel=1e-14)
    assert result.table.area.iloc[0] == pytest.approx(50 * metres_per_foot**2, rel=1e-14)
    assert result.table.percentage.tolist() == [50]
    assert result.summary['metres_per_coordinate_unit'] == pytest.approx(metres_per_foot)
    assert_balances(result)


@pytest.mark.parametrize('dims,wkt', [
    ('z', 'POLYGON Z ((0 0 5,10 0 6,10 10 7,0 10 8,0 0 5))'),
    ('m', 'POLYGON M ((0 0 5,10 0 6,10 10 7,0 10 8,0 0 5))'),
    ('zm', 'POLYGON ZM ((0 0 5 50,10 0 6 60,10 10 7 70,0 10 8 80,0 0 5 50))'),
])
def test_finite_z_and_m_are_preserved_in_sources_and_deliberately_dropped_only_in_analysis(dims, wkt):
    if 'm' in dims and not hasattr(shapely, 'has_m'):
        pytest.skip('Native M coordinates require current Shapely.')
    geom = shapely.from_wkt(wkt)
    zones, classes = layer(['zone'], [geom]), layer(['forest'], [geom])
    before = geom.wkb
    result = run(zones, classes)
    assert zones.geometry.iloc[0].wkb == classes.geometry.iloc[0].wkb == before
    assert result.table.area.tolist() == [100]
    assert result.summary['dimensionality']['zones']['z_features'] == int('z' in dims)
    assert result.summary['dimensionality']['zones']['m_features'] == int('m' in dims)
    assert not shapely.has_z(result.data.geometry).any()
    if hasattr(shapely, 'has_m'):
        assert not shapely.has_m(result.data.geometry).any()
    assert_balances(result)


@pytest.mark.parametrize('value', [None, pd.NA, pd.NaT, np.nan])
def test_null_zone_identifiers_are_rejected_even_with_unclassified_classes_enabled(value):
    zones = layer([value], [box(0, 0, 10, 10)])
    classes = layer(['forest'], [box(0, 0, 10, 10)])
    with pytest.raises(ValueError, match='zone_field has a missing value'):
        run(zones, classes, null_classes='unclassified')


@pytest.mark.parametrize('value', [float('inf'), float('-inf'), [1], {'a': 1}, (1, 2), complex(1, 2), 'bad\x00key'])
@pytest.mark.parametrize('which', ['zones', 'classes'])
def test_nonfinite_nonscalar_or_unexportable_identity_values_are_rejected(which, value):
    zones = layer([value if which == 'zones' else 'zone'], [box(0, 0, 10, 10)])
    classes = layer([value if which == 'classes' else 'forest'], [box(0, 0, 10, 10)])
    with pytest.raises(ValueError):
        run(zones, classes)


@pytest.mark.parametrize('geometry,match', [
    (None, 'missing or empty'), (Polygon(), 'missing or empty'),
    (GeometryCollection([box(0, 0, 1, 1)]), 'Polygon/MultiPolygon'),
    (Point(0, 0), 'Polygon/MultiPolygon'),
    (LineString([(0, 0), (1, 1)]), 'Polygon/MultiPolygon'),
    (Polygon([(0, 0), (2, 2), (0, 2), (2, 0), (0, 0)]), 'invalid geometry'),
])
@pytest.mark.parametrize('which', ['zones', 'classes'])
def test_unusable_geometry_is_refused_without_implicit_repair(which, geometry, match):
    zones = layer(['zone'], [geometry if which == 'zones' else box(0, 0, 10, 10)])
    classes = layer(['forest'], [geometry if which == 'classes' else box(0, 0, 10, 10)])
    with pytest.raises(ValueError, match=match):
        run(zones, classes)


@pytest.mark.parametrize('wkt', [
    'POLYGON Z ((0 0 NaN,10 0 0,10 10 0,0 10 0,0 0 NaN))',
    'POLYGON M ((0 0 NaN,10 0 0,10 10 0,0 10 0,0 0 NaN))',
])
def test_nonfinite_auxiliary_ordinates_are_refused_before_2d_projection(wkt):
    geom = shapely.from_wkt(wkt)
    zones = layer(['zone'], [geom])
    classes = layer(['forest'], [box(0, 0, 10, 10)])
    with pytest.raises(ValueError, match='nonfinite coordinates'):
        run(zones, classes)


@pytest.mark.parametrize('parameter,value,match', [
    ('area_unit', 'acre', 'area_unit'), ('area_unit', [], 'area_unit'),
    ('overlap_policy', 'first', 'overlap_policy'), ('overlap_policy', None, 'overlap_policy'),
    ('zone_overlap_policy', 'union', 'zone_overlap_policy'), ('zone_overlap_policy', True, 'zone_overlap_policy'),
    ('null_classes', 'drop', 'null_classes'), ('null_classes', {}, 'null_classes'),
    ('progress', 42, 'progress must be callable'),
])
def test_invalid_options_fail_explicitly(parameter, value, match):
    zones, classes = simple()
    with pytest.raises(ValueError, match=match):
        run(zones, classes, **{parameter: value})


@pytest.mark.parametrize('field', ['', 'missing', 'geometry', None, ['key']])
@pytest.mark.parametrize('which', ['zone_field', 'class_field'])
def test_group_fields_must_name_exactly_one_attribute(which, field):
    zones, classes = simple()
    params = {'zone_field': 'key', 'class_field': 'key', which: field}
    with pytest.raises(ValueError, match=which):
        tabulate_area(zones, classes, **params)


@pytest.mark.parametrize('which', ['zones', 'classes'])
def test_missing_crs_is_never_assigned_implicitly(which):
    zones, classes = simple()
    if which == 'zones':
        zones = zones.set_crs(None, allow_override=True)
    else:
        classes = classes.set_crs(None, allow_override=True)
    with pytest.raises(ValueError, match='no CRS'):
        run(zones, classes, metric_crs=3857)


def test_duplicate_attribute_names_are_refused():
    zones, classes = simple()
    zones.insert(1, 'other', ['a', 'b'])
    zones.columns = ['key', 'key', 'geometry']
    with pytest.raises(ValueError, match='field names must be unique'):
        run(zones, classes)


def test_layer_selectors_are_required_for_multilayer_files_and_in_memory_layers_reject_them(tmp_path):
    zones, classes = simple()
    path = tmp_path / 'layers.gpkg'
    zones.to_file(path, layer='zones', driver='GPKG')
    classes.to_file(path, layer='classes', driver='GPKG')
    before = path.read_bytes()
    with pytest.raises(ValueError, match='multiple layers'):
        run(path, classes)
    result = run(path, path, zones_layer='zones', classes_layer='classes')
    assert result.table.area.tolist() == [50, 50, 0, 0, 50, 0]
    assert result.summary['parameters']['zones_layer'] == 'zones'
    assert result.summary['parameters']['classes_layer'] == 'classes'
    assert path.read_bytes() == before
    with pytest.raises(ValueError, match='in-memory'):
        run(zones, classes, zones_layer='zones')
    with pytest.raises(ValueError, match='Unknown vector layer'):
        run(path, classes, zones_layer='absent')
    assert_balances(result)


def test_generated_polygon_products_can_be_reopened_with_exact_typed_identity_text(tmp_path):
    values = ['001', 'NA', 2**63 + 1, date(2026, 1, 1), True]
    zones = layer(values, [box(i * 2, 0, i * 2 + 2, 2) for i in range(len(values))])
    classes = layer(values, [box(i * 2, 0, i * 2 + 1, 2) for i in range(len(values))])
    result = run(zones, classes)
    for name in ['data', 'zones', 'gaps', 'overlaps']:
        output = getattr(result, name)
        path = tmp_path / (name + '.gpkg')
        write_geopackage(output, path, layer='features')
        restored = read_vector(path, layer='features')
        assert restored.geometry.to_wkb().tolist() == output.geometry.to_wkb().tolist()
        for column in output.columns:
            if column == 'geometry':
                continue
            assert restored[column].tolist() == output[column].tolist()
    assert result.zones.zone_value.tolist() == ['001', 'NA', str(2**63 + 1), '2026-01-01', 'true']


def test_progress_is_monotone_and_cancellation_returns_no_partial_result():
    zones, classes = simple()
    calls = []
    result = run(zones, classes, progress=lambda done, total: calls.append((done, total)))
    assert calls[0] == (0, 10000)
    assert calls[-1] == (10000, 10000)
    assert all(total == 10000 for _, total in calls)
    assert [done for done, _ in calls] == sorted(set(done for done, _ in calls))
    assert_balances(result)
    event = threading.Event()
    event.set()
    with pytest.raises(ProcessingCancelled):
        run(zones, classes, cancel=event)
    event.clear()
    visited = []
    def stop(done, total):
        visited.append(done)
        if done >= 4700:
            event.set()
    with pytest.raises(ProcessingCancelled):
        run(zones, classes, progress=stop, cancel=event)
    assert 10000 not in visited
    assert not event.is_set() or visited[-1] >= 4700


def test_aware_timestamp_categories_group_equivalent_offsets_by_instant():
    values = [pd.Timestamp('2026-01-01T00:00:00+01:00'),
              pd.Timestamp('2025-12-31T23:00:00Z'),
              pd.Timestamp('2025-12-31T23:00:00')]
    zones = layer(values, [box(0, 0, 1, 1), box(1, 0, 2, 1), box(2, 0, 3, 1)])
    classes = layer(['forest'], [box(0, 0, 3, 1)])
    result = run(zones, classes)
    assert result.zones.zone_type.tolist() == ['datetime_utc', 'datetime']
    assert result.zones.zone_value.tolist() == ['2025-12-31T23:00:00+00:00', '2025-12-31T23:00:00']
    assert result.zones.source_count.tolist() == [2, 1]
    assert result.table.area.tolist() == [2, 1]
    assert_balances(result)


def _rectangle_cells(bounds):
    """Independent integer-grid area oracle; no GEOS predicates or measurements."""
    x0, y0, x1, y1 = bounds
    return {(x, y) for x in range(x0, x1) for y in range(y0, y1)}


@pytest.mark.parametrize('seed', range(10))
def test_many_overlapping_rectangles_match_an_independent_integer_cell_oracle(seed):
    rng = np.random.default_rng(seed)
    def bounds(count):
        result = []
        for _ in range(count):
            x, y = map(int, rng.integers(-5, 7, size=2))
            w, h = map(int, rng.integers(1, 7, size=2))
            result.append((x, y, x + w, y + h))
        return result
    zone_rectangles = bounds(9)
    class_rectangles = bounds(24)
    zone_keys = ['west', 'east', 'west', 'centre', 'east', 'centre', 'west', 'east', 'centre']
    class_keys = ['forest', 'farm', 'water', None] * 6
    zone_cells, class_cells, source_zone_areas, source_class_areas = {}, {}, {}, {}
    null_cells = set()
    for key, rectangle in zip(zone_keys, zone_rectangles):
        cells = _rectangle_cells(rectangle)
        zone_cells.setdefault(key, set()).update(cells)
        source_zone_areas[key] = source_zone_areas.get(key, 0) + len(cells)
    for key, rectangle in zip(class_keys, class_rectangles):
        cells = _rectangle_cells(rectangle)
        if key is None:
            null_cells.update(cells)
        else:
            class_cells.setdefault(key, set()).update(cells)
            source_class_areas[key] = source_class_areas.get(key, 0) + len(cells)
    zones = layer(zone_keys, [box(*rectangle) for rectangle in zone_rectangles])
    classes = layer(class_keys, [box(*rectangle) for rectangle in class_rectangles])
    result = run(zones, classes, overlap_policy='report', null_classes='unclassified')
    classified = set().union(*class_cells.values())
    domain = set().union(*zone_cells.values())
    for row in result.table.itertuples():
        expected = len(zone_cells[row.zone_value] & class_cells[row.class_value])
        assert row.area == expected
        assert row.percentage == pytest.approx(100 * expected / len(zone_cells[row.zone_value]))
    for row in result.zones.itertuples():
        cells = zone_cells[row.zone_value]
        counts = [sum(cell in category for category in class_cells.values()) for cell in cells]
        known = cells & classified
        absent = cells - classified
        assert row.zone_area == len(cells)
        assert row.source_area == source_zone_areas[row.zone_value]
        assert row.same_zone_excess_area == source_zone_areas[row.zone_value] - len(cells)
        assert row.covered_area == len(known)
        assert row.uncovered_area == len(absent)
        assert row.unclassified_area == len(absent & null_cells)
        assert row.no_coverage_area == len(absent - null_cells)
        assert row.overlap_area == sum(count >= 2 for count in counts)
        assert row.excess_area == sum(max(count - 1, 0) for count in counts)
        assert row.summed_class_area == sum(counts)
        assert row.closure_error == 0
    for row in result.categories.itertuples():
        cells = class_cells[row.class_value]
        assert row.source_area == source_class_areas[row.class_value]
        assert row.dissolved_area == len(cells)
        assert row.same_class_excess_area == source_class_areas[row.class_value] - len(cells)
        assert row.covered_domain_area == len(cells & domain)
        assert row.outside_area == len(cells - domain)
    totals = result.summary['totals']['domain']
    assert totals['zone_area'] == len(domain)
    assert totals['covered_area'] == len(domain & classified)
    assert totals['uncovered_area'] == len(domain - classified)
    assert totals['unclassified_area'] == len((domain - classified) & null_cells)
    assert totals['no_coverage_area'] == len(domain - classified - null_cells)
    assert totals['overlap_area'] == sum(sum(cell in c for c in class_cells.values()) >= 2 for cell in domain)
    assert totals['zone_overlap_area'] == sum(sum(cell in z for z in zone_cells.values()) >= 2 for cell in domain)
    assert result.summary['totals']['zone_sums']['zone_excess_area'] == sum(map(len, zone_cells.values())) - len(domain)
    assert_balances(result)


def test_projection_that_generates_nonfinite_xy_is_rejected_before_overlay():
    zones = layer(['invalid_latitude'], [box(0, 100, 1, 101)], crs=4326)
    classes = layer(['forest'], [box(0, 0, 10, 10)], crs=3857)
    with pytest.raises(ValueError, match='nonfinite coordinates'):
        run(zones, classes, metric_crs=3857)
