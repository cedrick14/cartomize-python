"""The no-code automatic path uses real inputs and enforces its coverage policy."""
import json
import os
from pathlib import Path
import threading

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

pytest.importorskip('PySide6')
from PySide6.QtCore import QEventLoop, QTimer, QSettings, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (QApplication, QAbstractButton, QAbstractSpinBox, QLabel,
                              QPushButton, QStyleFactory, QWidget)

import cartomize as cm
from cartomize.desktop import CartomizeWindow
from test_imagery_automatic import catalog_service


@pytest.fixture(scope='module')
def application():
    return QApplication.instance() or QApplication([])


def wait(window):
    if window.thread is not None:
        loop = QEventLoop()
        timer = QTimer()
        timer.timeout.connect(lambda: loop.quit() if window.thread is None else None)
        timer.start(10)
        QTimer.singleShot(20000, loop.quit)
        loop.exec()
        timer.stop()
    assert window.thread is None, window.status.text()


def configure(window, write_raster, tmp_path, *, width=4):
    files, masks = [], {}
    for scene, x, red in [('A', 300000, .2), ('B', 300020, .4)]:
        transform = from_origin(x, 9500000, 10, 10)
        for name, value in [('red', red), ('nir', red + .4)]:
            files.append(str(write_raster(f'{scene}_{name}.tif', np.full((2, 2), value, dtype='float32'),
                                          transform=transform)))
        masks[scene] = write_raster(f'{scene}_valid.tif', np.ones((2, 2), dtype='uint8'),
                                   transform=transform, nodata=255)
    zone = tmp_path / 'zone.geojson'
    cm.GeoDataFrame(geometry=[box(300000, 9499980, 300000 + width * 10, 9500000)], crs=32733).to_file(zone)
    window.select_tool('prepare')
    page = window.tool('prepare')
    page.mode.setCurrentIndex(page.mode.findData('manual'))
    page.files = files
    page.load_inputs()
    assert page.clouds.isChecked(), 'Loading custom bands must not disable the quality policy'
    for row in range(4):
        page.assets.item(row, 1).setText('A' if row < 2 else 'B')
        page.assets.item(row, 2).setText('red' if row % 2 == 0 else 'nir')
        page.assets.item(row, 7).setText('2026-08-17')
    for row in range(page.quality_masks.rowCount()):
        scene = page.quality_masks.item(row, 0).text()
        page.quality_masks.item(row, 1).setText(str(masks[scene]))
        choice = page.quality_masks.cellWidget(row, 2)
        choice.setCurrentIndex(choice.findData('valid_mask'))
    page.aoi.edit.setText(str(zone))
    page.output.edit.setText(str(tmp_path))
    page.name.setText('automatic')
    return page, zone


def close(window, application):
    if window.thread is not None:
        window.cancel()
        wait(window)
    window.close()
    application.processEvents()


def test_automatic_worker_selects_mosaic_and_registers_all_products(application, write_raster, tmp_path):
    window = CartomizeWindow()
    try:
        page, _ = configure(window, write_raster, tmp_path)
        assert page.preparation_mode.currentData() == 'automatic'
        assert not page.mosaic.isEnabled()
        assert not page.clip.isEnabled()
        # Automatic decisions ignore the dormant expert controls.
        page.mosaic.setChecked(False)
        page.clip.setChecked(False)
        window.start()
        wait(window)
        assert window.status.text().startswith('Traitement terminé'), window.status.text()
        record = json.loads(Path(window.output_path).read_text(encoding='utf-8'))
        assert record['schema'] == 'cartomize.imagery.automatic.v1'
        assert record['status'] == 'complete'
        assert record['threshold_met']
        assert set(record['selected_scene_ids']) == {'A', 'B'}
        assert len(record['products']) == 1
        product = record['products'][0]
        with rasterio.open(product['multiband']) as src:
            assert (src.width, src.height, src.count) == (4, 2, 2)
            np.testing.assert_allclose(src.read(1), [[.2, .2, .4, .4]] * 2)
            assert src.read_masks(1).min() == 255
        for key in ('audit', 'coverage', 'gaps', 'preparation'):
            assert record[key] in window.workspace.records
        for key in ('coverage', 'gaps'):
            layer = next(layer for layer in window.results if layer['data'] == record[key])
            assert layer['purpose'] == 'diagnostic'
        assert window.tool('indices').source.text() == product['multiband']
        assert window.tool('classification').source.text() == product['multiband']
        assert 'zone entièrement couverte' in page.coverage_summary.text()
        assert 'Mosaïque automatique de 2 scènes' in page.coverage_summary.text()
        assert 'EPSG:32733 ; résolution 10 m' in page.coverage_summary.text()
        assert 'Découpage à la zone d’étude réalisé' in page.coverage_summary.text()
    finally:
        close(window, application)


def test_automatic_result_exposes_clickable_transformation_timeline(application, write_raster, tmp_path):
    window = CartomizeWindow()
    try:
        page, _ = configure(window, write_raster, tmp_path)
        window.start()
        wait(window)
        record = json.loads(Path(window.output_path).read_text(encoding='utf-8'))
        assert [step['key'] for step in record['transformations']] == [
            'scene_selection', 'quality_masking', 'mosaic', 'composition', 'aoi_clip'
        ]
        assert page.transformation_steps.isVisible()
        assert page.transformation_steps.rowCount() == 5
        # The automatic two-scene test requires a mosaic.
        assert 'Mosaïque des scènes retenues' in page.transformation_steps.item(2, 1).text()
        product_item = page.transformation_steps.item(0, 2)
        path = product_item.data(Qt.ItemDataRole.UserRole)
        assert path and Path(path).is_file()
        page.open_transformation_result(product_item)
        assert str(Path(path).resolve()) in window.workspace.records
    finally:
        close(window, application)


def test_automatic_retains_one_sufficient_scene_and_clips_to_aoi(application, write_raster, tmp_path):
    window = CartomizeWindow()
    try:
        page, zone = configure(window, write_raster, tmp_path, width=2)
        # Both scenes are selected; the user only chooses a smaller study area.
        cm.GeoDataFrame(geometry=[box(300000, 9499980, 300010, 9500000)], crs=32733).to_file(zone)
        assert len(page.selected_scenes()) == 2
        window.start()
        wait(window)
        assert window.status.text().startswith('Traitement terminé'), window.status.text()
        record = json.loads(Path(window.output_path).read_text(encoding='utf-8'))
        assert record['status'] == 'complete'
        assert record['selected_scene_ids'] == ['A']
        assert not record['mosaic']
        with rasterio.open(record['products'][0]['multiband']) as src:
            assert (src.width, src.height, src.count) == (1, 2, 2)
            assert tuple(src.bounds) == (300000, 9499980, 300010, 9500000)
            np.testing.assert_allclose(src.read(1), .2)
            assert src.read_masks().min() == 255
        assert 'Une seule scène retenue ; aucune mosaïque nécessaire' in page.coverage_summary.text()
        assert 'Découpage à la zone d’étude réalisé' in page.coverage_summary.text()
    finally:
        close(window, application)


def test_insufficient_coverage_keeps_diagnostics_without_scientific_output(application, write_raster, tmp_path):
    window = CartomizeWindow()
    try:
        page, _ = configure(window, write_raster, tmp_path, width=6)
        window.start()
        wait(window)
        assert window.status.text().startswith('Échec du traitement'), window.status.text()
        assert not (tmp_path / 'automatic').exists()
        assert window.folder_button.isEnabled()
        report = json.loads(Path(window.output_path).read_text(encoding='utf-8'))
        assert report['schema'] == 'cartomize.imagery.audit.v1'
        assert report['usable_percent'] == pytest.approx(100 * 4 / 6)
        assert '66,67' in page.coverage_summary.text()
        assert {layer['purpose'] for layer in window.results} == {'diagnostic'}
        assert not window.tool('indices').source.text()
        assert not window.tool('classification').source.text()
        assert report['gaps'] in window.workspace.records
    finally:
        close(window, application)


@pytest.mark.parametrize('threshold,allow_partial,threshold_met', [(60., False, True), (100., True, False)])
def test_partial_result_is_identified_even_when_threshold_is_met(application, write_raster, tmp_path,
                                                               threshold, allow_partial, threshold_met):
    window = CartomizeWindow()
    try:
        page, _ = configure(window, write_raster, tmp_path, width=6)
        page.coverage_threshold.setValue(threshold)
        page.allow_partial.setChecked(allow_partial)
        window.start()
        wait(window)
        assert window.status.text().startswith('Traitement terminé avec couverture partielle'), window.status.text()
        record = json.loads(Path(window.output_path).read_text(encoding='utf-8'))
        assert record['status'] == 'partial'
        assert record['threshold_met'] is threshold_met
        assert record['allow_partial'] is allow_partial
        assert 'couverture partielle' in page.coverage_summary.text()
        assert ('Seuil demandé atteint' in page.coverage_summary.text()) is threshold_met
        with rasterio.open(record['products'][0]['multiband']) as src:
            assert np.count_nonzero(src.read_masks(1)) == 8
            assert src.width * src.height == 12
        scientific = next(layer for layer in window.results if layer['data'] == record['products'][0]['multiband'])
        assert 'couverture partielle' in scientific['name']
    finally:
        close(window, application)


def test_custom_masks_and_automatic_policy_survive_portable_session(application, write_raster, tmp_path):
    original, restored = CartomizeWindow(), CartomizeWindow()
    try:
        page, _ = configure(original, write_raster, tmp_path)
        page.coverage_threshold.setValue(98.5)
        page.allow_partial.setChecked(True)
        page.catalog_enabled.setChecked(True)
        page.catalog_endpoint.setText('https://example.org/stac')
        page.catalog_collections.setText('sentinel-2-l2a')
        page.catalog_dates.setText('2026-08-01/2026-08-31')
        page.catalog_max_items.setValue(3)
        page.catalog_max_mb.setValue(500)
        session = original.save_session_file(tmp_path / 'automatic.cmz', portable=True)
        restored.open_session_file(session)
        current = restored.tool('prepare')
        assert current.preparation_mode.currentData() == 'automatic'
        assert current.coverage_threshold.value() == 98.5
        assert current.allow_partial.isChecked()
        assert current.catalog_parameters()['max_bytes'] == 500_000_000
        assert current.catalog_parameters()['max_items'] == 3
        for scene in current.selected_scenes():
            assert Path(scene.quality).is_file()
            assert scene.quality_kind == 'valid_mask'
        current._audit_report = {'recommended_scene_ids': ['A']}
        current.apply_audit_button.setEnabled(True)
        current.quality_masks.cellWidget(0, 2).setCurrentIndex(0)
        assert not current.apply_audit_button.isEnabled()
        with pytest.raises(ValueError, match='type du masque'):
            current.selected_scenes()
    finally:
        close(original, application)
        close(restored, application)


def test_custom_loading_requires_explicit_quality_policy(application, write_raster, tmp_path):
    window = CartomizeWindow()
    try:
        page, _ = configure(window, write_raster, tmp_path)
        for row in range(page.quality_masks.rowCount()):
            page.quality_masks.item(row, 1).setText('')
        window.start()
        assert window.thread is None
        assert 'Associer un masque de qualité' in window.status.text()
        assert page.clouds.isChecked()
        page.clouds.setChecked(False)
        window.start()
        wait(window)
        assert window.status.text().startswith('Traitement terminé'), window.status.text()
    finally:
        close(window, application)


def test_automatic_requires_aoi_and_remote_only_requires_explicit_grid(application, write_raster, tmp_path):
    window = CartomizeWindow()
    try:
        page, _ = configure(window, write_raster, tmp_path)
        page.aoi.edit.clear()
        window.start()
        assert window.thread is None
        assert 'zone d’étude' in window.status.text()
        page.files = []
        page.assets.setRowCount(0)
        page.catalog_enabled.setChecked(True)
        page.catalog_endpoint.setText('https://example.org/stac')
        page.aoi.edit.setText(str(tmp_path / 'zone.geojson'))
        window.start()
        assert window.thread is None
        assert 'bandes à obtenir' in window.status.text()
        page.catalog_bands.setText('red,nir')
        window.start()
        assert window.thread is None
        assert 'système projeté cible' in window.status.text()
    finally:
        close(window, application)


def test_remote_only_gui_downloads_supported_scenes_and_uses_their_masks(application, tmp_path, catalog_service):
    service = catalog_service
    for name, left in [('left', 300000), ('right', 300020)]:
        item = service['add'](name, left=left, mask=4)
        item['collection'] = 'sentinel-2-l2a'
        item['properties']['platform'] = 'sentinel-2a'
        item['properties']['processing:level'] = 'L2A'
        item['assets']['scl'] = item['assets'].pop('valid')
    zone = tmp_path / 'zone.geojson'
    cm.GeoDataFrame(geometry=[box(300000, 9499980, 300040, 9500000)], crs=32733).to_file(zone)
    window = CartomizeWindow()
    try:
        window.select_tool('prepare')
        page = window.tool('prepare')
        page.aoi.edit.setText(str(zone))
        page.crs.setText('EPSG:32733')
        page.resolution.setValue(10)
        page.catalog_enabled.setChecked(True)
        page.catalog_endpoint.setText(service['endpoint'])
        page.catalog_collections.setText('sentinel-2-l2a')
        page.catalog_dates.setText('2026-10-26/2026-10-26')
        page.catalog_bands.setText('red,nir')
        page.catalog_max_items.setValue(2)
        page.catalog_max_mb.setValue(1)
        page.output.edit.setText(str(tmp_path))
        page.name.setText('from_catalog')
        window.start()
        wait(window)
        assert window.status.text().startswith('Traitement terminé'), window.status.text()
        record = json.loads(Path(window.output_path).read_text(encoding='utf-8'))
        assert record['status'] == 'complete'
        assert record['selected_scene_ids'] == ['left', 'right']
        assert page.clouds.isChecked()
        with rasterio.open(record['products'][0]['multiband']) as src:
            np.testing.assert_allclose(src.read(1), .9)
            np.testing.assert_allclose(src.read(2), 2.9)
            assert src.read_masks(1).min() == 255
        assert any(kind == 'search' and payload['collections'] == ['sentinel-2-l2a']
                   for kind, payload in service['requests'])
        assert sum(kind == 'asset' for kind, payload in service['requests']) == 4
        assert record['gaps'] in window.workspace.records
    finally:
        close(window, application)


@pytest.mark.parametrize('allow_partial', [False, True])
def test_coverage_policy_and_diagnostics_reach_the_processing_page(application, write_raster, tmp_path, allow_partial):
    from dataclasses import asdict
    from cartomize.storage import save_json
    window = CartomizeWindow()
    try:
        preparation, zone = configure(window, write_raster, tmp_path, width=6)
        manifest = tmp_path / 'scenes.json'
        save_json(dict(schema='cartomize.scenes.v1', scenes=[asdict(scene) for scene in preparation.selected_scenes()]), manifest)
        window.select_tool('processing')
        page = window.tool('processing')
        page.processing_steps.set_records([dict(id='image', operation='imagery.preprocess',
            parameters=dict(sources=str(manifest), aoi=str(zone), band_order=['red', 'nir'],
                            coverage_threshold=100., allow_partial=allow_partial))])
        page.output.edit.setText(str(tmp_path))
        page.name.setText('chain')
        window.start()
        wait(window)
        if allow_partial:
            assert window.status.text().startswith('Traitement terminé avec couverture partielle'), window.status.text()
            assert (tmp_path / 'chain/automation.json').is_file()
            assert window.tool('indices').source.text()
            assert window.tool('classification').source.text()
            assert any(layer.get('purpose') == 'diagnostic' for layer in window.results)
        else:
            assert window.status.text().startswith('Échec du traitement'), window.status.text()
            assert not (tmp_path / 'chain').exists()
            report = json.loads(Path(window.output_path).read_text(encoding='utf-8'))
            assert report['usable_percent'] == pytest.approx(100 * 4 / 6)
            assert Path(report['gaps']).is_file()
            assert report['gaps'] in window.workspace.records
            assert window.folder_button.isEnabled()
            assert {layer['purpose'] for layer in window.results} == {'diagnostic'}
    finally:
        close(window, application)


@pytest.mark.parametrize('font_size', [12, 16])
@pytest.mark.parametrize('style', QStyleFactory.keys())
@pytest.mark.parametrize('spin_button_space', [0, 28], ids=['native', 'wide-spin-buttons'])
def test_automatic_controls_fit_the_window(application, tmp_path, monkeypatch, font_size, style, spin_button_space):
    import cartomize.desktop as desktop
    previous_style = application.style().objectName()
    application.setStyle(style)
    monkeypatch.setattr(desktop, 'QSettings', lambda *args: QSettings(str(tmp_path / 'appearance.ini'), QSettings.Format.IniFormat))
    window = desktop.CartomizeWindow()
    try:
        window.select_tool('prepare')
        page = window.tool('prepare')
        page.catalog_enabled.setChecked(True)
        window._workbench.font_size.setValue(font_size)
        window.resize(1440, 940)
        window.show()
        QTest.qWait(50)
        if spin_button_space:
            # Windows 11 adds more room for native spin buttons than the Linux
            # styles. Exercise that constraint even when this style is absent.
            for control in page.findChildren(QAbstractSpinBox):
                control.setMinimumWidth(control.minimumSizeHint().width() + spin_button_space)
            QTest.qWait(50)
        scroll = window.stack.currentWidget()
        viewport = scroll.viewport()
        assert window.size().toTuple() == (1440, 940)
        if scroll.horizontalScrollBar().maximum():
            print(_width_diagnostic(window, page, viewport))
        assert scroll.horizontalScrollBar().maximum() == 0
        for control in page.findChildren(QAbstractButton):
            if control.isVisible() and control.text():
                left = control.mapTo(viewport, QPoint(0, 0)).x()
                assert 0 <= left < left + control.width() <= viewport.width(), control.text()
                assert control.width() >= control.minimumSizeHint().width(), control.text()
                assert control.height() >= control.minimumSizeHint().height(), control.text()
        for label in page.findChildren(QLabel):
            if label.isVisible() and label.wordWrap() and label.text():
                assert label.height() >= label.heightForWidth(label.width()), label.text()
        for choice in (page.rgb_red, page.rgb_green, page.rgb_blue,
                       page.resampling, page.overlap):
            assert choice.toolTip() == choice.currentText()
            for index in range(choice.count()):
                assert choice.itemData(index, Qt.ItemDataRole.ToolTipRole) == choice.itemText(index)
        for field in (page.source, page.aoi, page.output):
            for button in field.findChildren(QPushButton):
                left = button.mapTo(viewport, QPoint(0, 0)).x()
                assert 0 <= left < left + button.width() <= viewport.width()
    finally:
        close(window, application)
        application.setStyle(previous_style)


def _width_diagnostic(window, page, viewport):
    """Make failures on native styles/font fallbacks actionable in CI logs."""
    controls = []
    for widget in [page] + page.findChildren(QWidget):
        if widget.isVisible():
            caption = (widget.text() if hasattr(widget, 'text') else
                       widget.title() if hasattr(widget, 'title') else widget.objectName())
            controls.append(dict(kind=type(widget).__name__, text=caption,
                size=widget.size().toTuple(), minimum=widget.minimumSize().toTuple(),
                hint=widget.minimumSizeHint().toTuple(), font=widget.font().toString()))
    return json.dumps(dict(viewport=viewport.size().toTuple(), controls_panel=window.controls_panel.size().toTuple(),
                page=page.size().toTuple(), form=page.form.minimumSize().toTuple(),
                widest=sorted(controls, key=lambda item: max(item['hint'][0], item['minimum'][0]), reverse=True)[:20]),
                ensure_ascii=False, indent=2)


def test_cancellation_during_automatic_diagnostic_preserves_no_product(application, write_raster, tmp_path, monkeypatch):
    entered = threading.Event()
    def delayed(scenes, destination, *, progress, cancel, stage, **kwargs):
        stage('Diagnostic automatique')
        entered.set()
        cancel.wait(5)
        raise cm.ProcessingCancelled()
    monkeypatch.setattr(cm, 'preprocess_imagery', delayed)
    window = CartomizeWindow()
    try:
        configure(window, write_raster, tmp_path)
        window.start()
        assert entered.wait(5)
        window.cancel()
        wait(window)
        assert window.status.text() == 'Traitement interrompu.'
        assert not (tmp_path / 'automatic').exists()
        assert not window.results
    finally:
        close(window, application)
