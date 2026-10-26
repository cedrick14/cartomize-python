"""File-based vector workflows retain the same data semantics as the Python API."""
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Point, box

import cartomize as cm
from cartomize.cli import main


def test_table_to_zonal_summary_chain_preserves_identifiers_and_missingness(tmp_path):
    table = tmp_path/'observations.csv'
    table.write_text('code;x;y;date\n001;2;2;2026-01-01\n001;2;2;2026-02-01\n'
                     '002;12;2;2026-02-01\n003;22;2;2026-02-01\n')
    measures = tmp_path/'measures.tsv'
    measures.write_text('code\tmeasure\n001\t4\n002\t\n003\t0\n')
    zones = gpd.GeoDataFrame({'zone': ['measured', 'missing', 'zero', 'empty']},
        geometry=[box(x, 0, x+10, 10) for x in (0, 10, 20, 30)], crs=32733)
    zones_file = tmp_path/'zones.gpkg'; zones.to_file(zones_file)
    originals = {p: p.read_bytes() for p in (table, measures, zones_file)}
    steps = [
        dict(id='points', operation='vector.from_xy', parameters=dict(data=str(table),
            x='x', y='y', crs='EPSG:32733', table_dtypes={'code': 'string'})),
        dict(id='latest', operation='vector.latest_records', parameters=dict(
            data='@points', group_by='code', order_by='date')),
        dict(id='selected', operation='vector.select_attributes', parameters=dict(
            data='@latest', field='code', comparison='in', value=['001', '002', '003'])),
        dict(id='joined', operation='vector.join_attributes', parameters=dict(
            data='@selected', table=str(measures), left_on='code', table_dtypes={'code': 'string'})),
        dict(id='summary', operation='vector.spatial_summary', parameters=dict(
            zones=str(zones_file), observations='@joined', field='measure', statistic='sum')),
        dict(id='audit', operation='vector.validate', parameters=dict(data='@summary')),
    ]
    record = json.loads(cm.run_plan(cm.processing_plan(steps), tmp_path/'chain').read_text())
    joined = gpd.read_file(record['results']['joined'])
    assert joined.code.tolist() == ['001', '002', '003']
    result = gpd.read_file(record['results']['summary'])
    expected = cm.spatial_summary(zones, cm.join_attributes(
        cm.latest_records(cm.from_xy(pd.read_csv(table, sep=';', dtype={'code': 'string'}),
            x='x', y='y', crs=32733), group_by='code', order_by='date'),
        pd.read_csv(measures, sep='\t', dtype={'code': 'string'}), left_on='code'),
        field='measure', statistic='sum')
    np.testing.assert_allclose(result.sum_measure, [4, np.nan, 0, 0], equal_nan=True)
    np.testing.assert_allclose(result.sum_measure, expected.sum_measure, equal_nan=True)
    assert result.zone.tolist() == zones.zone.tolist()
    assert json.loads(Path(record['results']['audit']).read_text())['invalid_geometries'] == 0
    assert all(p.read_bytes() == data for p, data in originals.items())


def test_large_integer_selection_python_cli_and_registry_agree(tmp_path, capsys):
    source = tmp_path/'identifiers.gpkg'
    numbers = [2**53, 2**53+1, 2**53+2]
    data = gpd.GeoDataFrame({'identifier': numbers}, geometry=[Point(i, 0) for i in range(3)], crs=32733)
    data.to_file(source)
    parameters = dict(data=str(source), field='identifier', comparison='eq', value=str(2**53+1))
    parameter_file = tmp_path/'parameters.json'
    parameter_file.write_text(json.dumps(parameters))
    assert main(['process', 'vector.select_attributes', str(parameter_file), str(tmp_path/'cli')]) == 0
    output = json.loads(capsys.readouterr().out)
    registered = gpd.read_file(output['primary'])
    direct = cm.select_attributes(data, 'identifier', 'eq', str(2**53+1))
    assert registered.identifier.tolist() == direct.identifier.tolist() == [2**53+1]


def test_spatial_selection_geometry_and_audit_are_chainable(tmp_path):
    source = tmp_path/'source.gpkg'; mask = tmp_path/'mask.gpkg'
    gpd.GeoDataFrame({'id': [1, 2]}, geometry=[box(0, 0, 2, 2), box(4, 0, 6, 2)], crs=32733).to_file(source)
    gpd.GeoDataFrame(geometry=[box(-1, -1, 3, 3)], crs=32733).to_file(mask)
    steps = [dict(id='selection', operation='vector.select_location',
                  parameters=dict(data=str(source), mask=str(mask), predicate='within')),
             dict(id='centres', operation='vector.geometry_operation',
                  parameters=dict(data='@selection', operation='centroid'))]
    record = json.loads(cm.run_plan(cm.processing_plan(steps), tmp_path/'chain').read_text())
    result = gpd.read_file(record['results']['centres'])
    assert result.id.tolist() == [1]
    assert result.geometry.iloc[0].equals(Point(1, 1))


def test_join_policy_is_validated_before_any_product_is_published(tmp_path):
    source = tmp_path/'source.gpkg'
    gpd.GeoDataFrame({'code': ['a', None]}, geometry=[Point(0, 0), Point(1, 0)], crs=32733).to_file(source)
    table = tmp_path/'attributes.csv'; table.write_text('code,value\na,1\n,9\n')
    with pytest.raises(ValueError, match='missing'):
        cm.execute_operation('vector.join_attributes', dict(data=str(source), table=str(table),
            left_on='code', null_keys='error'), tmp_path/'failed')
    assert not (tmp_path/'failed').exists()
    result = cm.execute_operation('vector.join_attributes', dict(data=str(source), table=str(table),
        left_on='code'), tmp_path/'safe')
    assert pd.isna(gpd.read_file(result['primary']).value.iloc[1])


def test_chain_dialog_exposes_table_types_and_missing_key_policy():
    pytest.importorskip('PySide6')
    from PySide6.QtWidgets import QApplication
    from cartomize.desktop_processing import OperationDialog
    app = QApplication.instance() or QApplication([])
    dialog = OperationDialog([])
    dialog.operation.setCurrentIndex(dialog.operation.findData('vector.join_attributes'))
    for key, value in dict(data='source.gpkg', table='attributes.csv', left_on='code',
                           table_dtypes='{"code":"string"}', null_keys='error').items():
        dialog.controls[key].setCurrentText(value)
    assert dialog.controls['table'].findText('@scientific') >= 0
    record = dialog.value()
    assert record['parameters']['table_dtypes'] == {'code': 'string'}
    assert record['parameters']['null_keys'] == 'error'
    dialog.close(); dialog.deleteLater(); app.processEvents()
