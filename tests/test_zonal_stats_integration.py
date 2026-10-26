"""Calibrated zonal statistics and their provenance across public interfaces."""
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

import cartomize as cm
from cartomize.cli import main


def test_zonal_api_cli_and_chain_preserve_calibration_and_coverage(write_raster, tmp_path, capsys):
    source = write_raster('quantized.tif', np.array([[0, 1000, -9999], [2000, 3000, 4000]], dtype='int16'),
                          transform=from_origin(300000, 9500000, 10, 10))
    with rasterio.open(source, 'r+') as dst:
        dst.scales = (.001,); dst.offsets = (-.5,); dst.set_band_unit(1, 'reflectance')
    zones = gpd.GeoDataFrame({'name': ['partly_outside']},
        geometry=[box(300000, 9499980, 300040, 9500000)], crs=32733)
    zone_file = tmp_path/'zone.gpkg'; zones.to_file(zone_file)
    direct = cm.raster.zonal_stats(source, zones, include_coverage=True, prefix='obs_')
    parameters = dict(source=str(source), zones=str(zone_file), include_coverage=True,
                      prefix='obs_', value_mode='physical', block_size=1)
    parameter_file = tmp_path/'parameters.json'; parameter_file.write_text(json.dumps(parameters))
    assert main(['process', 'raster.zonal_stats', str(parameter_file), str(tmp_path/'cli')]) == 0
    cli = json.loads(capsys.readouterr().out)
    plan = cm.processing_plan([dict(id='statistics', operation='raster.zonal_stats', parameters=parameters)])
    chain = json.loads(cm.run_plan(plan, tmp_path/'chain').read_text())
    for result in (direct, gpd.read_file(cli['primary']), gpd.read_file(chain['results']['statistics'])):
        assert result.obs_count.tolist() == [5]
        np.testing.assert_allclose(result.obs_mean, 1.5)
        np.testing.assert_allclose(result.obs_sum, 7.5)
        assert result.obs_zone_pixels.tolist() == [8]
        assert result.obs_raster_pixels.tolist() == [6]
        np.testing.assert_allclose(result.obs_coverage_percent, 62.5)
    report_file = Path(cli['primary']).parent/'operation.json'
    record = json.loads(report_file.read_text())
    assert record['metadata']['value_mode'] == direct.attrs['cartomize']['value_mode'] == 'physical'
    assert record['metadata'] == cli['metadata']
    assert '.cartomize-' not in report_file.read_text()


def test_nested_operation_provenance_contains_only_published_paths(write_raster, tmp_path):
    source = write_raster('source.tif', np.ones((2, 2), dtype='float32'))
    with rasterio.open(source) as src:
        zones = gpd.GeoDataFrame(geometry=[box(*src.bounds)], crs=src.crs)
    zone_file = tmp_path/'zone.gpkg'; zones.to_file(zone_file)
    steps = [dict(id='computed', operation='calculate', parameters={
                 'inputs': {'a': [str(source), 1]}, 'expression': 'a * 2'}),
             dict(id='summary', operation='raster.zonal_stats', parameters={
                 'source': '@computed', 'zones': str(zone_file)})]
    record = json.loads(cm.run_plan(cm.processing_plan(steps), tmp_path/'run').read_text())
    report_file = Path(record['results']['summary']).parent/'operation.json'
    report = json.loads(report_file.read_text())
    assert '.cartomize-' not in report_file.read_text()
    assert Path(report['metadata']['source']).is_file()
    assert gpd.read_file(record['results']['summary'])['mean'].iloc[0] == 2
