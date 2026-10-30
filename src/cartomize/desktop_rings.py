"""Metric distance rings with explicit source choices and reusable balances."""
import json
import math
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QLabel, QLineEdit, QPushButton, QSpinBox, QWidget
from pyproj import CRS

from .desktop_selection import _combo, _form, _row
from .processing import execute_operation
from .recipes import safe_name


PRODUCTS = [
    ('data', 'Anneaux de distance'), ('table', 'Surfaces par intervalle'),
    ('sources', 'Sources et identifiants'), ('balances', 'Bilan des surfaces'),
    ('summary', 'Résumé du calcul'), ('audit', 'Vérification des résultats'),
]


def _distances(text):
    """Parse the documented semicolon list without sorting or dropping bounds."""
    pieces = text.split(';')
    try:
        values = [float(piece.strip()) for piece in pieces]
    except ValueError as exc:
        raise ValueError('Saisir des distances séparées par des points-virgules ; '
                         'utiliser le point pour les décimales.') from exc
    if not values or any(not math.isfinite(value) or value <= 0 for value in values):
        raise ValueError('Les distances doivent être des nombres finis strictement positifs, en mètres.')
    if any(right <= left for left, right in zip(values, values[1:])):
        raise ValueError('Les distances doivent être strictement croissantes, sans doublons.')
    return values


class RingsControls:
    """Keep executed parameters and products independent from later form edits."""

    def init_rings_controls(self):
        self._rings_source = None
        self._rings_info = None
        self._rings_loading = False
        self.rings_section = QWidget()
        form = _form(self.rings_section)
        self.rings_layer = _combo([('Choisir la couche', None)])
        self.rings_id = _combo([('Rang de la ligne source', None)])
        self.rings_source_note = QLabel('Choisir la couche source pour afficher ses champs.')
        self.rings_source_note.setWordWrap(True)
        _row(form, 'Couche du fichier source', self.rings_layer)
        form.addRow(self.rings_source_note)
        _row(form, 'Étiquette source (facultatif)', self.rings_id)

        self.rings_distances = QLineEdit('100; 250; 500; 1000')
        self.rings_distances.setPlaceholderText('Exemple : 50; 100; 250; 500; 1000')
        _row(form, 'Bornes supérieures en mètres', self.rings_distances)
        self.add_help('Séparer les distances par un point-virgule. Utiliser le point pour '
                      'les décimales. La première borne inférieure est zéro.',
            subject='Format des distances',summary='Séparateur « ; », point décimal.',form=form)
        self.rings_intervals_note = QLabel()
        self.rings_intervals_note.setWordWrap(True)
        form.addRow(self.rings_intervals_note)
        self.rings_mode = _combo([('Réunir toutes les sources', 'dissolved'),
                                  ('Traiter chaque source séparément', 'independent')])
        _row(form, 'Organisation des anneaux', self.rings_mode)
        self.rings_include_input = QCheckBox('Inclure les polygones')
        self.rings_include_input.setToolTip(
            'Inclure les polygones sources dans le premier intervalle ; les exclure laisse seulement les couronnes extérieures.')
        _row(form, 'Surface des polygones sources', self.rings_include_input)
        self.rings_policy_note = QLabel()
        self.rings_policy_note.setWordWrap(True)
        form.addRow(self.rings_policy_note)

        self.rings_crs = QLineEdit()
        self.rings_crs.setPlaceholderText('Exemple : EPSG:32733')
        self.rings_crs_note = QLabel()
        self.rings_crs_note.setWordWrap(True)
        self.rings_unit = _combo([('Hectares (ha)', 'ha'), ('Mètres carrés (m²)', 'm2'),
                                 ('Kilomètres carrés (km²)', 'km2')])
        self.rings_quad_segs = QSpinBox()
        self.rings_quad_segs.setRange(1, 1024)
        self.rings_quad_segs.setValue(16)
        self.rings_quad_segs.setToolTip(
            'Nombre de segments par quart de cercle. Une valeur plus élevée affine les courbes et augmente le calcul.')
        _row(form, 'SCR projeté du calcul', self.rings_crs)
        form.addRow(self.rings_crs_note)
        _row(form, 'Unité des surfaces', self.rings_unit)
        _row(form, 'Segments par quart de cercle', self.rings_quad_segs)
        self.add_help('Les extrémités et les angles sont arrondis. Les cercles sont '
                      'approchés par des segments ; le bilan conserve cette précision de construction.',
            subject='Précision des anneaux',summary='Courbes approchées par segments.',form=form)
        self.rings_folder = QLineEdit('anneaux_distance')
        _row(form, 'Nouveau dossier des résultats', self.rings_folder)

        self.rings_result_path = QLineEdit(self)
        self.rings_result_path.hide()
        self.rings_result_status = QLabel('Lancer le calcul pour consulter les anneaux et leurs surfaces.')
        self.rings_result_status.setWordWrap(True)
        form.addRow(self.rings_result_status)
        self._rings_buttons = {}
        for key, title in PRODUCTS:
            button = QPushButton(title)
            button.setEnabled(False)
            button.clicked.connect(lambda checked=False, name=key: self.open_rings_product(name))
            self._rings_buttons[key] = button
            setattr(self, 'rings_' + key + '_button', button)
            form.addRow(button)
        self.form.insertRow(self.form.rowCount() - 1, self.rings_section)
        self.operation.addItem('Anneaux de distance avec bilan', 'buffer_rings')
        self.operation.setItemData(self.operation.count() - 1, self.operation.itemText(self.operation.count() - 1),
                                   Qt.ItemDataRole.ToolTipRole)
        self.rings_layer.currentIndexChanged.connect(self.refresh_rings_fields)
        self.rings_distances.textChanged.connect(self.update_rings_notes)
        self.rings_mode.currentIndexChanged.connect(self.update_rings_notes)
        self.rings_include_input.toggled.connect(self.update_rings_notes)
        self.rings_crs.textChanged.connect(self.update_rings_notes)
        self.update_rings_notes()
        self.update_rings_controls()

    def refresh_rings_layers(self, *_):
        if not hasattr(self, 'rings_layer') or self._rings_loading:
            return
        import pyogrio
        self._rings_loading = True
        try:
            path = self.source.text()
            selected = self.rings_layer.currentData() if path == self._rings_source else None
            self._rings_source = path
            self.rings_layer.blockSignals(True)
            self.rings_layer.clear()
            self.rings_layer.addItem('Choisir la couche', None)
            if path and Path(path).is_file():
                try:
                    for name, kind in pyogrio.list_layers(path):
                        if kind is not None:
                            self.rings_layer.addItem(str(name), str(name))
                            self.rings_layer.setItemData(self.rings_layer.count() - 1, str(name), Qt.ItemDataRole.ToolTipRole)
                    index = self.rings_layer.findData(selected)
                    self.rings_layer.setCurrentIndex(index if index > 0 else (1 if self.rings_layer.count() == 2 else 0))
                except (OSError, ValueError, RuntimeError):
                    pass
            self.rings_layer.blockSignals(False)
            self.rings_layer.setToolTip(self.rings_layer.currentText())
        finally:
            self._rings_loading = False
        self.refresh_rings_fields()

    def refresh_rings_fields(self, *_):
        if self._rings_loading:
            return
        import pyogrio
        info, failure = None, None
        path, layer = self.source.text(), self.rings_layer.currentData()
        if path and layer is not None and Path(path).is_file():
            try:
                info = pyogrio.read_info(path, layer=layer)
            except (OSError, ValueError, RuntimeError) as exc:
                failure = str(exc)
        self._rings_info = info
        previous = self.rings_id.currentData()
        self.rings_id.blockSignals(True)
        self.rings_id.clear()
        self.rings_id.addItem('Rang de la ligne source', None)
        for field in list(info['fields']) if info else []:
            self.rings_id.addItem(str(field), str(field))
            self.rings_id.setItemData(self.rings_id.count() - 1, str(field), Qt.ItemDataRole.ToolTipRole)
        self.rings_id.setCurrentIndex(max(0, self.rings_id.findData(previous)))
        self.rings_id.blockSignals(False)
        self.rings_id.setToolTip(self.rings_id.currentText())
        self.rings_source_note.setText(
            f"Couche : {layer} · {info.get('features', '?')} objet(s) · SCR : {info.get('crs') or 'absent'}."
            if info else ('Lecture impossible : ' + failure if failure else
                         'Choisir explicitement la couche source. Les champs dépendent de cette sélection.'))
        self.update_rings_notes()

    def update_rings_notes(self, *_):
        try:
            distances = _distances(self.rings_distances.text())
        except ValueError as exc:
            self.rings_intervals_note.setText(str(exc))
        else:
            pairs = zip([0.0] + distances[:-1], distances)
            self.rings_intervals_note.setText('Intervalles : ' + ' ; '.join(
                f'{lower:g}–{upper:g} m' for lower, upper in pairs) + '.')
        if self.rings_mode.currentData() == 'independent':
            text = ('Les anneaux d’une même source ne se superposent pas. Ceux de sources différentes '
                    'peuvent se recouvrir ; leur somme ne représente donc pas nécessairement une surface unique. '
                    'Des étiquettes identiques restent des sources distinctes. ')
        else:
            text = ('Les sources sont réunies avant de construire les intervalles de distance. '
                    'Les anneaux ne se superposent pas ; les surfaces communes ne sont comptées qu’une fois. ')
        text += ('La surface des polygones sources est incluse dans le premier intervalle.'
                 if self.rings_include_input.isChecked() else
                 'La surface des polygones sources est exclue des anneaux.')
        self.rings_policy_note.setText(text)
        requested = self.rings_crs.text().strip()
        info = self._rings_info
        crs = None
        try:
            if requested or (info and info.get('crs')):
                crs = CRS.from_user_input(requested or info['crs'])
        except (ValueError, RuntimeError):
            pass
        if crs is not None and crs.is_projected:
            self.rings_crs_note.setText(
                f'Distances planes dans {crs.to_string()}. Choisir une projection adaptée au territoire ; '
                'les distances en mètres sont converties dans les unités de ce SCR.')
        else:
            self.rings_crs_note.setText(
                'Un SCR projeté adapté au territoire est obligatoire. Laisser ce champ vide seulement '
                'si la couche source utilise déjà un SCR projeté.')

    def update_rings_controls(self):
        if not hasattr(self, 'rings_section'):
            return
        active = self.operation.currentData() == 'buffer_rings'
        self.rings_section.setVisible(active)
        if not active:
            return
        self.cancellable = True
        self.form.labelForField(self.source).setText('Fichier des sources')
        previous_mode = self.output.mode
        self.output.mode = 'directory'
        self.output.filter = ''
        self.form.labelForField(self.output).setText('Répertoire parent des résultats')
        if self.output.text() and previous_mode != 'directory':
            previous = Path(self.output.text())
            if previous.suffix.lower() in {'.gpkg', '.geojson', '.json'}:
                self.output.edit.setText(str(previous.parent))

    def rings_job(self, options):
        source = self.source.text()
        if not source:
            raise ValueError('Choisir le fichier des sources.')
        if source != self._rings_source:
            self.refresh_rings_layers()
        layer = self.rings_layer.currentData()
        info = self._rings_info
        if layer is None or info is None:
            raise ValueError('Choisir explicitement la couche source.')
        identifier = self.rings_id.currentData()
        if identifier is not None and identifier not in info['fields']:
            raise ValueError('Choisir un champ présent dans la couche source.')
        if not info.get('crs'):
            raise ValueError('Le SCR source est absent ; le définir dans les données sources.')
        metric_crs = self.rings_crs.text().strip() or None
        try:
            crs = CRS.from_user_input(metric_crs or info['crs'])
        except (ValueError, RuntimeError) as exc:
            raise ValueError('Le SCR projeté du calcul n’est pas reconnu.') from exc
        if not crs.is_projected:
            raise ValueError('Choisir un SCR projeté adapté pour calculer les distances.')
        distances = _distances(self.rings_distances.text())
        folder = self.rings_folder.text().strip()
        if not folder:
            raise ValueError('Indiquer un nouveau dossier de résultats.')
        destination = Path(self.destination()) / safe_name(folder)
        parameters = dict(data=source, distances=distances, layer=layer,
                          metric_crs=metric_crs, mode=self.rings_mode.currentData(),
                          id_field=identifier, include_input=self.rings_include_input.isChecked(),
                          quad_segs=self.rings_quad_segs.value(), area_unit=self.rings_unit.currentData())

        def run(progress, cancel):
            execute_operation('vector.buffer_rings', parameters, destination, progress=progress, cancel=cancel)
            return destination / 'operation.json'
        return run

    def _rings_result_record(self):
        path = self.rings_result_path.text()
        if not path or not Path(path).is_file():
            return None
        try:
            record = json.loads(Path(path).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return None
        return record if isinstance(record, dict) and record.get('operation') == 'vector.buffer_rings' else None

    def update_rings_results(self):
        record = self._rings_result_record()
        products = record.get('products', {}) if record else {}

        def available(key):
            return bool(products.get(key) and Path(products[key]).is_file())

        for key, button in self._rings_buttons.items():
            button.setEnabled(available(key))
        if record is None:
            self.rings_result_status.setText('Lancer le calcul pour consulter les anneaux et leurs surfaces.')
            return
        summary = {}
        if available('summary'):
            try:
                summary = json.loads(Path(products['summary']).read_text(encoding='utf-8'))
            except (OSError, ValueError):
                pass
        counts = (f" : {summary['input_features']} source(s), {summary['band_count']} intervalle(s)"
                  if isinstance(summary, dict) and {'input_features', 'band_count'} <= summary.keys() else '')
        self.rings_result_status.setText(
            f'Calcul terminé{counts}. Le tableau présente les bornes et la surface de chaque intervalle ; '
            'le bilan vérifie la couverture et les recouvrements. Les identifiants relient les résultats aux sources.')
        window = self.window()
        if hasattr(window, 'workspace'):
            label = Path(self.rings_result_path.text()).parent.name
            for key, title in PRODUCTS:
                if available(key):
                    window.workspace.register(dict(data=products[key], name=f'{title} — {label}'))

    def open_rings_product(self, key):
        self.update_rings_results()
        record, window = self._rings_result_record(), self.window()
        if record and hasattr(window, 'workspace'):
            path = record.get('products', {}).get(key)
            if path and Path(path).is_file():
                document = window.workspace.open_result(path)
                if key == 'sources' and getattr(document, '_table', None) is not None:
                    document.views.setCurrentWidget(document._table)
                return document

    def show_result(self, path):
        path = Path(path)
        if path.suffix.lower() == '.json':
            record = json.loads(path.read_text(encoding='utf-8'))
            if isinstance(record, dict) and record.get('operation') == 'vector.buffer_rings':
                self.rings_result_path.setText(str(path.resolve()))
                self.update_rings_results()
                return
        return super().show_result(path)

    def restore_rings_controls(self):
        self._rings_source = self.source.text()
        if self.operation.currentData() == 'buffer_rings':
            self.refresh_rings_layers()
        self.update_rings_controls()
        self.update_rings_results()
