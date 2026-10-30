"""Review and convert vector or raster data through the normal desktop worker."""
from copy import deepcopy
import json
import math
from pathlib import Path
import re
import tempfile

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QFormLayout, QHeaderView, QLabel,
                               QLineEdit, QPushButton, QSizePolicy, QTableWidget,
                               QTableWidgetItem, QWidget)

from .desktop import Page, PathField, RASTER_FILTER, VECTOR_FILTER
from .processing import execute_operation
from .recipes import safe_name


INSPECTION_SCHEMA = 'cartomize.desktop.conversion-inspection.v1'
VECTOR_FORMATS = [('GeoPackage', 'GPKG'), ('GeoJSON', 'GeoJSON'),
                  ('Shapefile', 'ESRI Shapefile'), ('FlatGeobuf', 'FlatGeobuf')]
RASTER_FORMATS = [('GeoTIFF', 'GTiff'), ('GeoTIFF optimisé (COG)', 'COG')]
LOSS_POLICIES = [('Interrompre si une perte est détectée', 'error'),
                 ('Accepter et consigner les pertes', 'report')]


def _combo(choices, selected=None, *, editable=False):
    control = QComboBox()
    control.setEditable(editable)
    control.setMinimumContentsLength(8)
    control.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    control.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    for label, value in choices:
        control.addItem(label, value)
    if selected is not None:
        control.setCurrentIndex(control.findData(selected))
    control.setToolTip(control.currentText())
    control.currentTextChanged.connect(control.setToolTip)
    return control


def _form(section):
    form = QFormLayout(section)
    form.setContentsMargins(0, 0, 0, 0)
    form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
    return form


def _row(form, title, control):
    caption = QLabel(title)
    caption.setWordWrap(True)
    form.addRow(caption, control)


class ConversionPage(Page):
    """All decisions live in ordinary, session-persisted widgets."""

    engine = False
    cancellable = True

    def __init__(self):
        super().__init__('Conversion et formats',
                         'Convertir une couche ou un raster, puis vérifier les données relues et consulter le rapport.')
        self._loading = True
        self._next_action = None
        self._preview_dirs = []
        self._current_layer_index = -1
        self.kind = _combo([('Couche vectorielle', 'vector'), ('Raster', 'raster')])
        self.source = PathField(filter=VECTOR_FILTER)
        self.inspect_button = QPushButton('Analyser la source')
        self.inspect_button.clicked.connect(self.inspect_source)
        self.inspection_status = QLabel('Choisir une source, puis analyser ses couches et ses propriétés.')
        self.inspection_status.setWordWrap(True)
        for title, control in [('Type de données', self.kind), ('Fichier source', self.source)]:
            _row(self.form, title, control)
        self.form.addRow(self.inspect_button)
        self.form.addRow(self.inspection_status)

        self.vector_section = QWidget()
        vector = _form(self.vector_section)
        self.layer = _combo([])
        # Qt includes the placeholder in the minimum width, even after selection.
        self.layer.setPlaceholderText('Choisir la couche')
        self.layer.setEnabled(False)
        self.vector_driver = _combo(VECTOR_FORMATS)
        self.encoding = _combo([(value, value) for value in ('UTF-8', 'CP1252', 'ISO-8859-1')], editable=True)
        self.output_layer = QLineEdit('features')
        self.field_map = QTableWidget(0, 2)
        self.field_map.setHorizontalHeaderLabels(['Champ source', 'Nom de sortie'])
        self.field_map.verticalHeader().hide()
        self.field_map.setMinimumWidth(0)
        self.field_map.setMinimumHeight(110)
        self.field_map.setMaximumHeight(220)
        self.field_map.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.field_map.horizontalHeader().setMinimumSectionSize(60)
        self.field_map.horizontalHeader().setMinimumHeight(36)
        self.field_map.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.field_map.setHorizontalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        self.field_map.setToolTip('Renommer un champ dans la colonne de droite. Tous les champs sont conservés.')
        for title, control in [('Couche à convertir', self.layer), ('Format vectoriel', self.vector_driver),
                               ('Encodage des caractères', self.encoding), ('Nom de la couche de sortie', self.output_layer),
                               ('Noms des champs', self.field_map)]:
            _row(vector, title, control)
        self.vector_note = QLabel('Shapefile : vérifier les noms de champs et le rapport.')
        self.vector_note.setWordWrap(True)
        vector.addRow(self.vector_note)
        self.add_help('Tous les objets et champs sont conservés. Pour un Shapefile, choisir des noms de champs compatibles et examiner le rapport.',
            subject='Champs et formats vectoriels',form=vector)
        self.form.addRow(self.vector_section)

        self.raster_section = QWidget()
        raster = _form(self.raster_section)
        self.raster_driver = _combo(RASTER_FORMATS)
        self.dtype = _combo([('Conserver le type source', None)] + [(value, value) for value in
            ('uint8', 'int8', 'uint16', 'int16', 'uint32', 'int32', 'uint64', 'int64', 'float32', 'float64')])
        self.nodata_mode = _combo([('Conserver le NoData source', 'preserve'),
                                   ('Sans valeur NoData', 'none'), ('Définir une valeur', 'value')])
        self.nodata_value = QLineEdit()
        self.nodata_value.setPlaceholderText('Exemple : -9999 ; nan pour une valeur manquante flottante')
        self.compression = _combo([('LZW', 'lzw'), ('Deflate', 'deflate'), ('Zstandard', 'zstd'), ('Sans compression', 'none')])
        self.tile_size = _combo([(str(value), value) for value in (128, 256, 512, 1024)], 512)
        self.overviews_mode = _combo([('Conserver les niveaux source', 'preserve'),
                                      ('Aucun niveau', 'none'), ('Définir les facteurs', 'custom')])
        self.overviews = QLineEdit('2, 4, 8, 16')
        self.overviews.setPlaceholderText('Facteurs entiers séparés par des virgules')
        self.resampling = _combo([('Plus proche voisin', 'nearest'), ('Bilinéaire', 'bilinear'),
                                  ('Cubique', 'cubic'), ('Moyenne', 'average'), ('Valeur majoritaire', 'mode')])
        for title, control in [('Format raster', self.raster_driver), ('Type numérique', self.dtype),
                               ('Valeurs manquantes', self.nodata_mode), ('Valeur NoData', self.nodata_value),
                               ('Compression', self.compression), ('Taille des blocs (pixels)', self.tile_size),
                               ('Pyramides de résolution', self.overviews_mode), ('Facteurs des pyramides', self.overviews),
                               ('Rééchantillonnage des pyramides', self.resampling)]:
            _row(raster, title, control)
        self.add_help('La grille et les coordonnées sont conservées. Le rééchantillonnage concerne les pyramides ; choisir le plus proche voisin ou la valeur majoritaire pour des classes.',
            subject='Grille et pyramides',summary='Classes : plus proche voisin ou valeur majoritaire.',form=raster)
        self.form.addRow(self.raster_section)

        self.loss_policy = _combo(LOSS_POLICIES)
        _row(self.form, 'Différences détectées après conversion', self.loss_policy)
        self.output.mode = 'directory'
        self.output.filter = ''
        self.folder = QLineEdit('conversion_donnees')
        _row(self.form, 'Répertoire parent des résultats', self.output)
        _row(self.form, 'Nouveau dossier des résultats', self.folder)
        self.result_status = QLabel('')
        self.result_status.setWordWrap(True)
        self.form.addRow(self.result_status)
        self.report_button = QPushButton('Ouvrir le rapport')
        self.data_button = QPushButton('Afficher les données')
        self.report_button.clicked.connect(lambda: self.open_product(self.converted_report.text()))
        self.data_button.clicked.connect(lambda: self.open_product(self.converted_data.text()))
        self.form.addRow(self.report_button)
        self.form.addRow(self.data_button)
        # Persist result references alongside the existing page widgets.
        self.converted_data = QLineEdit(self)
        self.converted_report = QLineEdit(self)
        self.converted_data.hide()
        self.converted_report.hide()
        self.layout.addStretch()
        self.kind.currentIndexChanged.connect(self.changed)
        self.source.edit.textChanged.connect(self.invalidate_source)
        self.layer.currentIndexChanged.connect(self.select_layer)
        self.vector_driver.currentIndexChanged.connect(self.changed)
        self.nodata_mode.currentIndexChanged.connect(self.changed)
        self.overviews_mode.currentIndexChanged.connect(self.changed)
        self._loading = False
        self.changed()
        self._update_result_buttons()

    def changed(self, *_):
        if self._loading:
            return
        vector = self.kind.currentData() == 'vector'
        self.source.filter = VECTOR_FILTER if vector else RASTER_FILTER
        self.vector_section.setVisible(vector)
        self.raster_section.setVisible(not vector)
        shapefile = self.vector_driver.currentData() == 'ESRI Shapefile'
        self.encoding.setEnabled(shapefile)
        if not shapefile:
            self.encoding.setCurrentText('UTF-8')
        form = self.raster_section.layout()
        for widget, visible in ((self.nodata_value, self.nodata_mode.currentData() == 'value'),
                                (self.overviews, self.overviews_mode.currentData() == 'custom')):
            widget.setVisible(visible)
            form.labelForField(widget).setVisible(visible)
        self.resampling.setEnabled(self.overviews_mode.currentData() != 'none')

    def invalidate_source(self, *_):
        if not self._loading:
            self.inspection_status.setText('Source modifiée : analyser ses couches avant la conversion vectorielle.')

    def source_configuration(self):
        source = self.source.text()
        if not source:
            raise ValueError('Choisir le fichier source à convertir.')
        path = Path(source).expanduser().resolve()
        # Keep source paths as structured values so portable sessions can
        # relocate them together with the source widget and result references.
        signature = dict(source=str(path), kind=self.kind.currentData())
        return str(path), self.kind.currentData(), signature

    def _selected_layer(self):
        data = self.layer.currentData()
        return data if isinstance(data, dict) else None

    def _store_mapping(self):
        if self._loading or self._current_layer_index < 0:
            return
        item = self.layer.itemData(self._current_layer_index)
        if not isinstance(item, dict):
            return
        item['mapping'] = {self.field_map.item(row, 0).text(): self.field_map.item(row, 1).text()
                           for row in range(self.field_map.rowCount())}
        self.layer.setItemData(self._current_layer_index, item)

    def select_layer(self, *_):
        if self._loading:
            return
        self._store_mapping()
        self._current_layer_index = self.layer.currentIndex()
        self.field_map.setRowCount(0)
        selected = self._selected_layer()
        if not selected:
            return
        mapping = selected.get('mapping', {})
        for row, field in enumerate(selected.get('fields', [])):
            self.field_map.insertRow(row)
            source = QTableWidgetItem(field['name'])
            source.setFlags(source.flags() & ~Qt.ItemFlag.ItemIsEditable)
            source.setToolTip(f"{field['name']} · {field.get('dtype') or field.get('type') or ''}")
            self.field_map.setItem(row, 0, source)
            self.field_map.setItem(row, 1, QTableWidgetItem(mapping.get(field['name'], field['name'])))
        self.field_map.resizeRowsToContents()
        self.field_map.resizeColumnsToContents()
        if not selected.get('fields_loaded'):
            self.inspection_status.setText('Couche sélectionnée : analyser la source pour examiner ses champs.')

    def field_mapping(self):
        mapping = {}
        targets = set()
        for row in range(self.field_map.rowCount()):
            source = self.field_map.item(row, 0).text()
            target = self.field_map.item(row, 1).text().strip()
            if not target or target.casefold() in targets:
                raise ValueError('Chaque champ de sortie doit avoir un nom non vide et unique.')
            targets.add(target.casefold())
            if source != target:
                mapping[source] = target
        return mapping or None

    def raster_parameters(self):
        mode = self.nodata_mode.currentData()
        nodata = 'preserve' if mode == 'preserve' else None
        if mode == 'value':
            value = self.nodata_value.text().strip()
            try:
                if value.casefold() == 'nan':
                    nodata = 'nan'
                elif re.fullmatch(r'[+-]?\d+', value):
                    nodata = int(value)
                else:
                    nodata = float(value)
                    if not math.isfinite(nodata):
                        raise ValueError()
            except (ValueError, OverflowError) as exc:
                raise ValueError('Renseigner une valeur NoData numérique ou nan.') from exc
        mode = self.overviews_mode.currentData()
        overviews = None if mode == 'preserve' else []
        if mode == 'custom':
            try:
                overviews = [int(value.strip()) for value in self.overviews.text().split(',')]
            except ValueError as exc:
                raise ValueError('Les facteurs des pyramides doivent être des entiers séparés par des virgules.') from exc
            if not overviews or any(value < 2 for value in overviews) or len(set(overviews)) != len(overviews):
                raise ValueError('Choisir des facteurs de pyramides distincts, tous supérieurs ou égaux à 2.')
            overviews = sorted(overviews)
        return dict(driver=self.raster_driver.currentData(), dtype=self.dtype.currentData(), nodata=nodata,
                    compression=self.compression.currentData(), block_size=self.tile_size.currentData(),
                    overviews=overviews, resampling=self.resampling.currentData())

    def inspection_configuration(self):
        source, kind, signature = self.source_configuration()
        if kind == 'vector':
            selected = self._selected_layer()
            current = selected and selected.get('source_signature') == signature
            parameters = dict(layer=selected['name'] if current else None,
                              driver=self.vector_driver.currentData(), encoding=self.encoding.currentText().strip(),
                              field_map=self.field_mapping() if current and selected.get('fields_loaded') else None)
        else:
            parameters = self.raster_parameters()
            parameters = {key: parameters[key] for key in ('driver', 'dtype', 'nodata', 'compression')}
        request = json.dumps(dict(source=source, kind=kind, parameters=parameters), sort_keys=True, allow_nan=False)
        return source, kind, signature, parameters, request

    def inspect_source(self):
        window = self.window()
        if not hasattr(window, 'start') or not hasattr(window, 'thread'):
            self.inspection_status.setText('Ouvrir cet outil dans la fenêtre Cartomize pour analyser la source.')
            return
        if window.thread is not None:
            return
        self._next_action = 'inspect'
        try:
            window.start()
            if window.worker is not None:
                window.worker.failed.connect(lambda message: self.inspection_status.setText('Analyse interrompue : ' + message))
                window.worker.cancelled.connect(lambda: self.inspection_status.setText('Analyse annulée.'))
        finally:
            self._next_action = None

    def inspection_job(self):
        source, kind, signature, parameters, request = self.inspection_configuration()
        temporary = tempfile.TemporaryDirectory(prefix='cartomize-conversion-')
        self._preview_dirs.append(temporary)
        destination = Path(temporary.name) / 'inspection.json'
        self.inspection_status.setText('Analyse de la source en cours…')
        def run(progress, cancel):
            from . import ProcessingCancelled
            try:
                if cancel.is_set():
                    raise ProcessingCancelled()
                if kind == 'vector':
                    from .vector_conversion import inspect_vector_conversion
                    inspection = inspect_vector_conversion(source, **parameters)
                else:
                    from .raster_conversion import inspect_raster_conversion
                    inspection = inspect_raster_conversion(source, **parameters)
                if cancel.is_set():
                    raise ProcessingCancelled()
                destination.write_text(json.dumps(dict(schema=INSPECTION_SCHEMA, source_signature=signature,
                    request=request, kind=kind, inspection=inspection), ensure_ascii=False, indent=2,
                    allow_nan=False) + '\n', encoding='utf-8')
                progress(1, 1)
                return destination
            except Exception:
                temporary.cleanup()
                raise
        return run

    def _show_inspection(self, record):
        try:
            current_request = self.inspection_configuration()[-1]
        except ValueError:
            current_request = None
        if record.get('request') != current_request:
            self.inspection_status.setText('Cette analyse correspond à des paramètres précédents. Analyser à nouveau la source.')
            return
        inspection = record['inspection']
        if record['kind'] == 'vector':
            self._store_mapping()
            previous = {self.layer.itemData(index)['name']: self.layer.itemData(index)
                        for index in range(self.layer.count())
                        if isinstance(self.layer.itemData(index), dict)
                        and self.layer.itemData(index).get('source_signature') == record['source_signature']}
            selected_name = inspection.get('selected_layer')
            self._loading = True
            self.layer.clear()
            selected_index = -1
            for layer in inspection['layers']:
                data = {**deepcopy(previous.get(layer['name'], {})), **deepcopy(layer),
                        'source_signature': record['source_signature']}
                if layer['name'] == selected_name:
                    data.update(fields=inspection.get('fields', []), fields_loaded=True)
                    selected_index = self.layer.count()
                self.layer.addItem(layer['name'], data)
            self.layer.setCurrentIndex(selected_index)
            self.layer.setEnabled(self.layer.count() > 0)
            self._current_layer_index = -1
            self._loading = False
            self.select_layer()
            if selected_name is None:
                text = f"{self.layer.count()} couches disponibles. Choisir explicitement la couche à convertir, puis analyser ses champs."
            else:
                text = f"{selected_name} · {inspection.get('feature_count', '?')} entité(s) · SCR : {inspection.get('source_crs') or 'absent'}"
            issues = inspection.get('issues', [])
            if issues:
                text += '\n' + '\n'.join(str(issue.get('message', issue)) if isinstance(issue, dict) else str(issue) for issue in issues[:6])
        else:
            source = inspection['source']
            text = f"{source.get('width', '?')} × {source.get('height', '?')} pixels · {source.get('bands', '?')} bande(s)\nSCR : {source.get('crs') or 'absent'}"
            text += '\nTypes : ' + ', '.join(map(str, source.get('dtypes', [])))
            if inspection.get('notes'):
                text += '\n' + '\n'.join(map(str, inspection['notes']))
        self.inspection_status.setText(text)

    def job(self, options):
        if self._next_action == 'inspect':
            return self.inspection_job()
        source, kind, signature = self.source_configuration()
        if kind == 'vector':
            selected = self._selected_layer()
            if not selected or selected.get('source_signature') != signature or not selected.get('fields_loaded'):
                raise ValueError('Analyser la source et choisir explicitement une couche ; analyser ensuite les champs de cette couche.')
            output_layer = self.output_layer.text().strip()
            if not output_layer:
                raise ValueError('Renseigner le nom de la couche de sortie.')
            parameters = dict(source=source, layer=selected['name'], driver=self.vector_driver.currentData(),
                              encoding=self.encoding.currentText().strip(), output_layer=output_layer,
                              field_map=self.field_mapping())
        else:
            parameters = dict(source=source, **self.raster_parameters())
        parameters['loss_policy'] = self.loss_policy.currentData()
        folder = self.folder.text().strip()
        if not folder:
            raise ValueError('Renseigner un nouveau dossier de résultats.')
        destination = Path(self.destination()) / safe_name(folder)
        if destination.exists():
            raise ValueError('Ce dossier de résultats existe déjà. Choisir un nouveau nom.')
        parameters = deepcopy(parameters)
        operation = kind + '.convert'
        def run(progress, cancel):
            execute_operation(operation, parameters, destination, progress=progress, cancel=cancel)
            return destination / 'operation.json'
        return run

    def show_result(self, path):
        path = Path(path)
        if path.suffix.lower() != '.json':
            return
        record = json.loads(path.read_text(encoding='utf-8'))
        if record.get('schema') == INSPECTION_SCHEMA:
            self._show_inspection(record)
            return
        if record.get('operation') not in {'vector.convert', 'raster.convert'} and record.get('schema') not in {
                'cartomize.vector_conversion.v1', 'cartomize.raster_conversion.v1'}:
            return
        products = record.get('products', record)
        for field, key in ((self.converted_data, 'data'), (self.converted_report, 'report')):
            value = products.get(key) or (products.get('primary') if key == 'data' else None)
            if isinstance(value, str):
                candidate = Path(value)
                field.setText(str(candidate.resolve() if candidate.is_absolute() else (path.parent / candidate).resolve()))
            else:
                field.clear()
        self.result_status.setText('Conversion terminée. Les données relues et le rapport sont disponibles.')
        self._update_result_buttons()

    def _update_result_buttons(self):
        self.data_button.setEnabled(Path(self.converted_data.text()).is_file())
        self.report_button.setEnabled(Path(self.converted_report.text()).is_file())

    def open_product(self, path):
        if not path or not Path(path).is_file():
            self.result_status.setText('Ce résultat n’est plus disponible à son emplacement enregistré.')
            self._update_result_buttons()
            return
        window = self.window()
        if hasattr(window, 'workspace'):
            window.workspace.open_result(path)

    def restore_controls(self):
        self._current_layer_index = self.layer.currentIndex()
        self.layer.setEnabled(self.layer.count() > 0)
        self.changed()
        self.field_map.resizeRowsToContents()
        self.field_map.resizeColumnsToContents()
        self._update_result_buttons()
        if self.layer.count():
            self.inspection_status.setText('Couche et noms des champs restaurés. Les données seront vérifiées à nouveau au lancement.')
