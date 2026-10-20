"""Keep parameters and map views usable on compact desktop displays."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import QBoxLayout, QLayout, QScrollArea, QSizePolicy, QVBoxLayout, QWidget


class AdaptiveWorkspace(QObject):
    """Scroll parameter content while retaining the execution controls."""

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.pending = False
        self._closed = False
        self._transfer_row = None
        self._wrap_parameters()
        for index in range(window.results_box.layout().count()):
            row = window.results_box.layout().itemAt(index).layout()
            if isinstance(row, QBoxLayout) and row.indexOf(window.transfer_button) >= 0:
                self._transfer_row = row
                row.setDirection(QBoxLayout.Direction.TopToBottom)
                break
        window.result_target.setMinimumContentsLength(12)
        window.result_target.setSizeAdjustPolicy(window.result_choice.sizeAdjustPolicy())
        workbench = window._workbench
        window.workspace.setMinimumHeight(360)
        window.navigation.setMinimumHeight(70)
        for dock, minimum in ((window.project_explorer, 130), (workbench.tools_dock, 150)):
            panel = dock.widget()
            panel.setMinimumHeight(minimum)
            policy = panel.sizePolicy()
            policy.setVerticalPolicy(QSizePolicy.Policy.Ignored)
            panel.setSizePolicy(policy)
            dock.setMinimumHeight(minimum + 20)
        workbench.bottom_tabs.setMinimumHeight(90)
        policy = workbench.bottom_tabs.sizePolicy()
        policy.setVerticalPolicy(QSizePolicy.Policy.Ignored)
        workbench.bottom_tabs.setSizePolicy(policy)
        workbench.bottom_dock.setMinimumHeight(130)
        output = window.console_panel.output
        output.setMinimumHeight(32)
        policy = output.sizePolicy()
        policy.setVerticalPolicy(QSizePolicy.Policy.Ignored)
        output.setSizePolicy(policy)
        for key, label in [('open', 'Ouvrir'), ('save', 'Enregistrer'),
                           ('import', 'Importer'), ('run', 'Exécuter')]:
            action = workbench.actions[key]
            control = workbench.toolbar.widgetForAction(action)
            if control:
                control.setText(label)
                control.setToolTip(action.text())
        window.theme_selector.setMinimumWidth(90)
        workbench.font_size.setMinimumWidth(78)
        workbench.bottom_tabs.currentChanged.connect(self.schedule)
        window.workspace_splitter.splitterMoved.connect(self.schedule)
        workbench.font_size.valueChanged.connect(self.schedule)
        window.installEventFilter(self)
        self.schedule()

    def _wrap_parameters(self):
        window = self.window
        layout = window.controls_panel.layout()
        content = QWidget()
        body = QVBoxLayout(content)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(layout.spacing())
        body.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        execution = None
        while layout.count():
            item = layout.takeAt(0)
            child_layout = item.layout()
            if child_layout and child_layout.indexOf(window.run_button) >= 0:
                child_layout.setParent(None)
                execution = child_layout
            elif item.widget():
                body.addWidget(item.widget(), 1 if item.widget() is window.stack else 0)
            elif child_layout:
                child_layout.setParent(None)
                body.addLayout(child_layout)
            else:
                body.addItem(item)
        scroll = QScrollArea()
        scroll.setObjectName('parametersScroll')
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setMinimumHeight(160)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        if execution:
            layout.addLayout(execution)
        window.parameters_scroll = scroll

    def schedule(self, *_):
        if not self.pending and not self._closed:
            self.pending = True
            QTimer.singleShot(0, self.fit)

    def fit(self):
        self.pending = False
        if self._closed:
            return
        window = self.window
        if self._transfer_row is not None:
            direction = (QBoxLayout.Direction.TopToBottom if window.controls_panel.width() < 500
                         else QBoxLayout.Direction.LeftToRight)
            if self._transfer_row.direction() != direction:
                self._transfer_row.setDirection(direction)
        dock = window._workbench.bottom_dock
        if dock.isFloating() or not dock.isVisible():
            return
        if window.height() < 850:
            console_active = window._workbench.bottom_tabs.currentWidget() is window.console_panel
            tabs = window._workbench.bottom_tabs
            required = (window.console_panel.minimumSizeHint().height() + tabs.tabBar().sizeHint().height() + 16
                        if console_active else 90)
            tabs.setMinimumHeight(required)
            target = max(150, required + 40)
            window.resizeDocks([dock], [target], Qt.Orientation.Vertical)

    def eventFilter(self, watched, event):
        if watched is self.window:
            if event.type() in (QEvent.Type.Show, QEvent.Type.Resize):
                self.schedule()
            elif event.type() == QEvent.Type.Close and self.window.thread is None:
                self._closed = True
        return super().eventFilter(watched, event)


def install_adaptive_workspace(window):
    if not hasattr(window, '_adaptive_workspace'):
        window._adaptive_workspace = AdaptiveWorkspace(window)
    return window._adaptive_workspace
