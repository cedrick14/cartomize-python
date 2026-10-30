"""Explanations remain reachable without obscuring parameters or warnings."""
import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest

pytest.importorskip('PySide6')
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QToolButton

from cartomize.desktop import AtlasPage, Page
from cartomize.desktop_classification import ClassificationPage
from cartomize.desktop_session import capture_widgets
from cartomize.desktop_tools_base import RasterToolsPage


@pytest.fixture(scope='module')
def application():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize('font_size', [12, 16])
def test_page_help_is_reachable_by_keyboard_and_preserves_editable_state(application, font_size):
    explanation = 'La couverture utilise tous les pixels de la zone, y compris sa partie hors du raster.'
    page = Page('Traitement', explanation)
    font = page.font()
    font.setPixelSize(font_size)
    page.setFont(font)
    page.value = QLineEdit('125.5')
    page.form.addRow('Distance (m)', page.value)
    page.finish()
    page.resize(340, 360)
    try:
        page.show()
        application.processEvents()
        detail = page.findChild(QLabel, 'description')
        button = page.page_help.findChild(QToolButton, 'helpToggle')
        state = capture_widgets(page)
        assert detail.text() == explanation
        assert detail.isHidden()
        assert button.focusPolicy() == Qt.FocusPolicy.StrongFocus
        assert button.accessibleName().startswith('Aide')
        button.setFocus()
        QTest.keyClick(button, Qt.Key.Key_Space)
        application.processEvents()
        assert detail.isVisible()
        assert detail.height() >= detail.heightForWidth(detail.width())
        assert button.isChecked()
        assert page.value.isVisible()
        assert page.form.labelForField(page.value).text() == 'Distance (m)'
        assert capture_widgets(page) == state
        QTest.keyClick(button, Qt.Key.Key_Space)
        assert detail.isHidden()
        assert capture_widgets(page) == state
    finally:
        page.close()
        application.processEvents()


def test_atlas_keeps_its_own_live_description(application):
    page = AtlasPage()
    try:
        description = page.findChild(QLabel, 'description')
        assert 'couche d’index' in description.text()
        assert description.isHidden()
        button = page.page_help.findChild(QToolButton, 'helpToggle')
        button.click()
        assert not description.isHidden()
        description.setText('Emprise propre à chaque page de l’atlas.')
        button.click()
        button.click()
        assert description.text() == 'Emprise propre à chaque page de l’atlas.'
        assert page.findChild(QLabel, 'pageTitle').text() == 'Atlas cartographique'
    finally:
        page.close()


def test_operational_summary_stays_visible_when_its_details_are_collapsed(application):
    summary = 'Transformation horizontale ; Z conservé.'
    help_section = Page.context_help('Le rapport précise les transformations et les grilles utilisées.',
        subject='Reprojection', summary=summary)
    try:
        help_section.resize(380, 150)
        help_section.show()
        application.processEvents()
        note = help_section.findChild(QLabel, 'helpSummary')
        detail = help_section.findChild(QLabel, 'helpText')
        button = help_section.findChild(QToolButton, 'helpToggle')
        for checked in (False, True, False):
            button.setChecked(checked)
            application.processEvents()
            assert note.isVisible()
            assert note.text() == summary
            assert detail.isVisible() == checked
    finally:
        help_section.close()


def test_operation_specific_help_and_calibration_controls_remain_scoped(application):
    page = RasterToolsPage()
    try:
        page.operation.setCurrentIndex(page.operation.findData('zonal_stats'))
        assert not page.zonal_note.isHidden()
        assert not page.zonal_help.isHidden()
        assert page.zonal_help.findChild(QLabel, 'helpText').isHidden()
        assert 'NoData' in page.zonal_note.text()
        assert page.value_mode.currentData() == 'physical'
        assert 'zone_pixels' in page.include_coverage.toolTip()
        page.zonal_help.findChild(QToolButton, 'helpToggle').click()
        assert not page.zonal_help.findChild(QLabel, 'helpText').isHidden()
        page.operation.setCurrentIndex(page.operation.findData('reproject'))
        assert page.zonal_help.isHidden()
        assert page.zonal_note.isHidden()
        assert not page.resolution.isHidden()
        assert 'unités du système cible' in page.form.labelForField(page.resolution).text()
    finally:
        page.close()


def test_unsupervised_interpretation_notice_is_not_inside_collapsed_help(application):
    page = ClassificationPage()
    try:
        assert page.interpretation_note.isHidden()
        page.method.setCurrentIndex(page.method.findData('kmeans'))
        assert not page.interpretation_note.isHidden()
        assert page.findChild(QLabel, 'description').isHidden()
        button = page.page_help.findChild(QToolButton, 'helpToggle')
        for checked in (True, False):
            button.setChecked(checked)
            assert not page.interpretation_note.isHidden()
            assert page.method.currentData() == 'kmeans'
            assert page.clusters.isEnabled()
        page.method.setCurrentIndex(page.method.findData('model'))
        assert page.interpretation_note.isHidden()
    finally:
        page.close()
