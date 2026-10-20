"""Local project browser connected to the result viewer and processing inputs."""
from pathlib import Path

from PySide6.QtCore import Qt, QDir, Signal
from PySide6.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QFileDialog, QFileSystemModel, QTreeView, QLineEdit, QMessageBox,
)

from .viewer_data import SUPPORTED


class ProjectExplorer(QDockWidget):
    fileOpened = Signal(str)
    projectRequested = Signal(str)

    def __init__(self, workspace, parent=None):
        super().__init__('Explorateur de projet', parent)
        self.setObjectName('projectExplorerDock')
        self.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea |
                             Qt.DockWidgetArea.RightDockWidgetArea)
        self.workspace = workspace
        shell = QWidget(self)
        layout = QVBoxLayout(shell)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        row = QHBoxLayout()
        self.folder_button = QPushButton('Dossier')
        self.folder_button.clicked.connect(self.choose_directory)
        self.import_button = QPushButton('Importer')
        self.import_button.clicked.connect(self.import_files)
        self.parent_button = QPushButton('Parent')
        self.parent_button.setToolTip('Dossier parent')
        self.parent_button.clicked.connect(self.parent_directory)
        for button in (self.folder_button, self.parent_button, self.import_button):
            row.addWidget(button)
        layout.addLayout(row)
        self.path_label = QLineEdit()
        self.path_label.setReadOnly(True)
        self.path_label.setAccessibleName('Répertoire de travail')
        layout.addWidget(self.path_label)
        self.model = QFileSystemModel(self)
        self.model.setReadOnly(True)
        self.model.setFilter(QDir.Filter.AllEntries | QDir.Filter.NoDotAndDotDot)
        self.model.setRootPath(str(Path.home()))
        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.setHeaderHidden(True)
        self.tree.setSortingEnabled(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setAccessibleName('Fichiers du projet')
        for column in (1, 2, 3):
            self.tree.hideColumn(column)
        self.tree.doubleClicked.connect(self.open_item)
        layout.addWidget(self.tree, 1)
        self.setWidget(shell)
        self.setMinimumWidth(210)
        self.set_directory(Path.home())

    def set_directory(self, directory):
        directory = Path(directory).expanduser().resolve()
        if not directory.is_dir():
            return False
        self.model.setRootPath(str(directory))
        self.path_label.setText(str(directory))
        self.path_label.setToolTip(str(directory))
        self.tree.setRootIndex(self.model.index(str(directory)))
        return True

    def parent_directory(self):
        self.set_directory(Path(self.path_label.text()).parent)

    def choose_directory(self):
        folder = QFileDialog.getExistingDirectory(self, 'Répertoire du projet', self.path_label.text())
        if folder:
            self.set_directory(folder)

    def import_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, 'Importer des données', self.path_label.text(),
            'Données et projets (*.tif *.tiff *.vrt *.img *.jp2 *.gpkg *.shp *.geojson '
            '*.png *.jpg *.jpeg *.pdf *.svg *.csv *.tsv *.json *.cmz);;Tous les fichiers (*)',
        )
        for path in paths:
            self.open_path(path)
        if paths:
            self.set_directory(Path(paths[0]).parent)

    def open_item(self, index):
        path = Path(self.model.filePath(index))
        if path.is_dir():
            self.set_directory(path)
        else:
            self.open_path(path)

    def open_path(self, path):
        path = Path(path).expanduser().resolve()
        if not path.is_file():
            QMessageBox.information(self, 'Fichier indisponible', str(path))
            return None
        if path.suffix.lower() == '.cmz' or path.name.lower().endswith('.cartomize.json'):
            self.projectRequested.emit(str(path))
            return None
        if path.suffix.lower() not in SUPPORTED:
            QMessageBox.information(self, 'Format non pris en charge',
                                    'Le visualiseur ne prend pas en charge ce format.')
            return None
        document = self.workspace.open_result(str(path))
        if document is not None:
            self.fileOpened.emit(str(path))
        return document
