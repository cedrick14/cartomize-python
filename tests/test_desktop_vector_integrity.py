"""Attribute-join policies are explicit and preserved by desktop worker jobs."""
import os
from datetime import date
from pathlib import Path
import sqlite3
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
from cartomize.desktop_tools_base import write_result
from cartomize.vector_io import read_vector, write_geopackage


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


def test_geopackage_result_keeps_date_datetime_and_null_storage(tmp_path):
    frame = gpd.GeoDataFrame({
        'visit_date': [date(2024, 2, 29), None],
        'observed_at': [pd.Timestamp('2024-02-29T13:14:15.123'), None],
        'unknown_date': [None, None],
    }, geometry=[Point(300000, 9500000), Point(300001, 9500001)], crs=32733)
    frame.attrs['_cartomize_declared_fields'] = {'unknown_date': 'date'}
    destination = tmp_path / 'dates.gpkg'
    write_result(frame, destination)
    with sqlite3.connect(destination) as connection:
        layer = connection.execute('SELECT table_name FROM gpkg_contents').fetchone()[0]
        fields = {row[1]: row[2] for row in connection.execute(f'PRAGMA table_info("{layer}")')}
        assert fields['visit_date'] == 'DATE'
        assert fields['observed_at'] == 'DATETIME'
        assert fields['unknown_date'] == 'DATE'
        stored = connection.execute(f'SELECT visit_date, observed_at, unknown_date FROM "{layer}"').fetchall()
        assert stored[0][0] == '2024-02-29'
        assert pd.Timestamp(stored[0][1]) == pd.Timestamp('2024-02-29T13:14:15.123')
        assert stored[0][2] is None and stored[1] == (None, None, None)
    reloaded = read_vector(destination)
    assert type(reloaded.visit_date.iloc[0]) is date
    assert reloaded.visit_date.iloc[0] == date(2024, 2, 29)
    assert reloaded.observed_at.iloc[0] == pd.Timestamp('2024-02-29T13:14:15.123')
    assert pd.isna(reloaded.visit_date.iloc[1])


def test_latest_records_worker_preserves_native_date_fields(page, tmp_path):
    source = tmp_path / 'visits.gpkg'
    frame = gpd.GeoDataFrame({
        'pcode': ['a', 'a', 'b'],
        'visit_date': [date(2023, 1, 1), date(2024, 2, 29), date(2024, 1, 1)],
        'value': [10, 20, 30],
    }, geometry=[Point(300000 + i, 9500000) for i in range(3)], crs=32733)
    write_geopackage(frame, source)
    destination = tmp_path / 'latest.gpkg'
    page.operation.setCurrentIndex(page.operation.findData('latest_records'))
    page.source.edit.setText(str(source))
    page.left_key.setCurrentText('pcode')
    page.order_field.setCurrentText('visit_date')
    page.output.edit.setText(str(destination))
    successes, failures = execute(page.job({'overwrite': False}))
    assert not failures, failures
    assert successes == [str(destination)]
    result = read_vector(destination).set_index('pcode')
    assert type(result.loc['a', 'visit_date']) is date
    assert result.loc['a', 'visit_date'] == date(2024, 2, 29)
    assert result.loc['a', 'value'] == 20
    assert result.loc['b', 'visit_date'] == date(2024, 1, 1)


def test_unrepresentable_datetime_does_not_replace_existing_result(tmp_path):
    destination = tmp_path / 'existing.gpkg'
    frame = gpd.GeoDataFrame({'observed_at': [pd.Timestamp('2024-02-29T13:14:15.123')]},
                             geometry=[Point(300000, 9500000)], crs=32733)
    write_result(frame, destination)
    original = destination.read_bytes()
    frame.loc[0, 'observed_at'] = pd.Timestamp('2024-02-29T13:14:15.123456')
    with pytest.raises(ValueError, match='sub-millisecond'):
        write_result(frame, destination, overwrite=True)
    assert destination.read_bytes() == original
    assert not list(tmp_path.glob('.cartomize-output-*'))
