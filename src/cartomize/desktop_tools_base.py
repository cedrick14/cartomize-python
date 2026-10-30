"""Desktop access to the existing vector and raster processing APIs."""
from pathlib import Path
import json
import os
import tempfile
import math
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox,QLineEdit,QLabel,QPlainTextEdit,QPushButton,QCheckBox,QSizePolicy
import cartomize as cm
from .desktop import Page,PathField,spin,real,RASTER_FILTER,VECTOR_FILTER
from .desktop_reprojection import BatchReprojectionControls
from .desktop_merge import MergeControls
from ._validation import output_path


def _json_value(value):
    if isinstance(value,dict):return {str(k):_json_value(v) for k,v in value.items()}
    if isinstance(value,(tuple,list)):return [_json_value(v) for v in value]
    if isinstance(value,np.generic):return _json_value(value.item())
    if isinstance(value,float) and not math.isfinite(value):return None
    if isinstance(value,(str,int,float,bool)) or value is None:return value
    return str(value)


def write_result(result,destination,*,sources=(),overwrite=False):
    """Stage a single table/vector/report file; never overwrite an input."""
    destination=output_path(destination,overwrite,sources)
    suffix=destination.suffix.lower()
    if suffix not in {'.json','.csv','.geojson','.gpkg'}:raise ValueError('Choisir un fichier JSON, CSV, GeoJSON ou GeoPackage selon le résultat.')
    with tempfile.TemporaryDirectory(prefix='.cartomize-output-',dir=destination.parent) as temporary:
        staged=Path(temporary)/destination.name
        if isinstance(result,dict):
            if suffix!='.json':raise ValueError('Le rapport doit être enregistré en JSON.')
            staged.write_text(json.dumps(_json_value(result),ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
        elif hasattr(result,'geometry'):
            if suffix not in {'.gpkg','.geojson'}:raise ValueError('Une couche vectorielle exige un fichier .gpkg ou .geojson.')
            if suffix=='.gpkg':
                from .vector_io import write_geopackage
                write_geopackage(result,staged,layer=staged.stem)
            else:
                result.to_file(staged,driver='GeoJSON',index=False)
        else:
            if suffix!='.csv':raise ValueError('Le tableau doit être enregistré en CSV.')
            result.to_csv(staged,index=False)
        os.replace(staged,destination)
    return destination


class InspectionPage(Page):
    engine=False
    cancellable=False
    def __init__(self):
        super().__init__('Analyse des couches','Contrôle des géométries, des attributs, des systèmes de coordonnées, des bandes et du NoData.')
        self.kind=QComboBox();self.kind.addItem('Couche vectorielle','vector');self.kind.addItem('Raster','raster')
        self.source=PathField(filter=VECTOR_FILTER);self.band=spin();self.report=QPlainTextEdit();self.report.setReadOnly(True)
        self.report.setMinimumHeight(260);self.report.setPlaceholderText('Rapport d’analyse des couches.')
        self.form.addRow('Type de données',self.kind);self.form.addRow('Couche',self.source);self.form.addRow('Bande raster',self.band)
        note=QLabel('Les diagnostics raster reposent sur un échantillon. Les valeurs NoData suggérées ne sont pas appliquées aux données.')
        note.setWordWrap(True);self.form.addRow(note);self.form.addRow(self.report)
        self.output.filter='Rapport JSON (*.json)';self.finish()
        self.kind.currentIndexChanged.connect(self.changed);self.changed()
    def changed(self):
        raster=self.kind.currentData()=='raster';self.source.filter=RASTER_FILTER if raster else VECTOR_FILTER
        self.band.setVisible(raster);self.form.labelForField(self.band).setVisible(raster)
    def job(self,options):
        source=self.source.text();kind=self.kind.currentData();band=self.band.value();destination=self.destination()
        def run(progress,cancel):
            result=cm.raster.inspect(source,band=band) if kind=='raster' else cm.vector.analyze(source,name=Path(source).stem)
            return write_result(result,destination,sources=(source,),overwrite=options['overwrite'])
        return run
    def show_result(self,path):self.report.setPlainText(Path(path).read_text(encoding='utf-8'))


class VectorPage(MergeControls, BatchReprojectionControls, Page):
    engine=False
    cancellable=False
    OPERATIONS=[('Découpage','clip'),('Zone tampon','buffer'),('Intersection','intersection'),('Union','union'),
                ('Différence','difference'),('Différence symétrique','symmetric_difference'),('Jointure spatiale','sjoin'),
                ('Dissolution','dissolve'),('Reprojection','reproject'),('Réparation des géométries','make_valid'),
                ('Calcul des superficies','area'),('Calcul des longueurs','length'),('Proximité','nearest')]
    def __init__(self):
        super().__init__('Traitements vectoriels','Opérations géométriques, superpositions, jointures spatiales et mesures.')
        self.operation=QComboBox()
        for label,value in self.OPERATIONS:self.operation.addItem(label,value)
        self.source=PathField(filter=VECTOR_FILTER);self.secondary=PathField(filter=VECTOR_FILTER)
        self.crs=QLineEdit();self.crs.setPlaceholderText('Exemple : EPSG:32733');self.distance=real(100)
        self.maximum=real(0);self.maximum.setMinimum(0);self.maximum.setSpecialValueText('Sans limite')
        self.field=QLineEdit();self.field.setPlaceholderText('Vide : dissolution de toutes les entités')
        self.predicate=QComboBox();self.predicate.addItems(['intersects','within','contains','touches','overlaps'])
        self.join=QComboBox();self.join.addItem('Conserver les correspondances','inner');self.join.addItem('Conserver toutes les entités de gauche','left')
        self.unit=QComboBox();self.unit.addItems(['ha','m2','km2'])
        for label,widget in [('Opération',self.operation),('Couche source',self.source),('Couche de superposition',self.secondary),
            ('Système de coordonnées projeté',self.crs),('Distance (m)',self.distance),('Champ de dissolution',self.field),
            ('Distance maximale (m)',self.maximum),('Relation spatiale',self.predicate),('Type de jointure',self.join),('Unité',self.unit)]:self.form.addRow(label,widget)
        self.output.filter='GeoPackage (*.gpkg);;GeoJSON (*.geojson)';self.finish()
        self.init_reprojection_controls()
        self.init_merge_controls()
        self.operation.currentIndexChanged.connect(self.changed);self.changed()
    def changed(self):
        op=self.operation.currentData()
        show={self.secondary:op in {'clip','intersection','union','difference','symmetric_difference','sjoin','nearest'},
            self.crs:op in {'buffer','reproject','area','length','nearest'},self.distance:op=='buffer',self.field:op=='dissolve',self.maximum:op=='nearest',
            self.predicate:op=='sjoin',self.join:op in {'sjoin','nearest'},self.unit:op in {'area','length'}}
        for widget,visible in show.items():widget.setVisible(visible);self.form.labelForField(widget).setVisible(visible)
        self.unit.clear();self.unit.addItems(['m','km'] if op=='length' else ['ha','m2','km2'])
        self.update_reprojection_controls()
        self.update_merge_controls()
    def job(self,options):
        if self.operation.currentData()=='merge_layers':
            return self.merge_job(options)
        if self.operation.currentData()=='reproject_batch':
            return self.reprojection_job(options)
        op=self.operation.currentData();source=self.source.text();other=self.secondary.text();crs=self.crs.text().strip() or None
        distance=self.distance.value();field=self.field.text().strip() or None;unit=self.unit.currentText()
        predicate=self.predicate.currentText();how=self.join.currentData();destination=self.destination()
        needs_other=op in {'clip','intersection','union','difference','symmetric_difference','sjoin','nearest'}
        maximum=self.maximum.value() or None
        if not source or (needs_other and not other):raise ValueError('Renseigner les couches nécessaires au traitement.')
        if op=='reproject' and not crs:raise ValueError('Renseigner le système de coordonnées cible.')
        def run(progress,cancel):
            if op=='clip':result=cm.clip(source,other)
            elif op=='buffer':result=cm.buffer(source,distance,metric_crs=crs)
            elif op in {'intersection','union','difference','symmetric_difference'}:result=cm.overlay(source,other,how=op)
            elif op=='sjoin':result=cm.sjoin(source,other,how=how,predicate=predicate)
            elif op=='nearest':result=cm.nearest(source,other,metric_crs=crs,max_distance=maximum,how=how)
            elif op=='dissolve':result=cm.dissolve(source,by=field)
            elif op=='reproject':result=cm.reproject(source,crs)
            elif op=='make_valid':result=cm.make_valid(source)
            else:
                result=cm.read_file(source);values=cm.area(result,unit,metric_crs=crs) if op=='area' else cm.length(result,unit,metric_crs=crs)
                if values.name in result.columns:raise ValueError(f'Le champ {values.name} existe déjà.')
                result[values.name]=values
            sources=(source,other) if needs_other else (source,)
            return write_result(result,destination,sources=sources,overwrite=options['overwrite'])
        return run


class RasterToolsPage(Page):
    engine=False
    cancellable=False
    def __init__(self):
        super().__init__('Traitements raster','Découpage, reprojection, reclassification, statistiques zonales, surfaces et transitions.')
        self.operation=QComboBox()
        for label,value in [('Extraction par masque','clip'),('Reprojection','reproject'),('Reclassification','reclassify'),
            ('Statistiques zonales','zonal_stats'),('Superficies par classe','class_areas'),('Matrice de transition','change_matrix')]:self.operation.addItem(label,value)
        self.source=PathField();self.secondary=PathField(filter=VECTOR_FILTER);self.band=spin()
        self.crs=QLineEdit();self.crs.setPlaceholderText('Exemple : EPSG:32733');self.resolution=real(0);self.resolution.setMinimum(0);self.resolution.setSpecialValueText('Automatique')
        self.resampling=QComboBox()
        for label,value in [('Plus proche voisin','nearest'),('Bilinéaire','bilinear'),('Cubique','cubic')]:self.resampling.addItem(label,value)
        self.mapping=QPlainTextEdit();self.mapping.setPlaceholderText('Valeur initiale = nouvelle valeur\n1 = 1\n2 = 0\n3 = 0');self.mapping.setMaximumHeight(140)
        self.unmatched=QComboBox();self.unmatched.addItem('Affecter NoData','nodata');self.unmatched.addItem('Conserver la valeur','keep')
        self.unit=QComboBox();self.unit.addItems(['ha','m2','km2'])
        self.value_mode=QComboBox()
        self.value_mode.addItem('Valeurs physiques (calibration du raster)','physical');self.value_mode.addItem('Valeurs brutes (DN)','raw')
        self.zonal_prefix=QLineEdit();self.zonal_prefix.setPlaceholderText('Exemple : ndvi_ ; vide : count, mean…')
        self.include_coverage=QCheckBox('Ajouter la couverture valide')
        self.include_coverage.setToolTip('Ajouter zone_pixels, raster_pixels et coverage_percent : pixels de toute la zone, pixels dans le raster et pourcentage de pixels valides. Le dénominateur inclut la partie hors du raster.')
        self.all_touched=QComboBox()
        self.all_touched.addItem('Centre du pixel dans la zone (par défaut)',False);self.all_touched.addItem('Tous les pixels touchés par la zone',True)
        for choice in (self.value_mode,self.all_touched):
            choice.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            choice.setMinimumContentsLength(12)
            choice.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
            for index in range(choice.count()):choice.setItemData(index,choice.itemText(index),Qt.ItemDataRole.ToolTipRole)
            choice.currentTextChanged.connect(choice.setToolTip);choice.setToolTip(choice.currentText())
        self.max_zone_pixels=spin(250_000_000,1,2_147_483_647);self.max_zone_pixels.setGroupSeparatorShown(True)
        self.max_zone_pixels.setToolTip('Limite du nombre de pixels de la fenêtre examinée par zone ; la partie hors du raster est incluse si la couverture est demandée.')
        self.zonal_note=QLabel('Valeur physique = valeur brute × facteur + décalage des métadonnées de la bande ; sans calibration, facteur 1 et décalage 0. '
            'Les pixels NoData ou masqués sont exclus ; un zéro valide est conservé. La couverture mesure la part de pixels valides sur toute la zone, y compris sa partie hors du raster.')
        self.zonal_note.setWordWrap(True)
        for label,widget in [('Opération',self.operation),('Raster source',self.source),('Bande',self.band),('Masque ou raster de comparaison',self.secondary),
            ('Système de coordonnées cible',self.crs),('Résolution (unités du système cible)',self.resolution),('Rééchantillonnage',self.resampling),
            ('Correspondance des classes',self.mapping),('Valeurs sans correspondance',self.unmatched),('Unité de superficie',self.unit),
            ('Valeurs utilisées',self.value_mode),('Préfixe des champs de résultat',self.zonal_prefix),('Couverture de chaque zone',self.include_coverage),
            ('Inclusion des pixels',self.all_touched),('Limite de pixels candidats par zone',self.max_zone_pixels)]:
            self.form.addRow(label,widget);self.form.labelForField(widget).setWordWrap(True)
        self.form.addRow(self.zonal_note)
        self.finish();self.operation.currentIndexChanged.connect(self.changed);self.changed()
    def changed(self):
        op=self.operation.currentData()
        show={self.secondary:op in {'clip','zonal_stats','change_matrix'},self.crs:op=='reproject',self.resolution:op=='reproject',
            self.resampling:op=='reproject',self.mapping:op=='reclassify',self.unmatched:op=='reclassify',self.unit:op=='class_areas',
            self.value_mode:op=='zonal_stats',self.zonal_prefix:op=='zonal_stats',self.include_coverage:op=='zonal_stats',
            self.all_touched:op in {'clip','zonal_stats'},self.max_zone_pixels:op=='zonal_stats'}
        for widget,visible in show.items():widget.setVisible(visible);self.form.labelForField(widget).setVisible(visible)
        self.zonal_note.setVisible(op=='zonal_stats');self.cancellable=op=='zonal_stats'
        self.secondary.filter=RASTER_FILTER if op=='change_matrix' else VECTOR_FILTER
        self.output.filter='Tableau CSV (*.csv)' if op in {'class_areas','change_matrix'} else 'GeoPackage (*.gpkg);;GeoJSON (*.geojson)' if op=='zonal_stats' else 'GeoTIFF (*.tif)'
        suffix='.csv' if op in {'class_areas','change_matrix'} else '.gpkg' if op=='zonal_stats' else '.tif'
        if self.output.text():self.output.edit.setText(str(Path(self.output.text()).with_suffix(suffix)))
    def job(self,options):
        op=self.operation.currentData();source=self.source.text();other=self.secondary.text();band=self.band.value();destination=self.destination()
        crs=self.crs.text().strip();resolution=self.resolution.value() or None;resampling=self.resampling.currentData();unit=self.unit.currentText();unmatched=self.unmatched.currentData()
        all_touched=self.all_touched.currentData()
        zonal=dict(value_mode=self.value_mode.currentData(),prefix=self.zonal_prefix.text().strip(),include_coverage=self.include_coverage.isChecked(),
                   all_touched=all_touched,max_zone_pixels=self.max_zone_pixels.value(),block_size=options.get('block_size',512))
        mapping={}
        if op=='reclassify':
            for line in self.mapping.toPlainText().splitlines():
                if not line.strip():continue
                try:key,value=[float(v.strip()) for v in line.split('=')]
                except ValueError:raise ValueError('Reclassification : une ligne par correspondance, sous la forme 1 = 0.') from None
                if key in mapping:raise ValueError('Une valeur initiale ne peut avoir deux correspondances.')
                mapping[key]=value
        if op=='reproject' and not crs:raise ValueError('Renseigner le système de coordonnées cible.')
        sources=(source,other) if op in {'clip','zonal_stats','change_matrix'} else (source,)
        # Check all inputs, including the vector mask, before invoking any writer.
        output_path(destination,options['overwrite'],sources)
        def run(progress,cancel):
            kwargs=dict(band=band,overwrite=options['overwrite'])
            if op=='clip':return cm.raster.clip(source,other,destination,all_touched=all_touched,**kwargs)
            if op=='reproject':return cm.raster.reproject(source,destination,crs,resolution=resolution,resampling=resampling,**kwargs)
            if op=='reclassify':return cm.raster.reclassify(source,destination,mapping,unmatched=unmatched,**kwargs)
            if op=='zonal_stats':
                result=cm.raster.zonal_stats(source,other,band=band,progress=progress,cancel=cancel,**zonal)
                if cancel.is_set():raise cm.ProcessingCancelled()
            elif op=='class_areas':result=cm.raster.class_areas(source,band=band,unit=unit)
            else:result=cm.raster.change_matrix(source,other,band=band)
            return write_result(result,destination,sources=sources,overwrite=options['overwrite'])
        return run
