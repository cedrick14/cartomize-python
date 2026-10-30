"""Auditable attribute and spatial extraction on the vector desktop page."""
from copy import deepcopy
import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem,
                               QPlainTextEdit, QPushButton, QSizePolicy,
                               QWidget)

from .desktop import PathField, VECTOR_FILTER
from .processing import execute_operation
from .recipes import safe_name


COMPARISONS = [
    ('Égal à', 'eq'), ('Différent de', 'ne'), ('Supérieur à', 'gt'),
    ('Supérieur ou égal', 'ge'), ('Inférieur à', 'lt'), ('Inférieur ou égal', 'le'),
    ('Contient le texte', 'contains'), ('Commence par', 'starts_with'),
    ('Dans la liste', 'in'), ('Hors de la liste', 'not_in'),
    ('Valeur manquante', 'is_null'), ('Valeur renseignée', 'not_null'),
]
PREDICATES = [
    ('Intersecte', 'intersects'), ('Est à l’intérieur', 'within'),
    ('Contient', 'contains'), ('Couvre', 'covers'), ('Est couvert par', 'covered_by'),
    ('Touche', 'touches'), ('Chevauche', 'overlaps'), ('Croise', 'crosses'),
    ('Est disjoint', 'disjoint'),
]


def _combo(choices, *, editable=False):
    control = QComboBox()
    control.setEditable(editable)
    control.setMinimumContentsLength(8)
    control.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    control.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    for label, value in choices:
        control.addItem(label, value)
        control.setItemData(control.count() - 1, label, Qt.ItemDataRole.ToolTipRole)
    control.currentTextChanged.connect(control.setToolTip)
    control.setToolTip(control.currentText())
    return control


def _form(section):
    form = QFormLayout(section)
    form.setContentsMargins(0, 0, 0, 0)
    form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
    return form


def _row(form, title, control):
    label = QLabel(title)
    label.setWordWrap(True)
    form.addRow(label, control)


class SelectionControls:
    """Capture choices before starting the worker; retain completed products."""

    def init_selection_controls(self):
        self._selection_sources = {'source': None, 'mask': None}
        self._selection_info = None
        self._selection_loading = False
        self.selection_section = QWidget()
        form = _form(self.selection_section)
        self.selection_layer = _combo([('Choisir la couche', None)])
        self.selection_source_note = QLabel('Choisir une couche source pour afficher ses champs.')
        self.selection_source_note.setWordWrap(True)
        self.selection_id = _combo([('Rang source', None)])
        self.selection_id.setToolTip('Champ unique et renseigné, ou rang de la ligne source à partir de zéro.')
        self.selection_mode = _combo([('Attributs', 'attributes'), ('Espace', 'spatial'),
                                      ('Attributs et espace', 'combined')])
        for title, control in [('Couche du fichier source', self.selection_layer),
                               ('Identifiant de suivi', self.selection_id),
                               ('Critères de sélection', self.selection_mode)]:
            _row(form, title, control)
        form.insertRow(1, self.selection_source_note)

        self.selection_attribute_section = QWidget()
        attributes = _form(self.selection_attribute_section)
        self.selection_field = _combo([], editable=True)
        self.selection_comparison = _combo(COMPARISONS)
        self.selection_value = QPlainTextEdit()
        self.selection_value.setMinimumHeight(65)
        self.selection_value.setMaximumHeight(95)
        self.selection_value.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.selection_value_note = QLabel()
        self.selection_value_note.setWordWrap(True)
        self.selection_add = QPushButton('Ajouter le critère')
        self.selection_replace = QPushButton('Modifier le critère')
        self.selection_remove = QPushButton('Retirer le critère')
        self.selection_filters = QListWidget()
        self.selection_filters.setWordWrap(True)
        self.selection_filters.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.selection_filters.setMinimumWidth(0)
        self.selection_filters.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.selection_filters.setMinimumHeight(85)
        self.selection_filters.setMaximumHeight(160)
        self.selection_filters.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.selection_attribute_match = _combo([('Tous les critères (ET)', 'all'),
                                                 ('Au moins un (OU)', 'any')])
        for title, control in [('Champ', self.selection_field), ('Comparaison', self.selection_comparison),
                               ('Valeur recherchée', self.selection_value)]:
            _row(attributes, title, control)
        attributes.addRow(self.selection_value_note)
        attributes.addRow(self.selection_add)
        _row(attributes, 'Critères ajoutés', self.selection_filters)
        attributes.addRow(self.selection_replace)
        attributes.addRow(self.selection_remove)
        _row(attributes, 'Combiner les attributs', self.selection_attribute_match)
        form.addRow(self.selection_attribute_section)

        self.selection_spatial_section = QWidget()
        spatial = _form(self.selection_spatial_section)
        self.selection_mask = PathField(filter=VECTOR_FILTER)
        self.selection_mask_layer = _combo([('Choisir la couche', None)])
        self.selection_predicate = _combo(PREDICATES)
        self.selection_spatial_note = QLabel(
            'La relation compare chaque géométrie source à la réunion de toutes les géométries du masque. '
            'Les recouvrements du masque ne dupliquent pas les objets. Les géométries source vides ou '
            'manquantes ne satisfont aucune relation spatiale.')
        self.selection_spatial_note.setWordWrap(True)
        for title, control in [('Fichier du masque', self.selection_mask),
                               ('Couche du masque', self.selection_mask_layer),
                               ('Relation de la source au masque', self.selection_predicate)]:
            _row(spatial, title, control)
        spatial.addRow(self.selection_spatial_note)
        form.addRow(self.selection_spatial_section)
        self.selection_combination = _combo([('Les deux blocs (ET)', 'and'),
                                            ('Au moins un bloc (OU)', 'or')])
        _row(form, 'Combiner attributs et espace', self.selection_combination)
        self.selection_invert = QCheckBox('Inverser le résultat')
        self.selection_invert.setToolTip('Retenir le complément du résultat combiné final ; les décisions initiales restent dans le rapport.')
        form.addRow(self.selection_invert)
        self.selection_folder = QLineEdit('extraction_vectorielle')
        _row(form, 'Nouveau dossier des résultats', self.selection_folder)
        note = QLabel('Les objets retenus et exclus gardent leurs attributs, géométries et ordre source. '
                      'Le rapport indique les critères satisfaits et le motif de chaque décision. '
                      'Les rangs de ligne commencent à zéro. Le dossier de résultats doit être nouveau.')
        note.setWordWrap(True)
        form.addRow(note)

        self.selection_result_path = QLineEdit(self)
        self.selection_result_path.hide()
        self.selection_result_status = QLabel('Lancer l’extraction pour consulter les résultats.')
        self.selection_result_status.setWordWrap(True)
        form.addRow(self.selection_result_status)
        self.selection_data_button = QPushButton('Objets retenus')
        self.selection_rejected_button = QPushButton('Objets exclus')
        self.selection_report_button = QPushButton('Rapport détaillé')
        self.selection_summary_button = QPushButton('Bilan des sélections')
        for button, name in [(self.selection_data_button, 'data'),
                             (self.selection_rejected_button, 'rejected'),
                             (self.selection_report_button, 'report'),
                             (self.selection_summary_button, 'summary')]:
            button.setEnabled(False)
            button.clicked.connect(lambda checked=False, key=name: self.open_selection_product(key))
            form.addRow(button)
        self.form.insertRow(self.form.rowCount() - 1, self.selection_section)
        self.operation.addItem('Extraction avec bilan', 'extract_features')
        self.selection_mode.currentIndexChanged.connect(self.update_selection_controls)
        self.selection_layer.currentIndexChanged.connect(self.refresh_selection_fields)
        self.selection_comparison.currentIndexChanged.connect(self.update_selection_value)
        self.selection_field.currentTextChanged.connect(self.update_selection_value)
        self.selection_filters.currentRowChanged.connect(self.edit_selection_filter)
        self.selection_add.clicked.connect(self.add_selection_filter)
        self.selection_replace.clicked.connect(self.replace_selection_filter)
        self.selection_remove.clicked.connect(self.remove_selection_filter)
        self.selection_mask.edit.editingFinished.connect(self.refresh_selection_layers)
        self.selection_mask.edit.textChanged.connect(lambda *_: self._fields_timer.start())
        self.update_selection_value()
        self.update_selection_controls()

    def refresh_selection_layers(self, *_):
        if not hasattr(self, 'selection_layer') or self._selection_loading:
            return
        import pyogrio
        for key, path, control in [('source', self.source.text(), self.selection_layer),
                                    ('mask', self.selection_mask.text(), self.selection_mask_layer)]:
            previous = control.currentData() if path == self._selection_sources[key] else None
            self._selection_sources[key] = path
            control.blockSignals(True)
            control.clear()
            control.addItem('Choisir la couche', None)
            if path and Path(path).is_file():
                try:
                    for name, kind in pyogrio.list_layers(path):
                        if kind is not None:
                            control.addItem(str(name), str(name))
                            control.setItemData(control.count() - 1, str(name), Qt.ItemDataRole.ToolTipRole)
                    index = control.findData(previous)
                    control.setCurrentIndex(index if index > 0 else (1 if control.count() == 2 else 0))
                except (OSError, ValueError, RuntimeError):
                    pass
            control.blockSignals(False)
            control.setToolTip(control.currentText())
        self.refresh_selection_fields()

    def refresh_selection_fields(self, *_):
        if self._selection_loading:
            return
        import pyogrio
        self._selection_info = None
        source, layer = self.source.text(), self.selection_layer.currentData()
        failure = None
        if source and layer is not None and Path(source).is_file():
            try:
                self._selection_info = pyogrio.read_info(source, layer=layer)
            except (OSError, ValueError, RuntimeError) as exc:
                failure = str(exc)
        fields = list(self._selection_info['fields']) if self._selection_info else []
        previous_field, previous_id = self.selection_field.currentText(), self.selection_id.currentData()
        self.selection_field.blockSignals(True)
        self.selection_field.clear()
        self.selection_field.addItems(fields)
        self.selection_field.setCurrentText(previous_field if previous_field in fields else (fields[0] if fields else ''))
        self.selection_field.blockSignals(False)
        self.selection_id.blockSignals(True)
        self.selection_id.clear()
        self.selection_id.addItem('Rang source', None)
        for field in fields:
            self.selection_id.addItem(field, field)
        self.selection_id.setCurrentIndex(max(0, self.selection_id.findData(previous_id)))
        self.selection_id.blockSignals(False)
        info = self._selection_info
        self.selection_source_note.setText(
            f"Couche : {layer} · {info.get('features', '?')} objet(s) · SCR : {info.get('crs') or 'absent'}."
            if info else ('Lecture impossible : ' + failure if failure else
                         'Choisir explicitement la couche du fichier source. Les champs dépendent de cette sélection.'))
        self.update_selection_value()

    def _selection_field_type(self, field):
        info = self._selection_info
        if info is None or field not in info['fields']:
            return None
        return str(info['dtypes'][list(info['fields']).index(field)])

    def update_selection_value(self, *_):
        comparison = self.selection_comparison.currentData()
        null = comparison in {'is_null', 'not_null'}
        membership = comparison in {'in', 'not_in'}
        self.selection_value.setEnabled(not null)
        field_type = self._selection_field_type(self.selection_field.currentText())
        if null:
            note = 'Ce critère ne demande aucune valeur.'
        elif field_type == 'bool':
            note = 'Saisir true ou false.'
        elif field_type and 'datetime64' in field_type:
            note = 'Date : AAAA-MM-JJ. Date et heure : format ISO, par exemple 2026-10-30T08:30:00.'
        else:
            note = 'Saisir la valeur exacte, sans guillemets. Les nombres ne sont pas arrondis.'
        if membership and not null:
            note += ' Pour une liste, saisir une valeur par ligne.'
        self.selection_value_note.setText(note)
        self.selection_value.setPlaceholderText('Une valeur par ligne' if membership else 'Valeur exacte')

    def _selection_editor_filter(self):
        field = self.selection_field.currentText().strip()
        if not self._selection_info or field not in self._selection_info['fields']:
            raise ValueError('Choisir un champ de la couche source sélectionnée.')
        comparison = self.selection_comparison.currentData()
        value = None
        if comparison not in {'is_null', 'not_null'}:
            text = self.selection_value.toPlainText()
            values = text.splitlines() if comparison in {'in', 'not_in'} else [text]
            if comparison in {'in', 'not_in'} and not values:
                raise ValueError('Saisir au moins une valeur dans la liste, une par ligne.')
            if self._selection_field_type(field) == 'bool' and comparison not in {'contains', 'starts_with'}:
                if any(item.strip().casefold() not in {'true', 'false'} for item in values):
                    raise ValueError('Un champ booléen demande true ou false.')
                values = [item.strip().casefold() == 'true' for item in values]
            # Numeric text is deliberately kept intact. The core validates and
            # compares exact decimal thresholds without a float intermediary.
            value = values if comparison in {'in', 'not_in'} else values[0]
        return dict(field=field, comparison=comparison, value=value)

    @staticmethod
    def _selection_filter_label(record):
        title = dict((value, label) for label, value in COMPARISONS)[record['comparison']]
        value = record.get('value')
        rendered = json.dumps(value, ensure_ascii=False) if value is not None else ''
        return f"{record['field']} · {title}" + (f' · {rendered}' if rendered else '')

    def _selection_editor_action(self, replace=False):
        try:
            record = self._selection_editor_filter()
        except ValueError as exc:
            self.selection_value_note.setText(str(exc))
            return False
        item = self.selection_filters.currentItem() if replace else None
        if replace and item is None:
            self.selection_value_note.setText('Choisir un critère ajouté à modifier.')
            return False
        if item is None:
            item = QListWidgetItem(self.selection_filters)
        item.setText(self._selection_filter_label(record))
        item.setToolTip(item.text())
        item.setData(Qt.ItemDataRole.UserRole, record)
        self.selection_filters.setCurrentItem(item)
        self.update_selection_value()
        return True

    def add_selection_filter(self):
        return self._selection_editor_action()

    def replace_selection_filter(self):
        return self._selection_editor_action(replace=True)

    def remove_selection_filter(self):
        row = self.selection_filters.currentRow()
        if row >= 0:
            self.selection_filters.takeItem(row)

    def edit_selection_filter(self, row):
        if row < 0:
            return
        record = self.selection_filters.item(row).data(Qt.ItemDataRole.UserRole)
        self.selection_field.setCurrentText(record['field'])
        self.selection_comparison.setCurrentIndex(self.selection_comparison.findData(record['comparison']))
        value = record.get('value')
        values = value if isinstance(value, list) else [value]
        self.selection_value.setPlainText('\n'.join(
            'true' if item is True else 'false' if item is False else str(item) if item is not None else ''
            for item in values))

    def update_selection_controls(self, *_):
        if not hasattr(self, 'selection_section'):
            return
        active = self.operation.currentData() == 'extract_features'
        self.selection_section.setVisible(active)
        mode = self.selection_mode.currentData()
        self.selection_attribute_section.setVisible(mode != 'spatial')
        self.selection_spatial_section.setVisible(mode != 'attributes')
        self.selection_combination.setVisible(mode == 'combined')
        self.selection_section.layout().labelForField(self.selection_combination).setVisible(mode == 'combined')
        if not active:
            return
        self.cancellable = True
        previous_mode = self.output.mode
        self.output.mode = 'directory'
        self.output.filter = ''
        self.form.labelForField(self.output).setText('Répertoire parent des résultats')
        if self.output.text() and previous_mode != 'directory':
            previous = Path(self.output.text())
            if previous.suffix.lower() in {'.gpkg', '.geojson', '.json'}:
                self.output.edit.setText(str(previous.parent))

    def selection_job(self, options):
        source = self.source.text()
        if not source:
            raise ValueError('Choisir le fichier source.')
        if source != self._selection_sources['source'] or self.selection_mask.text() != self._selection_sources['mask']:
            self.refresh_selection_layers()
        layer = self.selection_layer.currentData()
        if layer is None or self._selection_info is None:
            raise ValueError('Choisir explicitement la couche source.')
        mode = self.selection_mode.currentData()
        filters = [deepcopy(self.selection_filters.item(i).data(Qt.ItemDataRole.UserRole))
                   for i in range(self.selection_filters.count())] if mode != 'spatial' else None
        if mode != 'spatial' and not filters:
            raise ValueError('Ajouter au moins un critère attributaire.')
        if filters and any(record['field'] not in self._selection_info['fields'] for record in filters):
            raise ValueError('Un critère utilise un champ absent de la couche source ; modifier ou retirer ce critère.')
        mask, mask_layer = None, None
        if mode != 'attributes':
            mask, mask_layer = self.selection_mask.text(), self.selection_mask_layer.currentData()
            if not mask or mask_layer is None:
                raise ValueError('Choisir le fichier et explicitement la couche du masque.')
        folder = self.selection_folder.text().strip()
        if not folder:
            raise ValueError('Indiquer un nouveau dossier de résultats.')
        destination = Path(self.destination()) / safe_name(folder)
        parameters = dict(data=source, layer=layer, filters=filters,
                          attribute_match=self.selection_attribute_match.currentData(),
                          mask=mask, mask_layer=mask_layer,
                          predicate=self.selection_predicate.currentData(),
                          combination=self.selection_combination.currentData(),
                          invert=self.selection_invert.isChecked(), id_field=self.selection_id.currentData())

        def run(progress, cancel):
            execute_operation('vector.extract_features', parameters, destination,
                              progress=progress, cancel=cancel)
            return destination / 'operation.json'
        return run

    def _selection_result_record(self):
        text = self.selection_result_path.text()
        if not text or not Path(text).is_file():
            return None
        try:
            record = json.loads(Path(text).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return None
        return record if isinstance(record, dict) and record.get('operation') == 'vector.extract_features' else None

    def update_selection_results(self):
        record = self._selection_result_record()
        products = record.get('products', {}) if record else {}
        def available(key):
            return bool(products.get(key) and Path(products[key]).is_file())
        for button, key in [(self.selection_data_button, 'data'),
                            (self.selection_rejected_button, 'rejected'),
                            (self.selection_report_button, 'report'),
                            (self.selection_summary_button, 'summary')]:
            button.setEnabled(available(key))
        if record is None:
            self.selection_result_status.setText('Lancer l’extraction pour consulter les résultats.')
            return
        summary = {}
        if available('summary'):
            try:
                summary = json.loads(Path(products['summary']).read_text(encoding='utf-8'))
            except (OSError, ValueError):
                pass
        self.selection_result_status.setText(
            f"Dernière extraction : {summary.get('input_features', '?')} objet(s), "
            f"{summary.get('selected_features', summary.get('output_features', '?'))} retenu(s), "
            f"{summary.get('rejected_features', '?')} exclu(s). Le rapport détaille chaque décision.")
        window = self.window()
        if hasattr(window, 'workspace'):
            label = Path(self.selection_result_path.text()).parent.name
            for key, title in [('data', 'Objets retenus'), ('rejected', 'Objets exclus'),
                               ('report', 'Décisions détaillées'), ('audit', 'Audit des décisions'),
                               ('summary', 'Bilan des sélections')]:
                if available(key):
                    window.workspace.register(dict(data=products[key], name=f'{title} — {label}'))

    def open_selection_product(self, key):
        self.update_selection_results()
        record, window = self._selection_result_record(), self.window()
        if record and hasattr(window, 'workspace'):
            path = record.get('products', {}).get(key)
            if path and Path(path).is_file():
                return window.workspace.open_result(path)

    def show_result(self, path):
        path = Path(path)
        if path.suffix.lower() == '.json':
            record = json.loads(path.read_text(encoding='utf-8'))
            if isinstance(record, dict) and record.get('operation') == 'vector.extract_features':
                self.selection_result_path.setText(str(path.resolve()))
                self.update_selection_results()
                return
        return super().show_result(path)

    def restore_selection_controls(self):
        self._selection_sources = {'source': self.source.text(), 'mask': self.selection_mask.text()}
        # Dormant controls remain byte-for-byte session state until the user
        # returns to G07; refreshing them during a G01 restore changes choices
        # that were never inspected by the extraction tool.
        if self.operation.currentData() == 'extract_features':
            self.refresh_selection_layers()
        self.update_selection_controls()
        self.update_selection_results()
