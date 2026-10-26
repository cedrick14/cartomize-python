"""Attribute-join policies are explicit and preserved by desktop worker jobs."""
import os
from pathlib import Path
import threading

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point

pytest.importorskip('PySide6')
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from cartomize.desktop import Worker
from cartomize.desktop_vector import VectorPage


@pytest.fixture(scope='module')
def application():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def page(application):
    widget = VectorPage()
    widget.operation.setCurrentIndex(widget.operation.findData('join_attributes'))
    widget.join.setCurrentIndex(widget.join.findData('left'))
    try:
        yield widget
    finally:
        widget.close()
        widget.deleteLater()
        application.processEvents()


def configure(page, tmp_path, keys, table):
    source = tmp_path / 'source.gpkg'
    gpd.GeoDataFrame({'code': keys}, geometry=[Point(300000 + i, 9500000) for i in range(len(keys))],
                     crs=32733).to_file(source, index=False)
    joined = tmp_path / 'attributes.csv'
    joined.write_text(table, encoding='utf-8')
    destination = tmp_path / 'joined.gpkg'
    page.source.edit.setText(str(source))
    page.secondary.edit.setText(str(joined))
    page.left_key.setCurrentText('code')
    page.right_key.setCurrentText('identifier')
    page.output.edit.setText(str(destination))
    return destination


def execute(job):
    cancelled = threading.Event()
    worker = Worker(job, cancelled)
    successes, failures = [], []
    worker.succeeded.connect(successes.append)
    worker.failed.connect(failures.append)
    loop = QEventLoop()
    worker.finished.connect(loop.quit)
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    timer.start(10000)
    worker.start()
    loop.exec()
    timer.stop()
    if worker.isRunning():
        cancelled.set()
        worker.wait(10000)
        pytest.fail('Attribute-join worker did not finish')
    worker.wait()
    worker.deleteLater()
    return successes, failures


def test_safe_defaults_preserve_leading_zero_keys_and_leave_missing_unmatched(page, tmp_path):
    destination = configure(page, tmp_path, ['001', None, '002'],
                            'identifier,value\n001,10\n,999\n002,20\n')
    assert page.join_cardinality.currentData() == 'many_to_one'
    assert page.join_null_keys.currentData() == 'unmatched'
    successes, failures = execute(page.job({'overwrite': False}))
    assert not failures, failures
    assert successes == [str(destination)]
    result = gpd.read_file(destination)
    assert result['code'].iloc[[0, 2]].tolist() == ['001', '002']
    assert result['value'].iloc[[0, 2]].tolist() == [10, 20]
    assert pd.isna(result['value'].iloc[1])
    assert result.crs.to_epsg() == 32733


def test_worker_uses_captured_null_policy_and_cardinality(page, tmp_path):
    destination = configure(page, tmp_path, ['001', None],
                            'identifier,value\n001,10\n001,11\n,900\n,901\n')
    page.join_cardinality.setCurrentIndex(page.join_cardinality.findData('one_to_many'))
    page.join_null_keys.setCurrentIndex(page.join_null_keys.findData('match'))
    job = page.job({'overwrite': False})
    # Only the immutable parameter snapshot belongs to this pending job.
    page.join_cardinality.setCurrentIndex(page.join_cardinality.findData('many_to_one'))
    page.join_null_keys.setCurrentIndex(page.join_null_keys.findData('error'))
    successes, failures = execute(job)
    assert not failures, failures
    assert successes == [str(destination)]
    result = gpd.read_file(destination)
    assert result['value'].tolist() == [10, 11, 900, 901]
    assert result['code'].iloc[:2].tolist() == ['001', '001']
    assert result['code'].iloc[2:].isna().all()


def test_error_policy_rejects_missing_keys_without_output(page, tmp_path):
    destination = configure(page, tmp_path, ['001', None],
                            'identifier,value\n001,10\n,999\n')
    page.join_null_keys.setCurrentIndex(page.join_null_keys.findData('error'))
    successes, failures = execute(page.job({'overwrite': False}))
    assert not successes
    assert failures and 'missing' in failures[0].lower()
    assert not destination.exists()


def test_default_cardinality_does_not_expand_duplicate_matches(page, tmp_path):
    destination = configure(page, tmp_path, ['001'], 'identifier,value\n001,10\n001,11\n')
    successes, failures = execute(page.job({'overwrite': False}))
    assert not successes
    assert failures and 'unique' in failures[0].lower()
    assert not destination.exists()


def test_numeric_key_keeps_numeric_join_compatibility(page, tmp_path):
    destination = configure(page, tmp_path, [1, 2], 'identifier,value\n1,10\n2,20\n')
    successes, failures = execute(page.job({'overwrite': False}))
    assert not failures, failures
    assert successes == [str(destination)]
    result = gpd.read_file(destination)
    assert result['code'].tolist() == [1, 2]
    assert result['value'].tolist() == [10, 20]


def test_join_controls_and_explanation_are_specific_to_attribute_join(page):
    controls = [page.join_cardinality, page.join_null_keys, page.join_policy_note]
    assert all(not widget.isHidden() for widget in controls)
    assert 'manquante' in page.join_policy_note.text()
    assert 'zéros initiaux' in page.join_policy_note.text()
    for operation in ['clip', 'sjoin', 'latest_records', 'from_xy', 'dissolve']:
        page.operation.setCurrentIndex(page.operation.findData(operation))
        assert all(widget.isHidden() for widget in controls)
        for widget in controls[:2]:
            assert page.form.labelForField(widget).isHidden()
    page.operation.setCurrentIndex(page.operation.findData('join_attributes'))
    assert all(not widget.isHidden() for widget in controls)
