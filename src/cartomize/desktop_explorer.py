"""File-system project explorer for the Cartomize desktop workspace."""
from pathlib import Path

from PySide6.QtCore import Qt, QDir
from PySide6.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFileDialog, QFileSystemModel, QTreeView,
    QLineEdit, QMessageBox,
)

from .viewer_data import SUPPORTED


class ProjectExplorer(QDockWidget):
    """Dockable local-data browser connected to the existing result viewer."""

    def __init__(self, workspace, parent=None):
        super().__init__("Explorateur de projet", parent)
        self.setObjectName("projectExplorerDock")
        self.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea |
                             Qt.DockWidgetArea.RightDockWidgetArea)
        self.workspace = workspace
        shell = QWidget(self)
        layout = QVBoxLayout(shell)
        layout.setContentsMargins(9, 9, 9, 9)
        layout.setSpacing(8)

        row = QHBoxLayout()
        open_folder = QPushButton("Dossier")
        open_folder.clicked.connect(self.choose_directory)
        import_files = QPushButton("Importer")
        import_files.clicked.connect(self.import_files)
        row.addWidget(open_folder)
        row.addWidget(import_files)
        layout.addLayout(row)

        self.path_label = QLineEdit()
        self.path_label.setReadOnly(True)
        self.path_label.setToolTip("Répertoire de travail")
        layout.addWidget(self.path_label)

        self.model = QFileSystemModel(self)
        self.model.setFilter(QDir.Filter.AllEntries | QDir.Filter.NoDotAndDotDot)
        self.model.setRootPath(str(Path.home()))
        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.setHeaderHidden(False)
        self.tree.setSortingEnabled(True)
        self.tree.setAlternatingRowColors(True)
        for column in (1, 2, 3):
            self.tree.hideColumn(column)
        self.tree.doubleClicked.connect(self.open_item)
        layout.addWidget(self.tree, 1)

        layout.addWidget(QLabel("Double-cliquer pour ouvrir un fichier ou un dossier."))
        self.setWidget(shell)
        self.setMinimumWidth(220)
        self.set_directory(Path.home())

    def set_directory(self, directory):
        directory = Path(directory).expanduser().resolve()
        if not directory.is_dir():
            return
        self.path_label.setText(str(directory))
        self.tree.setRootIndex(self.model.index(str(directory)))

    def choose_directory(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Répertoire du projet", self.path_label.text()
        )
        if folder:
            self.set_directory(folder)

    def import_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Importer des données", self.path_label.text(),
            "Données géospatiales et résultats (*.tif *.tiff *.vrt *.img *.jp2 "
            "*.gpkg *.shp *.geojson *.png *.jpg *.jpeg *.pdf *.svg "
            "*.csv *.tsv *.json);;Tous les fichiers (*)",
        )
        for path in paths:
            self.open_path(Path(path))
        if paths:
            self.set_directory(Path(paths[0]).parent)

    def open_item(self, index):
        path = Path(self.model.filePath(index))
        if path.is_dir():
            self.set_directory(path)
        else:
            self.open_path(path)

    def open_path(self, path):
        if path.suffix.lower() not in SUPPORTED:
            QMessageBox.information(
                self, "Format non pris en charge",
                "Le visualiseur ne prend pas en charge ce format."
            )
            return
        self.workspace.open_result(str(path))
