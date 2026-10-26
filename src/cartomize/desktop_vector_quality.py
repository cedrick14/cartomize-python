"""Explicit vector quality controls on the existing desktop vector page."""
import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QPushButton,
                               QSizePolicy, QVBoxLayout, QWidget)
from pyproj import CRS

from .desktop import PathField, VECTOR_FILTER, real
from .processing import execute_operation
from .recipes import safe_name


class VectorQualityControls:
    G01_OPERATIONS = {'audit_geometries', 'repair_geometries'}
    QUALITY_OPERATIONS = [
        ('Diagnostic détaillé des géométries', 'audit_geometries'),
        ('Réparation avec rapport des changements', 'repair_geometries'),
        ('Contrôle topologique', 'check_topology'),
        ('Traitement des doublons', 'deduplicate'),
    ]

    def init_quality_controls(self):
        self.operation.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.operation.setMinimumContentsLength(12)
        self.operation.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        def choices(items):
            control = QComboBox()
            control.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            control.setMinimumContentsLength(12)
            control.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            for label, value in items:
                control.addItem(label, value)
                control.setItemData(control.count() - 1, label, Qt.ItemDataRole.ToolTipRole)
            control.currentTextChanged.connect(control.setToolTip)
            control.setToolTip(control.currentText())
            return control

        self.quality_layer = choices([('Choisir une couche…', None)])
        self._quality_layer_source = None
        self._quality_layer_info = None
        self.quality_layer_note = QLabel('Choisir la couche à contrôler dans le fichier source.')
        self.quality_layer_note.setWordWrap(True)
        self.quality_id = QComboBox()
        self.quality_id.setEditable(True)
        self.quality_id.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.quality_id.setMinimumContentsLength(12)
        self.quality_id.setToolTip('Champ unique et renseigné ; vide : position de la ligne dans la source, à partir de zéro.')
        self.repair_method = choices([('Conserver les arêtes et sommets', 'linework'),
                                      ('Reconstruire les contours et trous', 'structure')])
        policies = [('Conserver et signaler', 'keep'), ('Écarter dans une couche séparée', 'drop'),
                    ('Interrompre le traitement', 'error')]
        self.repair_missing = choices(policies)
        self.repair_empty = choices(policies)
        self.repair_type_changes = choices([('Accepter et signaler', 'allow'),
                                           ('Écarter dans une couche séparée', 'drop'),
                                           ('Interrompre le traitement', 'error')])
        self.repair_collapsed = QCheckBox('Conserver\nlignes et\npoints')
        self.repair_collapsed.setToolTip('Conserver les composantes réduites à une ligne ou un point lors de la réparation.')
        self.repair_collapsed.setChecked(True)
        self.repair_tolerance = real(0)
        self.repair_tolerance.setMinimum(0)
        self.repair_tolerance.setSpecialValueText('Aucune grille')
        self.repair_tolerance.setToolTip('Pas de grille XY appliqué après la réparation GEOS, dans les unités du SCR source projeté. Zéro désactive la grille.')
        self.repair_grid_note = QLabel()
        self.repair_grid_note.setWordWrap(True)
        self.topology_rules = QListWidget()
        self.topology_rules.setWordWrap(True)
        self.topology_rules.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.topology_rules.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.topology_rules.setMaximumHeight(175)
        for title, rule in [('Géométries dupliquées', 'duplicates'),
                            ('Chevauchements', 'overlaps'),
                            ('Lacunes dans une emprise de référence', 'gaps'),
                            ('Dépassements de l’emprise de référence', 'outside'),
                            ('Extrémités de lignes non raccordées', 'dangles'),
                            ('Croisements de lignes non nœudés', 'crossings')]:
            item = QListWidgetItem(title, self.topology_rules)
            item.setToolTip(title)
            item.setData(Qt.ItemDataRole.UserRole, rule)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if rule in {'duplicates', 'overlaps'} else Qt.CheckState.Unchecked)
        self.topology_reference = PathField(filter=VECTOR_FILTER)
        self.topology_allowed_gaps = PathField(filter=VECTOR_FILTER)
        self.topology_tolerance = real(0)
        self.topology_tolerance.setMinimum(0)
        self.topology_min_area = real(0)
        self.topology_min_area.setMinimum(0)
        self.duplicate_keys = QLineEdit()
        self.duplicate_keys.setPlaceholderText('Exemple : parcelle, date ; vide si seule la géométrie est comparée')
        self.duplicate_geometry = choices([('Ne pas comparer la géométrie', 'none'),
                                           ('Géométrie strictement identique', 'exact'),
                                           ('Même géométrie, ordre des sommets indifférent', 'topological')])
        self.duplicate_keep = choices([('Conserver le premier enregistrement', 'first'),
                                       ('Conserver le dernier enregistrement', 'last'),
                                       ('Écarter tous les membres des groupes dupliqués', 'none')])
        self.duplicate_order = QLineEdit()
        self.duplicate_order.setPlaceholderText('Exemple : date ; vide : ordre des lignes sources')
        self.duplicate_ascending = QCheckBox('Ordre croissant')
        self.duplicate_ascending.setToolTip('Trier les champs choisis par ordre croissant avant de sélectionner le premier ou le dernier enregistrement.')
        self.duplicate_ascending.setChecked(True)
        self.duplicate_null_keys = choices([('Considérer chaque clé manquante comme distincte', 'distinct'),
                                            ('Regrouper les clés manquantes', 'match'),
                                            ('Refuser les clés manquantes', 'error')])
        self.quality_folder = QLineEdit('qualite_vectorielle')
        self.quality_note = QLabel()
        self.quality_note.setWordWrap(True)
        rows = [
            ('Couche du fichier source', self.quality_layer),
            ('Identifiant des entités (facultatif)', self.quality_id),
            ('Méthode de réparation', self.repair_method),
            ('Géométries manquantes', self.repair_missing),
            ('Géométries vides', self.repair_empty),
            ('Changements de type géométrique', self.repair_type_changes),
            ('Composantes effondrées', self.repair_collapsed),
            ('Pas de grille XY (SCR source)', self.repair_tolerance),
            ('Règles topologiques', self.topology_rules),
            ('Emprise de référence', self.topology_reference),
            ('Trous et lacunes légitimes', self.topology_allowed_gaps),
            ('Tolérance de raccordement des lignes (m)', self.topology_tolerance),
            ('Seuil de surface des anomalies (m²)', self.topology_min_area),
            ('Champs définissant un doublon', self.duplicate_keys),
            ('Comparaison géométrique', self.duplicate_geometry),
            ('Règle de conservation', self.duplicate_keep),
            ('Champs de tri', self.duplicate_order),
            ('Ordre du tri', self.duplicate_ascending),
            ('Clés de comparaison manquantes', self.duplicate_null_keys),
            ('Nouveau dossier des résultats', self.quality_folder),
        ]
        self._quality_controls = []
        for label, control in rows:
            self.form.insertRow(self.form.rowCount() - 1, label, control)
            self.form.labelForField(control).setWordWrap(True)
            self._quality_controls.append(control)
            if control is self.quality_layer:
                self.form.insertRow(self.form.rowCount() - 1, self.quality_layer_note)
            elif control is self.repair_tolerance:
                self.form.insertRow(self.form.rowCount() - 1, self.repair_grid_note)
        self.form.insertRow(self.form.rowCount() - 1, self.quality_note)
        # This path is captured by the existing session format. The views use
        # the completed bundle, even after controls have been edited again.
        self.quality_result_path = QLineEdit(self)
        self.quality_result_path.hide()
        self.quality_results = QWidget()
        result_layout = QVBoxLayout(self.quality_results)
        result_layout.setContentsMargins(0, 0, 0, 0)
        self.quality_result_status = QLabel('Lancer le diagnostic ou la réparation pour examiner les résultats.')
        self.quality_result_status.setWordWrap(True)
        result_layout.addWidget(self.quality_result_status)
        self.quality_issues_button = QPushButton('Anomalies')
        self.quality_report_button = QPushButton('Rapport')
        self.quality_compare_button = QPushButton('Comparer\navant / après')
        for button in (self.quality_issues_button, self.quality_report_button, self.quality_compare_button):
            button.setEnabled(False)
            result_layout.addWidget(button)
        self.quality_issues_button.clicked.connect(lambda: self.open_quality_product('issues'))
        self.quality_report_button.clicked.connect(lambda: self.open_quality_product('report'))
        self.quality_compare_button.clicked.connect(self.compare_quality_results)
        self.form.insertRow(self.form.rowCount() - 1, self.quality_results)
        for title, operation in self.QUALITY_OPERATIONS:
            self.operation.addItem(title, operation)
        for index in range(self.operation.count()):
            self.operation.setItemData(index, self.operation.itemText(index), Qt.ItemDataRole.ToolTipRole)
        self.operation.currentTextChanged.connect(self.operation.setToolTip)
        for row in range(self.form.rowCount()):
            item = self.form.itemAt(row, self.form.ItemRole.LabelRole)
            if item is not None and isinstance(item.widget(), QLabel):
                item.widget().setWordWrap(True)
        self.repair_method.currentIndexChanged.connect(self.update_quality_controls)
        self.quality_layer.currentIndexChanged.connect(self.refresh_quality_layer_fields)

    def refresh_quality_layers(self):
        """Choose a vector sublayer explicitly instead of GDAL's first layer."""
        import pyogrio
        source = self.source.text()
        selected = self.quality_layer.currentData() if source == self._quality_layer_source else None
        self._quality_layer_source = source
        self.quality_layer.blockSignals(True)
        self.quality_layer.clear()
        self.quality_layer.addItem('Choisir une couche…', None)
        failure = None
        if source and Path(source).is_file():
            try:
                for name, kind in pyogrio.list_layers(source):
                    if kind is not None:
                        self.quality_layer.addItem(str(name), str(name))
                        self.quality_layer.setItemData(self.quality_layer.count() - 1, str(name), Qt.ItemDataRole.ToolTipRole)
                index = self.quality_layer.findData(selected)
                self.quality_layer.setCurrentIndex(index if index > 0 else (1 if self.quality_layer.count() == 2 else 0))
            except (OSError, ValueError, RuntimeError) as exc:
                failure = str(exc)
        self.quality_layer.blockSignals(False)
        self.quality_layer.setToolTip(self.quality_layer.currentText())
        self.refresh_quality_layer_fields()
        if failure:
            self.quality_layer_note.setText('Lecture des couches impossible : ' + failure)

    def refresh_quality_layer_fields(self, *_):
        import pyogrio
        self._quality_layer_info = None
        previous = self.quality_id.currentText()
        fields = []
        failure = None
        source, layer = self.source.text(), self.quality_layer.currentData()
        if source and layer is not None and Path(source).is_file():
            try:
                self._quality_layer_info = pyogrio.read_info(source, layer=layer)
                fields = list(self._quality_layer_info['fields'])
            except (OSError, ValueError, RuntimeError) as exc:
                failure = str(exc)
        self.quality_id.blockSignals(True)
        self.quality_id.clear()
        self.quality_id.addItems(fields)
        self.quality_id.setCurrentText(previous if previous in fields else '')
        self.quality_id.blockSignals(False)
        info = self._quality_layer_info
        if info is None:
            self.quality_layer_note.setText('Lecture de la couche impossible : ' + failure if failure else
                'Choisir explicitement une couche du fichier. Les champs d’identifiant dépendent de cette sélection.')
            self.repair_grid_note.setText('La grille nécessite un SCR source projeté. Zéro conserve les coordonnées hors modifications de la réparation GEOS.')
            return
        self.quality_layer_note.setText(f"Couche : {layer} · {info.get('features', '?')} entité(s) · SCR : {info.get('crs') or 'absent'}. Choisir un identifiant unique et renseigné pour un suivi stable ; vide, le rapport utilise le rang source de cette exécution.")
        crs = CRS(info['crs']) if info.get('crs') else None
        if crs is not None and crs.is_projected:
            unit = crs.axis_info[0].unit_name if crs.axis_info else 'unité du SCR'
            unit = {'metre': 'mètre', 'foot': 'pied', 'US survey foot': 'pied d’arpentage US'}.get(unit, unit)
            self.repair_grid_note.setText(f'Unité de la grille : {unit}, dans le SCR source {crs.to_string()}. Le pas est appliqué après GEOS, avec suppression des composantes effondrées par la grille. Zéro désactive la grille. Le SCR des mesures ne change pas cette unité.')
        else:
            self.repair_grid_note.setText('Une grille positive exige un SCR source projeté. Choisir zéro ou reprojeter la couche au préalable. Le SCR projeté des mesures ne suffit pas.')

    def _quality_source_selection(self):
        import pyogrio
        if self.source.text() != self._quality_layer_source:
            self.refresh_quality_layers()
        layer = self.quality_layer.currentData()
        if layer is None:
            raise ValueError('Choisir la couche du fichier source à contrôler.')
        info = pyogrio.read_info(self.source.text(), layer=layer)
        identifier = self.quality_id.currentText().strip()
        if identifier and identifier not in info['fields']:
            raise ValueError('Choisir un identifiant appartenant à la couche sélectionnée.')
        if self.operation.currentData() == 'repair_geometries' and self.repair_tolerance.value() > 0:
            if not info.get('crs') or not CRS(info['crs']).is_projected:
                raise ValueError('Une grille XY positive exige un SCR source projeté ; le SCR des mesures ne modifie pas la source.')
        return layer

    def _quality_result_record(self):
        path = Path(self.quality_result_path.text())
        if not self.quality_result_path.text() or not path.is_file():
            return None
        try:
            record = json.loads(path.read_text(encoding='utf-8'))
        except (ValueError, OSError):
            return None
        if not isinstance(record, dict) or record.get('operation') not in {'vector.' + op for op in self.G01_OPERATIONS}:
            return None
        return record

    def update_quality_results(self):
        record = self._quality_result_record()
        products = record.get('products', {}) if record else {}
        def available(name):
            return bool(products.get(name) and Path(products[name]).is_file())
        self.quality_issues_button.setEnabled(available('issues'))
        self.quality_report_button.setEnabled(available('report'))
        self.quality_compare_button.setEnabled(bool(record and record['operation'] == 'vector.repair_geometries'
            and available('before') and available('data')))
        if record is None:
            self.quality_result_status.setText('Lancer le diagnostic ou la réparation pour examiner les résultats.')
            return
        title = 'Dernière réparation' if record['operation'] == 'vector.repair_geometries' else 'Dernier diagnostic'
        summary = {}
        if available('summary'):
            try:
                summary = json.loads(Path(products['summary']).read_text(encoding='utf-8'))
            except (OSError, ValueError):
                pass
        self.quality_result_status.setText(f"{title} : {summary.get('input_features', '?')} entité(s) en entrée, {summary.get('output_features', '?')} en sortie ; {summary.get('rejected_features', 0)} écartée(s), {summary.get('issue_features', '?')} anomalie(s). Le rapport détaille les identifiants, types et mesures avant/après.")
        window = self.window()
        if hasattr(window, 'workspace'):
            label = Path(self.quality_result_path.text()).parent.name
            repair = record['operation'] == 'vector.repair_geometries'
            names = {'before': 'Avant réparation' if repair else 'Avant contrôle', 'data': 'Après réparation' if repair else 'Couche contrôlée',
                     'issues': 'Anomalies initiales', 'report': 'Rapport détaillé', 'summary': 'Synthèse', 'rejected': 'Objets écartés'}
            for key, name in names.items():
                if available(key):
                    window.workspace.register(dict(data=products[key], name=f'{name} — {label}'))

    def open_quality_product(self, name):
        self.update_quality_results()
        record = self._quality_result_record()
        window = self.window()
        if record and hasattr(window, 'workspace'):
            path = record.get('products', {}).get(name)
            if path and Path(path).is_file():
                return window.workspace.open_result(path)

    def compare_quality_results(self):
        self.update_quality_results()
        record = self._quality_result_record()
        window = self.window()
        if record and self.quality_compare_button.isEnabled() and hasattr(window, 'workspace'):
            return window.workspace.compare(left=record['products']['before'], right=record['products']['data'])

    def show_result(self, path):
        path = Path(path)
        if path.suffix.lower() == '.json':
            record = json.loads(path.read_text(encoding='utf-8'))
            if isinstance(record, dict) and record.get('operation') in {'vector.' + op for op in self.G01_OPERATIONS}:
                self.quality_result_path.setText(str(path.resolve()))
                self.update_quality_results()
                return
        return super().show_result(path)

    def restore_quality_controls(self):
        self._quality_layer_source = self.source.text()
        self.update_quality_results()

    def update_quality_controls(self):
        if not hasattr(self, '_quality_controls'):
            return
        op = self.operation.currentData()
        active = op in {key for _, key in self.QUALITY_OPERATIONS}
        g01 = op in self.G01_OPERATIONS
        repair = op == 'repair_geometries'
        topology = op == 'check_topology'
        duplicates = op == 'deduplicate'
        show = {
            self.quality_id: active, self.quality_folder: active,
            self.quality_layer: g01, self.repair_tolerance: repair,
            self.repair_method: repair, self.repair_missing: repair,
            self.repair_empty: repair, self.repair_type_changes: repair,
            self.repair_collapsed: repair,
            self.topology_rules: topology, self.topology_reference: topology,
            self.topology_allowed_gaps: topology, self.topology_tolerance: topology,
            self.topology_min_area: topology,
            self.duplicate_keys: duplicates, self.duplicate_geometry: duplicates,
            self.duplicate_keep: duplicates, self.duplicate_order: duplicates,
            self.duplicate_ascending: duplicates, self.duplicate_null_keys: duplicates,
        }
        for widget, visible in show.items():
            widget.setVisible(visible)
            self.form.labelForField(widget).setVisible(visible)
        self.quality_note.setVisible(active)
        self.quality_layer_note.setVisible(g01)
        self.repair_grid_note.setVisible(repair)
        self.quality_results.setVisible(g01)
        if active:
            self.crs.setVisible(not duplicates)
            self.form.labelForField(self.crs).setVisible(not duplicates)
            self.form.labelForField(self.crs).setText('SCR projeté pour les mesures (si nécessaire)')
        linework = self.repair_method.currentData() == 'linework'
        self.repair_collapsed.setEnabled(not linework)
        if linework:
            self.repair_collapsed.setChecked(True)
        notes = {
            'audit_geometries': 'Le rapport décrit chaque entité. La couche d’anomalies facilite leur localisation. Les surfaces et longueurs nécessitent un SCR projeté adapté.',
            'repair_geometries': 'La réparation conserve les attributs et produit un rapport avant/après. Les objets écartés restent disponibles séparément. La méthode de reconstruction suppose que les contours et les trous sont correctement identifiés.',
            'check_topology': 'Les lacunes et dépassements exigent une emprise de référence. Les trous légitimes sont exclus des lacunes. La tolérance concerne le raccordement des lignes ; aucune géométrie n’est déplacée.',
            'deduplicate': 'Les champs et la géométrie sont comparés ensemble. Un enregistrement entier est conservé selon la règle choisie. Les dates distinctes restent distinctes si la date figure parmi les champs de comparaison.',
        }
        self.quality_note.setText(notes.get(op, ''))
        previous_mode = self.output.mode
        self.output.mode = 'directory' if active else 'save'
        self.output.filter = '' if active else 'GeoPackage (*.gpkg);;GeoJSON (*.geojson)'
        self.form.labelForField(self.output).setText('Répertoire parent des résultats' if active else 'Fichier de sortie')
        if self.output.text() and previous_mode != self.output.mode:
            previous = Path(self.output.text())
            if active and previous.suffix.lower() in {'.gpkg', '.geojson', '.json'}:
                self.output.edit.setText(str(previous.parent))
            elif not active and previous.is_dir():
                self.output.edit.setText(str(previous / 'resultat.gpkg'))
        self.cancellable = active

    def quality_job(self, options):
        operation = self.operation.currentData()
        source = self.source.text()
        if not source:
            raise ValueError('Sélectionner la couche source.')
        folder = self.quality_folder.text().strip()
        if not folder:
            raise ValueError('Indiquer un nouveau dossier de résultats.')
        destination = Path(self.destination()) / safe_name(folder)
        parameters = {'data': source, 'id_field': self.quality_id.currentText().strip() or None}
        if operation in self.G01_OPERATIONS:
            parameters['layer'] = self._quality_source_selection()
            parameters['id_field'] = self.quality_id.currentText().strip() or None
        if operation != 'deduplicate':
            parameters['metric_crs'] = self.crs.text().strip() or None
        if operation == 'repair_geometries':
            parameters.update(method=self.repair_method.currentData(),
                              missing=self.repair_missing.currentData(),
                              empty=self.repair_empty.currentData(),
                              type_changes=self.repair_type_changes.currentData(),
                              keep_collapsed=self.repair_collapsed.isChecked(),
                              tolerance=self.repair_tolerance.value())
        elif operation == 'check_topology':
            rules = [self.topology_rules.item(i).data(Qt.ItemDataRole.UserRole)
                     for i in range(self.topology_rules.count())
                     if self.topology_rules.item(i).checkState() == Qt.CheckState.Checked]
            if not rules:
                raise ValueError('Choisir au moins une règle topologique.')
            parameters.update(rules=rules, reference=self.topology_reference.text() or None,
                              allowed_gaps=self.topology_allowed_gaps.text() or None,
                              tolerance=self.topology_tolerance.value(),
                              min_area=self.topology_min_area.value())
        elif operation == 'deduplicate':
            keys = [key.strip() for key in self.duplicate_keys.text().split(',') if key.strip()]
            order = [key.strip() for key in self.duplicate_order.text().split(',') if key.strip()]
            parameters.update(keys=keys or None, geometry=self.duplicate_geometry.currentData(),
                              keep=self.duplicate_keep.currentData(), order_by=order or None,
                              ascending=self.duplicate_ascending.isChecked(),
                              null_keys=self.duplicate_null_keys.currentData())
            if not keys and parameters['geometry'] == 'none':
                raise ValueError('Choisir des champs de comparaison ou une comparaison géométrique.')

        def run(progress, cancel):
            execute_operation('vector.' + operation, parameters, destination,
                              progress=progress, cancel=cancel)
            return destination / 'operation.json'
        return run
