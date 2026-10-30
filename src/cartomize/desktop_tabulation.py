"""Polygon zonal area tables, explicit accounting and inspectable products."""
import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QLineEdit, QPushButton, QWidget
from pyproj import CRS

from .desktop import PathField, VECTOR_FILTER
from .desktop_selection import _combo, _form, _row
from .processing import execute_operation
from .recipes import safe_name


PRODUCTS = [
    ('data', 'Intersections'), ('table', 'Surfaces par catégorie'),
    ('matrix', 'Tableau croisé'), ('zones', 'Bilan par zone'),
    ('categories', 'Catégories'), ('gaps', 'Surfaces sans catégorie'),
    ('overlaps', 'Recouvrements'),
    ('summary', 'Bilan du croisement'),
]


class TabulationControls:
    """Keep source choices and finished results independent from later edits."""

    def init_tabulation_controls(self):
        self._tabulation_sources = {'zones': None, 'classes': None}
        self._tabulation_infos = {'zones': None, 'classes': None}
        self._tabulation_loading = False
        self.tabulation_section = QWidget()
        form = _form(self.tabulation_section)
        self.tabulation_zones_layer = _combo([('Choisir la couche', None)])
        self.tabulation_zone_field = _combo([('Choisir le champ', None)])
        self.tabulation_zones_note = QLabel('Choisir la couche des zones pour afficher ses champs.')
        self.tabulation_zones_note.setWordWrap(True)
        self.tabulation_classes = PathField(filter=VECTOR_FILTER)
        self.tabulation_classes_layer = _combo([('Choisir la couche', None)])
        self.tabulation_class_field = _combo([('Choisir le champ', None)])
        self.tabulation_classes_note = QLabel('Choisir la couche des catégories pour afficher ses champs.')
        self.tabulation_classes_note.setWordWrap(True)
        for title, control in [('Couche des zones', self.tabulation_zones_layer),
                               ('Champ des zones', self.tabulation_zone_field)]:
            _row(form, title, control)
        form.addRow(self.tabulation_zones_note)
        for title, control in [('Fichier d’occupation du sol', self.tabulation_classes),
                               ('Couche des catégories', self.tabulation_classes_layer),
                               ('Champ des catégories', self.tabulation_class_field)]:
            _row(form, title, control)
        form.addRow(self.tabulation_classes_note)

        self.tabulation_crs = QLineEdit()
        self.tabulation_crs.setPlaceholderText('Exemple : EPSG:32733')
        self.tabulation_unit = _combo([('Hectares (ha)', 'ha'), ('Mètres carrés (m²)', 'm2'),
                                       ('Kilomètres carrés (km²)', 'km2')])
        self.tabulation_crs_note = QLabel()
        self.tabulation_crs_note.setWordWrap(True)
        _row(form, 'SCR projeté des mesures', self.tabulation_crs)
        _row(form, 'Unité de superficie', self.tabulation_unit)
        form.addRow(self.tabulation_crs_note)
        self.tabulation_overlap = _combo([('Refuser les recouvrements', 'error'),
                                          ('Les mesurer et les signaler', 'report')])
        self.tabulation_zone_overlap = _combo([('Analyser chaque zone séparément', 'independent'),
                                               ('Refuser les zones superposées', 'error')])
        self.tabulation_null_classes = _combo([('Refuser les catégories manquantes', 'error'),
                                               ('Les traiter comme non classées', 'unclassified')])
        self.tabulation_policy_note = QLabel()
        self.tabulation_policy_note.setWordWrap(True)
        for title, control in [('Recouvrements des catégories', self.tabulation_overlap),
                               ('Recouvrements des zones', self.tabulation_zone_overlap),
                               ('Catégories manquantes', self.tabulation_null_classes)]:
            _row(form, title, control)
        form.addRow(self.tabulation_policy_note)
        self.tabulation_folder = QLineEdit('croisement_zonages')
        _row(form, 'Dossier des résultats', self.tabulation_folder)
        note = QLabel('Les polygones de même zone ou catégorie sont réunis. '
                      'Les tableaux incluent les surfaces nulles et un bilan de couverture par zone. '
                      'Choisir un nouveau dossier de résultats.')
        note.setWordWrap(True)
        form.addRow(note)
        self.tabulation_result_path = QLineEdit(self)
        self.tabulation_result_path.hide()
        self.tabulation_result_status = QLabel('Lancer le croisement pour consulter les résultats.')
        self.tabulation_result_status.setWordWrap(True)
        form.addRow(self.tabulation_result_status)
        self._tabulation_buttons = {}
        for key, title in PRODUCTS:
            button = QPushButton(title)
            button.setEnabled(False)
            button.clicked.connect(lambda checked=False, name=key: self.open_tabulation_product(name))
            self._tabulation_buttons[key] = button
            setattr(self, 'tabulation_' + key + '_button', button)
            form.addRow(button)
        self.form.insertRow(self.form.rowCount() - 1, self.tabulation_section)
        self.operation.addItem('Table croisée des surfaces', 'tabulate_area')
        self.operation.setItemData(self.operation.count() - 1, self.operation.itemText(self.operation.count() - 1),
                                   Qt.ItemDataRole.ToolTipRole)
        self.tabulation_zones_layer.currentIndexChanged.connect(self.refresh_tabulation_fields)
        self.tabulation_classes_layer.currentIndexChanged.connect(self.refresh_tabulation_fields)
        self.tabulation_classes.edit.editingFinished.connect(self.refresh_tabulation_layers)
        self.tabulation_classes.edit.textChanged.connect(lambda *_: self._fields_timer.start())
        self.tabulation_crs.textChanged.connect(self.update_tabulation_notes)
        for control in (self.tabulation_overlap, self.tabulation_zone_overlap, self.tabulation_null_classes):
            control.currentIndexChanged.connect(self.update_tabulation_notes)
        self.update_tabulation_notes()
        self.update_tabulation_controls()

    def refresh_tabulation_layers(self, *_):
        if not hasattr(self, 'tabulation_zones_layer') or self._tabulation_loading:
            return
        import pyogrio
        self._tabulation_loading = True
        try:
            for key, path, control in [('zones', self.source.text(), self.tabulation_zones_layer),
                                       ('classes', self.tabulation_classes.text(), self.tabulation_classes_layer)]:
                selected = control.currentData() if path == self._tabulation_sources[key] else None
                self._tabulation_sources[key] = path
                control.blockSignals(True)
                control.clear()
                control.addItem('Choisir la couche', None)
                if path and Path(path).is_file():
                    try:
                        for name, kind in pyogrio.list_layers(path):
                            if kind is not None:
                                control.addItem(str(name), str(name))
                                control.setItemData(control.count() - 1, str(name), Qt.ItemDataRole.ToolTipRole)
                        index = control.findData(selected)
                        control.setCurrentIndex(index if index > 0 else (1 if control.count() == 2 else 0))
                    except (OSError, ValueError, RuntimeError):
                        pass
                control.blockSignals(False)
                control.setToolTip(control.currentText())
        finally:
            self._tabulation_loading = False
        self.refresh_tabulation_fields()

    def refresh_tabulation_fields(self, *_):
        if self._tabulation_loading:
            return
        import pyogrio
        for key, path, layer_control, field_control, note in [
                ('zones', self.source.text(), self.tabulation_zones_layer,
                 self.tabulation_zone_field, self.tabulation_zones_note),
                ('classes', self.tabulation_classes.text(), self.tabulation_classes_layer,
                 self.tabulation_class_field, self.tabulation_classes_note)]:
            info, failure = None, None
            layer = layer_control.currentData()
            if path and layer is not None and Path(path).is_file():
                try:
                    info = pyogrio.read_info(path, layer=layer)
                except (OSError, ValueError, RuntimeError) as exc:
                    failure = str(exc)
            self._tabulation_infos[key] = info
            previous = field_control.currentData()
            fields = list(info['fields']) if info else []
            field_control.blockSignals(True)
            field_control.clear()
            field_control.addItem('Choisir le champ', None)
            for field in fields:
                field_control.addItem(str(field), str(field))
                field_control.setItemData(field_control.count() - 1, str(field), Qt.ItemDataRole.ToolTipRole)
            field_control.setCurrentIndex(max(0, field_control.findData(previous)))
            field_control.blockSignals(False)
            field_control.setToolTip(field_control.currentText())
            note.setText(f"Couche : {layer} · {info.get('features', '?')} objet(s) · "
                         f"SCR : {info.get('crs') or 'absent'}." if info else
                         ('Lecture impossible : ' + failure if failure else
                          'Choisir explicitement une couche pour afficher ses champs.'))
        self.update_tabulation_notes()

    def update_tabulation_notes(self, *_):
        requested = self.tabulation_crs.text().strip()
        info = self._tabulation_infos.get('zones')
        crs = None
        try:
            if requested or (info and info.get('crs')):
                crs = CRS.from_user_input(requested or info['crs'])
        except (ValueError, RuntimeError):
            pass
        if crs is not None and crs.is_projected:
            self.tabulation_crs_note.setText(
                f'Surfaces planes dans {crs.to_string()}. Choisir une projection adaptée au territoire ; '
                'les unités linéaires sont converties dans l’unité de surface choisie.')
        else:
            self.tabulation_crs_note.setText(
                'Un SCR projeté adapté au territoire est obligatoire pour mesurer les surfaces. '
                'Le champ peut rester vide seulement si les zones utilisent déjà un SCR projeté.')
        text = ('Les doublons d’une même catégorie sont réunis. '
                'Un chevauchement entre catégories différentes ')
        if self.tabulation_overlap.currentData() == 'report':
            text += ('est mesuré et signalé ; la somme des surfaces par catégorie peut dépasser '
                     'la surface réellement couverte. ')
        else:
            text += 'interrompt le calcul. '
        if self.tabulation_zone_overlap.currentData() == 'independent':
            text += 'Chaque zone est analysée séparément ; les surfaces communes figurent dans chaque zone. '
        else:
            text += 'Les zones distinctes ne doivent pas se recouvrir. '
        if self.tabulation_null_classes.currentData() == 'unclassified':
            text += ('Le bilan distingue les surfaces non classées des surfaces sans couverture.')
        else:
            text += 'Une catégorie manquante doit être renseignée avant le calcul.'
        self.tabulation_policy_note.setText(text)

    def update_tabulation_controls(self):
        if not hasattr(self, 'tabulation_section'):
            return
        active = self.operation.currentData() == 'tabulate_area'
        self.tabulation_section.setVisible(active)
        self.form.labelForField(self.source).setText('Fichier des zones' if active else 'Couche source')
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

    def tabulation_job(self, options):
        zones, classes = self.source.text(), self.tabulation_classes.text()
        if not zones:
            raise ValueError('Choisir le fichier des zones.')
        if not classes:
            raise ValueError('Choisir le fichier d’occupation du sol.')
        if zones != self._tabulation_sources['zones'] or classes != self._tabulation_sources['classes']:
            self.refresh_tabulation_layers()
        zones_layer, classes_layer = self.tabulation_zones_layer.currentData(), self.tabulation_classes_layer.currentData()
        if zones_layer is None or self._tabulation_infos['zones'] is None:
            raise ValueError('Choisir explicitement la couche des zones.')
        if classes_layer is None or self._tabulation_infos['classes'] is None:
            raise ValueError('Choisir explicitement la couche des catégories.')
        zone_field, class_field = self.tabulation_zone_field.currentData(), self.tabulation_class_field.currentData()
        if zone_field is None or zone_field not in self._tabulation_infos['zones']['fields']:
            raise ValueError('Choisir le champ de regroupement des zones.')
        if class_field is None or class_field not in self._tabulation_infos['classes']['fields']:
            raise ValueError('Choisir le champ des catégories.')
        metric_crs = self.tabulation_crs.text().strip() or None
        for label, info in [('zones', self._tabulation_infos['zones']), ('catégories', self._tabulation_infos['classes'])]:
            if not info.get('crs'):
                raise ValueError(f'Le SCR des {label} est absent ; le définir dans les données sources.')
        try:
            crs = CRS.from_user_input(metric_crs or self._tabulation_infos['zones']['crs'])
        except (ValueError, RuntimeError) as exc:
            raise ValueError('Le SCR projeté pour les surfaces n’est pas reconnu.') from exc
        if not crs.is_projected:
            raise ValueError('Choisir un SCR projeté adapté pour calculer les surfaces.')
        folder = self.tabulation_folder.text().strip()
        if not folder:
            raise ValueError('Indiquer un nouveau dossier de résultats.')
        destination = Path(self.destination()) / safe_name(folder)
        parameters = dict(zones=zones, classes=classes, zone_field=zone_field, class_field=class_field,
                          zones_layer=zones_layer, classes_layer=classes_layer, metric_crs=metric_crs,
                          area_unit=self.tabulation_unit.currentData(), overlap_policy=self.tabulation_overlap.currentData(),
                          zone_overlap_policy=self.tabulation_zone_overlap.currentData(),
                          null_classes=self.tabulation_null_classes.currentData())

        def run(progress, cancel):
            execute_operation('vector.tabulate_area', parameters, destination, progress=progress, cancel=cancel)
            return destination / 'operation.json'
        return run

    def _tabulation_result_record(self):
        path = self.tabulation_result_path.text()
        if not path or not Path(path).is_file():
            return None
        try:
            record = json.loads(Path(path).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return None
        return record if isinstance(record, dict) and record.get('operation') == 'vector.tabulate_area' else None

    def update_tabulation_results(self):
        record = self._tabulation_result_record()
        products = record.get('products', {}) if record else {}

        def available(key):
            return bool(products.get(key) and Path(products[key]).is_file())

        for key, button in self._tabulation_buttons.items():
            button.setEnabled(available(key))
        if record is None:
            self.tabulation_result_status.setText('Lancer le croisement pour consulter les résultats.')
            return
        summary = {}
        if available('summary'):
            try:
                summary = json.loads(Path(products['summary']).read_text(encoding='utf-8'))
            except (OSError, ValueError):
                pass
        counts = (f" : {summary['zone_count']} zone(s), {summary['class_count']} catégorie(s)"
                  if isinstance(summary, dict) and {'zone_count', 'class_count'} <= summary.keys() else '')
        self.tabulation_result_status.setText(
            f'Croisement terminé{counts}. Le tableau croisé et le bilan par zone permettent de vérifier '
            'les surfaces couvertes, non classées et superposées. '
            'Le tableau Catégories donne le libellé des colonnes du tableau croisé.')
        window = self.window()
        if hasattr(window, 'workspace'):
            label = Path(self.tabulation_result_path.text()).parent.name
            for key, title in PRODUCTS:
                if available(key):
                    window.workspace.register(dict(data=products[key], name=f'{title} — {label}'))
            if available('audit'):
                window.workspace.register(dict(data=products['audit'], name=f'Audit des surfaces — {label}'))

    def open_tabulation_product(self, key):
        self.update_tabulation_results()
        record, window = self._tabulation_result_record(), self.window()
        if record and hasattr(window, 'workspace'):
            path = record.get('products', {}).get(key)
            if path and Path(path).is_file():
                document = window.workspace.open_result(path)
                if key == 'zones' and getattr(document, '_table', None) is not None:
                    document.views.setCurrentWidget(document._table)
                return document

    def show_result(self, path):
        path = Path(path)
        if path.suffix.lower() == '.json':
            record = json.loads(path.read_text(encoding='utf-8'))
            if isinstance(record, dict) and record.get('operation') == 'vector.tabulate_area':
                self.tabulation_result_path.setText(str(path.resolve()))
                self.update_tabulation_results()
                return
        return super().show_result(path)

    def restore_tabulation_controls(self):
        self._tabulation_sources = {'zones': self.source.text(), 'classes': self.tabulation_classes.text()}
        if self.operation.currentData() == 'tabulate_area':
            self.refresh_tabulation_layers()
        self.update_tabulation_controls()
        self.update_tabulation_results()
