"""Integrated results workspace: documents, layers, tables and comparison views."""
import json
from pathlib import Path
import numpy as np
from matplotlib import colormaps
from PySide6.QtCore import Qt,Signal
from PySide6.QtGui import QColor, QIcon, QPixmap, QImage
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QToolButton,
    QComboBox,QSplitter,QTabWidget,QPlainTextEdit,QListWidget,QListWidgetItem,QCheckBox,QFileDialog)
from .desktop_canvas import GeoCanvas
from .desktop_tables import TablePanel
from .viewer_data import RASTERS,VECTORS,IMAGES,SUPPORTED,identity

MAP_FORMATS=RASTERS|VECTORS|IMAGES|{'.svg','.pdf'}


def button(text,callback,layout):
    widget=QPushButton(text); widget.clicked.connect(callback); layout.addWidget(widget); return widget


class MapDocument(QWidget):
    styleChanged=Signal()
    def __init__(self,path,options=None,*,compact=False,parent=None):
        super().__init__(parent); self.path=str(path); self.options=dict(options or {}); self.canvas=GeoCanvas(path,self.options,self)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.file_id=identity(path); self._closed=False; self._table=None; self.reload_handler=None
        layout=QVBoxLayout(self); layout.setContentsMargins(4,4,4,4); layout.setSpacing(5)
        toolbar=QHBoxLayout(); toolbar.setSpacing(4)
        button('+',lambda:self.canvas.zoom(1.5),toolbar); button('−',lambda:self.canvas.zoom(1/1.5),toolbar)
        button('Étendue',self.canvas.fit_extent,toolbar)
        button('1:1',self.canvas.native_scale,toolbar)
        reload_button=button('↻' if compact else 'Actualiser',self.reload,toolbar); reload_button.setToolTip('Relire le résultat et ses métadonnées'); toolbar.addStretch()
        self.display_settings=QToolButton(); self.display_settings.setText('Affichage'); self.display_settings.setCheckable(True); self.display_settings.setChecked(not compact); toolbar.addWidget(self.display_settings)
        self.details=QToolButton(); self.details.setText('Infos' if compact else 'Informations'); self.details.setCheckable(True); self.details.setChecked(not compact); toolbar.addWidget(self.details)
        layout.addLayout(toolbar)
        self.styles=QWidget(); styles=QHBoxLayout(self.styles); styles.setContentsMargins(0,0,0,0); styles.setSpacing(4)
        self.mode=QComboBox(); self.mode.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon); self.mode.setMinimumContentsLength(10)
        self.palette=QComboBox()
        for name,key in [('Viridis','viridis'),('Gris','gray'),('Végétation','RdYlGn'),('Divergent','RdBu_r'),('Relief','terrain')]: self.palette.addItem(name,key)
        self.resampling=QComboBox(); self.resampling.addItem('Pixels','nearest'); self.resampling.addItem('Bilinéaire','bilinear')
        self.channels=[QComboBox() for _ in range(3)]
        for combo in self.channels: combo.setMinimumContentsLength(3); combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        styles.addWidget(self.mode,2)
        for channel in self.channels: styles.addWidget(channel,1)
        styles.addWidget(self.palette,1); styles.addWidget(self.resampling,1); layout.addWidget(self.styles)
        self.content=QSplitter(Qt.Orientation.Horizontal); layout.addWidget(self.content,1)
        self.views=QTabWidget(); self.views.addTab(self.canvas,'Carte' if self.canvas.info.get('crs') else 'Document'); self.content.addWidget(self.views)
        if self.canvas.kind=='vector':
            self._table=TablePanel(path,layer=self.canvas.info.get('layer')); self.views.addTab(self._table,'Attributs')
        self.info_tabs=QTabWidget(); self.info_tabs.setMinimumWidth(160); self.info_tabs.setMaximumWidth(310)
        legend=QWidget(); legend_layout=QVBoxLayout(legend); legend_layout.setContentsMargins(6,6,6,6)
        self.ramp=QLabel(); self.ramp.hide(); legend_layout.addWidget(self.ramp)
        self.legend=QListWidget(); self.legend.setWordWrap(True); legend_layout.addWidget(self.legend,1)
        self.info_tabs.addTab(legend,'Légende')
        metadata=QPlainTextEdit(); metadata.setReadOnly(True)
        metadata.setPlainText(json.dumps(self.canvas.info,ensure_ascii=False,indent=2,default=str)); self.info_tabs.addTab(metadata,'Métadonnées')
        self.content.addWidget(self.info_tabs); self.content.setStretchFactor(0,1); self.content.setSizes([800,200])
        self.info_tabs.setVisible(not compact); self.details.toggled.connect(self.info_tabs.setVisible)
        self.coordinates=QLabel('Molette : zoom · glisser : déplacement · clic : valeurs du pixel'); self.coordinates.setObjectName('muted'); self.coordinates.setWordWrap(True)
        self.values=QLabel(''); self.values.setWordWrap(True); self.note=QLabel('Chargement de la vue…'); self.note.setWordWrap(True); self.note.setObjectName('muted')
        layout.addWidget(self.coordinates); layout.addWidget(self.values); layout.addWidget(self.note)
        self.canvas.position.connect(self.coordinates.setText); self.canvas.identified.connect(self.values.setText)
        self.canvas.error.connect(lambda text:self.note.setText('Affichage impossible : '+text)); self.canvas.rendered.connect(self.show_legend)
        self._configure_controls(); self.styles.setVisible(self.canvas.kind in {'raster','pdf'} and not compact)
        self.display_settings.setVisible(self.canvas.kind in {'raster','pdf'}); self.display_settings.toggled.connect(self.styles.setVisible)
        if self.canvas.kind=='svg': self.note.setText('Document vectoriel · les images incorporées conservent la résolution de l’export.')

    def _configure_controls(self):
        canvas=self.canvas
        if canvas.kind=='raster':
            for i,label in enumerate(canvas.info['descriptions'],1):
                self.mode.addItem(f'{i} · {label}',i)
                for channel in self.channels: channel.addItem(f'{i} · {label}',i)
            if canvas.info['count']>=3: self.mode.addItem('Composition RVB','rgb')
            for channel,band in zip(self.channels,canvas.bands if len(canvas.bands)==3 else (1,2,3)):
                channel.setCurrentIndex(max(0,channel.findData(band)))
            self.mode.setCurrentIndex(self.mode.findData('rgb' if len(canvas.bands)==3 else canvas.bands[0]))
            self.palette.setCurrentIndex(self.palette.findData(canvas.palette_name))
            self.mode.currentIndexChanged.connect(self._change_style)
            for channel in self.channels: channel.currentIndexChanged.connect(self._change_style)
            self.palette.currentIndexChanged.connect(self._change_style); self.resampling.currentIndexChanged.connect(self._change_style)
            self._style_visibility()
        elif canvas.kind=='pdf':
            for i in range(canvas.info['pages']): self.mode.addItem(f'Page {i+1}',i)
            self.mode.currentIndexChanged.connect(lambda index:canvas.set_page(index))
            for control in [*self.channels,self.palette,self.resampling]: control.hide()

    def reload(self):
        if self.reload_handler: self.reload_handler()
        else: self.canvas.refresh()

    def _style_visibility(self):
        rgb=self.mode.currentData()=='rgb'
        for channel in self.channels: channel.setVisible(rgb)
        self.palette.setVisible(not rgb and not self.canvas.info.get('classes'))
        self.resampling.setEnabled(not bool(self.canvas.info.get('classes')))

    def _change_style(self,*args):
        bands=tuple(c.currentData() for c in self.channels) if self.mode.currentData()=='rgb' else (self.mode.currentData(),)
        self._style_visibility()
        if any(b is None for b in bands): return
        self.canvas.set_style(bands=bands,palette=self.palette.currentData(),resampling=self.resampling.currentData())
        self.styleChanged.emit()

    def show_legend(self,result):
        self.legend.clear()
        for label,color,code in result.get('legend',[]):
            item=QListWidgetItem(str(label)+(' · '+str(code) if color and code is not None else ''))
            if color:
                swatch=QPixmap(16,16); swatch.fill(QColor(color)); item.setIcon(QIcon(swatch))
            self.legend.addItem(item)
        continuous=self.canvas.kind=='raster' and len(self.canvas.bands)==1 and not self.canvas.info.get('classes')
        self.ramp.setVisible(continuous)
        if continuous:
            array=np.ascontiguousarray(colormaps[self.canvas.palette_name](np.tile(np.linspace(0,1,180),(12,1)),bytes=True))
            self.ramp.setPixmap(QPixmap.fromImage(QImage(array.data,180,12,array.strides[0],QImage.Format.Format_RGBA8888).copy()))
        note=result.get('warning')
        if not note:
            if self.canvas.kind=='raster':
                note='Valeurs originales conservées · NoData transparents · zoom par lecture de l’emprise visible.'
                if not self.canvas.info.get('classes') and self.canvas.limits is None: note+=' Contraste : percentiles 2–98 % sur échantillon fixe.'
            elif self.canvas.kind=='pdf': note='PDF rendu à la résolution de la vue ; les rasters incorporés gardent leur résolution d’origine.'
            elif self.canvas.kind=='vector': note='Géométries de l’emprise visible · symbologie d’exploration. L’habillage final appartient à la mise en page.'
            else: note='Image originale · le zoom au-delà des pixels natifs n’ajoute pas de détail mesuré.'
        self.note.setText(note)

    def capture(self): return dict(type='map',path=self.path,options=self.options,view=self.canvas.capture(),details=self.details.isChecked())
    def restore(self,state):
        view=state.get('view',{})
        self.details.setChecked(state.get('details',True)); self.canvas.restore(view)
        if self.canvas.kind=='raster':
            for widget in [self.mode,self.palette,self.resampling,*self.channels]: widget.blockSignals(True)
            self.mode.setCurrentIndex(self.mode.findData('rgb' if len(self.canvas.bands)==3 else self.canvas.bands[0]))
            for control,band in zip(self.channels,self.canvas.bands): control.setCurrentIndex(control.findData(band))
            self.palette.setCurrentIndex(self.palette.findData(self.canvas.palette_name)); self.resampling.setCurrentIndex(self.resampling.findData(self.canvas.resampling))
            for widget in [self.mode,self.palette,self.resampling,*self.channels]: widget.blockSignals(False)
            self._style_visibility()
        elif self.canvas.kind=='pdf': self.mode.setCurrentIndex(self.canvas.page)
    def dispose(self):
        if self._closed: return
        self._closed=True; self.canvas.dispose()
        if self._table: self._table.dispose()

    def closeEvent(self,event):
        self.dispose(); super().closeEvent(event)


class Comparison(QWidget):
    def __init__(self,records,left,right,parent=None):
        super().__init__(parent); self.records=records; self.documents=[None,None]; self._syncing=False; self._shared_applied=False
        layout=QVBoxLayout(self); controls=QHBoxLayout(); self.link=QCheckBox('Synchroniser les emprises'); self.link.setChecked(True)
        self.common_scale=QCheckBox('Échelle colorimétrique commune')
        controls.addWidget(self.link); controls.addWidget(self.common_scale); controls.addStretch(); layout.addLayout(controls)
        self.note=QLabel(''); self.note.setWordWrap(True); layout.addWidget(self.note)
        self.splitter=QSplitter(Qt.Orientation.Horizontal); layout.addWidget(self.splitter,1); self.choices=[]; self.holders=[]
        for side,path in enumerate([left,right]):
            container=QWidget(); box=QVBoxLayout(container); box.setContentsMargins(0,0,0,0)
            choice=QComboBox(); choice.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon); choice.setMinimumContentsLength(16)
            for key,record in records.items():
                if Path(key).suffix.lower() in MAP_FORMATS: choice.addItem(record.get('name') or Path(key).name,key)
            box.addWidget(choice); self.holders.append(box); self.choices.append(choice); self.splitter.addWidget(container)
            choice.setCurrentIndex(choice.findData(path)); choice.currentIndexChanged.connect(lambda _,i=side:self.choose(i)); self.choose(side)
        self.link.toggled.connect(lambda checked:self.synchronize(0))
        self.common_scale.toggled.connect(self.shared_scale_changed)
        self.splitter.setSizes([500,500]); self.synchronize(0)

    def choose(self,side):
        path=self.choices[side].currentData()
        if not path: return
        old=self.documents[side]
        self._shared_applied=False
        state=old.capture() if old and old.path==path else None
        if old: old.dispose(); self.holders[side].removeWidget(old); old.deleteLater()
        try:
            doc=MapDocument(path,self.records[path],compact=True); self.documents[side]=doc; self.holders[side].addWidget(doc,1)
            doc.reload_handler=lambda i=side:self.choose(i)
            if state: doc.restore(state)
            if self.common_scale.isChecked():
                for current in self.documents:
                    if current and current.canvas.kind=='raster':
                        current.canvas._default_limits(); current.canvas.last_render=None; current.canvas.refresh()
            doc.canvas.rendered.connect(lambda result:self.apply_shared_scale())
            doc.styleChanged.connect(self.reset_shared_scale)
            doc.canvas.extentChanged.connect(lambda extent,crs,i=side:self.synchronize(i,extent,crs)); self.synchronize(side)
        except Exception as exc: self.documents[side]=None; self.note.setText(str(exc))

    def synchronize(self,side,extent=None,crs=None):
        if self._syncing or not all(self.documents): return
        source=self.documents[side].canvas; target=self.documents[1-side].canvas
        compatible=bool(source.info.get('crs') and target.info.get('crs')); self.link.setEnabled(compatible)
        self.note.setText('Zoom et déplacement liés par coordonnées géographiques ; valeurs et styles restent indépendants.' if compatible else 'Comparaison visuelle : synchronisation géographique indisponible pour un document sans SCR.')
        if not compatible or not self.link.isChecked(): return
        self._syncing=True
        try: target.set_geographic_extent(extent or source.geographic_extent(),crs or source.info['crs'])
        except (ValueError,RuntimeError) as exc: self.note.setText('Emprises non synchronisées : '+str(exc))
        finally: self._syncing=False

    def shared_scale_changed(self,checked):
        self._shared_applied=False
        if not checked:
            for doc in self.documents:
                if doc and doc.canvas.kind=='raster':
                    doc.canvas._default_limits(); doc.canvas.palette_name=doc.palette.currentData() or 'viridis'; doc.canvas.refresh()
        else: self.apply_shared_scale()

    def reset_shared_scale(self):
        self._shared_applied=False
        if not self.common_scale.isChecked(): return
        for doc in self.documents:
            if doc and doc.canvas.kind=='raster':
                doc.canvas._default_limits(); doc.canvas.palette_name=doc.palette.currentData() or 'viridis'; doc.canvas.last_render=None; doc.canvas.refresh()

    def apply_shared_scale(self):
        if not all(self.documents): return
        canvases=[d.canvas for d in self.documents]
        compatible=all(c.kind=='raster' and not c.info.get('classes') and not c.info.get('native_rgb') for c in canvases) and len(canvases[0].bands)==len(canvases[1].bands)
        self.common_scale.setEnabled(compatible)
        if not compatible or not self.common_scale.isChecked() or self._shared_applied: return
        if not all(c.last_render and c.last_render.get('ranges') for c in canvases): return
        ranges=[c.last_render['ranges'] for c in canvases]
        shared=tuple((min(a[0],b[0]),max(a[1],b[1])) for a,b in zip(*ranges))
        self._shared_applied=True
        for canvas in canvases:
            canvas.limits=shared; canvas.palette_name=canvases[0].palette_name; canvas.refresh()
        self.note.setText('Échelle colorimétrique commune appliquée. Vérifier que les bandes représentent la même grandeur et les mêmes unités.')

    def capture(self): return dict(type='comparison',views=[d.capture() for d in self.documents if d],linked=self.link.isChecked(),common_scale=self.common_scale.isChecked())
    def restore(self,state):
        for doc,view in zip(self.documents,state.get('views',[])): doc.restore(view)
        self.link.setChecked(state.get('linked',True)); self.common_scale.setChecked(state.get('common_scale',False)); self.synchronize(0)
    def dispose(self):
        for doc in self.documents:
            if doc: doc.dispose()


class ResultsWorkspace(QWidget):
    """Persistent result catalogue and bounded, reusable embedded document tabs."""
    def __init__(self,parent=None):
        super().__init__(parent); self.records={}; self._documents={}; self._saved={}; self._closed=False
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        layout=QVBoxLayout(self); layout.setContentsMargins(0,0,0,0); layout.setSpacing(8)
        heading=QHBoxLayout(); title=QLabel('Visualisation des résultats'); title.setObjectName('panelTitle'); heading.addWidget(title); heading.addStretch()
        button('Ouvrir un résultat',self.browse,heading); layout.addLayout(heading)
        row=QHBoxLayout(); self.catalog=QComboBox(); self.catalog.setMinimumContentsLength(20)
        self.catalog.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        row.addWidget(self.catalog,1); button('Afficher',self.open_selected,row); self.compare_button=button('Comparer',self.compare,row); layout.addLayout(row)
        self.catalog.activated.connect(self.open_selected)
        self.tabs=QTabWidget(); self.tabs.setTabsClosable(True); self.tabs.setMovable(True); self.tabs.tabCloseRequested.connect(self.close_tab)
        layout.addWidget(self.tabs,1); self.empty=QLabel('Les résultats apparaîtront ici après le traitement.\n\nCartes et rasters · tableaux · graphiques · rapports\n\nOuvrez un résultat existant ou configurez un traitement dans le panneau de gauche.')
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter); self.empty.setWordWrap(True); self.empty.setObjectName('emptyResults'); self.tabs.addTab(self.empty,'Espace de résultats')
        self.activity=QLabel('Aucun traitement en cours.'); self.activity.setObjectName('muted'); self.activity.setWordWrap(True); layout.addWidget(self.activity)
        self.message=QLabel(''); self.message.setWordWrap(True); layout.addWidget(self.message)

    def register(self,record):
        if isinstance(record,(str,Path)): record=dict(data=str(record))
        path=str(Path(record['data']).resolve())
        if Path(path).suffix.lower() not in SUPPORTED or not Path(path).is_file(): return
        fresh=path not in self.records; self.records[path]={**self.records.get(path,{}),**record,'data':path}
        if fresh: self.catalog.addItem(record.get('name') or Path(path).name,path)
        index=self.catalog.findData(path); self.catalog.setItemData(index,path,Qt.ItemDataRole.ToolTipRole)
        for key in ('report','model','quality_report'):
            if record.get(key) and str(record[key])!=path: self.register(record[key])

    def browse(self):
        paths=QFileDialog.getOpenFileNames(self,'Résultats à visualiser',filter='Résultats (*.tif *.tiff *.jp2 *.vrt *.img *.gpkg *.shp *.geojson *.png *.jpg *.jpeg *.svg *.pdf *.csv *.tsv *.json)')[0]
        for path in paths: self.register(path); self.open_result(path)

    def open_selected(self,*args):
        path=self.catalog.currentData()
        if path: self.open_result(path)

    def _room(self):
        if self.tabs.indexOf(self.empty)>=0: self.tabs.removeTab(self.tabs.indexOf(self.empty))
        if self.tabs.count()>=8:
            self.close_tab(0); self.message.setText('Huit vues actives au maximum. Les résultats fermés restent disponibles dans la liste.')

    def open_result(self,path,*,title=None,refresh=False,transient=False):
        path=str(Path(path).resolve()); self.register(path)
        if path not in self.records: return None
        if transient: self.records[path]['transient']=True
        try:
            old=self._documents.get(path)
            if old is not None:
                changed=getattr(old,'file_id',None)!=identity(path) or getattr(old,'options',{})!=self.records[path]
                if refresh or changed:
                    index=self.tabs.indexOf(old); self.close_tab(index)
                else: self.tabs.setCurrentWidget(old); return old
            self._room()
            if Path(path).suffix.lower() in MAP_FORMATS:
                document=MapDocument(path,self.records[path]); document.reload_handler=lambda p=path:self.open_result(p,refresh=True)
            else:
                document=TablePanel(path); document.file_id=identity(path); document.options=dict(self.records[path])
                document.capture=lambda p=path:dict(type='table',path=p)
            self._documents[path]=document
            index=self.tabs.addTab(document,title or self.records[path].get('name') or Path(path).name); self.tabs.setTabToolTip(index,path); self.tabs.setCurrentIndex(index)
            self.catalog.setCurrentIndex(self.catalog.findData(path))
            if path in self._saved and hasattr(document,'restore'): document.restore(self._saved[path])
            self.message.clear(); return document
        except Exception as exc:
            self.message.setText('Visualisation impossible : '+str(exc)); return None

    def compare(self,*args,left=None,right=None):
        paths=[p for p in self.records if Path(p).suffix.lower() in MAP_FORMATS]
        if len(paths)<2: self.message.setText('Charger au moins deux cartes ou couches pour les comparer.'); return None
        left=left or (self.catalog.currentData() if self.catalog.currentData() in paths else paths[-2]); right=right or next(p for p in reversed(paths) if p!=left)
        self._room(); comparison=Comparison(dict(self.records),left,right); index=self.tabs.addTab(comparison,'Comparaison'); self.tabs.setCurrentIndex(index); return comparison

    def close_tab(self,index):
        widget=self.tabs.widget(index)
        if widget is None or widget is self.empty: return
        if hasattr(widget,'path'):
            if hasattr(widget,'capture'): self._saved[widget.path]=widget.capture()
            self._documents.pop(widget.path,None)
        if hasattr(widget,'dispose'): widget.dispose()
        self.tabs.removeTab(index); widget.deleteLater()

    def show_output(self,path):
        """Collect declared products and display the completed output, never a partial file."""
        path=Path(path).resolve(); self.message.clear()
        if path.is_dir():
            files=sorted(p for p in path.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED)
            for file in files: self.register(file)
            if files: self.open_result(files[0])
            return
        self.register(path)
        if path.suffix.lower()!='.json': self.open_result(path,refresh=True); return
        try:
            if path.stat().st_size>16*1024*1024: self.open_result(path); return
            record=json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(record,dict): self.open_result(path); return
            primary=[]; products=[]
            def valid(value):
                if not isinstance(value,str) or len(value)>4096 or '\n' in value: return None
                candidate=Path(value); candidate=candidate if candidate.is_absolute() else path.parent/candidate
                return candidate.resolve() if candidate.suffix.lower() in SUPPORTED and candidate.is_file() else None
            for key in ('outputs','maps'):
                primary.extend(p for value in record.get(key,[]) if (p:=valid(value)))
            if record.get('schema')=='cartomize.imagery.result.v1' or path.name=='imagery.json':
                for product in record.get('products',[]):
                    for key in ('composition','multiband'):
                        if p:=valid(product.get(key)): primary.append(p)
                    for band in product.get('bands',{}).values():
                        if p:=valid(band.get('path')): products.append(p)
            for key in ('primary','multiband','composite','quality_report'):
                if p:=valid(record.get(key)): products.append(p)
            for layer in record.get('layers',[]):
                if isinstance(layer,dict) and (p:=valid(layer.get('data'))): self.register({**layer,'data':str(p)}); products.append(p)
            for key in ('results','products'):
                if isinstance(record.get(key),dict):
                    def walk(value):
                        if isinstance(value,dict):
                            for child in value.values(): walk(child)
                        elif p:=valid(value): products.append(p)
                    walk(record[key])
            if str(record.get('schema','')).startswith('cartomize.batch.'):
                for job in record.get('jobs',[]):
                    if p:=valid(job.get('result') or job.get('output')): products.append(p)
            for p in primary+products: self.register(p)
            # PDF/SVG preserve vector labels and map furniture when zooming.
            ordered=sorted(primary,key=lambda p:{'.pdf':0,'.svg':1,'.png':2}.get(p.suffix.lower(),3))
            target=(ordered or products or [path])[0]
            self.open_result(target,refresh=True)
        except (ValueError,OSError,TypeError) as exc:
            self.open_result(path); self.message.setText('Rapport conservé ; collecte des produits : '+str(exc))

    def capture(self):
        records={p:r for p,r in self.records.items() if not r.get('transient')}
        views=[]
        for i in range(self.tabs.count()):
            widget=self.tabs.widget(i)
            if not hasattr(widget,'capture'): continue
            view=widget.capture()
            paths=[v['path'] for v in view.get('views',[])] if view['type']=='comparison' else [view['path']]
            if all(p in records for p in paths): views.append(view)
        return dict(records=list(records.values()),views=views,selected=self.tabs.currentIndex())

    def restore(self,state):
        for index in reversed(range(self.tabs.count())): self.close_tab(index)
        self.records={}; self.catalog.clear(); self._saved={}
        for record in state.get('records',[]): self.register(record)
        for view in state.get('views',[])[:8]:
            if view.get('type')=='comparison':
                paths=[v['path'] for v in view.get('views',[]) if Path(v['path']).is_file()]
                if len(paths)==2:
                    comparison=self.compare(left=paths[0],right=paths[1])
                    if comparison: comparison.restore(view)
            elif Path(view.get('path','')).is_file():
                document=self.open_result(view['path'])
                if document and hasattr(document,'restore'): document.restore(view)
        self.tabs.setCurrentIndex(min(state.get('selected',0),self.tabs.count()-1))

    def dispose(self):
        if self._closed: return
        self._closed=True
        for i in range(self.tabs.count()):
            document=self.tabs.widget(i)
            if hasattr(document,'dispose'): document.dispose()

    def closeEvent(self,event):
        self.dispose(); super().closeEvent(event)
