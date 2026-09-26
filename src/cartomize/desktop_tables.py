"""Paged result tables and scientific plots embedded in the main workspace."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Slot
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QComboBox,QPushButton,QLabel,
                              QLineEdit,QTableView,QPlainTextEdit,QTabWidget)
from .desktop_canvas import ReadJob,IO_POOL
from .viewer_data import table_page, report_tables


class FrameModel(QAbstractTableModel):
    def __init__(self,frame,offset=0,parent=None): super().__init__(parent); self.frame=frame; self.offset=offset
    def rowCount(self,parent=QModelIndex()): return 0 if parent.isValid() else len(self.frame)
    def columnCount(self,parent=QModelIndex()): return 0 if parent.isValid() else len(self.frame.columns)
    def data(self,index,role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid(): return None
        value=self.frame.iat[index.row(),index.column()]
        if isinstance(value,np.generic): value=value.item()
        if role==Qt.ItemDataRole.UserRole: return value if isinstance(value,(float,int,str)) else str(value)
        if role in {Qt.ItemDataRole.DisplayRole,Qt.ItemDataRole.ToolTipRole}:
            if value is None: return ''
            if isinstance(value,float): return '' if pd.isna(value) else f'{value:.8g}'
            return str(value)
        return None
    def headerData(self,section,orientation,role=Qt.ItemDataRole.DisplayRole):
        if role!=Qt.ItemDataRole.DisplayRole: return None
        return str(self.frame.columns[section]) if orientation==Qt.Orientation.Horizontal else str(self.offset+section+1)


class TablePanel(QWidget):
    def __init__(self,path,*,layer=None,parent=None):
        super().__init__(parent); self.path=str(path); self.layer=layer; self.offset=0; self._closed=False; self._serial=0
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.frame=pd.DataFrame(); self._reports={}; self._report_mode=Path(path).suffix.lower()=='.json'
        layout=QVBoxLayout(self); layout.setContentsMargins(0,0,0,0)
        row=QHBoxLayout(); self.selection=QComboBox(); self.selection.setMinimumContentsLength(14)
        self.filter=QLineEdit(); self.filter.setPlaceholderText('Filtrer les lignes affichées')
        self.previous=QPushButton('Précédent'); self.next=QPushButton('Suivant')
        self.previous.clicked.connect(lambda:self.load(max(0,self.offset-2000))); self.next.clicked.connect(lambda:self.load(self.offset+2000))
        row.addWidget(self.selection,1); row.addWidget(self.filter,1); row.addWidget(self.previous); row.addWidget(self.next); layout.addLayout(row)
        self.tabs=QTabWidget(); layout.addWidget(self.tabs,1)
        self.table=QTableView(); self.table.setAlternatingRowColors(True); self.table.setSortingEnabled(True)
        self.proxy=QSortFilterProxyModel(self); self.proxy.setSortRole(Qt.ItemDataRole.UserRole)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive); self.proxy.setFilterKeyColumn(-1)
        self.table.setModel(self.proxy); self.filter.textChanged.connect(self.proxy.setFilterFixedString)
        self.tabs.addTab(self.table,'Tableau')
        graph=QWidget(); self.graph_layout=QVBoxLayout(graph); controls=QHBoxLayout()
        self.x=QComboBox(); self.y=QComboBox(); self.plot_kind=QComboBox()
        for label,key in [('Barres','bar'),('Courbe','line'),('Nuage de points','scatter'),('Matrice','matrix')]: self.plot_kind.addItem(label,key)
        draw=QPushButton('Tracer'); draw.clicked.connect(self.plot)
        controls.addWidget(QLabel('X')); controls.addWidget(self.x,1); controls.addWidget(QLabel('Y')); controls.addWidget(self.y,1); controls.addWidget(self.plot_kind); controls.addWidget(draw)
        self.graph_layout.addLayout(controls); self.plot_note=QLabel('Le graphique utilise les lignes de la page affichée.'); self.plot_note.setWordWrap(True); self.graph_layout.addWidget(self.plot_note)
        self.tabs.addTab(graph,'Graphique'); self.figure=None; self.canvas=None
        self.raw=QPlainTextEdit(); self.raw.setReadOnly(True)
        if self._report_mode: self.tabs.addTab(self.raw,'Rapport complet')
        self.status=QLabel('Chargement du résultat…'); self.status.setWordWrap(True); layout.addWidget(self.status)
        self.selection.currentIndexChanged.connect(self.select_report)
        self.previous.setVisible(not self._report_mode); self.next.setVisible(not self._report_mode)
        self.selection.setVisible(self._report_mode); self.load(0)

    def load(self,offset=0):
        self._serial+=1; serial=self._serial; path=self.path; layer=self.layer; reports=self._report_mode
        self.previous.setEnabled(False); self.next.setEnabled(False); self.status.setText('Lecture de la page…')
        def read():
            if not reports: return table_page(path,offset,layer=layer)
            if Path(path).stat().st_size>16*1024*1024: raise ValueError('Rapport supérieur à 16 Mio : consulter le fichier complet avec un éditeur adapté.')
            document=json.loads(Path(path).read_text(encoding='utf-8')); text=json.dumps(document,ensure_ascii=False,indent=2)
            return dict(reports=report_tables(document),text=text[:500000],truncated=len(text)>500000)
        self._job=ReadJob(serial,read); self._job.signals.done.connect(self._loaded); IO_POOL.start(self._job)

    @Slot(object,object,str)
    def _loaded(self,serial,result,error):
        if self._closed or serial!=self._serial: return
        if error: self.status.setText('Lecture impossible : '+error); return
        if self._report_mode:
            self._reports=result['reports']; self.raw.setPlainText(result['text'])
            self.selection.blockSignals(True); self.selection.clear(); self.selection.addItems(list(self._reports)); self.selection.blockSignals(False)
            self.select_report()
            if result['truncated']: self.status.setText('Texte limité à 500 000 caractères ; le rapport original est conservé intégralement.')
        else:
            self.offset=result['offset']; self.previous.setEnabled(self.offset>0); self.next.setEnabled(result['more']); self.set_frame(result['frame'])
            self.status.setText(f'Lignes {self.offset+1 if len(self.frame) else 0}–{self.offset+len(self.frame)} · lecture par pages de 2 000 lignes. Tri et filtre sur la page affichée.')

    def select_report(self,*args):
        if self._reports:
            self.offset=0; self.set_frame(self._reports[self.selection.currentText()]); self.status.setText(f'{len(self.frame)} lignes · {self.selection.currentText()}')

    def set_frame(self,frame):
        self.frame=frame; old=getattr(self,'model',None); self.model=FrameModel(frame,self.offset,self)
        self.proxy.setSourceModel(self.model)
        if old is not None: old.deleteLater()
        self.table.resizeColumnsToContents()
        for i in range(len(frame.columns)): self.table.setColumnWidth(i,min(260,max(90,self.table.columnWidth(i))))
        self.x.clear(); self.y.clear()
        for i,column in enumerate(frame.columns): self.x.addItem(str(column),i); self.y.addItem(str(column),i)
        numeric=[i for i in range(len(frame.columns)) if pd.to_numeric(frame.iloc[:,i],errors='coerce').notna().any()]
        if numeric: self.y.setCurrentIndex(numeric[-1])
        if self.figure is not None: self.figure.clear(); self.canvas.draw_idle()

    def plot(self):
        if self.frame.empty: self.plot_note.setText('Aucune valeur à représenter.'); return
        if self.figure is None:
            from matplotlib.figure import Figure
            from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg,NavigationToolbar2QT
            self.figure=Figure(figsize=(6,4),constrained_layout=True); self.canvas=FigureCanvasQTAgg(self.figure)
            self.graph_layout.addWidget(NavigationToolbar2QT(self.canvas,self)); self.graph_layout.addWidget(self.canvas,1)
        self.figure.clear(); ax=self.figure.add_subplot(111); kind=self.plot_kind.currentData()
        try:
            if kind=='matrix':
                numeric=self.frame.apply(pd.to_numeric,errors='coerce').dropna(axis=1,how='all')
                if numeric.empty: raise ValueError('Choisir un tableau contenant une matrice numérique.')
                if numeric.shape[0]>200 or numeric.shape[1]>200: raise ValueError('La matrice affichée est limitée à 200 × 200 cellules.')
                im=ax.imshow(numeric.to_numpy(dtype=float),cmap='viridis',aspect='auto'); self.figure.colorbar(im,ax=ax)
                ax.set_xlabel('Colonnes'); ax.set_ylabel('Lignes')
            else:
                xi,yi=self.x.currentData(),self.y.currentData()
                values=pd.to_numeric(self.frame.iloc[:,yi],errors='coerce'); valid=values.notna()
                x=self.frame.iloc[:,xi][valid]; y=values[valid]
                if not len(y): raise ValueError('La colonne Y ne contient pas de valeurs numériques.')
                if kind=='bar':
                    if len(y)>100: raise ValueError('Choisir une courbe ou un nuage de points pour plus de 100 catégories.')
                    ax.bar(range(len(y)),y,color='#42644f'); ax.set_xticks(range(len(y)),x.astype(str),rotation=45,ha='right')
                else:
                    x=pd.to_numeric(x,errors='coerce'); good=x.notna()
                    if not good.any(): raise ValueError('La colonne X doit être numérique pour cette représentation.')
                    if kind=='line': ax.plot(x[good],y[good],color='#42644f')
                    else: ax.scatter(x[good],y[good],color='#42644f',s=16)
                ax.set_xlabel(str(self.frame.columns[xi])); ax.set_ylabel(str(self.frame.columns[yi])); ax.grid(alpha=.15)
            self.plot_note.setText('Graphique de la page affichée · navigation et export disponibles ci-dessous.')
            self.tabs.setCurrentIndex(1)
        except (ValueError,TypeError) as exc: self.plot_note.setText(str(exc))
        self.canvas.draw_idle()

    def dispose(self):
        self._closed=True; self._serial+=1
        if self._job.future is not None: self._job.future.cancel()

    def closeEvent(self,event):
        self.dispose(); super().closeEvent(event)
