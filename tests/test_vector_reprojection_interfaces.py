"""The batch contract is shared by the CLI, operation registry and plans."""
import json
from pathlib import Path
from threading import Event

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import Point

import cartomize as cm
from cartomize.cli import main


def source_file(tmp_path):
    path = tmp_path / 'input.gpkg'
    data = gpd.GeoDataFrame({'id': [2**53 + 1, 2**53 + 3], 'fid': [6, 6], 'code': ['001', '002']},
                           geometry=[Point(15, -4), Point(16, -5)], crs=4326)
    data.to_file(path, layer='sites', index=False, layer_options={'FID': '_source_record'})
    return path


def test_cli_inspection_selection_and_execution_preserve_source(tmp_path, capsys):
    source = source_file(tmp_path)
    before = source.read_bytes()
    assert main(['reprojection-options', str(source), '--crs', 'EPSG:3857']) == 0
    inspected = json.loads(capsys.readouterr().out)
    layer = inspected['layers'][0]
    selection = tmp_path / 'choice.json'
    selection.write_text(json.dumps({layer['id']: layer['catalogue']['operations'][0]['id']}))
    assert main(['reproject-batch', str(tmp_path / 'projected'), str(source), '--crs', '3857',
                 '--operations', str(selection)]) == 0
    record = json.loads(capsys.readouterr().out)
    assert set(record['products']) == {'primary', 'manifest', 'report', layer['id']}
    assert all(Path(path).is_file() for path in record['products'].values())
    output = gpd.read_file(record['products'][layer['id']])
    assert output.id.tolist() == [2**53 + 1, 2**53 + 3]
    assert output.fid.tolist() == [6, 6]
    document = json.loads(Path(record['primary']).read_text())
    assert document['layers'][0]['selection'] == 'explicit'
    assert document['layers'][0]['output'] == record['products'][layer['id']]
    assert source.read_bytes() == before


def test_generic_process_cli_uses_same_operation_and_manifest(tmp_path, capsys):
    source = source_file(tmp_path)
    parameters = tmp_path / 'parameters.json'
    parameters.write_text(json.dumps({'sources': [str(source)], 'target_crs': 3857}))
    assert main(['process', 'vector.reproject_batch', str(parameters), str(tmp_path / 'processed')]) == 0
    record = json.loads(capsys.readouterr().out)
    manifest = json.loads(Path(record['primary']).read_text())
    assert manifest['schema'] == 'cartomize.vector_reprojection.v1'
    assert manifest['status'] == 'complete'
    assert record['metadata']['feature_count'] == 2


def test_batch_outputs_feed_following_plan_steps_and_paths_survive_relocation(tmp_path):
    source = source_file(tmp_path)
    layer_id = cm.discover_vector_layers(source)[0]['id']
    steps = [
        dict(id='projected', operation='vector.reproject_batch', parameters={
            'sources': [str(source)], 'target_crs': 'EPSG:32733'}),
        dict(id='buffered', operation='vector.buffer', parameters={
            'data': '@projected:' + layer_id, 'distance': 100}),
    ]
    manifest = cm.run_plan(cm.processing_plan(steps), tmp_path / 'plan')
    document = json.loads(Path(manifest).read_text())
    projected = document['products']['projected']
    batch = json.loads(Path(projected['manifest']).read_text())
    assert batch['layers'][0]['output'] == projected[layer_id]
    assert Path(batch['report']).is_file()
    data = gpd.read_file(document['results']['buffered'])
    assert len(data) == 2 and data.geometry.is_valid.all()
    np.testing.assert_allclose(data.geometry.area, np.pi * 100**2, rtol=.01)
    assert not list(tmp_path.rglob('.cartomize-*'))
    assert '.cartomize-' not in Path(manifest).read_text()
    assert '.cartomize-' not in Path(projected['manifest']).read_text()


def test_operation_cancellation_removes_inner_and_outer_products(tmp_path):
    source = source_file(tmp_path)
    event = Event()
    def cancel_after_one(completed, total):
        if completed:
            event.set()
    with pytest.raises(cm.ProcessingCancelled):
        cm.execute_operation('vector.reproject_batch', {'sources': str(source), 'target_crs': 3857},
                             tmp_path / 'cancelled', progress=cancel_after_one, cancel=event)
    assert not (tmp_path / 'cancelled').exists()
    assert not list(tmp_path.rglob('.cartomize-*'))


def test_inspection_can_be_cancelled_between_layers(tmp_path):
    source = source_file(tmp_path)
    event = Event()
    def stop(completed, total):
        if completed:
            event.set()
    with pytest.raises(cm.ProcessingCancelled):
        cm.inspect_reprojection(source, 3857, progress=stop, cancel=event)


def test_invalid_selection_in_cli_fails_without_publishing(tmp_path, capsys):
    source = source_file(tmp_path)
    selections = tmp_path / 'invalid-choice.json'
    selections.write_text(json.dumps({'nonexistent_layer': 'nonexistent_operation'}))
    status = main(['reproject-batch', str(tmp_path / 'failed'), str(source), '--crs', '3857',
                   '--operations', str(selections)])
    assert status != 0
    assert not (tmp_path / 'failed').exists()
