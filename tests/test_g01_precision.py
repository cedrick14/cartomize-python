"""G01 precision has explicit units, geometric effects and row correspondence."""
from contextlib import closing
import hashlib
import sqlite3
import struct
import warnings

import geopandas as gpd
from geopandas.testing import assert_geodataframe_equal
import pandas as pd
import pytest
import shapely
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box

from cartomize.vector_quality import audit_geometries, repair_geometries


HAS_M = hasattr(shapely, 'has_m') and tuple(shapely.geos_version) >= (3, 12, 0)


def frame(geometries, *, crs=32733, **attributes):
    return gpd.GeoDataFrame(attributes, geometry=geometries, crs=crs)


def wkb_values(geometries):
    return [None if geometry is None else geometry.wkb for geometry in geometries]


def bowtie(offset=0.):
    return Polygon([(offset, offset), (2 + offset, 2 + offset),
                    (offset, 2 + offset), (2 + offset, offset), (offset, offset)])


def test_default_and_explicit_zero_preserve_valid_wkb_and_complete_before_layer():
    source = frame([box(.12, .24, 2.26, 3.37),
                    LineString([(.12, .24, 7.5), (2.26, 3.37, 9.5)]), None, Point()],
                   identifier=['001', '002', '003', '004'], source_row=[91, 92, 93, 94])
    source = source.rename_geometry('outline')
    source.index = [8, 8, 2, 2]
    original = source.copy(deep=True)
    for result in (repair_geometries(source, id_field='identifier'),
                   repair_geometries(source, id_field='identifier', tolerance=0.)):
        assert wkb_values(result.data.geometry) == wkb_values(source.geometry)
        assert_geodataframe_equal(result.before, source)
        assert result.before is not source
        assert result.data.identifier.tolist() == source.identifier.tolist()
        assert result.data.source_row.tolist() == [91, 92, 93, 94]
        assert result.data.index.tolist() == [8, 8, 2, 2]
        assert not result.report.repair_changed.any()
        assert not result.report.precision_changed.any()
        assert result.summary['tolerance'] == 0.
        assert result.summary['precision_mode'] is None
    assert_geodataframe_equal(source, original)


def test_valid_rectangle_grid_has_analytical_area_and_separate_precision_audit():
    original = box(.1, .1, 2.2, 3.2)
    result = repair_geometries(frame([original], identifier=['001']),
                               id_field='identifier', tolerance=1.)
    repaired = result.data.geometry.iloc[0]
    assert repaired.equals(box(0, 0, 2, 3))
    assert set(repaired.exterior.coords) == {(0., 0.), (2., 0.), (2., 3.), (0., 3.)}
    row = result.report.iloc[0]
    assert row.before_area_m2 == pytest.approx(6.51)
    assert row.after_area_m2 == pytest.approx(6.)
    assert row.area_delta_m2 == pytest.approx(-.51)
    assert row.after_length_m == pytest.approx(10.)
    assert not row.repair_changed
    assert row.precision_changed and row.geometry_changed
    assert row.before_coordinate_count == row.after_coordinate_count == 5
    assert row.before_part_count == row.after_part_count == 1
    assert row.before_coordinate_dimension == row.after_coordinate_dimension == 2
    assert row.before_topological_dimension == row.after_topological_dimension == 2
    assert row.before_wkb_sha256 == hashlib.sha256(original.wkb).hexdigest()
    assert row.after_wkb_sha256 == hashlib.sha256(repaired.wkb).hexdigest()
    assert result.before.geometry.iloc[0].wkb == original.wkb
    assert result.summary['tolerance'] == 1.
    assert result.summary['tolerance_unit'] == 'metre'
    assert result.summary['tolerance_metres_per_unit'] == 1.
    assert result.summary['precision_mode'] == 'valid_output'
    assert result.summary['repair_changed_features'] == 0
    assert result.summary['precision_changed_features'] == 1


def test_invalid_bowtie_is_repaired_before_grid_with_known_triangles():
    original = bowtie(.1)
    result = repair_geometries(frame([original]), tolerance=1.)
    expected = MultiPolygon([
        Polygon([(0, 0), (2, 0), (1, 1), (0, 0)]),
        Polygon([(0, 2), (1, 1), (2, 2), (0, 2)]),
    ])
    actual = result.data.geometry.iloc[0]
    assert actual.is_valid and actual.equals(expected)
    assert sorted(part.area for part in actual.geoms) == [1., 1.]
    row = result.report.iloc[0]
    assert row.repair_changed and row.precision_changed
    assert row.before_area_m2 == pytest.approx(0.)
    assert row.after_area_m2 == pytest.approx(2.)
    assert row.before_coordinate_count == 5 and row.after_coordinate_count == 8
    assert row.before_part_count == 1 and row.after_part_count == 2
    assert row.before_geometry_type == 'Polygon' and row.after_geometry_type == 'MultiPolygon'
    assert result.before.geometry.iloc[0].wkb == original.wkb


@pytest.mark.parametrize('policy', ['keep', 'drop', 'error'])
def test_precision_collapse_uses_empty_policy_and_preserves_rejected_original(policy):
    original = box(.1, .1, .2, .2)
    source = frame([original], identifier=['thin'])
    if policy == 'error':
        with pytest.raises(ValueError):
            repair_geometries(source, tolerance=1., empty=policy)
        assert source.geometry.iloc[0].wkb == original.wkb
        return
    result = repair_geometries(source, id_field='identifier', tolerance=1., empty=policy)
    row = result.report.iloc[0]
    assert row.after_empty and row.collapsed
    assert row.precision_changed and not row.repair_changed
    assert row.before_area_m2 == pytest.approx(.01) and row.after_area_m2 == 0.
    assert result.before.geometry.iloc[0].wkb == original.wkb
    if policy == 'keep':
        assert result.data.geometry.iloc[0].is_empty and result.rejected.empty
        assert row.output_row == 0 and pd.isna(row.rejected_row)
    else:
        assert result.data.empty
        assert result.rejected.geometry.iloc[0].wkb == original.wkb
        assert pd.isna(row.output_row) and row.rejected_row == 0


@pytest.mark.parametrize('policy', ['allow', 'drop', 'error'])
def test_precision_split_uses_type_change_policy_after_grid(policy):
    # Two unit squares joined by a 2 x 0.1 corridor. Its two y values
    # both snap to zero; valid-output precision leaves the two squares.
    original = Polygon([(0, 0), (1, 0), (1, .1), (3, .1), (3, 0), (4, 0),
                        (4, 1), (3, 1), (3, .2), (1, .2), (1, 1), (0, 1), (0, 0)])
    assert original.is_valid
    source = frame([original], identifier=['bridge'])
    if policy == 'error':
        with pytest.raises(ValueError):
            repair_geometries(source, tolerance=1., type_changes=policy)
        return
    result = repair_geometries(source, tolerance=1., type_changes=policy)
    row = result.report.iloc[0]
    assert row.type_changed and row.precision_changed and not row.repair_changed
    assert row.before_geometry_type == 'Polygon' and row.after_geometry_type == 'MultiPolygon'
    assert row.before_area_m2 == pytest.approx(2.2) and row.after_area_m2 == pytest.approx(2.)
    if policy == 'allow':
        assert result.data.geometry.iloc[0].equals(MultiPolygon([box(0, 0, 1, 1), box(3, 0, 4, 1)]))
    else:
        assert result.data.empty
        assert result.rejected.geometry.iloc[0].wkb == original.wkb


@pytest.mark.parametrize('value', [True, False, -1., float('nan'), float('inf'), -float('inf')])
def test_grid_rejects_boolean_negative_and_nonfinite_tolerance(value):
    with pytest.raises(ValueError):
        repair_geometries(frame([Point(0, 0)]), tolerance=value)


@pytest.mark.parametrize('metric_crs', [None, 32733])
def test_positive_grid_requires_projected_source_even_with_metric_crs(metric_crs):
    with pytest.raises(ValueError):
        repair_geometries(frame([Point(15, -4)], crs=4326), tolerance=.1, metric_crs=metric_crs)


def test_grid_uses_source_survey_feet_and_is_independent_of_measurement_crs():
    source = frame([box(900000.1, 120000.1, 900002.2, 120003.2)], crs=2263)
    result = repair_geometries(source, tolerance=1.)
    measured_elsewhere = repair_geometries(source, tolerance=1., metric_crs=3857)
    assert result.data.geometry.iloc[0].equals(box(900000, 120000, 900002, 120003))
    assert result.data.geometry.iloc[0].wkb == measured_elsewhere.data.geometry.iloc[0].wkb
    factor = 1200 / 3937
    assert result.report.iloc[0].after_area_m2 == pytest.approx(6 * factor**2)
    assert result.report.iloc[0].after_length_m == pytest.approx(10 * factor)
    for item in (result, measured_elsewhere):
        assert item.summary['tolerance_unit'] == 'US survey foot'
        assert item.summary['tolerance_metres_per_unit'] == pytest.approx(factor)


def test_two_observations_that_snap_to_same_geometry_are_both_retained():
    identifiers = [2**60 + 3, 2**60 + 5]
    source = frame([Point(.1, .1), Point(.2, .2)], identifier=identifiers)
    source.index = [7, 7]
    result = repair_geometries(source, id_field='identifier', tolerance=1.)
    assert len(result.data) == 2
    assert result.data.identifier.tolist() == result.report.feature_id.tolist() == identifiers
    assert result.data.geometry.iloc[0].wkb == result.data.geometry.iloc[1].wkb
    assert result.report.output_row.tolist() == [0, 1] and result.report.rejected_row.isna().all()
    assert_geodataframe_equal(result.before, source)


def test_row_correspondence_covers_kept_and_rejected_rows_without_using_index_labels():
    source = frame([None, bowtie(), Point(.1, .1), Polygon(), Point(.2, .2)],
                   identifier=['A', 'B', 'C', 'D', 'E'], source_row=[20, 21, 22, 23, 24])
    source.index = [9, 9, 8, 8, 9]
    result = repair_geometries(source, id_field='identifier', missing='drop', empty='drop',
                               type_changes='drop', tolerance=1.)
    assert result.data.identifier.tolist() == ['C', 'E']
    assert result.rejected.identifier.tolist() == ['A', 'B', 'D']
    assert result.report.source_row.tolist() == [0, 1, 2, 3, 4]
    assert result.report.feature_id.tolist() == ['A', 'B', 'C', 'D', 'E']
    assert str(result.report.output_row.dtype) == str(result.report.rejected_row.dtype) == 'Int64'
    assert result.report.output_row.dropna().tolist() == [0, 1]
    assert result.report.output_row.isna().tolist() == [True, True, False, True, False]
    assert result.report.rejected_row.dropna().tolist() == [0, 1, 2]
    assert result.report.rejected_row.isna().tolist() == [False, False, True, False, True]
    assert result.data.source_row.tolist() == [22, 24]
    assert wkb_values(result.rejected.geometry) == wkb_values(source.geometry.iloc[[0, 1, 3]])
    assert_geodataframe_equal(result.before, source)


def test_xy_grid_preserves_z_and_reports_coordinate_dimensions():
    result = repair_geometries(frame([Point(.1, .2, 7.3)]), tolerance=1.)
    assert list(result.data.geometry.iloc[0].coords) == [(0., 0., 7.3)]
    row = result.report.iloc[0]
    assert row.before_has_z and row.after_has_z and not row.before_has_m and not row.after_has_m
    assert row.before_coordinate_dimension == row.after_coordinate_dimension == 3
    assert row.before_topological_dimension == row.after_topological_dimension == 0
    assert row.before_coordinate_count == row.after_coordinate_count == 1


@pytest.mark.skipif(not HAS_M, reason='M needs Shapely >= 2.1 and GEOS >= 3.12')
def test_measured_input_is_rejected_before_any_required_mutation(monkeypatch):
    source = frame([bowtie(), shapely.from_wkt('POINT M (4.1 4.2 100)')])
    original = wkb_values(source.geometry)
    def forbidden(*args, **kwargs):
        pytest.fail('No GEOS repair or precision mutation may precede the M preflight refusal.')
    monkeypatch.setattr(shapely, 'make_valid', forbidden)
    monkeypatch.setattr(shapely, 'set_precision', forbidden)
    with pytest.raises(ValueError):
        repair_geometries(source, tolerance=1.)
    assert wkb_values(source.geometry) == original


@pytest.mark.skipif(not HAS_M, reason='M needs Shapely >= 2.1 and GEOS >= 3.12')
def test_invalid_measured_polygon_cannot_lose_m_in_linework_repair():
    geometry = shapely.from_wkt('POLYGON M ((0 0 0, 2 2 2, 0 2 4, 2 0 6, 0 0 0))')
    with pytest.raises(ValueError):
        repair_geometries(frame([geometry]))


@pytest.mark.skipif(not HAS_M, reason='M needs Shapely >= 2.1 and GEOS >= 3.12')
def test_audit_and_zero_tolerance_keep_valid_measured_geometry_in_memory():
    geometry = shapely.from_wkt('POINT M (1 2 123.5)')
    source = frame([geometry], identifier=['M'])
    audit = audit_geometries(source, id_field='identifier')
    repaired = repair_geometries(source, id_field='identifier', tolerance=0.)
    for result in (audit, repaired):
        assert result.data.geometry.iloc[0].wkb == result.before.geometry.iloc[0].wkb == geometry.wkb
    row = audit.report.iloc[0]
    assert row.has_m and not row.has_z
    assert row.coordinate_dimension == 3 and row.topological_dimension == 0
    assert row.coordinate_count == row.part_count == 1
    assert row.wkb_sha256 == hashlib.sha256(geometry.wkb).hexdigest()
    assert row.output_row == row.source_row == 0


@pytest.mark.skipif(not HAS_M, reason='M needs Shapely >= 2.1 and GEOS >= 3.12')
def test_measured_file_is_preserved_now_and_refused_before_old_engine_conversion(tmp_path, monkeypatch):
    import pyogrio
    path = tmp_path / 'measured.gpkg'
    frame([Point(1, 2)], identifier=['M']).to_file(path, layer='features', index=False,
        layer_options={'GEOMETRY_NAME': 'geom', 'SPATIAL_INDEX': 'NO'})
    measured = shapely.from_wkt('POINT M (1 2 123.5)')
    # A real GPKG M blob: version 0, little endian, no envelope, EPSG:32733,
    # followed by ISO WKB. SQLite avoids the driver's M-writing limitation.
    blob = b'GP' + bytes([0, 1]) + struct.pack('<i', 32733) + shapely.to_wkb(measured, flavor='iso')
    with closing(sqlite3.connect(path)) as connection:
        connection.execute('UPDATE features SET geom=?', (blob,))
        connection.execute('UPDATE gpkg_geometry_columns SET m=1')
        connection.commit()
        stored = connection.execute('SELECT geom FROM features').fetchone()[0]
        assert shapely.from_wkb(stored[8:]).wkb == measured.wkb
        assert connection.execute('SELECT m FROM gpkg_geometry_columns').fetchone() == (1,)
    original = path.read_bytes()
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore', message=r'.*[Mm]easured.*geometry types.*', category=UserWarning)
        result = audit_geometries(path, id_field='identifier')
    assert result.data.geometry.iloc[0].wkb == result.before.geometry.iloc[0].wkb == measured.wkb
    assert result.report.iloc[0].has_m
    def forbidden_read(*args, **kwargs):
        pytest.fail('An old GEOS runtime must refuse measured metadata before converting the geometry.')
    monkeypatch.setattr(shapely, 'geos_version', (3, 11, 0))
    monkeypatch.setattr(pyogrio, 'read_dataframe', forbidden_read)
    with pytest.raises(ValueError):
        audit_geometries(path, id_field='identifier')
    assert path.read_bytes() == original


@pytest.mark.parametrize('function', [audit_geometries, repair_geometries])
def test_explicit_layer_selects_multilayer_source_and_ambiguous_input_is_refused(tmp_path, function):
    path = tmp_path / 'layers.gpkg'
    frame([Point(1, 1)], identifier=['first']).to_file(path, layer='first', index=False)
    frame([Point(2, 2), Point(3, 3)], identifier=['001', '002']).to_file(path, layer='selected', index=False)
    original = path.read_bytes()
    with pytest.raises(ValueError):
        function(path, id_field='identifier')
    result = function(path, layer='selected', id_field='identifier')
    assert result.data.identifier.tolist() == ['001', '002']
    assert result.data.geometry.x.tolist() == [2., 3.]
    assert result.summary['source_layer'] == 'selected'
    assert_geodataframe_equal(result.before, result.data)
    assert path.read_bytes() == original
    with pytest.raises(ValueError):
        function(path, layer='absent', id_field='identifier')


@pytest.mark.parametrize('function', [audit_geometries, repair_geometries])
def test_layer_selector_is_rejected_for_in_memory_data(function):
    with pytest.raises(ValueError):
        function(frame([Point(0, 0)]), layer='features')
