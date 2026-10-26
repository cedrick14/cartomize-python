"""The classifier uses the same class identity through API, plans and CLI."""
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

import cartomize as cm
from cartomize.cli import main


def test_classification_numeric_identity_survives_files_cli_and_model_reload(write_raster, tmp_path, capsys):
    data = np.ones((2, 24, 24), dtype='float32')
    data[:, :, 12:] = 9
    source = write_raster('image.tif', data, transform=from_origin(300000, 9500000, 10, 10))
    training = gpd.GeoDataFrame({'classe': [1., 2.], 'libelle': ['Végétation', 'Sol']},
        geometry=[box(300000, 9499920, 300080, 9500000), box(300160, 9499920, 300240, 9500000)], crs=32733)
    validation = gpd.GeoDataFrame({'classe': [1, 2]},
        geometry=[box(300000, 9499760, 300080, 9499840), box(300160, 9499760, 300240, 9499840)], crs=32733)
    training_file = tmp_path/'training.gpkg'; training.to_file(training_file)
    validation_file = tmp_path/'validation.gpkg'; validation.to_file(validation_file)
    parameters = dict(source=str(source), training=str(training_file), validation=str(validation_file),
                      class_column='classe', label_column='libelle', n_estimators=10, max_depth=4, sample_limit=128)
    direct = cm.classify_landcover(source, training, tmp_path/'direct', validation=validation,
        class_column='classe', label_column='libelle', n_estimators=10, max_depth=4, sample_limit=128)
    parameter_file = tmp_path/'parameters.json'; parameter_file.write_text(json.dumps(parameters), encoding='utf-8')
    assert main(['process', 'classify', str(parameter_file), str(tmp_path/'cli')]) == 0
    cli = json.loads(capsys.readouterr().out)
    plan = cm.processing_plan([dict(id='classes', operation='classify', parameters=parameters)])
    chain = json.loads(cm.run_plan(plan, tmp_path/'chain').read_text(encoding='utf-8'))
    with rasterio.open(direct) as src:
        expected = src.read(1)
    assert set(np.unique(expected)) == {1, 2}
    for path in (cli['primary'], chain['results']['classes']):
        with rasterio.open(path) as src:
            np.testing.assert_array_equal(src.read(1), expected)
        metadata = json.loads((Path(path).parent/'classification.json').read_text(encoding='utf-8'))
        assert metadata['validation']['accuracy'] == 1
        assert {x['value']: x['code'] for x in metadata['class_encoding']} == {'1': 1, '2': 2}
        assert metadata['classes']['1'][0] == 'Végétation'
    restored = cm.load_classifier(Path(cli['primary']).parent/'model')
    prediction = cm.classify_landcover(source, None, tmp_path/'restored', model=restored)
    with rasterio.open(prediction) as src:
        np.testing.assert_array_equal(src.read(1), expected)
