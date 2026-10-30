"""Form-based construction of named processing dependencies."""
import json
from copy import deepcopy
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QDialog,QDialogButtonBox,
    QComboBox,QLineEdit,QCheckBox,QPushButton,QLabel,QTableWidget,QTableWidgetItem,QFileDialog,
    QMessageBox,QScrollArea)
from .processing import operation_catalog,operation_spec,validate_parameters


LABELS={'data':'Couche source','source':'Raster ou couche source','left':'Couche principale','right':'Couche secondaire',
        'mask':'Masque de découpage','sources':'Rasters sources (liste JSON)','inputs':'Variables et rasters (objet JSON)',
        'expression':'Expression raster','crs':'Système de coordonnées cible','metric_crs':'Système de coordonnées projeté',
        'distance':'Distance (m)','band':'Bande','by':'Champ de regroupement','column':'Champ',
        'products':'Dérivées du terrain (liste JSON)','kernel':'Matrice de convolution (JSON)',
        'mapping':'Correspondance des classes (objet JSON)','zones':'Couche des zones','before':'Raster initial',
        'after':'Raster final','training':'Échantillons de référence','class_column':'Champ des classes','indices':'Indices (liste JSON)',
        'border_values':'Valeurs périphériques à masquer (liste JSON)','keep_values':'Valeurs à conserver (liste JSON)',
        'table':'Tableau attributaire (CSV ou TSV)','observations':'Couche des observations','aoi':'Zone d’étude',
        'field':'Champ attributaire','comparison':'Comparaison','value':'Valeur ou liste de valeurs',
        'left_on':'Clé de la couche','right_on':'Clé du tableau','validate':'Cardinalité de la jointure',
        'null_keys':'Clés manquantes',
        'table_dtypes':'Types des colonnes (objet JSON)','delimiter':'Séparateur du tableau','encoding':'Encodage du tableau',
        'group_by':'Identifiant de regroupement','order_by':'Champ de date','output_field':'Champ de sortie',
        'operation':'Transformation géométrique','tolerance':'Tolérance (m)','statistic':'Statistique','predicate':'Relation spatiale',
        'value_mode':'Valeurs utilisées','prefix':'Préfixe des champs de résultat','snap':'Rattachement au réseau',
        'include_coverage':'Mesurer la couverture de chaque zone','max_zone_pixels':'Limite de pixels candidats par zone',
        'all_touched':'Inclure tous les pixels touchés par la zone'}
LABELS.update({
    'layer': 'Couche du fichier vectoriel',
    'id_field': 'Identifiant unique des entités', 'method': 'Méthode de réparation',
    'missing': 'Géométries manquantes', 'empty': 'Géométries vides',
    'type_changes': 'Changements de type géométrique', 'keep_collapsed': 'Conserver les composantes effondrées',
    'rules': 'Règles topologiques (liste JSON)', 'reference': 'Emprise de référence',
    'allowed_gaps': 'Trous et lacunes légitimes', 'min_area': 'Seuil de surface des anomalies (m²)',
    'keys': 'Champs définissant un doublon (liste JSON)', 'geometry': 'Comparaison géométrique',
    'keep': 'Règle de conservation', 'ascending': 'Trier par ordre croissant',
    'target_crs': 'Système de coordonnées cible',
    'recursive': 'Inclure les sous-dossiers',
    'operations': 'Transformations par identifiant de couche (objet JSON)',
    'area_of_interest': 'Emprise WGS 84 : ouest, sud, est, nord (liste JSON)',
    'accuracy': 'Précision annoncée maximale (m)',
    'allow_ballpark': 'Autoriser une transformation approximative',
    'require_best': 'Exiger la meilleure transformation et ses grilles',
    'area_policy': 'Hors du domaine de validité',
    'schema': 'Schéma des champs cibles (objet JSON)',
    'field_maps': 'Correspondances des champs par couche (objet JSON)',
    'reprojection_options': 'Paramètres géodésiques facultatifs (objet JSON)',
    'conversion_errors': 'Échec de conversion',
    'missing_fields': 'Champs absents',
    'extra_fields': 'Champs hors du schéma cible',
    'driver': 'Format de sortie',
    'output_layer': 'Nom de la couche de sortie',
    'field_map': 'Renommage des champs (objet source : nom de sortie)',
    'dtype': 'Type numérique',
    'nodata': 'NoData : preserve, null ou valeur',
    'compression': 'Compression',
    'overviews': 'Facteurs des pyramides (liste ; vide : source)',
    'resampling': 'Rééchantillonnage',
    'loss_policy': 'Différences après conversion',
    'filters': 'Critères attributaires (liste JSON)',
    'attribute_match': 'Combinaison des critères attributaires',
    'mask_layer': 'Couche du masque spatial',
    'combination': 'Combinaison attributs et localisation',
    'invert': 'Inverser la sélection finale',
})
PATHS={'data','source','left','right','mask','zones','before','after','training','validation','model','valid_footprint','outlets','table','observations','aoi'}
PATHS.update({'reference', 'allowed_gaps'})
COMPLEX={'inputs','sources','kernel','mapping','products','indices','border_values','nodata_values','keep_values','classes','band_map','bands','predictors','rgb','start','end','bbox','collections','assets','band_order','table_dtypes'}
COMPLEX.update({'keys', 'rules', 'operations', 'area_of_interest'})
COMPLEX.update({'schema', 'field_maps', 'reprojection_options'})
COMPLEX.update({'field_map', 'overviews'})
COMPLEX.add('filters')
CHOICES={
    'snap':[('Sur le segment le plus proche','edge'),('Sur le sommet le plus proche','node')],
    'null_keys':[('Ne pas apparier','unmatched'),('Apparier les clés manquantes','match'),('Refuser les clés manquantes','error')],
    'value_mode':[('Valeurs physiques (calibration du raster)','physical'),('Valeurs brutes (DN)','raw')],
}
OPERATION_CHOICES = {
    'vector.extract_features': {
        'attribute_match': [('Tous les critères', 'all'), ('Au moins un critère', 'any')],
        'combination': [('Attributs ET localisation', 'and'), ('Attributs OU localisation', 'or')],
        'predicate': [(name, name) for name in ('intersects', 'within', 'contains', 'covers',
                                               'covered_by', 'touches', 'overlaps', 'crosses', 'disjoint')],
    },
    'vector.convert': {
        'driver': [('GeoPackage', 'GPKG'), ('GeoJSON', 'GeoJSON'),
                   ('Shapefile', 'ESRI Shapefile'), ('FlatGeobuf', 'FlatGeobuf')],
        'loss_policy': [('Interrompre si une perte est détectée', 'error'),
                        ('Accepter et consigner les pertes', 'report')],
    },
    'raster.convert': {
        'driver': [('GeoTIFF', 'GTiff'), ('GeoTIFF optimisé (COG)', 'COG')],
        'dtype': [('Conserver le type source', None)] + [(value, value) for value in
                  ('uint8', 'int8', 'uint16', 'int16', 'uint32', 'int32', 'uint64', 'int64', 'float32', 'float64')],
        'compression': [('LZW', 'lzw'), ('Deflate', 'deflate'), ('Zstandard', 'zstd'), ('Sans compression', 'none')],
        'resampling': [('Plus proche voisin', 'nearest'), ('Bilinéaire', 'bilinear'), ('Cubique', 'cubic'),
                       ('Moyenne', 'average'), ('Valeur majoritaire', 'mode')],
        'loss_policy': [('Interrompre si une perte est détectée', 'error'),
                        ('Accepter et consigner les pertes', 'report')],
    },
    'vector.merge_layers': {
        'conversion_errors': [('Interrompre', 'error'), ('Valeur nulle et rapport', 'null')],
        'missing_fields': [('Valeur nulle ou défaut', 'null'), ('Interrompre', 'error')],
        'extra_fields': [('Interrompre', 'error'), ('Écarter et consigner', 'drop')],
    },
    'vector.reproject_batch': {
        'area_policy': [('Arrêter le lot', 'error'), ('Continuer avec un avertissement', 'warn')],
    },
    'vector.repair_geometries': {
        'method': [('Conserver les arêtes et sommets', 'linework'), ('Reconstruire les contours et trous', 'structure')],
        'missing': [('Conserver et signaler', 'keep'), ('Écarter', 'drop'), ('Interrompre', 'error')],
        'empty': [('Conserver et signaler', 'keep'), ('Écarter', 'drop'), ('Interrompre', 'error')],
        'type_changes': [('Accepter et signaler', 'allow'), ('Écarter', 'drop'), ('Interrompre', 'error')],
    },
    'vector.deduplicate': {
        'null_keys': [('Considérer comme distinctes', 'distinct'), ('Regrouper', 'match'), ('Refuser', 'error')],
        'geometry': [('Ne pas comparer', 'none'), ('Strictement identique', 'exact'), ('Égalité topologique', 'topological')],
        'keep': [('Conserver le premier', 'first'), ('Conserver le dernier', 'last'), ('Écarter tout le groupe', 'none')],
    },
}


class OperationDialog(QDialog):
    def __init__(self,steps,record=None,parent=None,*,allow_map=True):
        super().__init__(parent);self.setWindowTitle('Étape de traitement');self.resize(620,620)
        self.previous=steps;self.record=record;self.allow_map=allow_map;layout=QVBoxLayout(self);form=QFormLayout()
        self.ident=QLineEdit(record['id'] if record else f'process_{len(steps)+1:02d}')
        self.operation=QComboBox()
        for spec in operation_catalog():self.operation.addItem(spec['label'],spec['id'])
        form.addRow('Identifiant du résultat',self.ident);form.addRow('Opération',self.operation);layout.addLayout(form)
        scroll=QScrollArea();scroll.setWidgetResizable(True);self.fields=QWidget();self.form=QFormLayout(self.fields);scroll.setWidget(self.fields);layout.addWidget(scroll)
        self.product=QComboBox();product_label=QLabel('Produit cartographique');layout.addWidget(product_label);layout.addWidget(self.product)
        self.add_map=QCheckBox('Ajouter le résultat à la carte');self.add_map.setChecked(record is not None and record.get('map_layer') is not None);layout.addWidget(self.add_map)
        for widget in (product_label,self.product,self.add_map):widget.setVisible(allow_map)
        note=QLabel('Choisir un fichier ou le résultat d’une étape précédente. Les identifiants précédés de @ désignent des résultats intermédiaires.');note.setWordWrap(True);layout.addWidget(note)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)
        self.operation.currentIndexChanged.connect(self.changed)
        if record:self.operation.setCurrentIndex(self.operation.findData(record['operation']))
        self.changed()
        if record:
            self.product.setCurrentIndex(max(0,self.product.findText((record.get('map_layer') or {}).get('product','primary'))))
            for name,value in record['parameters'].items():
                if name in self.controls:
                    widget=self.controls[name]
                    if name in self._choices:
                        index=widget.findData(value)
                        if index<0:
                            self._invalid_choices[name]=value
                            widget.setPlaceholderText(f'Valeur inconnue : {value!r} — choisir')
                        widget.setCurrentIndex(index)
                    elif value is None:
                        self._explicit_nulls.add(name)
                        if isinstance(widget,QCheckBox):widget.setTristate(True);widget.setCheckState(Qt.CheckState.PartiallyChecked)
                        else:widget.setCurrentText('')
                    elif isinstance(widget,QCheckBox):widget.setChecked(bool(value))
                    else:widget.setCurrentText(json.dumps(value,ensure_ascii=False) if isinstance(value,(dict,list,tuple)) else str(value))
    def changed(self):
        while self.form.rowCount():self.form.removeRow(0)
        self.controls={};self._explicit_nulls=set();self._invalid_choices={};spec=operation_spec(self.operation.currentData())
        self._choices = {**CHOICES, **OPERATION_CHOICES.get(spec['id'], {})}
        self.add_map.setEnabled(self.allow_map and spec['output'] in {'raster','vector'});self.product.clear();self.product.addItems(spec['products'])
        for field in spec['parameters']:
            name=field['name'];default=field['default'];label=LABELS.get(name,name.replace('_',' '))+(' *' if field['required'] else '')
            if spec['id'] == 'vector.repair_geometries' and name == 'tolerance':
                label='Pas de grille XY (unités du SCR source projeté ; 0 désactive)'
            if spec['id'] == 'vector.convert' and name == 'encoding':
                label='Encodage des caractères (UTF-8 hors Shapefile)'
            if spec['id'] in {'vector.reproject_batch', 'vector.merge_layers'} and name=='sources':
                label='Fichiers, dossiers ou couches sélectionnées (liste JSON) *'
            if name in self._choices:
                widget=QComboBox();widget.setPlaceholderText('Choisir une valeur')
                for title,value in self._choices[name]:widget.addItem(title,value)
                widget.setCurrentIndex(widget.findData(default));row=widget
            elif isinstance(default,bool):widget=QCheckBox();widget.setChecked(default);row=widget
            else:
                widget=QComboBox();widget.setEditable(True);widget.setMinimumWidth(270)
                if name in PATHS:
                    widget.addItem('');widget.addItem('@scientific')
                    for step in self.previous:
                        widget.addItem('@'+step['id'])
                        for product in operation_spec(step['operation'])['products'][1:]:widget.addItem('@'+step['id']+':'+product)
                text=json.dumps(default,ensure_ascii=False) if isinstance(default,(list,tuple,dict)) else str(default) if default is not None else ''
                widget.setCurrentText(text);row=widget
                if name in PATHS:
                    row=QWidget();line=QHBoxLayout(row);line.setContentsMargins(0,0,0,0);line.addWidget(widget)
                    button=QPushButton('Parcourir');line.addWidget(button)
                    button.clicked.connect(lambda checked=False,w=widget:self.browse(w))
            self.controls[name]=widget;self.form.addRow(label,row)
    def browse(self,widget):
        path=QFileDialog.getOpenFileName(self,'Donnée source')[0]
        if path:widget.setCurrentText(path)
    def value(self):
        parameters={};spec=operation_spec(self.operation.currentData())
        for field in spec['parameters']:
            name=field['name'];widget=self.controls[name]
            if name in self._choices:
                if widget.currentIndex()<0:
                    detail=f' (valeur enregistrée non reconnue : {self._invalid_choices[name]!r})' if name in self._invalid_choices else ''
                    raise ValueError('Choisir '+LABELS.get(name,name)+detail)
                value=widget.currentData()
            elif isinstance(widget,QCheckBox):value=None if widget.checkState()==Qt.CheckState.PartiallyChecked else widget.isChecked()
            else:
                text=widget.currentText().strip()
                if not text:
                    if name in self._explicit_nulls:
                        parameters[name]=None
                        continue
                    if field['required']:raise ValueError('Renseigner '+LABELS.get(name,name))
                    continue
                default=field['default']
                if name in PATHS or name in {'layer', 'mask_layer', 'id_field'}:value=text
                elif name in COMPLEX or isinstance(default,(list,tuple,dict)):value=json.loads(text)
                elif isinstance(default,int):value=int(text)
                elif isinstance(default,float):value=float(text)
                else:
                    try:value=json.loads(text)
                    except json.JSONDecodeError:value=text
            parameters[name]=value
        validate_parameters(spec['id'],parameters)
        record=dict(id=self.ident.text().strip(),operation=spec['id'],parameters=parameters)
        if self.add_map.isEnabled() and self.add_map.isChecked():record['map_layer']=deepcopy(self.record.get('map_layer',{})) if self.record else {}
        if record.get('map_layer') is not None:
            record['map_layer'].pop('product',None)
            if self.product.currentText()!='primary':record['map_layer']['product']=self.product.currentText()
        return record
    def accept(self):
        try:
            record=self.value()
            import re
            if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}',record['id']):raise ValueError('Identifiant : lettres, chiffres et soulignement, commençant par une lettre.')
            if record['id'] in {s['id'] for s in self.previous}:raise ValueError('Cet identifiant existe déjà.')
            self.result_record=record
        except (ValueError,TypeError) as exc:QMessageBox.warning(self,'Paramètres',str(exc));return
        super().accept()


class ProcessingSteps(QWidget):
    def __init__(self,parent=None,*,allow_map=True):
        super().__init__(parent);self.allow_map=allow_map;layout=QVBoxLayout(self)
        self.table=QTableWidget(0,3);self.table.setHorizontalHeaderLabels(['Résultat','Opération','Ajouter à la carte']);self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows);self.table.setMinimumHeight(170);layout.addWidget(self.table)
        self.table.setColumnHidden(2,not allow_map)
        row=QHBoxLayout();layout.addLayout(row)
        for text,fn in [('Ajouter',self.add),('Modifier',self.edit),('Monter',lambda:self.move(-1)),('Descendre',lambda:self.move(1)),('Retirer',self.remove)]:
            button=QPushButton(text);button.clicked.connect(fn);row.addWidget(button)
    def records(self):return [deepcopy(self.table.item(r,0).data(Qt.ItemDataRole.UserRole)) for r in range(self.table.rowCount())]
    def set_records(self,records):
        self.table.setRowCount(0)
        for record in records:
            row=self.table.rowCount();self.table.insertRow(row)
            for col,text in enumerate([record['id'],operation_spec(record['operation'])['label'],'Oui' if record.get('map_layer') is not None else 'Non']):
                item=QTableWidgetItem(text);item.setFlags(item.flags()&~Qt.ItemFlag.ItemIsEditable)
                if col==0:item.setData(Qt.ItemDataRole.UserRole,deepcopy(record))
                self.table.setItem(row,col,item)
        self.table.resizeColumnsToContents()
    def add(self):
        records=self.records();dialog=OperationDialog(records,parent=self,allow_map=self.allow_map)
        if dialog.exec():self.set_records(records+[dialog.result_record])
    def edit(self):
        row=self.table.currentRow();records=self.records()
        if row<0:return
        dialog=OperationDialog(records[:row],records[row],self,allow_map=self.allow_map)
        if dialog.exec():records[row]=dialog.result_record;self.set_records(records)
    def move(self,offset):
        row=self.table.currentRow();records=self.records();other=row+offset
        if row>=0 and 0<=other<len(records):records[row],records[other]=records[other],records[row];self.set_records(records);self.table.selectRow(other)
    def remove(self):
        row=self.table.currentRow()
        if row>=0:self.table.removeRow(row)



from .desktop import Page,PathField
class ProcessingPage(Page):
    engine=True
    staged=True
    def __init__(self):
        super().__init__('Chaîne de traitements','Définir les opérations et leurs dépendances, puis exécuter l’ensemble dans un nouveau dossier.')
        self.processing_steps=ProcessingSteps(allow_map=False);self.form.addRow(self.processing_steps)
        self.output.mode='directory';self.name=QLineEdit('traitements');self.form.addRow('Répertoire parent',self.output);self.form.addRow('Nouveau dossier',self.name);self.layout.addStretch()
    def job(self,options):
        from .automation import processing_plan,run_plan
        from pathlib import Path
        from .recipes import safe_name
        plan=processing_plan(self.processing_steps.records());destination=Path(self.destination())/safe_name(self.name.text())
        engine={k:options[k] for k in ('execution','device','scheduler_address') if k in options}
        return lambda progress,cancel,stage:run_plan(plan,destination,workers=options.get('workers',1),block_size=options.get('block_size',512),memory_limit_mb=options.get('memory_limit_mb',512),progress=progress,cancel=cancel,stage=stage,**engine)
