"""Explicit vector quality controls on the existing desktop vector page."""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QSizePolicy)

from .desktop import PathField, VECTOR_FILTER, real
from .processing import execute_operation
from .recipes import safe_name


class VectorQualityControls:
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
        self.repair_collapsed = QCheckBox('Conserver lignes et points')
        self.repair_collapsed.setToolTip('Conserver les composantes réduites à une ligne ou un point lors de la réparation.')
        self.repair_collapsed.setChecked(True)
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
            ('Identifiant des entités (facultatif)', self.quality_id),
            ('Méthode de réparation', self.repair_method),
            ('Géométries manquantes', self.repair_missing),
            ('Géométries vides', self.repair_empty),
            ('Changements de type géométrique', self.repair_type_changes),
            ('Composantes effondrées', self.repair_collapsed),
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
        self.form.insertRow(self.form.rowCount() - 1, self.quality_note)
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

    def update_quality_controls(self):
        if not hasattr(self, '_quality_controls'):
            return
        op = self.operation.currentData()
        active = op in {key for _, key in self.QUALITY_OPERATIONS}
        repair = op == 'repair_geometries'
        topology = op == 'check_topology'
        duplicates = op == 'deduplicate'
        show = {
            self.quality_id: active, self.quality_folder: active,
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
        if operation != 'deduplicate':
            parameters['metric_crs'] = self.crs.text().strip() or None
        if operation == 'repair_geometries':
            parameters.update(method=self.repair_method.currentData(),
                              missing=self.repair_missing.currentData(),
                              empty=self.repair_empty.currentData(),
                              type_changes=self.repair_type_changes.currentData(),
                              keep_collapsed=self.repair_collapsed.isChecked())
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
