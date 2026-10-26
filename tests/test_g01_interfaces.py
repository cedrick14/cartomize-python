"""G01 layer and precision choices survive CLI, plan links and form serialization."""
import json
import os
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import geopandas as gpd
import pytest
from shapely.geometry import Point

import cartomize as cm
from cartomize.cli import main
from cartomize.viewer_data import table_page


def source_file(tmp_path):
    path = tmp_path / 'layers.gpkg'
    gpd.GeoDataFrame({'reference': ['background']}, geometry=[Point(20, 20)], crs=32733).to_file(
        path, layer='reference', index=False)
    gpd.GeoDataFrame({'1': ['0001', '0002']}, geometry=[Point(.1, .2), Point(1.8, 2.2)],
                     crs=32733).to_file(path, layer='1', index=False)
    return path


def test_cli_requires_a_layer_and_publishes_the_selected_precision_contract(tmp_path, capsys):
    source = source_file(tmp_path)
    original = source.read_bytes()
    config = tmp_path / 'parameters.json'
    parameters = {'data': str(source), 'id_field': '1', 'tolerance': 1.}
    config.write_text(json.dumps(parameters), encoding='utf-8')
    assert main(['process', 'vector.repair_geometries', str(config), str(tmp_path / 'ambiguous')]) == 2
    captured = capsys.readouterr()
    assert 'layer' in captured.err + captured.out
    assert not (tmp_path / 'ambiguous').exists()
    parameters['layer'] = '1'
    config.write_text(json.dumps(parameters), encoding='utf-8')
    assert main(['process', 'vector.repair_geometries', str(config), str(tmp_path / 'repair')]) == 0
    record = json.loads(capsys.readouterr().out)
    summary = json.loads(Path(record['products']['summary']).read_text(encoding='utf-8'))
    assert summary['source_layer'] == '1' and summary['tolerance'] == 1.
    assert summary['repair_changed_features'] == 0 and summary['precision_changed_features'] == 2
    assert cm.read_file(record['products']['data']).geometry.tolist() == [Point(0, 0), Point(2, 2)]
    assert cm.read_file(record['products']['before']).geometry.tolist() == [Point(.1, .2), Point(1.8, 2.2)]
    assert table_page(record['products']['report'])['frame'].feature_id.tolist() == ['0001', '0002']
    assert source.read_bytes() == original


def test_plan_can_reopen_original_and_corrected_g01_products_independently(tmp_path):
    source = source_file(tmp_path)
    steps = [
        dict(id='repair', operation='vector.repair_geometries', parameters={
            'data': str(source), 'layer': '1', 'id_field': '1', 'tolerance': 1.}),
        dict(id='original', operation='vector.audit_geometries', parameters={
            'data': '@repair:before', 'id_field': '1'}),
        dict(id='corrected', operation='vector.audit_geometries', parameters={
            'data': '@repair:data', 'id_field': '1'}),
    ]
    path = cm.run_plan(cm.processing_plan(steps), tmp_path / 'chain')
    record = json.loads(Path(path).read_text(encoding='utf-8'))
    original = cm.read_file(record['products']['original']['data'])
    corrected = cm.read_file(record['products']['corrected']['data'])
    assert original['1'].tolist() == corrected['1'].tolist() == ['0001', '0002']
    assert original.geometry.tolist() == [Point(.1, .2), Point(1.8, 2.2)]
    assert corrected.geometry.tolist() == [Point(0, 0), Point(2, 2)]


def test_plan_form_keeps_numeric_looking_layer_and_field_names_as_strings():
    pytest.importorskip('PySide6')
    from PySide6.QtWidgets import QApplication
    from cartomize.desktop_processing import OperationDialog
    app = QApplication.instance() or QApplication([])
    dialog = OperationDialog([])
    restored = None
    try:
        dialog.operation.setCurrentIndex(dialog.operation.findData('vector.repair_geometries'))
        for name, value in {'data': 'layers.gpkg', 'layer': '1', 'id_field': '1', 'tolerance': '.25'}.items():
            dialog.controls[name].setCurrentText(value)
        record = dialog.value()
        assert record['parameters']['layer'] == record['parameters']['id_field'] == '1'
        assert record['parameters']['tolerance'] == .25
        assert 'unités du SCR source projeté' in dialog.form.labelForField(dialog.controls['tolerance']).text()
        assert 'before' in [dialog.product.itemText(i) for i in range(dialog.product.count())]
        restored = OperationDialog([], record)
        assert restored.value() == record
    finally:
        for widget in (dialog, restored):
            if widget is not None:
                widget.close()
                widget.deleteLater()
        app.processEvents()
