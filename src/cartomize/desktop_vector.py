"""Graphical vector selections, summaries, geometry operations and table joins."""
from __future__ import annotations

import json
from pathlib import Path
from pandas.api.types import is_string_dtype
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QComboBox, QLineEdit, QLabel

import cartomize as cm
from .tableio import read_table
from .desktop_tools_base import VectorPage as BaseVectorPage, write_result
from .desktop_vector_quality import VectorQualityControls
from .vector_workflows import (select_attributes, select_location, geometry_operation,
                               spatial_summary, join_attributes, latest_records)


class VectorPage(VectorQualityControls, BaseVectorPage):
    EXTRA = [('Sélection par attribut', 'select_attributes'), ('Sélection spatiale', 'select_location'),
             ('Synthèse par zone', 'spatial_summary'), ('Jointure attributaire', 'join_attributes'),
             ('Dernier relevé par identifiant', 'latest_records'), ('Centroïdes', 'centroid'),
             ('Points intérieurs', 'representative_point'), ('Limites des géométries', 'boundary'),
             ('Enveloppes convexes', 'convex_hull'), ('Simplification', 'simplify'),
             ('Séparation des parties', 'explode'), ('Points depuis un tableau XY', 'from_xy')]

    def __init__(self):
        self._advanced_ready = False
        self._extra_widgets = {}
        super().__init__()
        def field():
            widget = QComboBox()
            widget.setEditable(True)
            widget.setMinimumContentsLength(12)
            widget.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            return widget
        self.attribute = field()
        self.comparison = QComboBox()
        for label,key in [('Égal à','eq'),('Différent de','ne'),('Supérieur à','gt'),('Supérieur ou égal','ge'),
                          ('Inférieur à','lt'),('Inférieur ou égal','le'),('Contient le texte','contains'),
                          ('Commence par','starts_with'),('Valeur manquante','is_null'),('Valeur renseignée','not_null')]:
            self.comparison.addItem(label,key)
        self.filter_value = QLineEdit()
        self.summary_field = field()
        self.summary_stat = QComboBox()
        for label,key in [('Nombre','count'),('Somme','sum'),('Moyenne','mean'),('Minimum','min'),('Maximum','max')]:
            self.summary_stat.addItem(label,key)
        self.result_field = QLineEdit()
        self.left_key = field()
        self.right_key = field()
        self.join_cardinality = QComboBox()
        for label, key in [('Plusieurs vers un (N:1)', 'many_to_one'), ('Un vers un (1:1)', 'one_to_one'),
                           ('Un vers plusieurs (1:N)', 'one_to_many'), ('Plusieurs vers plusieurs (N:N)', 'many_to_many')]:
            self.join_cardinality.addItem(label, key)
        self.join_null_keys = QComboBox()
        for label, key in [('Ne pas apparier (par défaut)', 'unmatched'),
                           ('Apparier les valeurs manquantes', 'match'),
                           ('Refuser les valeurs manquantes', 'error')]:
            self.join_null_keys.addItem(label, key)
        self.join_policy_note = QLabel(
            'Une clé manquante ne correspond à aucune autre par défaut. « Apparier » relie aussi les clés manquantes ; '
            '« Refuser » interrompt le traitement. N:1 exige une seule ligne du tableau pour chaque clé appariée ; '
            '1:N et N:N peuvent produire plusieurs lignes par entité. Les identifiants textuels du tableau conservent leurs zéros initiaux.')
        self.join_policy_note.setWordWrap(True)
        self.order_field = field()
        self.x_field = QLineEdit('longitude')
        self.y_field = QLineEdit('latitude')
        self.aggregation = QComboBox()
        for label,key in [('Premier attribut','first'),('Somme','sum'),('Moyenne','mean'),('Minimum','min'),('Maximum','max')]:
            self.aggregation.addItem(label,key)
        specifications = [('Champ attributaire', self.attribute), ('Comparaison', self.comparison),
                          ('Valeur', self.filter_value), ('Champ numérique', self.summary_field),
                          ('Statistique', self.summary_stat), ('Champ de sortie', self.result_field),
                          ('Identifiant source', self.left_key), ('Identifiant de jointure', self.right_key),
                          ('Cardinalité de la jointure', self.join_cardinality), ('Clés manquantes', self.join_null_keys),
                          ('Champ de date', self.order_field), ('Agrégation des attributs', self.aggregation),
                          ('Champ X', self.x_field), ('Champ Y', self.y_field)]
        for label, widget in specifications:
            self.form.insertRow(self.form.rowCount()-1, label, widget)
            self._extra_widgets[widget] = self.form.labelForField(widget)
        self.form.insertRow(self.form.rowCount()-1, self.join_policy_note)
        for label,key in self.EXTRA:
            self.operation.addItem(label,key)
        self.init_quality_controls()
        self._fields_timer = QTimer(self)
        self._fields_timer.setSingleShot(True)
        self._fields_timer.setInterval(180)
        self._fields_timer.timeout.connect(self.refresh_fields)
        for control in (self.source.edit, self.secondary.edit):
            control.textChanged.connect(lambda *_: self._fields_timer.start())
            control.editingFinished.connect(self.refresh_fields)
        self._advanced_ready = True
        self.changed()

    def refresh_fields(self):
        import pyogrio
        source_controls = [self.attribute,self.left_key,self.order_field,self.quality_id]
        other_controls = [self.right_key]
        (source_controls if self.operation.currentData()=='dissolve' else other_controls).append(self.summary_field)
        for text, controls in [(self.source.text(),source_controls),(self.secondary.text(),other_controls)]:
            if not text or not Path(text).is_file():
                continue
            try:
                if Path(text).suffix.lower() in {'.csv','.tsv'}:
                    columns = list(read_table(text, nrows=0).columns)
                else:
                    columns = list(pyogrio.read_info(text)['fields'])
            except (OSError, ValueError, RuntimeError):
                continue
            for widget in controls:
                previous = widget.currentText()
                widget.blockSignals(True)
                widget.clear()
                widget.addItems(columns)
                widget.setCurrentText(previous)
                widget.blockSignals(False)

    def changed(self):
        super().changed()
        if not self._advanced_ready:
            return
        op = self.operation.currentData()
        def visible(widget, show):
            widget.setVisible(show)
            label = self.form.labelForField(widget)
            if label:
                label.setVisible(show)
        if op in {key for _,key in self.EXTRA}:
            for widget in (self.secondary,self.crs,self.distance,self.field,self.maximum,self.predicate,self.join,self.unit):
                visible(widget, False)
            visible(self.secondary, op in {'select_location','spatial_summary','join_attributes'})
            visible(self.predicate, op in {'select_location','spatial_summary'})
            visible(self.crs, op in {'centroid','simplify','from_xy'})
            visible(self.distance, op == 'simplify')
            visible(self.join, op == 'join_attributes')
        show = {self.attribute:op=='select_attributes', self.comparison:op=='select_attributes',
                self.filter_value:op=='select_attributes', self.summary_field:op in {'spatial_summary','dissolve'},
                self.summary_stat:op=='spatial_summary', self.result_field:op=='spatial_summary',
                self.left_key:op in {'join_attributes','latest_records'}, self.right_key:op=='join_attributes',
                self.join_cardinality:op=='join_attributes', self.join_null_keys:op=='join_attributes',
                self.join_policy_note:op=='join_attributes',
                self.order_field:op=='latest_records', self.aggregation:op=='dissolve',
                self.x_field:op=='from_xy', self.y_field:op=='from_xy'}
        for widget, shown in show.items():
            visible(widget, shown)
        previous = self.predicate.currentText()
        predicates = ['within','intersects','covered_by'] if op=='spatial_summary' else ['intersects','within','contains','touches','overlaps','covers','covered_by','crosses']
        if op=='select_location':
            predicates.append('disjoint')
        self.predicate.clear()
        self.predicate.addItems(predicates)
        if previous in predicates:
            self.predicate.setCurrentText(previous)
        vector_filter = 'Données vectorielles (*.gpkg *.shp *.geojson *.json *.zip);;Tous les fichiers (*)'
        table_filter = 'Tableaux (*.csv *.tsv);;Tous les fichiers (*)'
        self.source.filter = table_filter if op=='from_xy' else vector_filter
        self.secondary.filter = table_filter if op=='join_attributes' else vector_filter
        self.form.labelForField(self.distance).setText('Tolérance (m)' if op=='simplify' else 'Distance (m)')
        self.form.labelForField(self.crs).setText('SCR des coordonnées XY' if op=='from_xy' else 'Système de coordonnées projeté')
        self.refresh_fields()
        self.update_quality_controls()

    def job(self, options):
        op = self.operation.currentData()
        if op in {key for _, key in self.QUALITY_OPERATIONS}:
            return self.quality_job(options)
        if op not in {key for _,key in self.EXTRA} and op!='dissolve':
            return super().job(options)
        source, other = self.source.text(), self.secondary.text()
        destination = self.destination()
        if not source:
            raise ValueError('Sélectionner les données sources.')
        needs_other = op in {'select_location','spatial_summary','join_attributes'}
        if needs_other and not other:
            raise ValueError('Sélectionner les données de comparaison.')
        p = dict(attribute=self.attribute.currentText().strip(), comparison=self.comparison.currentData(),
                 value=self.filter_value.text(), field=self.summary_field.currentText().strip() or None,
                 statistic=self.summary_stat.currentData(), output_field=self.result_field.text().strip() or None,
                 predicate=self.predicate.currentText(), left=self.left_key.currentText().strip(),
                 right=self.right_key.currentText().strip() or None, order=self.order_field.currentText().strip(),
                 crs=self.crs.text().strip() or None, tolerance=self.distance.value(),
                 x=self.x_field.text().strip(), y=self.y_field.text().strip(), how=self.join.currentData(),
                 join_cardinality=self.join_cardinality.currentData(), null_keys=self.join_null_keys.currentData(),
                 group=self.field.text().strip() or None, aggregation=self.aggregation.currentData())
        def run(progress, cancel):
            if cancel.is_set():
                raise cm.ProcessingCancelled()
            if op=='select_attributes':
                value = p['value']
                if p['comparison'] not in {'contains','starts_with'}:
                    try:
                        value = json.loads(value)
                    except (ValueError, TypeError):
                        pass
                result = select_attributes(source,p['attribute'],p['comparison'],value)
            elif op=='select_location':
                result = select_location(source,other,predicate=p['predicate'])
            elif op=='spatial_summary':
                result = spatial_summary(source,other,field=p['field'],statistic=p['statistic'],
                                         predicate=p['predicate'],output_field=p['output_field'])
            elif op=='join_attributes':
                data = cm.read_file(source)
                if p['left'] not in data:
                    raise ValueError('Le champ de jointure source est absent : '+p['left'])
                table_key = p['right'] or p['left']
                dtype = {table_key: 'string'} if is_string_dtype(data[p['left']].dtype) else None
                result = join_attributes(data,read_table(other, dtype=dtype),
                                         left_on=p['left'],right_on=p['right'],how=p['how'],
                                         validate=p['join_cardinality'],null_keys=p['null_keys'])
            elif op=='latest_records':
                result = latest_records(source,group_by=p['left'],order_by=p['order'])
            elif op=='from_xy':
                if not p['crs']:
                    raise ValueError('Indiquer le SCR des coordonnées XY.')
                result = cm.from_xy(read_table(source),x=p['x'],y=p['y'],crs=p['crs'])
            elif op=='dissolve':
                if p['aggregation']!='first' and not p['field']:
                    raise ValueError('Indiquer le champ numérique à agréger.')
                aggregate = 'first' if p['aggregation']=='first' else {p['field']:p['aggregation']}
                result = cm.dissolve(source,by=p['group'],aggfunc=aggregate).reset_index(drop=p['group'] is None)
            else:
                result = geometry_operation(source,op,metric_crs=p['crs'],tolerance=p['tolerance'])
            if cancel.is_set():
                raise cm.ProcessingCancelled()
            return write_result(result,destination,sources=(source,other) if needs_other else (source,),
                                overwrite=options.get('overwrite',False))
        return run

    def restore_controls(self):
        """Restore conditional controls after loading a saved desktop session."""
        self.changed()
