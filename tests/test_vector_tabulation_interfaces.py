"""G09 verified publication, exact labels, CLI, chained products and rollback."""
from datetime import date
import hashlib
import json
import os
from pathlib import Path
from threading import Event

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

import cartomize as cm
from cartomize.cli import main
from cartomize.vector_io import write_geopackage
from cartomize.viewer_data import table_page


def sources(tmp_path):
    zones = gpd.GeoDataFrame({'007': ['001', 'NA']},
        geometry=[box(0, 0, 10, 10), box(10, 0, 20, 10)], crs=32733)
    classes = gpd.GeoDataFrame({'008': ['Forêt, dense\nA', 'Eau', 'Forêt, dense\nA', 'Extérieur']},
        geometry=[box(0, 0, 5, 10), box(5, 0, 15, 10), box(0, 0, 5, 10), box(50, 0, 60, 10)], crs=32733)
    zp, cp = tmp_path / 'zones.gpkg', tmp_path / 'classes.gpkg'
    write_geopackage(zones, zp, layer='123')
    write_geopackage(classes, cp, layer='456')
    return dict(zones=str(zp), classes=str(cp), zone_field='007', class_field='008',
                zones_layer='123', classes_layer='456', area_unit='m2')


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def test_public_api_and_catalog_expose_every_named_product():
    spec = next(row for row in cm.operation_catalog() if row['id'] == 'vector.tabulate_area')
    assert spec['output'] == 'vector' and spec['tool'] == 'vector'
    assert {field['name'] for field in spec['parameters'] if field['required']} == {
        'zones', 'classes', 'zone_field', 'class_field'}
    assert set(spec['products']) == {'primary', 'data', 'table', 'matrix', 'zones',
                                     'categories', 'gaps', 'overlaps', 'audit', 'summary'}
    assert callable(cm.tabulate_area) and cm.AreaTabulationResult


def test_every_published_product_is_exact_reopenable_and_audited(tmp_path):
    parameters = sources(tmp_path)
    originals = {key: Path(parameters[key]).read_bytes() for key in ('zones', 'classes')}
    expected = cm.tabulate_area(**parameters)
    progress = []
    destination = tmp_path / 'published'
    record = cm.execute_operation('vector.tabulate_area', parameters, destination,
                                  progress=lambda done, total: progress.append((done, total)))
    assert record['primary'] == record['products']['data']
    assert len(list(destination.iterdir())) == 13
    assert progress[-1] == (10000, 10000)
    assert all(a[0] <= b[0] for a, b in zip(progress, progress[1:]))
    for name in ('data', 'zones', 'gaps', 'overlaps'):
        wanted = getattr(expected, name)
        saved = cm.read_file(record['products'][name], layer='features')
        pd.testing.assert_frame_equal(pd.DataFrame(saved.drop(columns='geometry')),
            pd.DataFrame(wanted.drop(columns='geometry')), check_dtype=False, check_exact=True)
        assert saved.crs == wanted.crs
        assert saved.geometry.to_wkb().tolist() == wanted.geometry.to_wkb().tolist()
    for name in ('table', 'matrix', 'categories'):
        saved = table_page(record['products'][name], size=100)['frame']
        pd.testing.assert_frame_equal(saved, getattr(expected, name), check_dtype=False, check_exact=True)
    table = table_page(record['products']['table'])['frame']
    assert table['zone_value'].tolist() == ['001'] * 3 + ['NA'] * 3
    assert table['class_value'].tolist() == ['Forêt, dense\nA', 'Eau', 'Extérieur'] * 2
    assert table['area'].tolist() == [50., 50., 0., 0., 50., 0.]
    audit = read_json(record['products']['audit'])
    assert audit['schema'] == 'cartomize.vector_tabulation.audit.v1'
    assert audit['tables']['overlaps']['records'][0]['zone_id'] is None
    for name, proof in audit['verified_files'].items():
        assert hashlib.sha256((destination / name).read_bytes()).hexdigest() == proof['sha256']
    assert record['metadata']['totals']['domain']['uncovered_area'] == 50.
    for path in destination.glob('*.json'):
        assert '.cartomize-' not in path.read_text(encoding='utf-8')
    assert {key: Path(parameters[key]).read_bytes() for key in originals} == originals


def test_mixed_typed_labels_survive_all_publication_formats(tmp_path):
    values = ['001', 'NA', '', '1', 1, True, 2**64 - 1, date(2026, 10, 30)]
    zones = gpd.GeoDataFrame({'zone': ['001']}, geometry=[box(0, 0, 8, 1)], crs=32733)
    classes = gpd.GeoDataFrame({'code': pd.Series(values, dtype=object)},
        geometry=[box(i, 0, i + 1, 1) for i in range(len(values))], crs=32733)
    record = cm.execute_operation('vector.tabulate_area', dict(zones=zones, classes=classes,
        zone_field='zone', class_field='code', area_unit='m2'), tmp_path / 'mixed')
    registry = table_page(record['products']['categories'])['frame']
    assert registry['class_type'].tolist() == ['string'] * 4 + ['integer', 'boolean', 'integer', 'date']
    assert registry['class_value'].tolist() == ['001', 'NA', '', '1', '1', 'true', str(2**64 - 1), '2026-10-30']
    data = cm.read_file(record['products']['data'])
    assert data['class_value'].tolist() == registry['class_value'].tolist()
    assert len(set(data['class_id'])) == 8
    assert table_page(record['products']['matrix'])['frame'].iloc[0, 3:].tolist() == [1.] * 8


@pytest.mark.parametrize('case', ['outside', 'empty_classes', 'empty_zones'])
def test_empty_intersections_and_diagnostics_remain_typed_products(tmp_path, case):
    zones = gpd.GeoDataFrame({'zone': pd.Series(['A'], dtype='string')}, geometry=[box(0, 0, 10, 10)], crs=32733)
    classes = gpd.GeoDataFrame({'class': pd.Series(['B'], dtype='string')}, geometry=[box(20, 0, 30, 10)], crs=32733)
    if case == 'empty_classes':
        classes = classes.iloc[:0].copy()
    if case == 'empty_zones':
        zones = zones.iloc[:0].copy()
    record = cm.execute_operation('vector.tabulate_area', dict(zones=zones, classes=classes,
        zone_field='zone', class_field='class', area_unit='m2'), tmp_path / case)
    for name in ('data', 'overlaps'):
        saved = cm.read_file(record['products'][name])
        assert saved.empty and saved.crs == zones.crs
    assert len(cm.read_file(record['products']['gaps'])) == (0 if case == 'empty_zones' else 1)
    assert read_json(record['products']['summary'])['totals']['domain']['covered_area'] == 0
    for name in ('table', 'matrix', 'categories'):
        assert list(table_page(record['products'][name])['frame'].columns)


@pytest.mark.parametrize('dedicated', [False, True])
def test_cli_both_paths_use_explicit_layers_and_preserve_source_bytes(tmp_path, capsys, dedicated):
    parameters = sources(tmp_path)
    original = {key: Path(parameters[key]).read_bytes() for key in ('zones', 'classes')}
    config = tmp_path / 'parameters.json'
    config.write_text(json.dumps(parameters), encoding='utf-8')
    destination = tmp_path / 'cli'
    args = (['tabulate-area', parameters['zones'], parameters['classes'], str(destination),
             '--zone-field', '007', '--class-field', '008', '--zones-layer', '123',
             '--classes-layer', '456', '--area-unit', 'm2'] if dedicated else
            ['process', 'vector.tabulate_area', str(config), str(destination)])
    assert main(args) == 0
    record = json.loads(capsys.readouterr().out)
    assert table_page(record['products']['table'])['frame']['area'].tolist() == [50., 50., 0., 0., 50., 0.]
    assert {key: Path(parameters[key]).read_bytes() for key in original} == original


def test_plan_chains_zone_and_gap_products(tmp_path):
    parameters = sources(tmp_path)
    plan = cm.processing_plan([
        dict(id='cross', operation='vector.tabulate_area', parameters=parameters),
        dict(id='zone', operation='vector.select_attributes', parameters=dict(
            data='@cross:zones', field='zone_value', comparison='eq', value='NA')),
        dict(id='measure', operation='vector.area', parameters=dict(source='@cross:gaps', unit='m2')),
    ])
    manifest = Path(cm.run_plan(plan, tmp_path / 'plan'))
    result = read_json(manifest)
    assert cm.read_file(result['products']['zone']['primary'])['zone_value'].tolist() == ['NA']
    assert cm.read_file(result['products']['measure']['primary'])['area_m2'].sum() == 50.
    for product in result['products']['cross'].values():
        assert Path(product).is_file()
    assert '.cartomize-' not in manifest.read_text(encoding='utf-8')


def test_vector_verification_failure_rolls_back_entire_publication(tmp_path, monkeypatch):
    parameters = sources(tmp_path)
    import cartomize.vector_io as io
    writer = io.write_geopackage
    def fail(data, path, **kwargs):
        if Path(path).name == 'zones.gpkg':
            raise ValueError('Independent zone readback mismatch')
        return writer(data, path, **kwargs)
    monkeypatch.setattr(io, 'write_geopackage', fail)
    with pytest.raises(ValueError, match='zone readback'):
        cm.execute_operation('vector.tabulate_area', parameters, tmp_path / 'failed')
    assert not (tmp_path / 'failed').exists() and not list(tmp_path.glob('.cartomize-*'))


def test_csv_verification_detects_changed_numeric_value_and_rolls_back(tmp_path, monkeypatch):
    parameters = sources(tmp_path)
    reader = pd.read_csv
    def changed(path, *args, **kwargs):
        result = reader(path, *args, **kwargs)
        if Path(path).name == 'matrix.csv':
            result.loc[0, 'c000001'] += 1
        return result
    monkeypatch.setattr(pd, 'read_csv', changed)
    with pytest.raises(ValueError, match='readback.*matrix'):
        cm.execute_operation('vector.tabulate_area', parameters, tmp_path / 'failed')
    assert not (tmp_path / 'failed').exists() and not list(tmp_path.glob('.cartomize-*'))


def test_cancellation_during_publication_rolls_back_and_preserves_sources(tmp_path):
    parameters = sources(tmp_path)
    originals = {key: Path(parameters[key]).read_bytes() for key in ('zones', 'classes')}
    event = Event()
    def cancel_after_first_product(done, total):
        if done > 8000:
            event.set()
    with pytest.raises(cm.ProcessingCancelled):
        cm.execute_operation('vector.tabulate_area', parameters, tmp_path / 'cancelled',
                             cancel=event, progress=cancel_after_first_product)
    assert not (tmp_path / 'cancelled').exists() and not list(tmp_path.glob('.cartomize-*'))
    assert {key: Path(parameters[key]).read_bytes() for key in originals} == originals


def test_multilayer_ambiguity_and_existing_or_source_destination_are_refused(tmp_path):
    parameters = sources(tmp_path)
    gpd.GeoDataFrame({'007': ['other']}, geometry=[box(30, 0, 40, 10)], crs=32733).to_file(
        parameters['zones'], layer='second')
    ambiguous = {**parameters, 'zones_layer': None}
    with pytest.raises(ValueError, match='layer|couche'):
        cm.execute_operation('vector.tabulate_area', ambiguous, tmp_path / 'ambiguous')
    assert not (tmp_path / 'ambiguous').exists()
    existing = tmp_path / 'existing'
    existing.mkdir()
    (existing / 'keep.txt').write_text('preserve me', encoding='utf-8')
    with pytest.raises(FileExistsError):
        cm.execute_operation('vector.tabulate_area', parameters, existing)
    with pytest.raises(ValueError, match='source'):
        cm.execute_operation('vector.tabulate_area', parameters, tmp_path)
    assert (existing / 'keep.txt').read_text(encoding='utf-8') == 'preserve me'


def test_plan_editor_roundtrip_preserves_numeric_named_fields_and_class_path():
    pytest.importorskip('PySide6')
    from PySide6.QtWidgets import QApplication
    from cartomize.desktop_processing import OperationDialog
    app = QApplication.instance() or QApplication([])
    record = dict(id='cross', operation='vector.tabulate_area', parameters=dict(
        zones='123', classes='456', zones_layer='007', classes_layer='008',
        zone_field='0', class_field='1', metric_crs='EPSG:32733', area_unit='km2',
        overlap_policy='report', zone_overlap_policy='error', null_classes='unclassified'))
    dialog = OperationDialog([], record)
    try:
        assert dialog.value()['parameters'] == record['parameters']
        assert 'classes' in dialog._paths
        assert 'gaps' in [dialog.product.itemText(i) for i in range(dialog.product.count())]
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()
