"""Projected network endpoints and zero routes survive saved workflows."""
import json

import geopandas as gpd
import numpy as np
from shapely.geometry import LineString, Point

import cartomize as cm
from cartomize.cli import main


def test_edge_route_python_cli_and_chain_agree(tmp_path, capsys):
    network = gpd.GeoDataFrame({'name': ['long road']},
        geometry=[LineString([(0, 0), (1000, 0)])], crs=32733)
    source = tmp_path/'roads.gpkg'; network.to_file(source)
    original = source.read_bytes()
    parameters = dict(source=str(source), start=[400, 25], end=[600, -10], max_snap_m=30)
    direct = cm.shortest_path(network, parameters['start'], parameters['end'], max_snap_m=30)
    parameter_file = tmp_path/'parameters.json'; parameter_file.write_text(json.dumps(parameters))
    assert main(['process', 'routing', str(parameter_file), str(tmp_path/'cli')]) == 0
    cli = json.loads(capsys.readouterr().out)
    steps = [dict(id='route', operation='routing', parameters=parameters),
             dict(id='measure', operation='vector.length', parameters=dict(source='@route', unit='m'))]
    record = json.loads(cm.run_plan(cm.processing_plan(steps), tmp_path/'chain').read_text())
    for result in (direct, gpd.read_file(cli['primary']), gpd.read_file(record['results']['measure'])):
        np.testing.assert_allclose(result.distance_m, 200)
        np.testing.assert_allclose(result.start_snap_m, 25)
        np.testing.assert_allclose(result.end_snap_m, 10)
        assert result.snap_method.tolist() == ['edge']
        assert result.route_status.tolist() == ['ok']
        assert result.geometry.iloc[0].equals(LineString([(400, 0), (600, 0)]))
        assert result.crs == network.crs
    assert gpd.read_file(record['results']['measure']).length_m.iloc[0] == 200
    assert source.read_bytes() == original


def test_coincident_route_remains_valid_after_geopackage_export(tmp_path):
    source = tmp_path/'roads.gpkg'
    gpd.GeoDataFrame(geometry=[LineString([(0, 0), (100, 0)])], crs=32733).to_file(source)
    record = cm.execute_operation('routing', dict(source=str(source), start=[20, 5],
        end=[20, -5], max_snap_m=5), tmp_path/'result')
    result = gpd.read_file(record['primary'])
    assert result.geometry.is_valid.all()
    assert result.geometry.iloc[0].equals(Point(20, 0))
    assert result.distance_m.iloc[0] == 0
    assert result.route_status.iloc[0] == 'coincident'
