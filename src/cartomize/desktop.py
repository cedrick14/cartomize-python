"""Optional Qt desktop application for Cartomize processing tools."""
from pathlib import Path
import os
import sys
import threading
import tempfile

try:
    from PySide6.QtCore import Qt, QObject, QThread, Signal, Slot, QUrl, QSize, QSettings
    from PySide6.QtGui import QDesktopServices, QIcon, QPixmap, QColor, QPalette
    from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QHBoxLayout,QVBoxLayout,
        QFormLayout,QLabel,QLineEdit,QPushButton,QFileDialog,QListWidget,QListWidgetItem,
        QStackedWidget,QComboBox,QSpinBox,QDoubleSpinBox,QCheckBox,QPlainTextEdit,
        QTableWidget,QTableWidgetItem,QHeaderView,QProgressBar,QMessageBox,QGroupBox,QScrollArea,QTabWidget,QSplitter,QToolButton,QListView,QDockWidget,QSizePolicy)
except ImportError as exc:
    raise ImportError('Interface graphique indisponible. Installer : python -m pip install "cartomize[gui]"') from exc

from .desktop_connections import ProjectConnections
from .desktop_session import SessionControls

import rasterio
import cartomize as cm
from .composition import ORDER

RASTER_FILTER="Données raster (*.tif *.tiff *.vrt *.img *.jp2);;Tous les fichiers (*)"
VECTOR_FILTER="Données vectorielles (*.gpkg *.shp *.geojson *.json *.fgb);;Tous les fichiers (*)"
STATISTICS={"Moyenne":"mean","Somme":"sum","Minimum":"min","Maximum":"max","Écart-type":"std","Nombre de valeurs valides":"count"}
ROLE_LABELS={"Fond raster":"background","Occupation du sol":"landcover","Données thématiques":"thematic",
             "Polygones":"polygon","Hydrographie":"water","Lignes":"line","Routes":"roads",
             "Voies ferrées":"railways","Limites administratives":"boundaries","Localités":"localities","Points":"points"}


class PathField(QWidget):
    def __init__(self,mode="open",filter=RASTER_FILTER):
        super().__init__();self.mode=mode;self.filter=filter
        layout=QHBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        self.edit=QLineEdit();button=QPushButton("Parcourir…")
        layout.addWidget(self.edit,1);layout.addWidget(button);button.clicked.connect(self.browse)
    def browse(self):
        if self.mode=="directory":path=QFileDialog.getExistingDirectory(self,"Sélectionner un répertoire",self.edit.text())
        elif self.mode=="save":path=QFileDialog.getSaveFileName(self,"Fichier de sortie",self.edit.text(),self.filter)[0]
        else:path=QFileDialog.getOpenFileName(self,"Données d’entrée",self.edit.text(),self.filter)[0]
        if path:self.edit.setText(path)
    def text(self):return self.edit.text().strip()


def spin(value=1,minimum=1,maximum=999):
    widget=QSpinBox();widget.setRange(minimum,maximum);widget.setValue(value);return widget


def real(value=1.):
    widget=QDoubleSpinBox();widget.setDecimals(8);widget.setRange(-1e9,1e9);widget.setValue(value);return widget


class Page(QWidget):
    staged=False
    cancellable=True
    engine=True
    def __init__(self,title,description):
        super().__init__();self.layout=QVBoxLayout(self)
        heading=QLabel(title);heading.setObjectName("pageTitle");heading.setWordWrap(True)
        detail=QLabel(description);detail.setWordWrap(True);detail.setObjectName("description")
        self.page_help=self.context_help(description,heading=heading,content=detail)
        self.layout.addWidget(self.page_help)
        self.parameter_card=QGroupBox('Paramètres');self.parameter_card.setObjectName('parameterCard')
        self.form=QFormLayout(self.parameter_card);self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        self.layout.addWidget(self.parameter_card)
        self.output=PathField("save","GeoTIFF (*.tif)")
    @staticmethod
    def context_help(text,*,subject="Cet outil",heading=None,summary=None,content=None):
        """Keep explanatory text available without hiding operational messages."""
        section=QWidget();section.setObjectName("contextHelp")
        # Form rows must keep their wrapped height even when the detail is hidden.
        section.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Expanding)
        layout=QVBoxLayout(section);layout.setContentsMargins(0,0,0,0);layout.setSpacing(3)
        row=QHBoxLayout();row.setContentsMargins(0,0,0,0)
        if heading is not None:
            # Preserve heightForWidth while allowing the title to wrap beside Aide.
            policy=heading.sizePolicy();policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
            heading.setSizePolicy(policy)
            row.addWidget(heading,1)
        elif summary:
            note=QLabel(summary);note.setWordWrap(True);note.setTextFormat(Qt.TextFormat.PlainText)
            note.setObjectName("helpSummary");row.addWidget(note,1)
        button=QToolButton();button.setObjectName("helpToggle");button.setText("Aide")
        button.setCheckable(True);button.setAutoRaise(True)
        button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        button.setArrowType(Qt.ArrowType.RightArrow)
        button.setAccessibleName("Aide : "+subject)
        button.setToolTip("Afficher l’aide : "+subject)
        row.addWidget(button)
        if heading is None and not summary:row.addStretch()
        layout.addLayout(row)
        detail=content if content is not None else QLabel(text)
        if content is None:detail.setObjectName("helpText")
        detail.setWordWrap(True);detail.setTextFormat(Qt.TextFormat.PlainText)
        detail.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred)
        detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse|Qt.TextInteractionFlag.TextSelectableByKeyboard)
        detail.hide();layout.addWidget(detail)
        def expanded(checked):
            detail.setVisible(checked)
            button.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)
            button.setToolTip(("Masquer" if checked else "Afficher")+" l’aide : "+subject)
        button.toggled.connect(expanded)
        return section
    def add_help(self,text,*,subject="Cet outil",summary=None,form=None):
        section=self.context_help(text,subject=subject,summary=summary)
        (self.form if form is None else form).addRow(section)
        return section
    def finish(self):
        self.form.addRow("Fichier de sortie",self.output);self.layout.addStretch()
    def destination(self):
        if not self.output.text():raise ValueError("Sélectionner un fichier de sortie.")
        return self.output.text()


class IndicesPage(Page):
    def __init__(self):
        super().__init__("Indices spectraux","Calcul multibande des indices de végétation, d’humidité, d’eau, de sol et du bâti.")
        self.source=PathField();self.form.addRow("Raster multispectral",self.source)
        self.selection=QListWidget();self.selection.setMaximumHeight(165)
        for definition in cm.list_indices():
            item=QListWidgetItem(f"{definition['name']} : {definition['title']}",self.selection)
            item.setData(Qt.ItemDataRole.UserRole,definition["name"])
            item.setFlags(item.flags()|Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if definition["name"]=="NDVI" else Qt.CheckState.Unchecked)
            item.setToolTip(definition["formula"]+"\n"+definition["reference"])
        self.form.addRow("Indices",self.selection)
        self.bands=QTableWidget(0,2);self.bands.setHorizontalHeaderLabels(["Bande spectrale","Numéro de bande"])
        self.bands.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch);self.bands.setMaximumHeight(155)
        self.form.addRow("Correspondance spectrale",self.bands)
        self.parameters=QTableWidget(0,3);self.parameters.setHorizontalHeaderLabels(["Indice","Paramètre","Valeur"])
        self.parameters.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch);self.parameters.setMaximumHeight(110)
        self.form.addRow("Paramètres des indices",self.parameters)
        self.metadata=QCheckBox("Utiliser la calibration enregistrée dans le raster");self.metadata.setChecked(True)
        self.metadata.setToolTip("EVI, SAVI et MSAVI nécessitent des valeurs de réflectance calibrées. Le prétraitement multispectral prépare les produits Landsat et Sentinel pris en charge.")
        self.form.addRow("Calibration",self.metadata)
        self.scale=real(1);self.offset=real(0)
        self.form.addRow("Facteur multiplicatif",self.scale);self.form.addRow("Terme additif",self.offset)
        self.scale.setEnabled(False);self.offset.setEnabled(False)
        self.metadata.toggled.connect(lambda checked:(self.scale.setEnabled(not checked),self.offset.setEnabled(not checked)))
        self.selection.itemChanged.connect(self.refresh);self.source.edit.textChanged.connect(self.refresh)
        self.refresh();self.finish()
    def selected(self):
        return [self.selection.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.selection.count())
                if self.selection.item(i).checkState()==Qt.CheckState.Checked]
    def refresh(self):
        old={self.bands.item(i,0).text():self.bands.cellWidget(i,1).value() for i in range(self.bands.rowCount())}
        if getattr(self,"_band_source",None)!=self.source.text():old={}
        self._band_source=self.source.text()
        definitions=[cm.get_index(name) for name in self.selected()];required=sorted(set().union(*(d.bands for d in definitions)))
        labels=[];count=999
        try:
            with rasterio.open(self.source.text()) as src:
                labels=[(d or src.tags(i).get("semantic_name","")).casefold() for i,d in enumerate(src.descriptions,1)];count=src.count
        except (OSError,rasterio.errors.RasterioError):pass
        self.bands.setRowCount(len(required))
        for row,name in enumerate(required):
            item=QTableWidgetItem(name);item.setFlags(item.flags()&~Qt.ItemFlag.ItemIsEditable);self.bands.setItem(row,0,item)
            matches=[i+1 for i,label in enumerate(labels) if label==name]
            field=spin(matches[0] if len(matches)==1 else old.get(name,0),0,count);field.setSpecialValueText("Non affectée")
            self.bands.setCellWidget(row,1,field)
        params=[(d.name,k,v) for d in definitions for k,v in d.parameters.items()]
        self.parameters.setRowCount(len(params));self.parameters.setVisible(bool(params))
        self.form.labelForField(self.parameters).setVisible(bool(params))
        for row,(name,param,value) in enumerate(params):
            for col,text in enumerate([name,param]):
                item=QTableWidgetItem(text);item.setFlags(item.flags()&~Qt.ItemFlag.ItemIsEditable);self.parameters.setItem(row,col,item)
            self.parameters.setCellWidget(row,2,real(value))
    def job(self,options):
        names=self.selected()
        if not names:raise ValueError("Sélectionner au moins un indice spectral.")
        mapping={self.bands.item(i,0).text():self.bands.cellWidget(i,1).value() for i in range(self.bands.rowCount())}
        if 0 in mapping.values():raise ValueError("Affecter un numéro à chaque bande spectrale requise.")
        params={}
        for i in range(self.parameters.rowCount()):params.setdefault(self.parameters.item(i,0).text(),{})[self.parameters.item(i,1).text()]=self.parameters.cellWidget(i,2).value()
        source=self.source.text();destination=self.destination()
        calibration={} if self.metadata.isChecked() else {"scale":self.scale.value(),"offset":self.offset.value()}
        return lambda progress,cancel:cm.spectral_indices(source,destination,names,band_map=mapping,parameters=params,
               progress=progress,cancel=cancel,**calibration,**options)


class CalculatorPage(Page):
    def __init__(self):
        super().__init__("Calculatrice raster","Algèbre locale, expressions conditionnelles, fonctions mathématiques et reclassification.")
        self.inputs=QTableWidget(0,5);self.inputs.setHorizontalHeaderLabels(["Variable","Fichier raster","Bande","Facteur","Décalage"])
        self.inputs.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeMode.Stretch)
        for col in [0,2,3,4]:self.inputs.setColumnWidth(col,90)
        self.inputs.setMinimumHeight(200);self.form.addRow(self.inputs)
        buttons=QWidget();row=QHBoxLayout(buttons);row.setContentsMargins(0,0,0,0)
        add=QPushButton("Importer des rasters");remove=QPushButton("Supprimer la sélection")
        row.addWidget(add);row.addWidget(remove);row.addStretch();self.form.addRow(buttons)
        add.clicked.connect(self.browse);remove.clicked.connect(self.remove)
        self.expression=QPlainTextEdit();self.expression.setPlaceholderText("(nir - red) / (nir + red)")
        self.expression.setMaximumHeight(115);self.form.addRow("Expression",self.expression)
        self.add_help("Fonctions : where, coalesce, sqrt, log, exp, minimum, maximum, mean, median, std, bitand.",subject="Fonctions de la calculatrice")
        self.align=QCheckBox("Aligner les entrées sur la grille du premier raster");self.form.addRow("Grille",self.align)
        self.finish()
    def browse(self):
        paths=QFileDialog.getOpenFileNames(self,"Données raster",filter=RASTER_FILTER)[0]
        try:
            for path in paths:self.add_raster(path)
        except Exception as exc:QMessageBox.warning(self,"Importation raster",str(exc))
    def add_raster(self,path):
        with rasterio.open(path) as src:
            for index in range(1,src.count+1):
                row=self.inputs.rowCount();self.inputs.insertRow(row)
                alias=src.descriptions[index-1] or f"b{row+1}"
                existing={self.inputs.item(i,0).text() for i in range(row)}
                if not alias.isidentifier() or alias in existing:alias=f"b{row+1}"
                while alias in existing:alias+="_"
                self.inputs.setItem(row,0,QTableWidgetItem(alias));self.inputs.setItem(row,1,QTableWidgetItem(str(path)))
                self.inputs.setCellWidget(row,2,spin(index,1,src.count))
                self.inputs.setCellWidget(row,3,real(src.scales[index-1]));self.inputs.setCellWidget(row,4,real(src.offsets[index-1]))
    def remove(self):
        for row in sorted({i.row() for i in self.inputs.selectedIndexes()},reverse=True):self.inputs.removeRow(row)
    def job(self,options):
        inputs={}
        for i in range(self.inputs.rowCount()):
            name=self.inputs.item(i,0).text().strip()
            if name in inputs:raise ValueError("Les noms des variables doivent être uniques.")
            inputs[name]=cm.Band(self.inputs.item(i,1).text(),index=self.inputs.cellWidget(i,2).value(),
                                scale=self.inputs.cellWidget(i,3).value(),offset=self.inputs.cellWidget(i,4).value())
        expression=self.expression.toPlainText();destination=self.destination();align=self.align.isChecked()
        from .algebra import Expression
        Expression(expression)
        return lambda progress,cancel:cm.calculate(expression,inputs,destination,align=align,progress=progress,cancel=cancel,**options)


class FocalPage(Page):
    def __init__(self):
        super().__init__("Statistiques focales","Analyse du voisinage spatial par fenêtre mobile carrée.")
        self.source=PathField();self.band=spin();self.stat=QComboBox()
        for label,value in {**STATISTICS,"Étendue":"range"}.items():self.stat.addItem(label,value)
        self.size=spin(3,1,255);self.size.setSingleStep(2);self.minimum=spin(1,1,65025)
        self.preserve=QCheckBox("Conserver les pixels NoData au centre du voisinage");self.preserve.setChecked(True)
        for label,widget in [("Raster",self.source),("Bande",self.band),("Statistique",self.stat),
             ("Dimension de la fenêtre (pixels)",self.size),("Nombre minimal de voisins valides",self.minimum),("Masque",self.preserve)]:self.form.addRow(label,widget)
        self.finish()
    def job(self,options):
        kwargs=dict(source=self.source.text(),destination=self.destination(),band=self.band.value(),statistic=self.stat.currentData(),
                    size=self.size.value(),min_valid=self.minimum.value(),preserve_nodata=self.preserve.isChecked())
        return lambda progress,cancel:cm.focal(**kwargs,progress=progress,cancel=cancel,**options)


class TemporalPage(Page):
    def __init__(self):
        super().__init__("Statistiques multirasters","Synthèse pixel par pixel de rasters superposés ou d’une série temporelle.")
        self.sources=QListWidget();self.sources.setMinimumHeight(180);self.form.addRow("Rasters",self.sources)
        buttons=QWidget();row=QHBoxLayout(buttons);row.setContentsMargins(0,0,0,0)
        add=QPushButton("Importer des rasters");remove=QPushButton("Supprimer la sélection")
        row.addWidget(add);row.addWidget(remove);row.addStretch();self.form.addRow(buttons)
        self.sources.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        add.clicked.connect(lambda:self.sources.addItems(QFileDialog.getOpenFileNames(self,"Rasters",filter=RASTER_FILTER)[0]))
        remove.clicked.connect(lambda:[self.sources.takeItem(self.sources.row(i)) for i in self.sources.selectedItems()])
        self.band=spin();self.stat=QComboBox()
        for label,value in {**STATISTICS,"Médiane":"median"}.items():self.stat.addItem(label,value)
        self.minimum=spin();self.form.addRow("Bande",self.band);self.form.addRow("Statistique",self.stat)
        self.form.addRow("Nombre minimal d’observations",self.minimum);self.finish()
        self.stat.currentIndexChanged.connect(self.stat_changed)
    def stat_changed(self):
        count=self.stat.currentData()=='count';self.minimum.setEnabled(not count)
        if count:self.minimum.setValue(1)
    def job(self,options):
        sources=[self.sources.item(i).text() for i in range(self.sources.count())]
        kwargs=dict(statistic=self.stat.currentData(),band=self.band.value(),min_valid=self.minimum.value())
        destination=self.destination()
        return lambda progress,cancel:cm.reduce_rasters(sources,destination,progress=progress,cancel=cancel,**kwargs,**options)


class MappingPage(Page):
    engine=False
    cancellable=False
    previewRequested=Signal()
    reviewRequested=Signal()
    atlasRequested=Signal(object)
    def __init__(self):
        super().__init__("Mise en page cartographique","Maquettes, cadres multiples, légende, échelle, orientation et exports PDF, PNG ou SVG.")
        self._analysis_overrides={}
        from .desktop_layout import LayoutSettings
        self.tabs=QTabWidget();self.form.addRow(self.tabs)
        self.layer_tab=QWidget();layer_form=QFormLayout(self.layer_tab);self.tabs.addTab(self.layer_tab,"Couches et symbologie")
        self.layers=QTableWidget(0,7);self.layers.setHorizontalHeaderLabels(["Couche","Rôle","Étiquettes","Champ thématique","Bande","Opacité","Palette"])
        self.layers.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch)
        for col,width in [(1,135),(2,100),(3,125),(4,60),(5,70),(6,100)]:self.layers.setColumnWidth(col,width)
        self.layers.setMinimumHeight(190);layer_form.addRow(self.layers)
        buttons=QWidget();row=QHBoxLayout(buttons);row.setContentsMargins(0,0,0,0)
        button=QPushButton("Importer des couches…");remove=QPushButton("Supprimer la sélection")
        row.addWidget(button);row.addWidget(remove);row.addStretch();layer_form.addRow(buttons)
        button.clicked.connect(self.browse);remove.clicked.connect(lambda:[self.layers.removeRow(i) for i in sorted({x.row() for x in self.layers.selectedIndexes()},reverse=True)])
        self.crs=QLineEdit();self.crs.setPlaceholderText("Exemple : EPSG:32733")
        self.aoi=PathField(filter=VECTOR_FILTER);self.rgb=QComboBox();self.rgb.addItem("Bande unique (raster scientifique)",None)
        for label,value in [("Couleurs naturelles","natural"),("Végétation","vegetation"),("Infrarouge à ondes courtes","swir"),("Agriculture","agriculture")]:self.rgb.addItem(label,value)
        for label,widget in [("Système de coordonnées",self.crs),("Zone d’étude",self.aoi),("Composition colorée",self.rgb)]:layer_form.addRow(label,widget)
        self.title=QLineEdit();self.subtitle=QLineEdit();self.credits=QLineEdit();self.dpi=spin(300,72,1200)
        page=QWidget();form=QFormLayout(page);self.tabs.addTab(page,"Maquette et habillage")
        self.layout_settings=LayoutSettings()
        for label,widget in [("Titre",self.title),("Sous-titre",self.subtitle),("Sources et auteur",self.credits)]:form.addRow(label,widget)
        form.addRow(self.layout_settings)
        frames_tab=QWidget();form=QFormLayout(frames_tab);self.tabs.addTab(frames_tab,"Cadres et contenus")
        self.add_help("Les emprises utilisent le système de coordonnées de chaque cadre. Sans réglage, l’emprise et les couches de la carte sont utilisées.",
            subject="Emprises des cadres",summary="Emprises dans le SCR de chaque cadre.",form=form)
        form.addRow(self.layout_settings.frames)
        self.add_help("Contenus facultatifs des emplacements de la maquette : textes, tableaux CSV et graphiques.",subject="Contenus de la maquette",form=form)
        form.addRow(self.layout_settings.elements)
        geometry_tab=QWidget();geometry_form=QVBoxLayout(geometry_tab);geometry_form.addWidget(self.layout_settings.items);self.tabs.addTab(geometry_tab,"Géométrie des éléments")
        self.output.filter="Document PDF (*.pdf);;Image PNG (*.png);;Image SVG (*.svg)"
        self.form.addRow("Résolution d’export (ppp)",self.dpi)
        self.preview_button=QPushButton("Aperçu cartographique");self.preview_button.clicked.connect(self.previewRequested.emit);self.form.addRow(self.preview_button)
        self.review_button=QPushButton('Contrôler la carte');self.review_button.clicked.connect(self.reviewRequested.emit);self.form.addRow(self.review_button)
        self.atlas_button=QPushButton('Préparer l’atlas');self.atlas_button.clicked.connect(self.request_atlas);self.form.addRow(self.atlas_button)
        self.finish();self.tabs.setCurrentIndex(1)
    def browse(self):
        for path in QFileDialog.getOpenFileNames(self,"Couches géographiques",filter="Données SIG (*.tif *.tiff *.jp2 *.vrt *.gpkg *.shp *.geojson *.fgb)")[0]:self.add_layer(path)
    def add_layer(self,path):
        row=self.layers.rowCount();self.layers.insertRow(row);self.layers.setItem(row,0,QTableWidgetItem(str(path)))
        roles=QComboBox();roles.addItem("Automatique",None)
        for label,value in ROLE_LABELS.items():roles.addItem(label,value)
        self.layers.setCellWidget(row,1,roles);self.layers.setItem(row,2,QTableWidgetItem(""))
        if self.layers.columnCount()>3:
            self.layers.setItem(row,3,QTableWidgetItem(""));self.layers.setCellWidget(row,4,spin())
            opacity=spin(100,0,100);opacity.setSuffix(" %");self.layers.setCellWidget(row,5,opacity)
            palette=QComboBox();palette.addItems(["Greys","viridis","Greens","Blues","terrain","Set2","tab20"]);self.layers.setCellWidget(row,6,palette)
    def capture_map(self):
        layers=[]
        for row in range(self.layers.rowCount()):
            path=self.layers.item(row,0).text()
            layers.append(dict(self._analysis_overrides.get(path,{}),data=path,role=self.layers.cellWidget(row,1).currentData(),
                labels=self.layers.item(row,2).text().strip() or None,column=self.layers.item(row,3).text().strip() or None,
                band=self.layers.cellWidget(row,4).value(),alpha=self.layers.cellWidget(row,5).value()/100,cmap=self.layers.cellWidget(row,6).currentText()))
        if not layers:raise ValueError("Importer au moins une couche géographique dans Couches et symbologie.")
        return dict(layers=layers,rgb=self.rgb.currentData(),aoi=self.aoi.text() or None,
            options=dict(title=self.title.text(),subtitle=self.subtitle.text(),credits=self.credits.text(),crs=self.crs.text().strip() or None),
            layout=self.layout_settings.capture())
    def load_layers(self,layers):
        self.layers.setRowCount(0);self._analysis_overrides={}
        for layer in layers:self.append_layer(layer)
        self.tabs.setCurrentIndex(0)
    def append_layer(self,layer):
        layer=dict(layer)
        if layer.get('classes') and (layer.get('kind')=='raster' or Path(str(layer['data'])).suffix.lower() in {'.tif','.tiff','.jp2','.vrt','.img'}):layer['classes']={float(k):v for k,v in layer['classes'].items()}
        path=str(layer['data']);self.add_layer(path);row=self.layers.rowCount()-1
        self._analysis_overrides[path]={key:layer[key] for key in ('name','kind','classes','rgb','color','categorical','legend','zorder') if key in layer}
        role=self.layers.cellWidget(row,1);role.setCurrentIndex(max(0,role.findData(layer.get('role'))))
        self.layers.item(row,2).setText(layer.get('labels') or '');self.layers.item(row,3).setText(layer.get('column') or '')
        self.layers.cellWidget(row,4).setValue(layer.get('band',1));self.layers.cellWidget(row,5).setValue(round(100*layer.get('alpha',1)))
        palette=self.layers.cellWidget(row,6);cmap=layer.get('cmap','Greys')
        if palette.findText(cmap)<0:palette.addItem(cmap)
        palette.setCurrentText(cmap)
    def load_config(self,config):
        self.load_layers(config['layers']);self.rgb.setCurrentIndex(max(0,self.rgb.findData(config['rgb'])))
        self.aoi.edit.setText(config['aoi'] or '')
        for key in ('title','subtitle','credits','crs'):getattr(self,key).setText(config['options'].get(key) or '')
        self.layout_settings.restore(config['layout'])
    def request_atlas(self):
        try:self.atlasRequested.emit(self.capture_map())
        except ValueError as exc:QMessageBox.warning(self,'Atlas cartographique',str(exc))
    def review_job(self,path):
        from .desktop_tools import write_result
        config=self.capture_map()
        return lambda progress,cancel:write_result(self.build_map(config).audit(visual=True),path,overwrite=True)
    @staticmethod
    def build_map(config):
        from .desktop_layout import apply_layout
        layers=[dict(layer) for layer in config["layers"]]
        for layer in layers:
            if Path(layer["data"]).suffix.lower() in {".tif",".tiff",".jp2",".vrt",".img"}:
                with rasterio.open(layer["data"]) as src:
                    if src.count>=3 and config["rgb"] is not None:layer["rgb"]="native" if src.dtypes[:3]==("uint8",)*3 and tuple(c.name for c in src.colorinterp[:3])==("red","green","blue") else config["rgb"]
        settings=config["layout"];options={**config["options"],**{k:settings[k] for k in ("template","format","orientation")}}
        return apply_layout(cm.compose_map(layers,aoi=config["aoi"],**options),settings)
    def job(self,options):
        config=self.capture_map();destination=self.destination();dpi=self.dpi.value()
        return lambda progress,cancel:self.build_map(config).export(destination,dpi=dpi,overwrite=options["overwrite"])
    def preview_job(self,path):
        config=self.capture_map()
        return lambda progress,cancel:self.build_map(config).export(path,dpi=250,overwrite=True)


class AtlasPage(MappingPage):
    cancellable=True
    def __init__(self):
        super().__init__();self.findChild(QLabel,"pageTitle").setText("Atlas cartographique")
        self.atlas_button.hide()
        self.findChild(QLabel,"description").setText("Production d’une carte par entité de la couche d’index, avec maquette et habillage communs.")
        tab=QWidget();form=QFormLayout(tab);self.tabs.insertTab(0,tab,"Index de l’atlas")
        self.zones=PathField(filter=VECTOR_FILTER);self.name_column=QLineEdit();self.name_column.setPlaceholderText("Exemple : nom")
        self.atlas_format=QComboBox();self.atlas_format.addItems(["pdf","png","svg"])
        self.padding=spin(8,0,100);self.padding.setSuffix(" %")
        for label,widget in [("Couche d’index",self.zones),("Champ du nom des pages",self.name_column),("Format d’export",self.atlas_format),("Marge autour des entités",self.padding)]:form.addRow(label,widget)
        self.add_help("Chaque entité définit l’emprise principale d’une page. Les cadres ayant une emprise explicite conservent leur cadrage.",
            subject="Cadrage de l’atlas",summary="Cadres à emprise explicite conservés.",form=form)
        self.output.mode="directory";self.form.labelForField(self.output).setText("Répertoire de sortie")
        self.tabs.setCurrentIndex(0)
    def job(self,options):
        config=self.capture_map();directory=Path(self.destination());zones=self.zones.text();field=self.name_column.text().strip()
        if not zones or not field:raise ValueError("Renseigner la couche d’index et le champ du nom des pages.")
        kwargs=dict(name_column=field,format=self.atlas_format.currentText(),dpi=self.dpi.value(),padding=self.padding.value()/100,overwrite=options["overwrite"])
        def run(progress,cancel):
            paths=cm.atlas(self.build_map(config),zones,directory,progress=progress,cancel=cancel,**kwargs)
            if not paths:raise ValueError("La couche d’index ne contient aucune entité.")
            return paths[0]
        return run


class WorkflowPage(Page):
    engine=False
    staged=True
    def __init__(self):
        super().__init__("Production cartographique automatisée",
            "Des scènes satellites à la carte : traitement multispectral, superposition des couches et mise en page.")
        self.add_help("1. Importation des scènes   2. Mosaïque   3. Assemblage multibande\n"
                      "4. Extraction par masque   5. Composition colorée   6. Mise en page",subject="Étapes de production")
        tabs=QTabWidget();self.tabs=tabs;self.form.addRow(tabs)
        self.data_tab=QWidget();data=QFormLayout(self.data_tab);tabs.addTab(self.data_tab,"Données")
        self.source=PathField("directory");data.addRow("Répertoire des scènes",self.source)
        self.files=[];selection=QWidget();buttons=QHBoxLayout(selection);buttons.setContentsMargins(0,0,0,0)
        select=QPushButton("Sélectionner les bandes…");clear=QPushButton("Utiliser le répertoire")
        buttons.addWidget(select);buttons.addWidget(clear);buttons.addStretch();data.addRow(selection)
        self.inventory=QLabel("Landsat Collection 2 L2 ; Sentinel-2 L2A");self.inventory.setObjectName("muted")
        self.inventory.setWordWrap(True);data.addRow(self.inventory)
        select.clicked.connect(self.select_files);clear.clicked.connect(self.clear_files)
        self.aoi=PathField(filter=VECTOR_FILTER);data.addRow("Zone d’étude",self.aoi)
        self.layers=QTableWidget(0,3);self.layers.setHorizontalHeaderLabels(["Couche vectorielle","Rôle cartographique","Champ d’étiquette"])
        self.layers.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch)
        self.layers.setColumnWidth(1,180);self.layers.setColumnWidth(2,165);self.layers.setMaximumHeight(130);self.layers.setMinimumHeight(110)
        self.layers.setToolTip("Rôle automatique selon le nom et la géométrie. Vérifier les rôles avant la production.")
        data.addRow("Couches à superposer",self.layers)
        controls=QWidget();row=QHBoxLayout(controls);row.setContentsMargins(0,0,0,0)
        add=QPushButton("Importer des couches…");remove=QPushButton("Supprimer la sélection")
        row.addWidget(add);row.addWidget(remove);row.addStretch();data.addRow(controls)
        add.clicked.connect(self.browse_layers)
        remove.clicked.connect(lambda:[self.layers.removeRow(i) for i in sorted({x.row() for x in self.layers.selectedIndexes()},reverse=True)])
        prep=QWidget();form=QFormLayout(prep);tabs.addTab(prep,"Prétraitement")
        self.crs=QLineEdit();self.crs.setPlaceholderText("Automatique selon les scènes ; exemple : EPSG:32733")
        self.bands=QLineEdit();self.bands.setPlaceholderText('Toutes les bandes, ou noms spectraux séparés par des virgules')
        self.resolution=spin(0,0,100000);self.resolution.setSpecialValueText("Résolution native la plus grossière")
        self.clouds=QCheckBox("Appliquer les masques QA/SCL");self.clouds.setChecked(True)
        self.dates=QCheckBox("Autoriser une mosaïque multitemporelle")
        self.coverage_threshold=real(100.);self.coverage_threshold.setRange(.01,100.);self.coverage_threshold.setDecimals(2)
        self.allow_partial=QCheckBox("Accepter moins que le seuil")
        self.allow_partial.setToolTip("Avec une zone d’étude, autoriser explicitement une couverture utile sous le seuil demandé. Le rapport et l’état du traitement indiquent la couverture partielle.")
        for label,widget in [("Système de coordonnées cible",self.crs),("Bandes spectrales",self.bands),
            ("Résolution (m)",self.resolution),("Masque de qualité",self.clouds),("Dates d’acquisition",self.dates),
            ("Couverture utile minimale (%)",self.coverage_threshold),("Couverture sous le seuil",self.allow_partial)]:form.addRow(label,widget)
        note=QLabel("Calibration radiométrique et masque de qualité avant rééchantillonnage. Les scènes sont alignées sur une grille commune. Les bandes nécessaires à la composition colorée sont ajoutées à la sélection.")
        note.setWordWrap(True);note.setObjectName("muted");form.addRow(note)
        output=QWidget();form=QFormLayout(output);tabs.addTab(output,"Restitution cartographique")
        self.title=QLineEdit();self.subtitle=QLineEdit();self.credits=QLineEdit();self.rgb=QComboBox()
        for label,value in [("Couleurs naturelles","natural"),("Infrarouge proche : végétation","vegetation"),
            ("Infrarouge à ondes courtes","swir"),("Agriculture","agriculture")]:self.rgb.addItem(label,value)
        self.format=QComboBox()
        for label,value in [("PDF et PNG",("pdf","png")),("PDF",("pdf",)),("PNG",("png",)),("SVG",("svg",))]:self.format.addItem(label,value)
        self.dpi=spin(300,72,1200)
        for label,widget in [("Composition colorée",self.rgb),("Titre de la carte",self.title),
            ("Sous-titre",self.subtitle),("Sources et auteur",self.credits),("Format d’export",self.format),("Résolution d’export (ppp)",self.dpi)]:form.addRow(label,widget)
        from .desktop_layout import LayoutSettings
        self.layout_settings=LayoutSettings(compact=True);form.addRow(self.layout_settings)
        note=QLabel("Ordre des couches selon leur rôle cartographique ; reprojection, découpage vectoriel, légende, échelle et orientation intégrés à la mise en page.")
        note.setWordWrap(True);note.setObjectName("muted");form.addRow(note)
        self.directory=PathField("directory");self.project=QLineEdit("production_cartographique")
        self.form.addRow("Répertoire de sortie",self.directory);self.form.addRow("Nom de la production",self.project)
        products=QLabel("Produits : GeoTIFF multibande ; composition colorée ; carte PDF/PNG ; rapport de traitement")
        products.setWordWrap(True);products.setObjectName("muted");self.form.addRow(products)
        self.layout.addStretch()
    def select_files(self):
        paths=QFileDialog.getOpenFileNames(self,"Bandes spectrales et masques de qualité",filter=RASTER_FILTER)[0]
        if paths:
            self.files=paths;self.source.setEnabled(False)
            self.inventory.setText(f"{len(paths)} fichiers sélectionnés : inclure les bandes et les masques QA/SCL.")
    def clear_files(self):
        self.files=[];self.source.setEnabled(True);self.inventory.setText("Landsat Collection 2 L2 ; Sentinel-2 L2A")
    def browse_layers(self):
        for path in QFileDialog.getOpenFileNames(self,"Couches vectorielles",filter=VECTOR_FILTER)[0]:self.add_layer(path)
    def add_layer(self,path):
        MappingPage.add_layer(self,path)
    def job(self,options):
        source=list(self.files) if self.files else self.source.text()
        if not source:raise ValueError("Sélectionner un répertoire de scènes ou des bandes spectrales.")
        name=self.project.text().strip()
        if not name or name in {".",".."} or any(c in name for c in '/\\:*?"<>|'):
            raise ValueError("Renseigner un nom de production sans séparateur de chemin.")
        if not self.directory.text():raise ValueError("Sélectionner le répertoire de sortie.")
        destination=Path(self.directory.text())/name
        if destination.exists():raise ValueError("Ce nom de production existe déjà. Choisir un nouveau nom.")
        layers=[dict(data=self.layers.item(i,0).text(),role=self.layers.cellWidget(i,1).currentData(),
                     labels=self.layers.item(i,2).text().strip() or None) for i in range(self.layers.rowCount())]
        layout=self.layout_settings.capture()
        kwargs=dict(layers=layers,aoi=self.aoi.text() or None,band_order=[b.strip() for b in self.bands.text().split(",") if b.strip()] or None,
            target_crs=self.crs.text().strip() or None,resolution=self.resolution.value() or None,
            mask_clouds=self.clouds.isChecked(),allow_mixed_dates=self.dates.isChecked(),composition=self.rgb.currentData(),
            coverage_threshold=self.coverage_threshold.value(),allow_partial=self.allow_partial.isChecked(),
            title=self.title.text(),credits=self.credits.text(),formats=self.format.currentData(),dpi=self.dpi.value(),
            template=layout["template"],page_format=layout["format"],orientation=layout["orientation"],subtitle=self.subtitle.text(),
            legend=layout["legend"],scale_bar=layout["scale"],north_arrow=layout["north"])
        self.result_map_config=dict(layers=layers,rgb=None,aoi=kwargs['aoi'],layout=layout,
            options=dict(title=kwargs['title'],subtitle=kwargs['subtitle'],credits=kwargs['credits'],crs=kwargs['target_crs']))
        return lambda progress,cancel,stage:cm.cartographic_workflow(source,destination,progress=progress,cancel=cancel,stage=stage,**kwargs).manifest

    def show_result(self,path):
        import json
        record=json.loads(Path(path).read_text(encoding='utf-8'))
        if record.get('coverage_status')=='partial':
            self.window().status.setText('Traitement terminé avec couverture partielle : '+str(path))
            self.window().workspace.activity.setText('Traitement terminé avec couverture partielle.')


class CompositePage(Page):
    engine=False
    def __init__(self):
        super().__init__("Composition colorée","Affectation des bandes aux canaux rouge, vert et bleu et étirement radiométrique pour la visualisation.")
        self.source=PathField();self.rgb=QComboBox()
        for label,value in [("Couleurs naturelles","natural"),("Végétation","vegetation"),("Infrarouge à ondes courtes","swir"),("Agriculture","agriculture")]:self.rgb.addItem(label,value)
        self.form.addRow("Composite multibande",self.source);self.form.addRow("Composition colorée",self.rgb)
        note=QLabel("Le GeoTIFF de visualisation est enregistré séparément. Le composite multibande conserve ses valeurs de réflectance.")
        note.setWordWrap(True);self.form.addRow(note);self.finish()
    def job(self,options):
        source=self.source.text();destination=self.destination();bands=self.rgb.currentData()
        return lambda progress,cancel:cm.color_composite(source,destination,bands=bands,progress=progress,cancel=cancel,overwrite=options["overwrite"])


class Worker(QThread):
    progress=Signal(int,int);succeeded=Signal(str);failed=Signal(str);cancelled=Signal();stage=Signal(str);diagnostic_ready=Signal(str)
    def __init__(self,job,event,parent=None,staged=False):super().__init__(parent);self.job=job;self.cancel_event=event;self.staged=staged
    @Slot()
    def run(self):
        try:
            args=(self.progress.emit,self.cancel_event,self.stage.emit) if self.staged else (self.progress.emit,self.cancel_event)
            self.succeeded.emit(str(self.job(*args)))
        except cm.ProcessingCancelled:self.cancelled.emit()
        except cm.ImageryCoverageError as exc:
            self.diagnostic_ready.emit(str(exc.manifest))
            self.failed.emit(str(exc))
        except Exception as exc:self.failed.emit(str(exc))


class CartomizeWindow(SessionControls,ProjectConnections,QMainWindow):
    def __init__(self):
        super().__init__();self.setWindowTitle("Cartomize");self.resize(1440,940);self.setMinimumSize(1100,700)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._preferences=QSettings('Cartomize','Cartomize Desktop')
        self.thread=None;self.worker=None;self.cancel_event=None;self.output_path=None
        self._preview_target=None;self._preview_directory=tempfile.TemporaryDirectory(prefix="cartomize-preview-")
        root=QWidget();self.setCentralWidget(root);outer=QVBoxLayout(root)
        outer.setContentsMargins(20,14,20,14);outer.setSpacing(12)
        header=QHBoxLayout();icon_path=Path(__file__).parent/"assets"/"cartomize.png"
        icon=QPixmap(str(icon_path));self.setWindowIcon(QIcon(icon));self.brand_icon=QLabel()
        ratio=self.devicePixelRatioF();pixmap=icon.scaled(round(52*ratio),round(52*ratio),Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation)
        pixmap.setDevicePixelRatio(ratio);self.brand_icon.setPixmap(pixmap);self.brand_icon.setFixedSize(58,58)
        header.addWidget(self.brand_icon);identity=QVBoxLayout();identity.setSpacing(1)
        brand=QLabel("Cartomize");brand.setObjectName("brand");identity.addWidget(brand)
        subtitle=QLabel("Assistant cartographique");subtitle.setObjectName("muted");identity.addWidget(subtitle)
        header.addLayout(identity);header.addStretch()
        theme_label=QLabel('Thème');header.addWidget(theme_label)
        self.theme_selector=QComboBox();self.theme_selector.setObjectName('themeSelector')
        self.theme_selector.addItem('Système','system');self.theme_selector.addItem('Clair','light');self.theme_selector.addItem('Sombre','dark')
        saved_theme=self._preferences.value('appearance/theme','system')
        index=self.theme_selector.findData(saved_theme)
        self.theme_selector.setCurrentIndex(index if index>=0 else 0)
        header.addWidget(self.theme_selector)
        version=QLabel(f"Version {cm.__display_version__}");version.setObjectName("muted");header.addWidget(version);outer.addLayout(header)
        session_bar=QHBoxLayout();self.init_session(session_bar);session_bar.addStretch();outer.addLayout(session_bar)
        self.workspace_splitter=QSplitter(Qt.Orientation.Horizontal);self.workspace_splitter.setChildrenCollapsible(False);outer.addWidget(self.workspace_splitter,1)
        self.controls_panel=QWidget();self.controls_panel.setMinimumWidth(400);controls=QVBoxLayout(self.controls_panel);controls.setContentsMargins(0,0,8,0);controls.setSpacing(7)
        self.workspace_splitter.addWidget(self.controls_panel)
        from .desktop_results import ResultsWorkspace
        self.workspace=ResultsWorkspace();self.workspace.setMinimumWidth(500);self.workspace_splitter.addWidget(self.workspace)
        from .desktop_explorer import ProjectExplorer
        self.project_explorer=ProjectExplorer(self.workspace,self)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea,self.project_explorer)
        self.project_explorer.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable | QDockWidget.DockWidgetFeature.DockWidgetFloatable)
        self.project_explorer.setMinimumWidth(240)
        self.workspace_splitter.setStretchFactor(0,0);self.workspace_splitter.setStretchFactor(1,1);self.workspace_splitter.setSizes([490,910])
        panel_header=QHBoxLayout();panel_title=QLabel('Contrôle et traitements');panel_title.setObjectName('panelTitle');panel_header.addWidget(panel_title);panel_header.addStretch()
        self.catalogue_toggle=QToolButton();self.catalogue_toggle.setText('Outils');self.catalogue_toggle.setCheckable(True);self.catalogue_toggle.setChecked(True);panel_header.addWidget(self.catalogue_toggle);controls.addLayout(panel_header)
        self.catalogue=QWidget();catalogue_layout=QVBoxLayout(self.catalogue);catalogue_layout.setContentsMargins(0,0,0,0);catalogue_layout.setSpacing(4)
        self.tool_search=QLineEdit();self.tool_search.setPlaceholderText('Rechercher un traitement');catalogue_layout.addWidget(self.tool_search)
        self.navigation=QListWidget();self.navigation.setObjectName("navigation");self.navigation.setViewMode(QListView.ViewMode.ListMode)
        self.navigation.setResizeMode(QListView.ResizeMode.Adjust);self.navigation.setMovement(QListView.Movement.Static);self.navigation.setWordWrap(False)
        self.navigation.setMinimumHeight(230);self.navigation.setSpacing(2);catalogue_layout.addWidget(self.navigation,1)
        controls.addWidget(self.catalogue,1);self.catalogue_toggle.toggled.connect(self.catalogue.setVisible)
        self.tool_search.textChanged.connect(self.filter_tools)
        self.stack=QStackedWidget();self.stack.setMinimumHeight(230);controls.addWidget(self.stack,3)
        from .desktop_tools import InspectionPage,VectorPage,RasterToolsPage
        from .desktop_project import ProjectPage
        from .desktop_assistant import AssistantPage
        from .desktop_classification import ClassificationPage
        from .desktop_recipes import RecipesPage
        from .desktop_native import NativePage
        from .desktop_mapops import MapOpsPage
        from .desktop_terrain import TerrainPage
        from .assistant import TOOL_LABELS
        from .desktop_processing import ProcessingPage
        from .desktop_imagery import PreparationPage
        from .desktop_conversion import ConversionPage
        self.tool_pages=dict(assistant=AssistantPage(self._preview_directory.name),project=ProjectPage(),inspect=InspectionPage(),
            conversion=ConversionPage(),
            prepare=PreparationPage(),composite=CompositePage(),classification=ClassificationPage(),vector=VectorPage(),raster=RasterToolsPage(),terrain=TerrainPage(),indices=IndicesPage(),
            calculator=CalculatorPage(),focal=FocalPage(),temporal=TemporalPage(),mapping=MappingPage(),atlas=AtlasPage(),workflow=WorkflowPage(),processing=ProcessingPage(),recipes=RecipesPage(self),native=NativePage(self._preview_directory.name),mapops=MapOpsPage(self))
        order=('assistant','inspect','conversion','prepare','composite','classification','indices','calculator','focal','temporal','terrain','vector','raster','project','mapping','atlas','workflow','processing','recipes','native','mapops')
        self.tool_pages={key:self.tool_pages[key] for key in order}
        self.pages=list(self.tool_pages.values());titles=['Assistant cartographique' if key=='assistant' else TOOL_LABELS[key] for key in self.tool_pages]
        for title,page in zip(titles,self.pages):
            self.navigation.addItem(title);scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(page);self.stack.addWidget(scroll)
            for form in page.findChildren(QFormLayout):form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
            # Read-only diagnostics remain visible within their tool panels.
            if isinstance(page,MappingPage):
                page.previewRequested.connect(lambda:self.start(preview=True));page.reviewRequested.connect(lambda:self.start(review=True))
                page.atlasRequested.connect(self.prepare_atlas)
            if isinstance(page,ProjectPage):page.applyRequested.connect(self.apply_project)
        self.tool('native').layersRequested.connect(self.apply_project)
        self.tool('assistant').openRequested.connect(self.open_assistant_step)
        self.tool('assistant').planRequested.connect(lambda:self.start(proposal=True))
        self.tool('assistant').executeRequested.connect(lambda:self.start(execute_plan=True))
        self.navigation.currentRowChanged.connect(self.stack.setCurrentIndex);self.navigation.currentRowChanged.connect(self.page_changed)
        self.engine_toggle=QToolButton();self.engine_toggle.setText('Paramètres de calcul et de sortie');self.engine_toggle.setCheckable(True);controls.addWidget(self.engine_toggle)
        self.engine_panel=QWidget();engine_layout=QVBoxLayout(self.engine_panel);engine_layout.setContentsMargins(0,0,0,0);controls.addWidget(self.engine_panel);self.engine_panel.hide()
        self.engine_toggle.toggled.connect(self.engine_panel.setVisible)
        settings=QGroupBox("Paramètres de traitement");self.settings=settings;row=QFormLayout(settings)
        self.workers=spin(min(4,os.cpu_count() or 1),1,32);self.block_size=QComboBox();self.block_size.addItems(["256","512","1024","2048"]);self.block_size.setCurrentText("512")
        self.memory=spin(512,16,32768);self.memory.setSuffix(" Mio")
        self.overwrite=QCheckBox("Remplacer les fichiers existants")
        self.engine_labels=[]
        for label,widget in [("Threads de calcul",self.workers),("Bloc (pixels)",self.block_size),("Budget des tableaux",self.memory)]:
            caption=QLabel(label);self.engine_labels.append(caption);row.addRow(caption,widget)
        row.addRow(self.overwrite);engine_layout.addWidget(settings)
        from .desktop_execution import ExecutionSettings
        self.execution_settings=ExecutionSettings();engine_layout.addWidget(self.execution_settings)
        self.init_results(controls)
        bottom=QHBoxLayout();self.run_button=QPushButton("Exécuter");self.run_button.setObjectName("primary")
        self.cancel_button=QPushButton("Annuler");self.cancel_button.setEnabled(False)
        self.folder_button=QPushButton("Ouvrir le répertoire de sortie");self.folder_button.setEnabled(False)
        bottom.addWidget(self.run_button);bottom.addWidget(self.cancel_button);bottom.addStretch();session_bar.addWidget(self.folder_button);controls.addLayout(bottom)
        self.progress=QProgressBar();self.progress.setValue(0);controls.addWidget(self.progress)
        self.status=QLabel("Prêt.");self.status.setWordWrap(True);self.status.setMaximumHeight(62);controls.addWidget(self.status)
        self.run_button.clicked.connect(self.start);self.cancel_button.clicked.connect(self.cancel)
        self.folder_button.clicked.connect(lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self.output_path).resolve() if Path(self.output_path).is_dir() else Path(self.output_path).resolve().parent))))
        self.navigation.setCurrentRow(0)
        self.checkpoint()
        self._system_palette=QApplication.instance().palette()
        self.theme_selector.currentIndexChanged.connect(self.apply_theme)
        self.apply_theme()
        from .desktop_workbench import install_workbench
        install_workbench(self)

    def apply_theme(self,*_):
        from .desktop_theme import apply_theme
        apply_theme(self)

    def filter_tools(self,text):
        if hasattr(self, '_workbench'):
            self._workbench.filter_tools(text)
            return
        for i in range(self.navigation.count()):
            self.navigation.item(i).setHidden(text.casefold() not in self.navigation.item(i).text().casefold())

    def page_changed(self,index):
        if index<0:return
        page=self.pages[index]
        key=next(k for k,v in self.tool_pages.items() if v is page)
        self.execution_settings.setVisible(key in {'calculator','indices','temporal','focal','terrain','processing'})
        self.execution_settings.device.setEnabled(key in {'calculator','indices','temporal','processing'})
        for widget in (*self.engine_labels,self.workers,self.block_size,self.memory):widget.setVisible(page.engine)
        from .desktop_project import ProjectPage
        from .desktop_assistant import AssistantPage
        self.settings.setVisible(key not in {'workflow','project','assistant','prepare'})
        self.engine_toggle.setVisible(key not in {'workflow','project','assistant','prepare'})
        self.engine_panel.setVisible(self.engine_toggle.isChecked() and self.engine_toggle.isVisible())
        self.settings.setTitle("Paramètres de traitement" if page.engine else "")
        self.settings.setStyleSheet("" if page.engine else "QGroupBox { border: none; margin-top: 0px; padding-top: 0px; }")
        self.run_button.setText("Exécuter la chaîne" if isinstance(page,WorkflowPage) else "Analyser le projet" if isinstance(page,ProjectPage) else "Produire l’atlas" if isinstance(page,AtlasPage) else "Exporter la carte" if isinstance(page,MappingPage) else "Exécuter")
        if isinstance(page,AssistantPage):self.run_button.setText('Examiner les données')
    def apply_project(self,layers):
        self.checkpoint()
        for layer in layers:self.register_result(layer)
        page=next(page for page in self.pages if type(page) is MappingPage)
        page.load_layers(layers);self.navigation.setCurrentRow(self.pages.index(page))
        assessment=self.tool('assistant').assessment
        if assessment and not page.title.text():self.open_assistant_step('mapping',assessment)
        self.status.setText('Couches et symbologie appliquées à la mise en page.')
    def start(self,checked=False,*,preview=False,review=False,proposal=False,execute_plan=False):
        if self.thread is not None:return
        self.checkpoint()
        options=dict(workers=self.workers.value(),block_size=int(self.block_size.currentText()),
                     memory_limit_mb=self.memory.value(),overwrite=self.overwrite.isChecked())
        page=self.pages[self.stack.currentIndex()]
        key=next(k for k,v in self.tool_pages.items() if v is page)
        if key in {'calculator','indices','temporal','focal','terrain','processing'}:
            options.update(self.execution_settings.parameters(gpu=key in {'calculator','indices','temporal','processing'}))
        self._preview_target=None;self._reviewing=review
        try:
            if proposal:job=page.plan_job()
            elif execute_plan:job=page.execution_job(options)
            elif preview:
                self._preview_target=Path(self._preview_directory.name)/"apercu.svg"
                job=page.preview_job(self._preview_target)
            elif review:job=page.review_job(Path(self._preview_directory.name)/'controle.json')
            else:job=page.job(options)
        except Exception as exc:self.status.setText(str(exc));return
        self.cancel_event=threading.Event();self.worker=Worker(job,self.cancel_event,self,staged=execute_plan or self.pages[self.stack.currentIndex()].staged);self.thread=self.worker
        self.worker.progress.connect(self.show_progress);self.worker.stage.connect(self.status.setText);self.worker.succeeded.connect(self.completed)
        self.worker.stage.connect(self.workspace.activity.setText)
        self.worker.failed.connect(self.failed);self.worker.cancelled.connect(self.cancelled)
        self.worker.diagnostic_ready.connect(self.show_failed_diagnostic)
        self.thread.finished.connect(self.cleaned);self.thread.finished.connect(self.thread.deleteLater)
        self.run_button.setEnabled(False);self.navigation.setEnabled(False);self.stack.setEnabled(False);self.settings.setEnabled(False)
        self.results_box.setEnabled(False)
        self.cancel_button.setEnabled(page.cancellable and not preview and not review)
        self.folder_button.setEnabled(False);self.progress.setRange(0,0);self.status.setText("Traitement en cours.")
        self.workspace.activity.setText('Traitement en cours.')
        self.thread.start()
    @Slot(int,int)
    def show_progress(self,done,total):
        self.progress.setRange(0,max(1,total));self.progress.setValue(done)
        self.workspace.activity.setText(f'Traitement : {int(done/max(1,total)*100)} % ; {self.status.text()}')
    @Slot(str)
    def completed(self,path):
        self.output_path=path;self.progress.setRange(0,100);self.progress.setValue(100)
        self.workspace.activity.setText('Traitement terminé.')
        if self._preview_target is not None:
            self.workspace.open_result(path,title='Aperçu cartographique',refresh=True,transient=True)
            self.status.setText("Aperçu cartographique actualisé.")
        elif self._reviewing:self.show_review(path)
        else:
            self.status.setText("Traitement terminé : "+path);self.folder_button.setEnabled(True)
            page=self.pages[self.stack.currentIndex()]
            if hasattr(page,"show_result"):page.show_result(path)
            self._result_partial_coverage=False
            self.collect_result(path)
            self.workspace.show_output(path)
            if self._result_partial_coverage:
                self.status.setText("Traitement terminé avec couverture partielle : "+path)
                self.workspace.activity.setText('Traitement terminé avec couverture partielle.')
    @Slot(str)
    def show_failed_diagnostic(self,path):
        self.output_path=path;self.folder_button.setEnabled(True)
        page=self.pages[self.stack.currentIndex()]
        if hasattr(page,'show_rejected_coverage'):page.show_rejected_coverage(path)
        self.collect_result(path)
        self.workspace.show_output(path)
    @Slot(str)
    def failed(self,error):
        self.progress.setRange(0,100);self.progress.setValue(0);self.status.setText("Échec du traitement : "+error)
        self.workspace.activity.setText('Échec du traitement : '+error)
    @Slot()
    def cancelled(self):
        self.progress.setRange(0,100);self.progress.setValue(0);self.status.setText("Traitement interrompu.")
        self.workspace.activity.setText('Traitement interrompu.')
    @Slot()
    def cleaned(self):
        self.thread=None;self.worker=None;self.run_button.setEnabled(True);self.navigation.setEnabled(True)
        self.results_box.setEnabled(True)
        self.stack.setEnabled(True);self.settings.setEnabled(True);self.page_changed(self.stack.currentIndex());self.cancel_button.setEnabled(False)
    def cancel(self):
        if self.cancel_event:self.cancel_event.set();self.cancel_button.setEnabled(False);self.status.setText("Interruption à la fin du bloc ou de l’export en cours.")
    def closeEvent(self,event):
        if self.thread is not None:
            self.cancel();self.status.setText("Attendre la fin du traitement avant de fermer la fenêtre.");event.ignore()
        else:self.workspace.dispose();event.accept()


_windows=[]


def _enable_ipython_loop():
    """Use IPython's Qt integration when running inside an interactive shell."""
    ipython=sys.modules.get("IPython")
    shell=ipython.get_ipython() if ipython is not None else None
    if shell is None or not callable(getattr(shell,"enable_gui",None)):
        return False
    # The application uses PySide6, including when another Qt binding is installed.
    previous=os.environ.get("QT_API")
    os.environ["QT_API"]="pyside6"
    try:
        shell.enable_gui("qt6")
    finally:
        if previous is None:os.environ.pop("QT_API",None)
        else:os.environ["QT_API"]=previous
    return True


def launch(*,block=None):
    """Open a native window and automatically integrate with local notebooks.

    With block=None, scripts run the Qt loop while IPython keeps its own loop.
    Explicit block=True/False retains control for embedding applications.
    """
    application=QApplication.instance();owns_loop=application is None
    if application is None:application=QApplication(["Cartomize"])
    interactive_loop=_enable_ipython_loop() if block is None else False
    window=CartomizeWindow();_windows.append(window)
    window.destroyed.connect(lambda:_windows.remove(window) if window in _windows else None)
    window.show()
    # Keep the application alive when embedded without a running Qt event loop.
    window._application=application
    if block is True or (block is None and owns_loop and not interactive_loop):application.exec()
    return window


def main():
    launch();return 0


if __name__=="__main__":raise SystemExit(main())
