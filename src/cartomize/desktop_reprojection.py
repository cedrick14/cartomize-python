"""Review source layers and coordinate operations before a vector batch job."""
from copy import deepcopy
import json
import math
from pathlib import Path
import tempfile

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout,
                               QGridLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPlainTextEdit, QPushButton,
                               QSizePolicy, QWidget)

from .processing import execute_operation
from .recipes import safe_name


INSPECTION_SCHEMA = 'cartomize.desktop.reprojection-inspection.v1'


class BatchReprojectionControls:
    """Keep batch selections in ordinary session-persisted page widgets."""

    def init_reprojection_controls(self):
        self.batch_section = QWidget()
        form = QFormLayout(self.batch_section)
        form.setContentsMargins(0, 0, 0, 0)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        self.batch_sources = QListWidget()
        self.batch_sources.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.batch_sources.setWordWrap(True)
        self.batch_sources.setMinimumHeight(75)
        self.batch_sources.setMaximumHeight(130)
        self.batch_sources.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        actions = QWidget()
        buttons = QGridLayout(actions)
        buttons.setContentsMargins(0, 0, 0, 0)
        for text, callback, row, column, span in [
            ('Fichiers…', self.browse_reprojection_files, 0, 0, 1),
            ('Dossier…', self.browse_reprojection_folder, 0, 1, 1),
            ('Retirer la sélection', self.remove_reprojection_sources, 1, 0, 2),
        ]:
            button = QPushButton(text)
            button.clicked.connect(callback)
            buttons.addWidget(button, row, column, 1, span)
        # QCheckBox does not wrap text to the available width. Explicit line
        # breaks keep the complete labels readable with wider native fonts.
        self.batch_recursive = QCheckBox('Inclure les\nsous-dossiers')
        self.batch_target_crs = QLineEdit()
        self.batch_target_crs.setPlaceholderText('Exemple : EPSG:32733')
        self.batch_accuracy = QLineEdit()
        self.batch_accuracy.setPlaceholderText('Vide : aucun seuil de précision annoncé')
        self.batch_accuracy.setToolTip('Précision annoncée maximale, en mètres. Ce seuil ne mesure pas la précision des données sources.')
        self.batch_aoi = QLineEdit()
        self.batch_aoi.setPlaceholderText('Ouest, sud, est, nord ; coordonnées en degrés')
        self.batch_aoi.setToolTip('Facultatif : emprise géographique WGS 84 utilisée pour rechercher les transformations.')
        self.batch_ballpark = QCheckBox('Autoriser une\napproximation')
        self.batch_ballpark.setToolTip('Autoriser explicitement une transformation géodésique approximative, qui sera signalée dans le rapport.')
        self.batch_require_best = QCheckBox('Exiger la\nmeilleure\ntransformation')
        self.batch_require_best.setChecked(True)
        self.batch_require_best.setToolTip('Arrêter si une grille nécessaire à la meilleure transformation est absente. Le lot n’active aucun téléchargement de grilles.')
        self.batch_area_policy = self._reprojection_combo()
        self.batch_area_policy.addItem('Arrêter le lot', 'error')
        self.batch_area_policy.addItem('Continuer avec un avertissement', 'warn')
        self.batch_inspect_button = QPushButton('Analyser les couches\net les transformations')
        self.batch_inspect_button.clicked.connect(self.inspect_reprojection_sources)
        self.batch_status = QLabel('Ajouter des fichiers ou un dossier, renseigner le SCR cible, puis analyser les couches.')
        self.batch_status.setWordWrap(True)
        self.batch_layers = QListWidget()
        self.batch_layers.setWordWrap(True)
        self.batch_layers.setMinimumHeight(100)
        self.batch_layers.setMaximumHeight(190)
        self.batch_layers.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.batch_layers.setToolTip('Cocher les couches à traiter. Sélectionner une ligne pour examiner sa transformation.')
        self.batch_layer_details = QLabel()
        self.batch_layer_details.setWordWrap(True)
        self.batch_operation = self._reprojection_combo()
        self.batch_operation_details = QPlainTextEdit()
        self.batch_operation_details.setReadOnly(True)
        self.batch_operation_details.setMinimumHeight(90)
        self.batch_operation_details.setMaximumHeight(150)
        self.batch_operation_details.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.batch_folder = QLineEdit('reprojection_vectorielle')
        for title, control in [
            ('Fichiers et dossiers sources', self.batch_sources), ('', actions),
            ('Recherche des sources', self.batch_recursive),
            ('Système de coordonnées cible', self.batch_target_crs),
            ('Précision annoncée maximale (m)', self.batch_accuracy),
            ('Emprise géographique facultative', self.batch_aoi),
            ('Transformation approximative', self.batch_ballpark),
            ('Grilles de transformation', self.batch_require_best),
            ('Hors du domaine de validité', self.batch_area_policy),
            ('', self.batch_inspect_button), ('', self.batch_status),
            ('Couches à traiter', self.batch_layers), ('', self.batch_layer_details),
            ('Transformation de la couche sélectionnée', self.batch_operation),
            ('Détail de la transformation', self.batch_operation_details),
            ('Nouveau dossier des résultats', self.batch_folder),
        ]:
            if title:
                caption = QLabel(title)
                caption.setWordWrap(True)
                form.addRow(caption, control)
            else:
                form.addRow(control)
        note = QLabel('Chaque couche conserve ses attributs. Le rapport indique les emprises avant/après, la transformation et ses grilles. Les coordonnées Z sont conservées ; le traitement est horizontal.')
        note.setWordWrap(True)
        form.addRow(note)
        self.form.insertRow(self.form.rowCount() - 1, self.batch_section)
        self.operation.addItem('Reprojection vectorielle par lot', 'reproject_batch')
        self.batch_layers.currentRowChanged.connect(self.show_reprojection_layer)
        self.batch_operation.currentIndexChanged.connect(self.select_reprojection_operation)
        for control in (self.batch_target_crs, self.batch_accuracy, self.batch_aoi):
            control.textChanged.connect(self.invalidate_reprojection_inspection)
        self.batch_recursive.toggled.connect(self.invalidate_reprojection_inspection)
        self.batch_ballpark.toggled.connect(self.invalidate_reprojection_inspection)
        self._batch_preview_dirs = []
        self._batch_next_action = None
        self.show_reprojection_layer()

    @staticmethod
    def _reprojection_combo():
        control = QComboBox()
        control.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        control.setMinimumContentsLength(12)
        control.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        control.currentTextChanged.connect(control.setToolTip)
        return control

    def add_reprojection_sources(self, sources):
        existing = {self.batch_sources.item(i).data(Qt.ItemDataRole.UserRole)
                    for i in range(self.batch_sources.count())}
        for source in sources:
            path = str(Path(source).expanduser().resolve())
            if path not in existing:
                item = QListWidgetItem(path, self.batch_sources)
                item.setData(Qt.ItemDataRole.UserRole, path)
                item.setToolTip(path)
                existing.add(path)
        self.invalidate_reprojection_inspection()

    def browse_reprojection_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, 'Couches vectorielles du lot',
            filter='Données vectorielles (*.gpkg *.shp *.geojson *.json *.fgb *.gml *.kml *.sqlite);;Tous les fichiers (*)')
        if paths:
            self.add_reprojection_sources(paths)

    def browse_reprojection_folder(self):
        path = QFileDialog.getExistingDirectory(self, 'Dossier des couches vectorielles')
        if path:
            self.add_reprojection_sources([path])

    def remove_reprojection_sources(self):
        for item in self.batch_sources.selectedItems():
            self.batch_sources.takeItem(self.batch_sources.row(item))
        self.invalidate_reprojection_inspection()

    def invalidate_reprojection_inspection(self, *_):
        self.batch_status.setText('Sources ou critères modifiés : analyser les couches pour actualiser les transformations.')

    def reprojection_configuration(self):
        sources = [self.batch_sources.item(i).data(Qt.ItemDataRole.UserRole)
                   for i in range(self.batch_sources.count())]
        if not sources:
            raise ValueError('Ajouter au moins un fichier ou un dossier source.')
        target = self.batch_target_crs.text().strip()
        if not target:
            raise ValueError('Renseigner le système de coordonnées cible du lot.')
        accuracy_text = self.batch_accuracy.text().strip()
        try:
            accuracy = float(accuracy_text) if accuracy_text else None
        except ValueError as exc:
            raise ValueError('La précision annoncée doit être un nombre strictement positif ; laisser vide pour ne pas imposer de seuil.') from exc
        if accuracy is not None and (not math.isfinite(accuracy) or accuracy <= 0):
            raise ValueError('La précision annoncée doit être un nombre strictement positif ; laisser vide pour ne pas imposer de seuil.')
        area_text = self.batch_aoi.text().strip()
        area = None
        if area_text:
            try:
                area = [float(value.strip()) for value in area_text.split(',')]
            except ValueError as exc:
                raise ValueError('Emprise : indiquer quatre nombres séparés par des virgules.') from exc
            if (len(area) != 4 or not all(math.isfinite(value) for value in area)
                    or not (-180 <= area[0] <= 180 and -180 <= area[2] <= 180)
                    or not -90 <= area[1] <= area[3] <= 90):
                raise ValueError('Emprise : ouest, sud, est, nord dans les limites des coordonnées géographiques.')
        parameters = dict(recursive=self.batch_recursive.isChecked(), accuracy=accuracy,
                          area_of_interest=area, allow_ballpark=self.batch_ballpark.isChecked())
        signature = json.dumps(dict(sources=sources, target_crs=target, **parameters), sort_keys=True)
        return sources, target, parameters, signature

    def inspect_reprojection_sources(self):
        window = self.window()
        if not hasattr(window, 'start') or not hasattr(window, 'thread'):
            self.batch_status.setText('Ouvrir cet outil dans la fenêtre Cartomize pour lancer l’analyse.')
            return
        if window.thread is not None:
            return
        self._batch_next_action = 'inspect'
        try:
            window.start()
            if window.worker is not None:
                window.worker.failed.connect(lambda message: self.batch_status.setText('Analyse interrompue : ' + message))
                window.worker.cancelled.connect(lambda: self.batch_status.setText('Analyse annulée.'))
        finally:
            self._batch_next_action = None

    def reprojection_inspection_job(self):
        sources, target, parameters, signature = self.reprojection_configuration()
        temporary = tempfile.TemporaryDirectory(prefix='cartomize-reprojection-')
        self._batch_preview_dirs.append(temporary)
        destination = Path(temporary.name) / 'inspection.json'
        self.batch_status.setText('Analyse des couches et des transformations en cours…')
        def run(progress, cancel):
            from . import ProcessingCancelled
            from .vector_reprojection import inspect_reprojection
            try:
                if cancel.is_set():
                    raise ProcessingCancelled()
                inspection = inspect_reprojection(sources, target, progress=progress, cancel=cancel, **parameters)
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
        """The normal window worker returns both inspection and batch manifests."""
        path = Path(path)
        if path.suffix.lower() != '.json':
            return
        record = json.loads(path.read_text(encoding='utf-8'))
        if record.get('schema') != INSPECTION_SCHEMA:
            return
        try:
            signature = self.reprojection_configuration()[3]
        except ValueError:
            signature = None
        if signature != record['signature']:
            self.batch_status.setText('Cette analyse correspond à des paramètres précédents. Analyser à nouveau les sources actuelles.')
            return
        previous = {self.batch_layers.item(i).data(Qt.ItemDataRole.UserRole)['id']:
                    (self.batch_layers.item(i).checkState(), self.batch_layers.item(i).data(Qt.ItemDataRole.UserRole).get('selected_operation'))
                    for i in range(self.batch_layers.count())}
        self.batch_layers.blockSignals(True)
        self.batch_layers.clear()
        for layer in record['inspection']['layers']:
            layer = deepcopy(layer)
            layer['inspection_signature'] = signature
            checked, selected = previous.get(layer['id'], (Qt.CheckState.Checked, None))
            layer['selected_operation'] = selected
            item = QListWidgetItem(f"{layer['name']} — {layer.get('source_crs') or 'SCR absent'}", self.batch_layers)
            item.setData(Qt.ItemDataRole.UserRole, layer)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(checked)
            item.setToolTip(str(layer.get('path', '')) + '\n' + str(layer.get('layer') or ''))
        self.batch_layers.blockSignals(False)
        self.batch_layers.setCurrentRow(0 if self.batch_layers.count() else -1)
        self.show_reprojection_layer()
        self.batch_status.setText(f'{self.batch_layers.count()} couche(s) analysée(s). Cocher les couches et vérifier leurs transformations avant de lancer le lot.')

    def show_reprojection_layer(self, *_):
        item = self.batch_layers.currentItem()
        self.batch_operation.blockSignals(True)
        self.batch_operation.clear()
        self.batch_operation.addItem('Automatique selon les critères', None)
        if item is None:
            self.batch_layer_details.clear()
            self.batch_operation_details.clear()
            self.batch_operation.setEnabled(False)
            self.batch_operation.blockSignals(False)
            return
        layer = item.data(Qt.ItemDataRole.UserRole)
        self.batch_layer_details.setText(f"{layer['name']}\n{layer.get('features', '?')} entité(s) · SCR source : {layer.get('source_crs') or 'absent'}\nEmprise source : {layer.get('bounds')}")
        operations = layer.get('catalogue', {}).get('operations', [])
        for operation in operations:
            accuracy = operation.get('accuracy')
            label = operation['description'] + (f' — {accuracy:g} m' if accuracy is not None else ' — précision inconnue')
            self.batch_operation.addItem(label, operation['id'])
            self.batch_operation.setItemData(self.batch_operation.count() - 1, label, Qt.ItemDataRole.ToolTipRole)
        selected = layer.get('selected_operation')
        index = self.batch_operation.findData(selected)
        if index < 0:
            self.batch_operation.addItem('Transformation enregistrée indisponible — choisir', selected)
            index = self.batch_operation.count() - 1
        self.batch_operation.setCurrentIndex(index)
        self.batch_operation.setEnabled(bool(operations))
        self.batch_operation.blockSignals(False)
        self.batch_operation.setToolTip(self.batch_operation.currentText())
        self.show_reprojection_operation_details()

    def select_reprojection_operation(self, *_):
        item = self.batch_layers.currentItem()
        if item is None:
            return
        layer = item.data(Qt.ItemDataRole.UserRole)
        layer['selected_operation'] = self.batch_operation.currentData()
        item.setData(Qt.ItemDataRole.UserRole, layer)
        self.show_reprojection_operation_details()

    def show_reprojection_operation_details(self):
        item = self.batch_layers.currentItem()
        if item is None:
            return
        layer = item.data(Qt.ItemDataRole.UserRole)
        catalogue = layer.get('catalogue', {})
        selected = layer.get('selected_operation')
        operations = catalogue.get('operations', [])
        operation = next((op for op in operations if op['id'] == selected), None) if selected else (operations[0] if operations else None)
        lines = []
        if operation:
            accuracy = operation.get('accuracy')
            lines = [operation['description'], 'Précision annoncée : ' + (f'{accuracy:g} m' if accuracy is not None else 'inconnue'),
                     'Transformation approximative : ' + ('oui' if operation.get('ballpark') else 'non')]
            if operation.get('area_of_use'):
                area = operation['area_of_use']
                lines.append('Domaine : ' + (str(area.get('name') or area.get('bounds') or area) if isinstance(area, dict) else str(area)))
            for grid in operation.get('grids', []):
                lines.append('Grille : ' + (str(grid.get('short_name') or grid.get('name') or grid) if isinstance(grid, dict) else str(grid)))
        else:
            lines.append('Aucune transformation utilisable. Vérifier le SCR, la précision demandée et les grilles disponibles.')
        if not catalogue.get('best_available', True):
            lines.append('Une grille de la meilleure transformation est absente. Le lot sera arrêté si cette transformation est exigée.')
        for unavailable in catalogue.get('unavailable_operations', []):
            lines.append('Indisponible : ' + str((unavailable.get('description') or unavailable.get('name') or unavailable) if isinstance(unavailable, dict) else unavailable))
            if isinstance(unavailable, dict):
                for grid in unavailable.get('grids', []):
                    if isinstance(grid, dict) and not grid.get('available', False):
                        lines.append('Grille absente : ' + str(grid.get('short_name') or grid.get('name') or grid))
        lines.extend(str(warning) for warning in catalogue.get('warnings', []))
        self.batch_operation_details.setPlainText('\n'.join(lines))

    def update_reprojection_controls(self):
        if not hasattr(self, 'batch_section'):
            return
        active = self.operation.currentData() == 'reproject_batch'
        self.batch_section.setVisible(active)
        self.source.setVisible(not active)
        self.form.labelForField(self.source).setVisible(not active)
        if active:
            previous_mode = self.output.mode
            self.output.mode = 'directory'
            self.output.filter = ''
            self.form.labelForField(self.output).setText('Répertoire parent des résultats')
            if previous_mode != 'directory' and Path(self.output.text()).suffix.lower() in {'.gpkg', '.geojson', '.json'}:
                self.output.edit.setText(str(Path(self.output.text()).parent))
            self.cancellable = True
        elif getattr(self, '_batch_mode_active', False):
            self.output.mode = 'save'
            self.output.filter = 'GeoPackage (*.gpkg);;GeoJSON (*.geojson)'
            self.form.labelForField(self.output).setText('Fichier de sortie')
            if self.output.text() and Path(self.output.text()).is_dir():
                self.output.edit.setText(str(Path(self.output.text()) / 'resultat.gpkg'))
            self.cancellable = False
        self._batch_mode_active = active

    def restore_reprojection_controls(self):
        # An older session stores its own combo entries. Retain that session's
        # selection while exposing the batch operation added by this release.
        if self.operation.findData('reproject_batch') < 0:
            self.operation.addItem('Reprojection vectorielle par lot', 'reproject_batch')
        self.update_reprojection_controls()
        self.batch_layers.setCurrentRow(0 if self.batch_layers.count() else -1)
        self.show_reprojection_layer()
        if self.batch_layers.count():
            self.batch_status.setText('Sélection du lot restaurée. Les transformations et les sources seront à nouveau contrôlées au lancement.')

    def reprojection_job(self, options):
        if self._batch_next_action == 'inspect':
            return self.reprojection_inspection_job()
        _, target, parameters, signature = self.reprojection_configuration()
        selected, operations = [], {}
        for row in range(self.batch_layers.count()):
            item = self.batch_layers.item(row)
            if item.checkState() != Qt.CheckState.Checked:
                continue
            layer = item.data(Qt.ItemDataRole.UserRole)
            if layer.get('inspection_signature') != signature:
                raise ValueError('Les sources ou les critères ont changé. Analyser à nouveau les couches.')
            candidates = layer.get('catalogue', {}).get('operations', [])
            choice = layer.get('selected_operation')
            if not candidates or (choice is not None and choice not in {op['id'] for op in candidates}):
                raise ValueError('Choisir une transformation disponible pour ' + layer['name'] + '.')
            selected.append({'path': layer['path'], 'layer': layer['layer']})
            if choice is not None:
                operations[layer['id']] = choice
        if not selected:
            raise ValueError('Analyser les sources et cocher au moins une couche à reprojeter.')
        folder = self.batch_folder.text().strip()
        if not folder:
            raise ValueError('Indiquer un nouveau dossier de résultats pour le lot.')
        destination = Path(self.destination()) / safe_name(folder)
        parameters.update(sources=selected, target_crs=target, recursive=False,
                          operations=operations or None, require_best=self.batch_require_best.isChecked(),
                          area_policy=self.batch_area_policy.currentData())
        parameters = deepcopy(parameters)
        def run(progress, cancel):
            execute_operation('vector.reproject_batch', parameters, destination, progress=progress, cancel=cancel)
            return destination / 'operation.json'
        return run
