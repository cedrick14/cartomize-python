"""Classification identities, persisted models and rotated sampling footprints."""
import copy
from decimal import Decimal
import json
import math

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import rasterio
from rasterio.transform import Affine, from_origin
from shapely.affinity import affine_transform
from shapely.geometry import Point, box

import cartomize as cm
from cartomize.classification import _class_table, _sample_features


def _world(geometry, transform):
    return affine_transform(geometry, [transform.a, transform.b, transform.d,
                                       transform.e, transform.c, transform.f])


def _references(write_raster, labels, *, validation_labels=None, name="spectral.tif"):
    """Four rows, disjoint train/validation halves, one spectrum per class."""
    spectra = 10+100*np.arange(len(labels), dtype="float32")
    values = np.tile(np.repeat(spectra, 4), (4, 1))
    source = write_raster(name, values)
    transform = from_origin(300000, 9500000, 10, 10)
    training = gpd.GeoDataFrame(
        {"class": pd.Series(labels, dtype=object)},
        geometry=[_world(box(4*i, 0, 4*i+4, 2), transform) for i in range(len(labels))], crs=32733)
    validation = gpd.GeoDataFrame(
        {"class": pd.Series(labels if validation_labels is None else validation_labels, dtype=object)},
        geometry=[_world(box(4*i, 2, 4*i+4, 4), transform) for i in range(len(labels))], crs=32733)
    return source, training, validation, spectra[:, None]


def _fit(source, training, **kwargs):
    options = dict(algorithm="extra_trees", n_estimators=3, sample_limit=200,
                   random_state=42, workers=1)
    options.update(kwargs)
    return cm.fit_classifier(source, training, "class", **options)


def _encoding(model):
    entries = model.report["class_encoding"]
    assert len({entry["code"] for entry in entries}) == len(entries)
    return {(entry["kind"], entry["value"]): entry["code"] for entry in entries}


@pytest.mark.parametrize("train_dtype, validation_dtype", [("float64", "int64"), ("int64", "float64")])
def test_numeric_identity_matches_independent_float_and_integer_validation(
        write_raster, train_dtype, validation_dtype):
    source, training, validation, spectra = _references(write_raster, [1, 2])
    training["class"] = training["class"].astype(train_dtype)
    validation["class"] = validation["class"].astype(validation_dtype)
    model = _fit(source, training, validation=validation)
    assert model.report["validation_method"] == "independent_features"
    assert model.report["validation"]["accuracy"] == 1
    assert model.report["counts"] == {"1": 8, "2": 8}
    assert _encoding(model) == {("number", "1"): 1, ("number", "2"): 2}
    predictions = model.arrays["codes"][model.probabilities(spectra).argmax(axis=1)]
    assert predictions.tolist() == [1, 2]
    assert str(training["class"].dtype) == train_dtype


def test_numeric_output_codes_preserved_only_for_all_admissible_integers(write_raster):
    source, training, validation, _ = _references(write_raster, [0, 2**24-1])
    model = _fit(source, training, validation=validation)
    assert set(model.arrays["codes"]) == {0, 2**24-1}
    assert _encoding(model) == {("number", "0"): 0, ("number", str(2**24-1)): 2**24-1}
    source, training, validation, _ = _references(write_raster, [-1, .5, 9], name="recoded.tif")
    model = _fit(source, training, validation=validation)
    assert set(model.arrays["codes"]) == {1, 2, 3}
    assert set(_encoding(model)) == {("number", "-1"), ("number", "0.5"), ("number", "9")}
    assert model.report["validation"]["accuracy"] == 1


def test_mixed_identifiers_keep_text_numbers_and_booleans_distinct(write_raster):
    labels = [1, "1", "01", True, False, 0]
    validation_labels = [1., "1", "01", np.bool_(True), np.bool_(False), 0.]
    source, training, validation, spectra = _references(write_raster, labels, validation_labels=validation_labels)
    names = ["Number one", "Text one", "Text zero one", "Boolean true", "Boolean false", "Number zero"]
    training["name"] = names
    model = _fit(source, training, validation=validation, label_column="name")
    encoding = _encoding(model)
    keys = [("number", "1"), ("string", "1"), ("string", "01"),
            ("boolean", True), ("boolean", False), ("number", "0")]
    assert set(encoding) == set(keys)
    assert set(encoding.values()) == set(range(1, 7))
    for key, name in zip(keys, names):
        assert model.classes[encoding[key]][0] == name
    assert model.report["validation"]["accuracy"] == 1
    predicted = model.arrays["codes"][model.probabilities(spectra).argmax(axis=1)]
    assert predicted.tolist() == [encoding[key] for key in keys]
    reordered = _fit(source, training.iloc[[5, 3, 1, 4, 2, 0]], validation=validation, label_column="name")
    assert reordered.report["class_encoding"] == model.report["class_encoding"]
    assert reordered.classes == model.classes


def test_large_integer_identity_survives_training_validation_and_json(write_raster, tmp_path):
    labels = [2**53, 2**53+1, 2**70+1, np.uint64(2**64-1)]
    validation_labels = [float(2**53), 2**53+1, 2**70+1, int(2**64-1)]
    source, training, validation, spectra = _references(write_raster, labels, validation_labels=validation_labels)
    model = _fit(source, training, validation=validation)
    encoding = _encoding(model)
    assert set(encoding) == {("number", str(int(label))) for label in labels}
    assert set(encoding.values()) == {1, 2, 3, 4}
    assert model.report["validation"]["accuracy"] == 1
    path = model.save(tmp_path/"large-model")
    document = json.loads(path.read_text())
    assert document["schema"] == "cartomize.classifier.v1"
    assert all(isinstance(row["value"], str) for row in document["report"]["class_encoding"])
    restored = cm.load_classifier(path)
    assert restored.report["class_encoding"] == model.report["class_encoding"]
    np.testing.assert_array_equal(restored.probabilities(spectra), model.probabilities(spectra))


def test_conflicting_names_for_equivalent_numeric_classes_rejected(write_raster):
    source, training, validation, _ = _references(write_raster, [1, 1., 2])
    training["name"] = ["Forest", "Water", "Crop"]
    with pytest.raises(ValueError, match="libellés"):
        _fit(source, training, validation=validation, label_column="name")
    training["name"] = ["Forest", "Forest", "Crop"]
    model = _fit(source, training, validation=validation, label_column="name")
    assert model.report["counts"] == {"1": 16, "2": 8}
    assert model.classes[1][0] == "Forest"


def test_group_split_uses_the_same_numeric_identity_as_sampling(write_raster):
    source = write_raster("groups.tif", np.tile(np.array([10]*4+[110]*4, dtype="float32"), (8, 1)))
    transform = from_origin(300000, 9500000, 10, 10)
    labels, groups, geometries = [], [], []
    for group in range(4):
        labels.extend([1 if group % 2 else 1., 2. if group % 2 else 2])
        groups.extend([f"group-{group}"]*2)
        for column in (0, 4):
            geometries.append(_world(box(column, 2*group, column+4, 2*group+2), transform))
    training = gpd.GeoDataFrame({"class": pd.Series(labels, dtype=object), "group": groups},
                                geometry=geometries, crs=32733)
    model = _fit(source, training, group_column="group", test_fraction=.25)
    assert model.report["validation_method"] == "held_out_groups"
    assert model.report["training_features"] == 6
    assert model.report["counts"] == {"1": 24, "2": 24}
    assert model.report["validation"]["features"] == 2
    assert model.report["validation"]["pixels"] == 16
    assert model.report["validation"]["accuracy"] == 1
    assert _encoding(model) == {("number", "1"): 1, ("number", "2"): 2}


def test_new_and_legacy_model_reports_preserve_predictions(write_raster, tmp_path):
    source, training, validation, spectra = _references(write_raster, ["01", "1"])
    model = _fit(source, training, validation=validation)
    assert set(_encoding(model)) == {("string", "01"), ("string", "1")}
    probabilities = model.probabilities(spectra)
    new_path = model.save(tmp_path/"new-model")
    restored = cm.load_classifier(new_path)
    assert restored.report["class_encoding"] == model.report["class_encoding"]
    assert restored.classes == model.classes
    np.testing.assert_array_equal(restored.probabilities(spectra), probabilities)
    legacy = copy.deepcopy(model)
    legacy.report.pop("class_encoding")
    legacy_path = legacy.save(tmp_path/"legacy-model")
    old_document = json.loads(legacy_path.read_text())
    assert old_document["schema"] == "cartomize.classifier.v1"
    assert "class_encoding" not in old_document["report"]
    old_model = cm.load_classifier(legacy_path)
    assert "class_encoding" not in old_model.report
    assert old_model.classes == model.classes
    np.testing.assert_array_equal(old_model.arrays["codes"], model.arrays["codes"])
    np.testing.assert_array_equal(old_model.probabilities(spectra), probabilities)


@pytest.mark.parametrize("invalid", [
    np.nan, np.inf, -np.inf, None, pd.NA, 1+2j,
    [1], {"id": 1}, b"one", Decimal("1.5"), pd.Timestamp("2026-01-01"),
])
def test_unsupported_or_nonfinite_class_identifiers_fail_explicitly(write_raster, invalid):
    source, training, validation, _ = _references(write_raster, [invalid, 2])
    with pytest.raises(ValueError, match="classe|identifiant|Identifiant"):
        _fit(source, training, validation=validation)


def test_numeric_validation_does_not_match_a_text_class(write_raster):
    source, training, validation, _ = _references(write_raster, ["01", "1"], validation_labels=["01", 1])
    with pytest.raises(ValueError, match="inconnues"):
        _fit(source, training, validation=validation)


def _rotated_transform():
    component = 10/math.sqrt(2)
    return Affine(component, component, 300000, component, -component, 9500000)


def test_rotated_training_samples_at_both_tips_are_found(write_raster):
    transform = _rotated_transform()
    source = write_raster("rotated.tif", np.arange(16, dtype="float32").reshape(4, 4), transform=transform)
    training = gpd.GeoDataFrame({"class": [1, 2]},
                                geometry=[_world(box(i, i, i+1, i+1), transform) for i in (0, 3)], crs=32733)
    model = _fit(source, training, sample_limit=20)
    assert model.report["counts"] == {"1": 1, "2": 1}
    assert model.report["training_pixels"] == 2
    predicted = model.arrays["codes"][model.probabilities([[0], [15]]).argmax(axis=1)]
    assert predicted.tolist() == [1, 2]


def test_rotated_validation_overlap_is_rejected_before_reservoir_sampling(write_raster):
    transform = _rotated_transform()
    values = np.zeros((12, 12), dtype="float32")
    values[:4, :4] = 10
    values[8:, 8:] = 110
    source = write_raster("rotated-overlap.tif", values, transform=transform)
    training = gpd.GeoDataFrame({"class": [1, 2]},
                                geometry=[_world(box(i, i, i+4, i+4), transform) for i in (0, 8)], crs=32733)
    mapping, _ = _class_table(training, "class")
    with rasterio.open(source) as src:
        _, _, selected_ids = _sample_features(src, training, "class", mapping, [1], 20, 42, None)
    assert len(selected_ids) == 20
    omitted = []
    for offset in (0, 8):
        candidates = {row*12+col for row in range(offset, offset+4) for col in range(offset, offset+4)}
        omitted.append(min(candidates-set(selected_ids)))
    points = [_world(Point(pixel % 12+.5, pixel//12+.5), transform) for pixel in omitted]
    validation = gpd.GeoDataFrame({"class": [1, 2]}, geometry=points, crs=32733)
    with rasterio.open(source) as src:
        _, _, validation_ids = _sample_features(src, validation, "class", mapping, [1], 20, 43, None)
    # The final sampled-ID check cannot catch this leakage. The full excluded
    # footprints must be queried and checked before training reservoir sampling.
    assert not np.intersect1d(selected_ids, validation_ids).size
    with pytest.raises(ValueError, match="partagent des pixels"):
        _fit(source, training, validation=validation, sample_limit=20)
