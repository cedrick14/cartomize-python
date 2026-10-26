"""Editable schema and field correspondences for vector layer harmonisation."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import json
import math
from pathlib import Path
import re
import tempfile

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout,
                               QGridLayout, QHeaderView, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QPushButton,
                               QSizePolicy, QTableWidget, QTableWidgetItem, QWidget)

from .processing import execute_operation
from .recipes import safe_name


INSPECTION_SCHEMA = 'cartomize.desktop.merge-inspection.v1'
FIELD_TYPES = [('Texte', 'string'), ('Entier', 'int64'), ('Réel', 'float64'),
               ('Booléen', 'boolean'), ('Date', 'date'),
               ('Date/heure', 'datetime'), ('Date/heure UTC', 'datetime_utc')]


def _combo(choices, value=None, *, editable=False):
    control = QComboBox()
    control.setEditable(editable)
    control.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    control.setMinimumContentsLength(5)
    control.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
    for label, data in choices:
        control.addItem(label, data)
    index = control.findData(value)
    if index >= 0:
        control.setCurrentIndex(index)
    control.setToolTip(control.currentText())
    control.currentTextChanged.connect(control.setToolTip)
    return control


def _item(text, *, editable=False, data=None):
    item = QTableWidgetItem(str(text))
    if not editable:
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    item.setData(Qt.ItemDataRole.UserRole, data)
    item.setToolTip(str(text))
    return item


def _table(headers, height):
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    table.setMinimumWidth(0)
    table.setMinimumHeight(height)
    table.setMaximumHeight(height + 90)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setMinimumSectionSize(42)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    # Stretching the last section can retain a width larger than the viewport
    # after the vertical scrollbar appears, hiding even its first characters
    # at the end of horizontal scrolling. Each column remains user-resizable.
    table.setHorizontalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    table.setWordWrap(True)
    return table


class MergeControls:
    """Store every editable decision in session-persisted widgets and items."""

    def init_merge_controls(self):
        self._merge_loading = True
        self._merge_current_layer_id = None
        self._merge_preview_dirs = []
        self._merge_next_action = None
        self.merge_section = QWidget()
        form = QFormLayout(self.merge_section)
        form.setContentsMargins(0, 0, 0, 0)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        self.merge_sources = QListWidget()
        self.merge_sources.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.merge_sources.setWordWrap(True)
        self.merge_sources.setMinimumHeight(70)
        self.merge_sources.setMaximumHeight(120)
        self.merge_sources.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        actions = QWidget()
        buttons = QGridLayout(actions)
        buttons.setContentsMargins(0, 0, 0, 0)
        for text, callback, row, column, span in [
            ('Fichiers…', self.browse_merge_files, 0, 0, 1),
            ('Dossier…', self.browse_merge_folder, 0, 1, 1),
            ('Retirer la sélection', self.remove_merge_sources, 1, 0, 2),
        ]:
            button = QPushButton(text)
            button.clicked.connect(callback)
            buttons.addWidget(button, row, column, 1, span)
        self.merge_recursive = QCheckBox('Inclure les\nsous-dossiers')
        self.merge_inspect_button = QPushButton('Analyser les\nschémas sources')
        self.merge_inspect_button.clicked.connect(self.inspect_merge_sources)
        self.merge_status = QLabel('Ajouter des fichiers ou des dossiers, puis analyser leurs couches.')
        self.merge_status.setWordWrap(True)
        self.merge_layers = QListWidget()
        self.merge_layers.setWordWrap(True)
        self.merge_layers.setMinimumHeight(90)
        self.merge_layers.setMaximumHeight(160)
        self.merge_layers.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.merge_layers.setToolTip('Cocher les couches à fusionner. Chaque enregistrement conserve sa géométrie et sa provenance.')
        # This visible choice also persists the active mapping table. QListWidget
        # selection itself is not included in the common session format.
        self.merge_layer_choice = _combo([])
        self.merge_layer_details = QLabel()
        self.merge_layer_details.setWordWrap(True)
        self.merge_source_fields = _table(['Champ', 'Type', 'NULL'], 125)
        for column, width in enumerate((135, 105, 65)):
            self.merge_source_fields.setColumnWidth(column, width)
        self.merge_schema = _table(['Champ', 'Type', 'Null', 'Défaut', 'Valeur'], 170)
        for column, width in enumerate((95, 90, 70, 120, 90)):
            self.merge_schema.setColumnWidth(column, width)
        self.merge_schema.setToolTip('Schéma exact de sortie : modifier les noms, choisir les types, autoriser les valeurs nulles et définir les valeurs par défaut.')
        schema_actions = QWidget()
        schema_buttons = QGridLayout(schema_actions)
        schema_buttons.setContentsMargins(0, 0, 0, 0)
        self.merge_add_field_button = QPushButton('Ajouter un champ')
        self.merge_remove_field_button = QPushButton('Retirer le champ')
        self.merge_add_field_button.clicked.connect(lambda: self.add_merge_field())
        self.merge_remove_field_button.clicked.connect(self.remove_merge_field)
        schema_buttons.addWidget(self.merge_add_field_button, 0, 0)
        schema_buttons.addWidget(self.merge_remove_field_button, 1, 0)
        schema_note = QLabel('Le type choisi définit la conversion. « Null » autorise une absence après conversion et application du défaut. Pour un texte vide par défaut, choisir « Valeur » et laisser sa cellule vide.')
        schema_note.setWordWrap(True)
        self.merge_mapping = _table(['Source', 'Type', 'Cible'], 160)
        for column, width in enumerate((115, 80, 140)):
            self.merge_mapping.setColumnWidth(column, width)
        mapping_note = QLabel('Choisir ou saisir le nom cible de chaque champ. « Écarter » exclut explicitement un champ. Les correspondances sont conservées séparément pour chaque couche.')
        mapping_note.setWordWrap(True)
        self.merge_conversion_errors = _combo([('Arrêter', 'error'), ('Mettre à NULL', 'null')], 'error')
        self.merge_missing_fields = _combo([('Créer des valeurs NULL', 'null'), ('Arrêter', 'error')], 'null')
        self.merge_extra_fields = _combo([('Arrêter', 'error'), ('Écarter les champs', 'drop')], 'error')
        self.merge_target_crs = QLineEdit()
        self.merge_target_crs.setPlaceholderText('Vide : les SCR doivent être identiques')
        crs_note = QLabel('Une cible explicite utilise les contrôles géodésiques stricts. Pour examiner et choisir les transformations, préparer les couches avec la reprojection par lot.')
        crs_note.setWordWrap(True)
        self.merge_folder = QLineEdit('fusion_vectorielle')
        note = QLabel('La fusion conserve toutes les lignes et leurs géométries, dans l’ordre des couches. Elle ajoute la provenance et un rapport des conversions. Les recouvrements et doublons sont conservés.')
        note.setWordWrap(True)
        for title, control in [
            ('Fichiers et dossiers sources', self.merge_sources), ('', actions),
            ('Recherche des sources', self.merge_recursive), ('', self.merge_inspect_button),
            ('', self.merge_status), ('Couches à fusionner', self.merge_layers),
            ('Couche à examiner', self.merge_layer_choice), ('', self.merge_layer_details),
            ('Schéma de la couche source', self.merge_source_fields),
            ('Schéma cible éditable', self.merge_schema), ('', schema_actions), ('', schema_note),
            ('Correspondances de cette couche', self.merge_mapping), ('', mapping_note),
            ('Conversion impossible', self.merge_conversion_errors),
            ('Champ cible absent d’une couche', self.merge_missing_fields),
            ('Champ source hors du schéma cible', self.merge_extra_fields),
            ('SCR cible facultatif', self.merge_target_crs), ('', crs_note),
            ('Nouveau dossier des résultats', self.merge_folder), ('', note),
        ]:
            if title:
                caption = QLabel(title)
                caption.setWordWrap(True)
                form.addRow(caption, control)
            else:
                form.addRow(control)
        self.form.insertRow(self.form.rowCount() - 1, self.merge_section)
        self.operation.addItem('Harmonisation et fusion', 'merge_layers')
        self.merge_recursive.toggled.connect(self.invalidate_merge_inspection)
        self.merge_layers.currentRowChanged.connect(self.select_merge_layer_row)
        self.merge_layer_choice.currentIndexChanged.connect(self.show_merge_layer)
        self._merge_loading = False
        self.show_merge_layer()

    def add_merge_sources(self, sources):
        existing = {self.merge_sources.item(i).data(Qt.ItemDataRole.UserRole)
                    for i in range(self.merge_sources.count())}
        for source in sources:
            path = str(Path(source).expanduser().resolve())
            if path not in existing:
                item = QListWidgetItem(path, self.merge_sources)
                item.setData(Qt.ItemDataRole.UserRole, path)
                item.setToolTip(path)
                existing.add(path)
        self.invalidate_merge_inspection()

    def browse_merge_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, 'Couches à harmoniser',
            filter='Données vectorielles (*.gpkg *.shp *.geojson *.json *.fgb *.gml *.kml *.sqlite);;Tous les fichiers (*)')
        if paths:
            self.add_merge_sources(paths)

    def browse_merge_folder(self):
        path = QFileDialog.getExistingDirectory(self, 'Dossier des couches à harmoniser')
        if path:
            self.add_merge_sources([path])

    def remove_merge_sources(self):
        for item in self.merge_sources.selectedItems():
            self.merge_sources.takeItem(self.merge_sources.row(item))
        self.invalidate_merge_inspection()

    def invalidate_merge_inspection(self, *_):
        self.merge_status.setText('Sources modifiées : analyser les couches avant de lancer la fusion. Le schéma cible édité sera conservé.')

    def merge_source_configuration(self):
        sources = [self.merge_sources.item(i).data(Qt.ItemDataRole.UserRole)
                   for i in range(self.merge_sources.count())]
        if not sources:
            raise ValueError('Ajouter au moins un fichier ou un dossier source à la fusion.')
        recursive = self.merge_recursive.isChecked()
        signature = json.dumps(dict(sources=sources, recursive=recursive), sort_keys=True)
        return sources, recursive, signature

    def _merge_layer_item(self, identifier):
        for row in range(self.merge_layers.count()):
            item = self.merge_layers.item(row)
            if item.data(Qt.ItemDataRole.UserRole)['id'] == identifier:
                return item
        return None

    def store_merge_mapping(self, *_):
        if self._merge_loading:
            return
        item = self._merge_layer_item(self._merge_current_layer_id)
        if item is None:
            return
        mapping = {}
        for row in range(self.merge_mapping.rowCount()):
            source = self.merge_mapping.item(row, 0)
            control = self.merge_mapping.cellWidget(row, 2)
            if source is None or control is None:
                continue
            name = source.data(Qt.ItemDataRole.UserRole)
            target = None if control.currentIndex() == 0 and control.currentText() == 'Écarter' else control.currentText().strip()
            if target != name:
                mapping[name] = target
        data = item.data(Qt.ItemDataRole.UserRole)
        data['field_map'] = mapping
        item.setData(Qt.ItemDataRole.UserRole, data)

    def _merge_field_maps(self, *, selected_only=False):
        self.store_merge_mapping()
        mappings = {}
        for row in range(self.merge_layers.count()):
            item = self.merge_layers.item(row)
            if selected_only and item.checkState() != Qt.CheckState.Checked:
                continue
            layer = item.data(Qt.ItemDataRole.UserRole)
            if layer.get('field_map'):
                mappings[layer['id']] = deepcopy(layer['field_map'])
        return mappings

    def inspect_merge_sources(self):
        window = self.window()
        if not hasattr(window, 'start') or not hasattr(window, 'thread'):
            self.merge_status.setText('Ouvrir cet outil dans la fenêtre Cartomize pour lancer l’analyse.')
            return
        if window.thread is not None:
            return
        self._merge_next_action = 'inspect'
        try:
            window.start()
            if window.thread is not None and window.worker is not None:
                window.worker.failed.connect(lambda message: self.merge_status.setText('Analyse interrompue : ' + message))
                window.worker.cancelled.connect(lambda: self.merge_status.setText('Analyse annulée.'))
            else:
                self.merge_status.setText(window.status.text())
        finally:
            self._merge_next_action = None

    def merge_inspection_job(self):
        sources, recursive, signature = self.merge_source_configuration()
        temporary = tempfile.TemporaryDirectory(prefix='cartomize-merge-')
        self._merge_preview_dirs.append(temporary)
        destination = Path(temporary.name) / 'inspection.json'
        self.merge_status.setText('Analyse des couches et des schémas en cours…')
        # Discovery remains independent of mappings that may refer to layers
        # removed from the source list. Edited mappings are retained by stable ID.
        def run(progress, cancel):
            from . import ProcessingCancelled
            try:
                if cancel.is_set():
                    raise ProcessingCancelled()
                from .vector_merge import inspect_merge
                inspection = inspect_merge(sources, recursive=recursive, progress=progress, cancel=cancel)
                if cancel.is_set():
                    raise ProcessingCancelled()
                destination.write_text(json.dumps(dict(schema=INSPECTION_SCHEMA, signature=signature,
                    inspection=inspection), ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
                progress(len(inspection['layers']), len(inspection['layers']))
                if cancel.is_set():
                    raise ProcessingCancelled()
                return destination
            except Exception:
                temporary.cleanup()
                raise
        return run

    def show_result(self, path):
        path = Path(path)
        if path.suffix.lower() != '.json':
            return super().show_result(path)
        record = json.loads(path.read_text(encoding='utf-8'))
        if record.get('schema') != INSPECTION_SCHEMA:
            return super().show_result(path)
        try:
            signature = self.merge_source_configuration()[2]
        except ValueError:
            signature = None
        if signature != record['signature']:
            self.merge_status.setText('Cette analyse correspond à des sources précédentes. Analyser à nouveau les sources actuelles.')
            return
        self.store_merge_mapping()
        previous = {self.merge_layers.item(i).data(Qt.ItemDataRole.UserRole)['id']:
                    (self.merge_layers.item(i).checkState(), self.merge_layers.item(i).data(Qt.ItemDataRole.UserRole).get('field_map', {}))
                    for i in range(self.merge_layers.count())}
        selected = self.merge_layer_choice.currentData()
        self._merge_loading = True
        self.merge_layers.blockSignals(True)
        self.merge_layer_choice.blockSignals(True)
        self.merge_layers.clear()
        self.merge_layer_choice.clear()
        inspection = record['inspection']
        for layer in inspection['layers']:
            layer = deepcopy(layer)
            layer['inspection_signature'] = signature
            checked, mapping = previous.get(layer['id'], (Qt.CheckState.Checked, {}))
            layer['field_map'] = mapping
            item = QListWidgetItem(f"{layer['name']} — {layer.get('features', '?')} entité(s)", self.merge_layers)
            item.setData(Qt.ItemDataRole.UserRole, layer)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(checked)
            item.setToolTip(str(layer.get('path', '')) + '\n' + str(layer.get('layer') or ''))
            self.merge_layer_choice.addItem(layer['name'], layer['id'])
        self.merge_layers.blockSignals(False)
        index = self.merge_layer_choice.findData(selected)
        self.merge_layer_choice.setCurrentIndex(index if index >= 0 else (0 if self.merge_layer_choice.count() else -1))
        self.merge_layer_choice.blockSignals(False)
        if self.merge_schema.rowCount() == 0:
            for name, specification in inspection.get('suggested_schema', {}).items():
                self.add_merge_field(name, specification)
        self._merge_current_layer_id = None
        self._merge_loading = False
        self.show_merge_layer()
        conflicts = inspection.get('conflicts', [])
        message = f'{self.merge_layers.count()} couche(s) analysée(s). Cocher les couches et vérifier le schéma cible et les correspondances.'
        if conflicts:
            message += ' Types à choisir : ' + ', '.join(str(conflict['field']) for conflict in conflicts) + '.'
        if not inspection.get('common_crs'):
            message += ' Les SCR diffèrent ou sont absents : vérifier le SCR cible.'
        self.merge_status.setText(message)

    def add_merge_field(self, name=None, specification=None):
        specification = specification or {'type': 'string', 'nullable': True}
        if isinstance(specification, str):
            specification = {'type': specification}
        existing = {self.merge_schema.item(row, 0).text() for row in range(self.merge_schema.rowCount())
                    if self.merge_schema.item(row, 0) is not None}
        if name is None:
            number = 1
            while f'champ_{number}' in existing:
                number += 1
            name = f'champ_{number}'
        row = self.merge_schema.rowCount()
        self.merge_schema.insertRow(row)
        self.merge_schema.setItem(row, 0, _item(name, editable=True))
        self.merge_schema.setCellWidget(row, 1, _combo([('À choisir', None), *FIELD_TYPES], specification.get('type')))
        nullable = QCheckBox()
        nullable.setChecked(specification.get('nullable', True))
        nullable.setToolTip('Autoriser une valeur nulle après conversion et application du défaut.')
        self.merge_schema.setCellWidget(row, 2, nullable)
        mode = 'none' if 'default' not in specification else 'null' if specification['default'] is None else 'value'
        self.merge_schema.setCellWidget(row, 3, _combo([('Aucun', 'none'), ('NULL', 'null'), ('Valeur', 'value')], mode))
        value = specification.get('default')
        text = '' if value is None else ('true' if value is True else 'false' if value is False else str(value))
        self.merge_schema.setItem(row, 4, _item(text, editable=True))
        self.merge_schema.resizeRowToContents(row)
        if not self._merge_loading:
            self.merge_schema.setCurrentCell(row, 0)
            self.refresh_merge_mapping_choices()

    def remove_merge_field(self):
        row = self.merge_schema.currentRow()
        if row >= 0:
            self.merge_schema.removeRow(row)
            self.refresh_merge_mapping_choices()

    def select_merge_layer_row(self, row):
        if self._merge_loading or row < 0:
            return
        item = self.merge_layers.item(row)
        self.merge_layer_choice.setCurrentIndex(self.merge_layer_choice.findData(item.data(Qt.ItemDataRole.UserRole)['id']))

    def show_merge_layer(self, *_):
        if self._merge_loading:
            return
        self.store_merge_mapping()
        self._merge_current_layer_id = self.merge_layer_choice.currentData()
        item = self._merge_layer_item(self._merge_current_layer_id)
        self._merge_loading = True
        self.merge_source_fields.setRowCount(0)
        self.merge_mapping.setRowCount(0)
        if item is None:
            self.merge_layer_details.clear()
            self.merge_layer_choice.setEnabled(False)
            self._merge_loading = False
            return
        self.merge_layer_choice.setEnabled(True)
        self.merge_layers.blockSignals(True)
        self.merge_layers.setCurrentItem(item)
        self.merge_layers.blockSignals(False)
        layer = item.data(Qt.ItemDataRole.UserRole)
        self.merge_layer_details.setText(f"{layer['name']}\n{layer.get('features', '?')} entité(s) · SCR : {layer.get('source_crs') or 'absent'}\nGéométries : {', '.join(layer.get('geometry_types', [])) or 'aucune'}")
        targets = [self.merge_schema.item(row, 0).text().strip() for row in range(self.merge_schema.rowCount())
                   if self.merge_schema.item(row, 0) is not None and self.merge_schema.item(row, 0).text().strip()]
        mapping = layer.get('field_map', {})
        for row, field in enumerate(layer.get('fields', [])):
            name = field['name']
            kind = str(field.get('type') or field.get('dtype') or '?')
            self.merge_source_fields.insertRow(row)
            for column, value in enumerate((name, kind, field.get('null_count', '?'))):
                self.merge_source_fields.setItem(row, column, _item(value))
            self.merge_mapping.insertRow(row)
            self.merge_mapping.setItem(row, 0, _item(name, data=name))
            self.merge_mapping.setItem(row, 1, _item(kind))
            target = mapping.get(name, name)
            choices = [('Écarter', None)] + [(value, value) for value in dict.fromkeys([*targets, *([target] if target else [])])]
            choice = _combo(choices, target, editable=True)
            choice.currentTextChanged.connect(self.store_merge_mapping)
            choice.setProperty('merge_mapping_connected', True)
            self.merge_mapping.setCellWidget(row, 2, choice)
        self.merge_source_fields.resizeRowsToContents()
        self.merge_mapping.resizeRowsToContents()
        self._merge_loading = False

    def refresh_merge_mapping_choices(self):
        if self._merge_loading:
            return
        self.show_merge_layer()

    @staticmethod
    def _merge_default(text, kind, name):
        if kind == 'string':
            return text
        value = text.strip()
        try:
            if kind == 'int64':
                if not re.fullmatch(r'[+-]?\d+', value):
                    raise ValueError()
                number = int(value)
                if not -(2**63) <= number < 2**63:
                    raise ValueError()
                return number
            if kind == 'float64':
                number = float(value)
                if not math.isfinite(number):
                    raise ValueError()
                exact = Decimal(value)
                if exact == exact.to_integral_value() and int(number) != int(exact):
                    raise ValueError()
                return number
            if kind == 'boolean':
                values = {'true': True, 'vrai': True, 'oui': True, '1': True,
                          'false': False, 'faux': False, 'non': False, '0': False}
                if value.casefold() not in values:
                    raise ValueError()
                return values[value.casefold()]
            if not value:
                raise ValueError()
            return value
        except (ValueError, InvalidOperation, OverflowError) as exc:
            raise ValueError(f'Valeur par défaut invalide pour le champ {name} ({kind}).') from exc

    def merge_schema_parameters(self):
        schema = {}
        names = set()
        for row in range(self.merge_schema.rowCount()):
            item = self.merge_schema.item(row, 0)
            name = item.text().strip() if item is not None else ''
            if not name or name.casefold() in names:
                raise ValueError('Chaque champ cible doit avoir un nom renseigné et unique, sans distinction de casse.')
            names.add(name.casefold())
            kind = self.merge_schema.cellWidget(row, 1).currentData()
            if kind not in {value for _, value in FIELD_TYPES}:
                raise ValueError('Choisir le type du champ cible ' + name + '.')
            specification = dict(type=kind, nullable=self.merge_schema.cellWidget(row, 2).isChecked())
            mode = self.merge_schema.cellWidget(row, 3).currentData()
            if mode == 'null':
                specification['default'] = None
            elif mode == 'value':
                cell = self.merge_schema.item(row, 4)
                specification['default'] = self._merge_default(cell.text() if cell else '', kind, name)
            schema[name] = specification
        if not schema:
            raise ValueError('Définir au moins un champ dans le schéma cible.')
        return schema

    def update_merge_controls(self):
        if not hasattr(self, 'merge_section'):
            return
        op = self.operation.currentData()
        active = op == 'merge_layers'
        self.merge_section.setVisible(active)
        if active:
            self.source.hide()
            self.form.labelForField(self.source).hide()
            previous_mode = self.output.mode
            self.output.mode = 'directory'
            self.output.filter = ''
            self.form.labelForField(self.output).setText('Répertoire parent des résultats')
            if previous_mode != 'directory' and Path(self.output.text()).suffix.lower() in {'.gpkg', '.geojson', '.json'}:
                self.output.edit.setText(str(Path(self.output.text()).parent))
            self.cancellable = True
        elif getattr(self, '_merge_mode_active', False) and op != 'reproject_batch' and op not in {key for _, key in getattr(self, 'QUALITY_OPERATIONS', [])}:
            self.output.mode = 'save'
            self.output.filter = 'GeoPackage (*.gpkg);;GeoJSON (*.geojson)'
            self.form.labelForField(self.output).setText('Fichier de sortie')
            if self.output.text() and Path(self.output.text()).is_dir():
                self.output.edit.setText(str(Path(self.output.text()) / 'resultat.gpkg'))
            self.cancellable = False
        self._merge_mode_active = active

    def restore_merge_controls(self):
        if self.operation.findData('merge_layers') < 0:
            self.operation.addItem('Harmonisation et fusion', 'merge_layers')
        self.update_merge_controls()
        # The common reader recreates cell widgets and does not retain their
        # editability or signals. Keep their saved choices/index instead of
        # rebuilding the table: an unfinished typed mapping is still a choice.
        self._merge_loading = True
        for row in range(self.merge_schema.rowCount()):
            nullable = self.merge_schema.cellWidget(row, 2)
            if nullable is not None:
                nullable.setToolTip('Autoriser une valeur nulle après conversion et application du défaut.')
            for column in (1, 3):
                control = self.merge_schema.cellWidget(row, column)
                if control is not None:
                    control.setMinimumContentsLength(5)
                    control.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
                    control.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
                    control.setToolTip(control.currentText())
                    control.currentTextChanged.connect(control.setToolTip)
        self._merge_current_layer_id = self.merge_layer_choice.currentData()
        item = self._merge_layer_item(self._merge_current_layer_id)
        self.merge_layer_choice.setEnabled(item is not None)
        if item is not None:
            layer = item.data(Qt.ItemDataRole.UserRole)
            self.merge_layers.blockSignals(True)
            self.merge_layers.setCurrentItem(item)
            self.merge_layers.blockSignals(False)
            self.merge_layer_details.setText(f"{layer['name']}\n{layer.get('features', '?')} entité(s) · SCR : {layer.get('source_crs') or 'absent'}\nGéométries : {', '.join(layer.get('geometry_types', [])) or 'aucune'}")
            for row in range(self.merge_mapping.rowCount()):
                source = self.merge_mapping.item(row, 0)
                control = self.merge_mapping.cellWidget(row, 2)
                if source is None or control is None:
                    continue
                name = source.data(Qt.ItemDataRole.UserRole)
                target = layer.get('field_map', {}).get(name, name)
                control.setEditable(True)
                control.setMinimumContentsLength(5)
                control.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
                control.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
                control.setEditText('Écarter' if target is None else target)
                control.setToolTip(control.currentText())
                if not control.property('merge_mapping_connected'):
                    control.currentTextChanged.connect(self.store_merge_mapping)
                    control.currentTextChanged.connect(control.setToolTip)
                    control.setProperty('merge_mapping_connected', True)
        self._merge_loading = False
        if self.merge_layers.count():
            self.merge_status.setText('Schéma, couches et correspondances restaurés. Les données seront à nouveau contrôlées au lancement.')

    def merge_job(self, options):
        if self._merge_next_action == 'inspect':
            return self.merge_inspection_job()
        _, _, signature = self.merge_source_configuration()
        schema = self.merge_schema_parameters()
        mappings = self._merge_field_maps(selected_only=True)
        selected = []
        for row in range(self.merge_layers.count()):
            item = self.merge_layers.item(row)
            if item.checkState() != Qt.CheckState.Checked:
                continue
            layer = item.data(Qt.ItemDataRole.UserRole)
            if layer.get('inspection_signature') != signature:
                raise ValueError('Les sources ont changé. Analyser à nouveau les couches avant la fusion.')
            mapping = mappings.get(layer['id'], {})
            targets = []
            for field in layer.get('fields', []):
                target = mapping.get(field['name'], field['name'])
                if target is None:
                    continue
                if not target:
                    raise ValueError('Indiquer un champ cible ou choisir « Écarter » pour ' + field['name'] + '.')
                if target.casefold() in targets:
                    raise ValueError('Plusieurs champs aboutissent au même champ cible dans ' + layer['name'] + '.')
                targets.append(target.casefold())
                if target not in schema and self.merge_extra_fields.currentData() == 'error':
                    raise ValueError('Le champ ' + target + ' est absent du schéma cible. Le définir, le mapper ou choisir de l’écarter.')
            selected.append({'path': layer['path'], 'layer': layer['layer']})
        if not selected:
            raise ValueError('Analyser les sources et cocher au moins une couche à fusionner.')
        folder = self.merge_folder.text().strip()
        if not folder:
            raise ValueError('Indiquer un nouveau dossier de résultats pour la fusion.')
        destination = Path(self.destination()) / safe_name(folder)
        parameters = deepcopy(dict(sources=selected, schema=schema, field_maps=mappings or None,
            recursive=False, target_crs=self.merge_target_crs.text().strip() or None,
            conversion_errors=self.merge_conversion_errors.currentData(),
            missing_fields=self.merge_missing_fields.currentData(), extra_fields=self.merge_extra_fields.currentData()))
        def run(progress, cancel):
            execute_operation('vector.merge_layers', parameters, destination, progress=progress, cancel=cancel)
            return destination / 'operation.json'
        return run
