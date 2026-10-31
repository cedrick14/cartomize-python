"""Window-local appearance; scientific layer styles remain unchanged."""
from PySide6.QtCore import Qt
import os
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


COLORS = {
    'dark': dict(bg='#1c232d', panel='#242e3b', field='#283544', text='#e5ecf4',
                 muted='#a3b2c4', line='#3b4b5e', selected='#254568', accent='#3688d6'),
    'light': dict(bg='#f3f5f8', panel='#ffffff', field='#ffffff', text='#243142',
                  muted='#5b6b7f', line='#d1d9e3', selected='#dcecff', accent='#1768b2'),
}


def apply_theme(window, *_):
    choice = window.theme_selector.currentData() or 'system'
    window._preferences.setValue('appearance/theme', choice)
    scheme = QApplication.instance().styleHints().colorScheme()
    if choice == 'system':
        dark = (scheme == Qt.ColorScheme.Dark if scheme != Qt.ColorScheme.Unknown
                else window._system_palette.color(QPalette.ColorRole.Window).lightness() < 128)
    else:
        dark = choice == 'dark'
    colors = COLORS['dark' if dark else 'light']
    window._effective_theme = 'dark' if dark else 'light'
    palette = QPalette(window._system_palette)
    roles = {
        'Window': 'bg', 'WindowText': 'text', 'Base': 'field', 'AlternateBase': 'panel',
        'Text': 'text', 'Button': 'panel', 'ButtonText': 'text', 'Highlight': 'accent',
        'Link': 'accent', 'LinkVisited': 'accent', 'ToolTipBase': 'panel',
        'ToolTipText': 'text', 'PlaceholderText': 'muted', 'Accent': 'accent',
    }
    for role, name in roles.items():
        palette.setColor(getattr(QPalette.ColorRole, role), QColor(colors[name]))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor('#ffffff'))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText,
                 QPalette.ColorRole.WindowText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(colors['muted']))
    window.setPalette(palette)
    try:
        size = max(11, min(16, int(window._preferences.value('appearance/font_size', 12))))
    except (TypeError, ValueError):
        size = 12
    # Font inheritance is much cheaper than a universal QWidget QSS selector.
    # The previous "QMainWindow, QWidget" rule forced Qt to repolish the complete
    # (large) Cartomize widget tree on Windows and could stall startup.
    font = window.font()
    font.setPixelSize(size)
    window.setFont(font)
    if os.environ.get('CARTOMIZE_SAFE_THEME', '').strip() == '1':
        window.setStyleSheet('')
        if hasattr(window, 'dock_manager'):
            window.dock_manager._sync_titles()
        return
    c = dict(colors, size=size)
    stylesheet = '''
        QMainWindow { background: %(bg)s; color: %(text)s; }
        QLabel#brand { font-size: 21px; font-weight: 700; }
        QLabel#panelTitle { font-size: 15px; font-weight: 600; }
        QLabel#pageTitle { font-size: 18px; font-weight: 600; padding: 2px 0 5px; }
        QLabel#description, QLabel#muted { color: %(muted)s; }
        QLabel#emptyResults { background: %(panel)s; color: %(muted)s; padding: 22px; }
        QLabel#sequence { background: %(panel)s; padding: 8px; }
        QToolBar { border: 0; border-bottom: 1px solid %(line)s; spacing: 5px; padding: 5px; }
        QToolBar::separator { width: 1px; background: %(line)s; margin: 5px; }
        QMenuBar, QStatusBar { background: %(panel)s; }
        QMenuBar::item { padding: 6px 10px; }
        QMenuBar::item:selected, QMenu::item:selected { background: %(selected)s; }
        QMenu { background: %(panel)s; border: 1px solid %(line)s; padding: 4px; }
        QMenu::item { padding: 6px 24px 6px 12px; }
        QMenu::separator { height: 1px; background: %(line)s; margin: 4px 8px; }
        QDockWidget { border: 0; }
        QDockWidget::title { background: %(panel)s; padding: 7px; font-weight: 600; }
        QWidget#dockPanelTitle { background: %(panel)s; border-bottom: 1px solid %(line)s; }
        QLabel#dockPanelLabel { background: transparent; font-weight: 600; }
        QToolButton#dockPanelAction { padding: 2px; border: 0; border-radius: 3px; }
        QToolButton#dockPanelAction:hover { background: %(selected)s; }
        QMainWindow::separator { background: %(line)s; width: 5px; height: 5px; }
        QMainWindow::separator:hover { background: %(accent)s; }
        QSplitter::handle { background: %(line)s; width: 5px; height: 5px; }
        QLineEdit, QPlainTextEdit, QTableWidget, QTableView, QListWidget, QTreeWidget,
        QTreeView, QComboBox, QSpinBox, QDoubleSpinBox, QAbstractItemView {
            background: %(field)s; color: %(text)s; border: 1px solid %(line)s;
            border-radius: 4px; padding: 5px;
            selection-background-color: %(selected)s; selection-color: %(text)s;
            alternate-background-color: %(panel)s;
        }
        QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus { border-color: %(accent)s; }
        QListWidget#navigation { background: %(panel)s; padding: 3px; }
        QListWidget#navigation::item { border: 0; padding: 7px 8px; margin: 1px; }
        QListWidget#navigation::item:selected { background: %(selected)s; font-weight: 600; }
        QPushButton, QToolButton { background: %(panel)s; border: 1px solid %(line)s;
            border-radius: 4px; padding: 6px 9px; }
        QPushButton:hover, QToolButton:hover { border-color: %(accent)s; }
        QPushButton#primary { background: %(accent)s; color: #ffffff;
            border: 0; min-width: 105px; font-weight: 600; padding: 8px 12px; }
        QPushButton:disabled, QToolButton:disabled { color: %(muted)s; background: %(bg)s; }
        QGroupBox { border: 1px solid %(line)s; border-radius: 5px;
            margin-top: 15px; padding: 10px 6px 6px; }
        QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
        QProgressBar { border: 1px solid %(line)s; background: %(field)s;
            text-align: center; min-height: 14px; }
        QProgressBar::chunk { background: %(accent)s; }
        QScrollArea { border: 0; }
        QTabWidget::pane { border: 1px solid %(line)s; padding: 2px; }
        QTabBar::tab { background: %(panel)s; padding: 7px 10px;
            border-bottom: 2px solid transparent; }
        QTabBar::tab:selected { background: %(bg)s; border-bottom: 2px solid %(accent)s; }
        QHeaderView::section { background: %(panel)s; color: %(text)s;
            border: 0; border-bottom: 1px solid %(line)s; padding: 6px; }
        QToolTip { background: %(panel)s; color: %(text)s; border: 1px solid %(line)s; }
        QScrollBar:vertical { background: %(bg)s; width: 12px; margin: 0; }
        QScrollBar:horizontal { background: %(bg)s; height: 12px; margin: 0; }
        QScrollBar::handle { background: %(line)s; border-radius: 4px; min-height: 24px; min-width: 24px; }
        QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
        QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
    ''' % c
    # Avoid needless repolish when the effective theme and font did not change.
    if getattr(window, '_cartomize_stylesheet', None) != stylesheet:
        window.setStyleSheet(stylesheet)
        window._cartomize_stylesheet = stylesheet
    if hasattr(window, 'dock_manager'):
        window.dock_manager._sync_titles()
