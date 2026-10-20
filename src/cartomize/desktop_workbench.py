"""Integrated desktop workbench built around the existing processing pages."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
import sys
import unicodedata

from PySide6.QtCore import QByteArray, QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QAction, QFontDatabase, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDockWidget, QFileDialog, QLabel, QMessageBox,
    QPlainTextEdit, QSpinBox, QToolBar, QTreeWidget, QTreeWidgetItem, QTabWidget,
)

from .desktop_console import ConsolePanel, EnvironmentPanel
from .desktop_theme import apply_theme


CATEGORIES = {
    'Projet': ('assistant', 'inspect', 'project'),
    'Raster': ('prepare', 'composite', 'classification', 'indices', 'calculator',
               'focal', 'temporal', 'raster'),
    'Vecteur': ('vector',),
    'Terrain': ('terrain',),
    'Cartographie': ('mapping', 'atlas', 'mapops'),
    'Automatisation': ('workflow', 'processing', 'recipes'),
    'Passerelles': ('native',),
}


def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFKD', text.casefold())
                   if not unicodedata.combining(c))


class Workbench(QObject):
    """Own UI connections without replacing processing engines or page state."""

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.initial_session = deepcopy(window.capture_session())
        self._last_status = ''
        self._catalogue_signature = None
        self.actions = {}
        self._closed = False
        self._build_workspace()
        self._build_bottom_panel()
        self._build_actions()
        self._configure_imports()
        self._default_docks = window.saveState(2)
        self.restore_layout()
        QApplication.instance().styleHints().colorSchemeChanged.connect(self.system_theme_changed)
        window.installEventFilter(self)
        window.setAcceptDrops(True)
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.synchronize)
        self.timer.start()
        self.synchronize()

    def _build_workspace(self):
        w = self.window
        # Keep the old header alive: some integration clients retain its widgets.
        old_root = w.takeCentralWidget()
        w.workspace_splitter.setParent(w)
        w.setCentralWidget(w.workspace_splitter)
        old_root.setParent(w)
        old_root.hide()
        self._retired_header = old_root
        w.workspace_splitter.insertWidget(0, w.workspace)
        w.workspace.setMinimumWidth(420)
        w.controls_panel.setMinimumWidth(350)
        w.controls_panel.setMaximumWidth(750)
        w.workspace_splitter.setStretchFactor(0, 1)
        w.workspace_splitter.setStretchFactor(1, 0)
        w.workspace_splitter.setSizes([800, 390])
        w.controls_panel.layout().setContentsMargins(8, 6, 8, 6)
        for label in w.controls_panel.findChildren(QLabel):
            if label.objectName() == 'panelTitle':
                label.setText('Paramètres')
        w.catalogue_toggle.hide()
        w.navigation.setMinimumHeight(150)
        w.navigation.setWordWrap(True)
        w.catalogue.setMinimumWidth(210)
        self.category = QComboBox()
        self.category.setAccessibleName('Catégorie de traitements')
        self.category.addItem('Tous les outils', '')
        for category in CATEGORIES:
            self.category.addItem(category, category)
        w.catalogue.layout().insertWidget(0, self.category)
        self.tool_count = QLabel()
        self.tool_count.setObjectName('muted')
        w.catalogue.layout().addWidget(self.tool_count)
        w.tool_search.setClearButtonEnabled(True)
        w.tool_search.setAccessibleName('Rechercher un outil')
        self.category.currentIndexChanged.connect(lambda *_: self.filter_tools(w.tool_search.text()))
        self.tools_dock = QDockWidget('Traitements', w)
        self.tools_dock.setObjectName('toolCatalogueDock')
        self.tools_dock.setWidget(w.catalogue)
        self.tools_dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        w.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.tools_dock)
        w.project_explorer.setMinimumWidth(210)
        w.project_explorer.setMaximumWidth(750)
        w.project_explorer.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable |
                                      QDockWidget.DockWidgetFeature.DockWidgetMovable |
                                      QDockWidget.DockWidgetFeature.DockWidgetFloatable)
        w.splitDockWidget(w.project_explorer, self.tools_dock, Qt.Orientation.Vertical)
        w.setDockNestingEnabled(True)
        self.filter_tools('')
        w.resizeDocks([w.project_explorer], [230], Qt.Orientation.Horizontal)
        w.resizeDocks([w.project_explorer, self.tools_dock], [210, 330], Qt.Orientation.Vertical)
        w.status.setMaximumHeight(36)
        w.statusBar().addWidget(w.status, 1)
        w.progress.setFixedWidth(160)
        w.statusBar().addPermanentWidget(w.progress)
        w.setCorner(Qt.Corner.BottomLeftCorner, Qt.DockWidgetArea.BottomDockWidgetArea)
        w.setCorner(Qt.Corner.BottomRightCorner, Qt.DockWidgetArea.BottomDockWidgetArea)

    def _build_bottom_panel(self):
        w = self.window
        self.bottom_dock = QDockWidget('Console et résultats', w)
        self.bottom_dock.setObjectName('consoleResultsDock')
        self.bottom_tabs = QTabWidget()
        self.console = ConsolePanel()
        self.console.activity.connect(self.log)
        self.logs = QPlainTextEdit()
        self.logs.setReadOnly(True)
        self.logs.setMaximumBlockCount(5000)
        self.logs.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.loaded = QTreeWidget()
        self.loaded.setHeaderLabels(['Données et résultats', 'Format', 'Emplacement'])
        self.loaded.setRootIsDecorated(False)
        self.loaded.setAlternatingRowColors(True)
        self.loaded.itemDoubleClicked.connect(self.open_loaded)
        self.loaded.currentItemChanged.connect(self.select_loaded)
        self.environment = EnvironmentPanel()
        self.bottom_tabs.addTab(self.console, 'Console Python')
        self.bottom_tabs.addTab(self.logs, 'Journaux')
        self.bottom_tabs.addTab(self.loaded, 'Données chargées')
        self.bottom_tabs.addTab(self.environment, 'Environnement')
        self.bottom_tabs.setCurrentWidget(self.logs)
        self.bottom_dock.setWidget(self.bottom_tabs)
        self.bottom_dock.setMinimumHeight(170)
        w.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.bottom_dock)
        w.resizeDocks([self.bottom_dock], [230], Qt.Orientation.Vertical)
        # Public references for embedding applications and automated GUI checks.
        w.console_panel = self.console
        w.environment_panel = self.environment
        w.tools_dock = self.tools_dock
        w.bottom_dock = self.bottom_dock

    def action(self, key, title, callback, shortcut=None):
        action = QAction(title, self.window)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(lambda checked=False: callback())
        self.actions[key] = action
        return action

    def _build_actions(self):
        w = self.window
        files = w.menuBar().addMenu('Fichier')
        definitions = (
            ('new', 'Nouveau projet', self.new_project, 'Ctrl+N'),
            ('open', 'Ouvrir un projet', w.open_session_dialog, 'Ctrl+O'),
            ('save', 'Enregistrer le projet', w.save_session_dialog, 'Ctrl+S'),
            ('portable', 'Exporter le projet portable', w.pack_session_dialog, 'Ctrl+Shift+S'),
            ('import', 'Importer des données', w.project_explorer.import_files, 'Ctrl+I'),
            ('open_script', 'Ouvrir un script', self.open_script, None),
            ('save_script', 'Enregistrer le script', self.save_script, None),
            ('quit', 'Quitter', w.close, 'Ctrl+Q'),
        )
        for key, title, callback, shortcut in definitions:
            files.addAction(self.action(key, title, callback, shortcut))
        edit = w.menuBar().addMenu('Édition')
        edit.addAction(self.action('undo', 'Annuler la modification', w.undo_session, 'Ctrl+Z'))
        edit.addAction(self.action('redo', 'Rétablir la modification', w.redo_session, 'Ctrl+Shift+Z'))
        views = w.menuBar().addMenu('Affichage')
        for dock in (w.project_explorer, self.tools_dock, self.bottom_dock):
            views.addAction(dock.toggleViewAction())
        views.addAction(self.action('console', 'Console Python', self.show_console, 'Ctrl+`'))
        views.addAction(self.action('reset_layout', 'Rétablir la disposition', self.reset_layout))
        tools = w.menuBar().addMenu('Traitements')
        for category, keys in CATEGORIES.items():
            submenu = tools.addMenu(category)
            for key in keys:
                if key in w.tool_pages:
                    title = w.navigation.item(list(w.tool_pages).index(key)).text()
                    submenu.addAction(self.action('tool_' + key, title, lambda k=key: self.select_tool(k)))
        tools.addAction(self.action('search', 'Rechercher un outil', self.focus_search, 'Ctrl+K'))
        tools.addAction(self.action('run', 'Exécuter le traitement', w.run_button.click, 'F5'))
        tools.addAction(self.action('cancel', 'Interrompre le traitement', w.cancel_button.click, 'Shift+F5'))
        help_menu = w.menuBar().addMenu('Aide')
        help_menu.addAction(self.action('environment', 'Diagnostic de l’environnement', self.show_environment))
        help_menu.addAction(self.action('about', 'À propos de Cartomize', self.show_about))
        toolbar = QToolBar('Projet', w)
        toolbar.setObjectName('projectToolbar')
        toolbar.setMovable(False)
        w.addToolBar(toolbar)
        w.brand_icon.setFixedSize(32, 32)
        pixmap = w.windowIcon().pixmap(28, 28)
        w.brand_icon.setPixmap(pixmap)
        toolbar.addWidget(w.brand_icon)
        brand = QLabel('Cartomize')
        brand.setObjectName('brand')
        toolbar.addWidget(brand)
        toolbar.addSeparator()
        for key in ('open', 'save', 'import', 'run'):
            toolbar.addAction(self.actions[key])
        toolbar.addSeparator()
        toolbar.addWidget(QLabel('Thème'))
        toolbar.addWidget(w.theme_selector)
        toolbar.addWidget(QLabel('Texte'))
        self.font_size = QSpinBox()
        self.font_size.setRange(11, 16)
        self.font_size.setSuffix(' px')
        try:
            size = int(w._preferences.value('appearance/font_size', 12))
        except (TypeError, ValueError):
            size = 12
        self.font_size.setValue(size)
        self.font_size.setAccessibleName('Taille du texte de l’interface')
        self.font_size.valueChanged.connect(self.set_font_size)
        toolbar.addWidget(self.font_size)
        self.toolbar = toolbar

    def _configure_imports(self):
        w = self.window
        # The explorer emits only after a supported file was actually opened.
        w.project_explorer.fileOpened.connect(self.imported)
        w.project_explorer.projectRequested.connect(self.open_project)

    def imported(self, path):
        w = self.window
        try:
            w.register_result({'data': path})
        except (OSError, ValueError) as exc:
            self.log(str(exc))
        self.synchronize()

    def open_project(self, path):
        try:
            self.window.open_session_file(path)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self.window, 'Ouverture du projet', str(exc))

    def log(self, text):
        self.logs.appendPlainText(f'{datetime.now():%H:%M:%S}  {text}')

    def synchronize(self):
        if self._closed:
            return
        w = self.window
        status = w.status.text()
        if status and status != self._last_status:
            self.log(status)
            self._last_status = status
        busy = w.thread is not None
        for key in ('new', 'open', 'save', 'portable', 'undo', 'redo'):
            self.actions[key].setEnabled(not busy)
        self.actions['run'].setEnabled(w.run_button.isEnabled())
        self.actions['cancel'].setEnabled(w.cancel_button.isEnabled())
        signature = tuple((p, str(r.get('name', ''))) for p, r in w.workspace.records.items())
        if signature != self._catalogue_signature:
            selected = self.loaded.currentItem()
            selected_path = selected.data(0, Qt.ItemDataRole.UserRole) if selected else None
            self.loaded.blockSignals(True)
            self.loaded.clear()
            for path, title in signature:
                item = QTreeWidgetItem([title or Path(path).name, Path(path).suffix.lstrip('.').upper(), path])
                item.setData(0, Qt.ItemDataRole.UserRole, path)
                item.setToolTip(0, path)
                self.loaded.addTopLevelItem(item)
                if path == selected_path:
                    self.loaded.setCurrentItem(item)
            self.loaded.blockSignals(False)
            self.loaded.resizeColumnToContents(0)
            self.loaded.resizeColumnToContents(1)
            self.console.context_paths = [p for p, _ in signature]
            self._catalogue_signature = signature

    def filter_tools(self, text):
        w = self.window
        category = self.category.currentData()
        allowed = set(CATEGORIES.get(category, w.tool_pages))
        query = normalized(text)
        count = 0
        for index, key in enumerate(w.tool_pages):
            item = w.navigation.item(index)
            visible = key in allowed and query in normalized(item.text())
            item.setHidden(not visible)
            count += int(visible)
        self.tool_count.setText(f'{count} / {len(w.tool_pages)} outils')

    def select_tool(self, key):
        if self.window.thread is not None:
            return
        self.category.setCurrentIndex(0)
        self.window.tool_search.clear()
        self.tools_dock.show()
        self.window.select_tool(key)
        self.window.navigation.scrollToItem(self.window.navigation.currentItem())

    def focus_search(self):
        self.tools_dock.show()
        self.window.tool_search.setFocus()
        self.window.tool_search.selectAll()

    def show_console(self):
        self.bottom_dock.show()
        self.bottom_tabs.setCurrentWidget(self.console)
        self.console.editor.setFocus()

    def show_environment(self):
        self.environment.refresh()
        self.bottom_dock.show()
        self.bottom_tabs.setCurrentWidget(self.environment)

    def open_loaded(self, item, column=0):
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if path:
            self.window.workspace.open_result(path)

    def select_loaded(self, item, previous=None):
        if item is None or self.window.thread is not None:
            return
        path = item.data(0, Qt.ItemDataRole.UserRole)
        try:
            self.window.register_result({'data': path})
        except (OSError, ValueError) as exc:
            self.log(str(exc))

    def new_project(self):
        w = self.window
        if w.thread is not None:
            return
        answer = QMessageBox.question(w, 'Nouveau projet',
                                      'Fermer le projet courant ? Les modifications non enregistrées seront perdues.',
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        w.restore_session(deepcopy(self.initial_session))
        w.session_path = None
        w.history = []
        w.history_index = -1
        w.output_path = None
        w.folder_button.setEnabled(False)
        w.checkpoint()
        w.status.setText('Nouveau projet')
        self.synchronize()

    def open_script(self):
        path, _ = QFileDialog.getOpenFileName(self.window, 'Ouvrir un script', filter='Python (*.py);;Texte (*.txt)')
        if not path:
            return
        try:
            source = Path(path)
            if source.stat().st_size > 1_000_000:
                raise ValueError('Le script dépasse 1 Mo.')
            self.console.editor.setPlainText(source.read_text(encoding='utf-8-sig'))
            self.show_console()
        except (OSError, UnicodeError, ValueError) as exc:
            QMessageBox.warning(self.window, 'Ouverture du script', str(exc))

    def save_script(self):
        path, _ = QFileDialog.getSaveFileName(self.window, 'Enregistrer le script', 'analyse.py', 'Python (*.py)')
        if path:
            try:
                Path(path).write_text(self.console.editor.toPlainText(), encoding='utf-8')
            except OSError as exc:
                QMessageBox.warning(self.window, 'Enregistrement du script', str(exc))

    def show_about(self):
        import cartomize as cm
        QMessageBox.about(self.window, 'Cartomize',
                          f'Cartomize {cm.__version__}\nCartographie et traitements géospatiaux\n'
                          f'Python {sys.version.split()[0]}\nLicence GPL-3.0-only')

    def set_font_size(self, size):
        self.window._preferences.setValue('appearance/font_size', size)
        apply_theme(self.window)

    def system_theme_changed(self, *_):
        if self.window.theme_selector.currentData() == 'system':
            apply_theme(self.window)

    def restore_layout(self):
        w = self.window
        geometry = w._preferences.value('workbench/geometry')
        state = w._preferences.value('workbench/docks')
        if isinstance(geometry, QByteArray):
            w.restoreGeometry(geometry)
        if isinstance(state, QByteArray):
            w.restoreState(state, 2)
        directory = w._preferences.value('workbench/directory', '')
        if directory and Path(str(directory)).is_dir():
            w.project_explorer.set_directory(directory)

    def reset_layout(self):
        w = self.window
        w.restoreState(self._default_docks, 2)
        for dock in (w.project_explorer, self.tools_dock, self.bottom_dock):
            dock.setFloating(False)
            dock.show()
        w.workspace_splitter.setSizes([800, 390])
        w.resizeDocks([w.project_explorer], [230], Qt.Orientation.Horizontal)
        w.resizeDocks([self.bottom_dock], [230], Qt.Orientation.Vertical)

    def shutdown(self):
        if self._closed:
            return
        self._closed = True
        self.timer.stop()
        self.console.shutdown()
        w = self.window
        w._preferences.setValue('workbench/geometry', w.saveGeometry())
        w._preferences.setValue('workbench/docks', w.saveState(2))
        w._preferences.setValue('workbench/directory', w.project_explorer.path_label.text())

    def eventFilter(self, watched, event):
        if watched is self.window:
            if event.type() == QEvent.Type.Close and self.window.thread is None:
                self.shutdown()
            elif event.type() == QEvent.Type.DragEnter:
                if event.mimeData().hasUrls() and all(u.isLocalFile() for u in event.mimeData().urls()):
                    event.acceptProposedAction()
                    return True
            elif event.type() == QEvent.Type.Drop and event.mimeData().hasUrls():
                for url in event.mimeData().urls():
                    if url.isLocalFile():
                        path = Path(url.toLocalFile())
                        if path.is_dir():
                            self.window.project_explorer.set_directory(path)
                        else:
                            self.window.project_explorer.open_path(path)
                event.acceptProposedAction()
                return True
        return super().eventFilter(watched, event)


def install_workbench(window):
    if not hasattr(window, '_workbench'):
        window._workbench = Workbench(window)
    return window._workbench
