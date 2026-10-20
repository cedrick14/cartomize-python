"""Graphical vector selections, summaries, geometry operations and table joins."""
from __future__ import annotations

import json
from pathlib import Path
import pandas as pd
from PySide6.QtWidgets import QComboBox, QLineEdit

import cartomize as cm
from .desktop_tools import VectorPage as BaseVectorPage, write_result
from .vector_workflows import (select_attributes, select_location, geometry_operation,
                               spatial_summary, join_attributes, latest_records)


class VectorPage(BaseVectorPage):
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
                          ('Champ de date', self.order_field), ('Agrégation des attributs', self.aggregation),
                          ('Champ X', self.x_field), ('Champ Y', self.y_field)]
        for label, widget in specifications:
            self.form.insertRow(self.form.rowCount()-1, label, widget)
            self._extra_widgets[widget] = self.form.labelForField(widget)
        for label,key in self.EXTRA:
            self.operation.addItem(label,key)
        for predicate in ('covers','covered_by','crosses','disjoint'):
            if self.predicate.findText(predicate)<0:
                self.predicate.addItem(predicate)
        self.source.edit.editingFinished.connect(self.refresh_fields)
        self.secondary.edit.editingFinished.connect(self.refresh_fields)
        self._advanced_ready = True
        self.changed()

    def refresh_fields(self):
        import pyogrio
        for text, controls in [(self.source.text(), (self.attribute,self.left_key,self.order_field)),
                               (self.secondary.text(), (self.right_key,self.summary_field))]:
            if not text or not Path(text).is_file():
                continue
            try:
                if Path(text).suffix.lower() in {'.csv','.tsv'}:
                    columns = list(pd.read_csv(text, sep=None, engine='python', nrows=0).columns)
                else:
                    columns = list(pyogrio.read_info(text)['fields'])
            except Exception:
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
        extra = {key for _,key in self.EXTRA}
        def visible(widget, show):
            widget.setVisible(show)
            label = self.form.labelForField(widget)
            if label:
                label.setVisible(show)
        if op in extra:
            for widget in (self.secondary,self.crs,self.distance,self.field,self.maximum,self.predicate,self.join,self.unit):
                visible(widget, False)
            visible(self.secondary, op in {'select_location','spatial_summary','join_attributes'})
            visible(self.predicate, op in {'select_location','spatial_summary'})
            visible(self.crs, op in {'centroid','simplify','from_xy'})
            visible(self.distance, op == 'simplify')
            visible(self.join, op == 'join_attributes')
        show = {self.attribute: op=='select_attributes', self.comparison:op=='select_attributes',
                self.filter_value:op=='select_attributes', self.summary_field:op in {'spatial_summary','dissolve'},
                self.summary_stat:op=='spatial_summary', self.result_field:op=='spatial_summary',
                self.left_key:op in {'join_attributes','latest_records'}, self.right_key:op=='join_attributes',
                self.order_field:op=='latest_records', self.aggregation:op=='dissolve',
                self.x_field:op=='from_xy', self.y_field:op=='from_xy'}
        for widget, shown in show.items():
            visible(widget, shown)
        vector_filter = 'Données vectorielles (*.gpkg *.shp *.geojson *.json *.zip);;Tous les fichiers (*)'
        table_filter = 'Tableaux (*.csv *.tsv);;Tous les fichiers (*)'
        self.source.filter = table_filter if op=='from_xy' else vector_filter
        self.secondary.filter = table_filter if op=='join_attributes' else vector_filter
        if op in {'select_location','spatial_summary'} and self.predicate.currentText() not in {'within','intersects','covered_by'}:
            self.predicate.setCurrentText('intersects')
        self.form.labelForField(self.distance).setText('Tolérance (m)' if op=='simplify' else 'Distance (m)')
        self.form.labelForField(self.crs).setText('SCR des coordonnées XY' if op=='from_xy' else 'Système de coordonnées projeté')

    def job(self, options):
        op = self.operation.currentData()
        if op not in {key for _,key in self.EXTRA} and not (op=='dissolve' and self.aggregation.currentData()!='first'):
            return super().job(options)
        source, other = self.source.text(), self.secondary.text()
        destination = self.destination()
        if not source:
            raise ValueError('Sélectionner les données sources.')
        needs_other = op in {'select_location','spatial_summary','join_attributes'}
        if needs_other and not other:
            raise ValueError('Sélectionner les données de comparaison.')
        parameters = dict(attribute=self.attribute.currentText().strip(), comparison=self.comparison.currentData(),
                          value=self.filter_value.text(), field=self.summary_field.currentText().strip() or None,
                          statistic=self.summary_stat.currentData(), output_field=self.result_field.text().strip() or None,
                          predicate=self.predicate.currentText(), left=self.left_key.currentText().strip(),
                          right=self.right_key.currentText().strip() or None, order=self.order_field.currentText().strip(),
                          crs=self.crs.text().strip() or None, tolerance=self.distance.value(),
                          x=self.x_field.text().strip(), y=self.y_field.text().strip(), how=self.join.currentData(),
                          group=self.field.text().strip() or None, aggregation=self.aggregation.currentData())
        def run(progress, cancel):
            if cancel.is_set():
                raise cm.ProcessingCancelled()
            p = parameters
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
                table = pd.read_csv(other,sep=None,engine='python')
                result = join_attributes(source,table,left_on=p['left'],right_on=p['right'],how=p['how'])
            elif op=='latest_records':
                result = latest_records(source,group_by=p['left'],order_by=p['order'])
            elif op=='from_xy':
                if not p['crs']:
                    raise ValueError('Indiquer le SCR des coordonnées XY.')
                result = cm.from_xy(pd.read_csv(source,sep=None,engine='python'),x=p['x'],y=p['y'],crs=p['crs'])
            elif op=='dissolve':
                if not p['field']:
                    raise ValueError('Indiquer le champ numérique à agréger.')
                result = cm.dissolve(source,by=p['group'],aggfunc={p['field']:p['aggregation']}).reset_index()
            else:
                result = geometry_operation(source,op,metric_crs=p['crs'],tolerance=p['tolerance'])
            if cancel.is_set():
                raise cm.ProcessingCancelled()
            return write_result(result,destination,sources=(source,other) if needs_other else (source,),
                                overwrite=options.get('overwrite',False))
        return run
