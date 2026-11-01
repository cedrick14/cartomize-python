"""Movable Qt panels, placement guides and reversible workspace focus."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QDockWidget, QHBoxLayout, QLabel, QMainWindow, QMenu,
    QSizePolicy, QStyle, QToolButton, QWidget,
)
from shiboken6 import isValid


LAYOUT_VERSION = 3
AREAS = (
    ('left', 'À gauche', Qt.DockWidgetArea.LeftDockWidgetArea),
    ('right', 'À droite', Qt.DockWidgetArea.RightDockWidgetArea),
    ('top', 'En haut', Qt.DockWidgetArea.TopDockWidgetArea),
    ('bottom', 'En bas', Qt.DockWidgetArea.BottomDockWidgetArea),
)


def panel_icon(symbol, palette, ratio=1):
    """Small, theme-aware controls shared by docks and central result tabs."""
    color = palette.buttonText().color()
    pixmap = QPixmap(round(18 * ratio), round(18 * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(color, 1.5))
    if symbol == QStyle.StandardPixmap.SP_TitleBarCloseButton:
        painter.drawLine(5, 5, 13, 13)
        painter.drawLine(13, 5, 5, 13)
    elif symbol == QStyle.StandardPixmap.SP_TitleBarMaxButton:
        painter.drawRect(4, 4, 10, 10)
        painter.drawLine(4, 6, 14, 6)
    elif symbol == QStyle.StandardPixmap.SP_TitleBarNormalButton:
        painter.drawRect(3, 7, 8, 8)
        painter.fillRect(7, 3, 8, 8, palette.window())
        painter.drawRect(7, 3, 8, 8)
    elif symbol == QStyle.StandardPixmap.SP_ArrowBack:
        painter.drawLine(13, 9, 4, 9)
        painter.drawLine(4, 9, 9, 4)
        painter.drawLine(4, 9, 9, 14)
    else:
        painter.setBrush(color)
        for x in (4, 9, 14):
            painter.drawEllipse(QPoint(x, 9), 1, 1)
    painter.end()
    return QIcon(pixmap)


@dataclass
class DockTarget:
    area: Qt.DockWidgetArea
    relative: QDockWidget | None = None
    tabify: bool = False
    reattach: bool = False


class DockGuides(QWidget):
    """A transparent, non-interactive overlay above the panel being dragged."""

    def __init__(self, manager):
        flags = (Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint |
                 Qt.WindowType.WindowTransparentForInput |
                 Qt.WindowType.WindowDoesNotAcceptFocus)
        super().__init__(manager.window, flags)
        self.manager = manager
        self.setObjectName('dockPlacementGuides')
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setStyleSheet('QWidget#dockPlacementGuides { background: transparent; }')
        self.targets = {}
        self.active_target = None
        self.preview = QRect()
        self.anchor = QRect()

    def update_target(self, global_position, dock):
        window = self.manager.window
        position = window.mapFromGlobal(global_position)
        if not window.rect().contains(position):
            self.active_target = None
            self.hide()
            return None
        relative = self.manager.panel_at(global_position, excluding=dock)
        anchor_widget = relative or window.centralWidget()
        self.anchor = QRect(anchor_widget.mapTo(window, QPoint()), anchor_widget.size())
        self.setGeometry(QRect(window.mapToGlobal(QPoint()), window.size()))
        self.targets = {}
        center = self.anchor.center()
        offsets = {'left': QPoint(-36, 0), 'right': QPoint(36, 0),
                   'top': QPoint(0, -36), 'bottom': QPoint(0, 36)}
        for name, _, area in AREAS:
            point = center + offsets[name]
            self.targets[name] = (QRect(point - QPoint(15, 15), QSize(30, 30)),
                                  DockTarget(area, relative))
        can_return = self.manager.return_callback(dock) is not None
        if relative is not None or can_return:
            self.targets['center'] = (
                QRect(center - QPoint(15, 15), QSize(30, 30)),
                DockTarget(Qt.DockWidgetArea.NoDockWidgetArea, relative,
                           tabify=relative is not None, reattach=relative is None),
            )
        # Outer targets position a panel against the complete workspace.
        bounds = window.centralWidget().geometry().united(self.anchor)
        outer = {'left': QPoint(20, bounds.center().y()),
                 'right': QPoint(window.width() - 20, bounds.center().y()),
                 'top': QPoint(window.width() // 2, window.menuBar().height() + 20),
                 'bottom': QPoint(window.width() // 2,
                                  window.height() - window.statusBar().height() - 20)}
        for name, _, area in AREAS:
            self.targets['outer_' + name] = (
                QRect(outer[name] - QPoint(15, 15), QSize(30, 30)), DockTarget(area),
            )
        self.active_target = next((target for rect, target in self.targets.values()
                                   if rect.contains(position)), None)
        if self.active_target is None and self.anchor.contains(position):
            distances = [('left', position.x() - self.anchor.left()),
                         ('right', self.anchor.right() - position.x()),
                         ('top', position.y() - self.anchor.top()),
                         ('bottom', self.anchor.bottom() - position.y())]
            name, distance = min(distances, key=lambda item: item[1])
            if distance <= 26:
                self.active_target = self.targets[name][1]
        self.preview = self.preview_for(self.active_target)
        self.show()
        self.raise_()
        self.update()
        return self.active_target

    def preview_for(self, target):
        if target is None:
            return QRect()
        rect = QRect(self.anchor)
        if target.relative is None and not target.reattach:
            window = self.manager.window
            rect = window.rect().adjusted(4, window.menuBar().height() + 4,
                                          -4, -window.statusBar().height() - 4)
        if target.tabify or target.reattach:
            return rect.adjusted(3, 3, -3, -3)
        if target.area == Qt.DockWidgetArea.LeftDockWidgetArea:
            rect.setWidth(rect.width() // 2)
        elif target.area == Qt.DockWidgetArea.RightDockWidgetArea:
            rect.setLeft(rect.center().x())
        elif target.area == Qt.DockWidgetArea.TopDockWidgetArea:
            rect.setHeight(rect.height() // 2)
        elif target.area == Qt.DockWidgetArea.BottomDockWidgetArea:
            rect.setTop(rect.center().y())
        return rect.adjusted(3, 3, -3, -3)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = self.manager.window.palette()
        accent = palette.highlight().color()
        if not self.preview.isEmpty():
            fill = QColor(accent)
            fill.setAlpha(55)
            painter.setPen(QPen(accent, 2))
            painter.setBrush(fill)
            painter.drawRoundedRect(self.preview, 4, 4)
        for name, (rect, target) in self.targets.items():
            selected = target is self.active_target
            painter.setPen(QPen(accent if selected else palette.mid().color(), 2))
            painter.setBrush(palette.highlight() if selected else palette.button())
            painter.drawRoundedRect(rect, 4, 4)
            inner = rect.adjusted(7, 7, -7, -7)
            ink = palette.highlightedText().color() if selected else palette.windowText().color()
            painter.setPen(QPen(ink, 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(inner)
            part = QRect(inner)
            direction = name.removeprefix('outer_')
            if direction == 'left':
                part.setWidth(6)
            elif direction == 'right':
                part.setLeft(part.right() - 5)
            elif direction == 'top':
                part.setHeight(6)
            elif direction == 'bottom':
                part.setTop(part.bottom() - 5)
            else:
                part = inner.adjusted(3, 3, -3, -3)
            painter.fillRect(part, ink)


class DockTitleBar(QWidget):
    def __init__(self, dock, manager, return_callback=None):
        super().__init__(dock)
        self.dock = dock
        self.manager = manager
        self.setObjectName('dockPanelTitle')
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 3, 2)
        layout.setSpacing(2)
        self.label = QLabel(dock.windowTitle())
        self.label.setObjectName('dockPanelLabel')
        self.label.setMinimumWidth(24)
        self.label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.label, 1)
        self.return_button = None
        if return_callback is not None:
            self.return_button = self.button('Réintégrer dans les vues',
                QStyle.StandardPixmap.SP_ArrowBack, return_callback, layout)
        self.position_button = self.button('Positionner', QStyle.StandardPixmap.SP_TitleBarShadeButton,
                                           self.position_menu, layout)
        self.float_button = self.button('Détacher', QStyle.StandardPixmap.SP_TitleBarNormalButton,
            lambda: manager.set_floating(dock, not dock.isFloating()), layout)
        self.focus_button = self.button('Agrandir', QStyle.StandardPixmap.SP_TitleBarMaxButton,
                                        lambda: manager.focus(dock), layout)
        self.close_button = self.button('Fermer', QStyle.StandardPixmap.SP_TitleBarCloseButton,
                                        dock.close, layout)
        dock.windowTitleChanged.connect(self.sync)
        dock.topLevelChanged.connect(self.sync)
        self.sync()

    def button(self, title, icon, callback, layout):
        button = QToolButton(self)
        button.setObjectName('dockPanelAction')
        button.setFixedSize(24, 24)
        button.setIconSize(QSize(14, 14))
        button._dock_symbol = icon
        self.set_button_icon(button)
        button.setToolTip(title)
        button.setAccessibleName(title)
        button.setAutoRaise(True)
        button.setCursor(Qt.CursorShape.ArrowCursor)
        button.clicked.connect(lambda checked=False: callback())
        layout.addWidget(button)
        return button

    def set_button_icon(self, button):
        color = self.manager.window.palette().windowText().color()
        symbol = button._dock_symbol
        key = (color.name(), symbol, self.devicePixelRatioF())
        if getattr(button, '_dock_icon_key', None) == key:
            return
        button.setIcon(panel_icon(symbol, self.manager.window.palette(), self.devicePixelRatioF()))
        button._dock_icon_key = key

    def sync(self, *_):
        title = self.dock.windowTitle()
        self.label.setText(self.label.fontMetrics().elidedText(
            title, Qt.TextElideMode.ElideRight, max(24, self.label.width())))
        self.label.setToolTip(title)
        self.label.setAccessibleName(title)
        floating = self.dock.isFloating()
        label = 'Ancrer' if floating else 'Détacher'
        self.float_button.setToolTip(label)
        self.float_button.setAccessibleName(label)
        focused = self.manager.focused is self.dock or self.dock.isMaximized()
        label = 'Rétablir' if focused else 'Agrandir'
        self.focus_button.setToolTip(label)
        self.focus_button.setAccessibleName(label)
        self.focus_button._dock_symbol = (QStyle.StandardPixmap.SP_TitleBarNormalButton if focused
                                          else QStyle.StandardPixmap.SP_TitleBarMaxButton)
        for button in (self.position_button, self.float_button, self.focus_button,
                       self.close_button, self.return_button):
            if button is not None:
                self.set_button_icon(button)

    def position_menu(self):
        menu = QMenu(self)
        for _, label, area in AREAS:
            menu.addAction(label, lambda checked=False, a=area: self.manager.dock(self.dock, a))
        others = [dock for dock in self.manager.docks if dock is not self.dock]
        if others:
            group = menu.addMenu('Grouper avec')
            for dock in others:
                group.addAction(dock.windowTitle(), lambda checked=False, other=dock:
                    self.manager.dock(self.dock, self.manager.window.dockWidgetArea(other),
                                      relative=other, tabify=True))
        menu.addSeparator()
        menu.addAction('Détacher' if not self.dock.isFloating() else 'Ancrer',
                       lambda: self.manager.set_floating(self.dock, not self.dock.isFloating()))
        callback = self.manager.return_callback(self.dock)
        if callback is not None:
            menu.addAction('Réintégrer dans les vues', callback)
        menu.exec(self.position_button.mapToGlobal(QPoint(0, self.position_button.height())))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.sync()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.manager.begin_drag(self.dock, event.globalPosition().toPoint())
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        event.accept()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.manager.cancel_drag()
            self.manager.set_floating(self.dock, not self.dock.isFloating())
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)


class DockController(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self._panels = {}
        self._returns = {}
        self._areas = {}
        self._press = None
        self._dragging = False
        self._focus_state = None
        self.focused = None
        self.user_layout = False
        self._closed = False
        self.guides = DockGuides(self)
        window.setDockOptions(QMainWindow.DockOption.AnimatedDocks |
                              QMainWindow.DockOption.AllowNestedDocks |
                              QMainWindow.DockOption.AllowTabbedDocks |
                              QMainWindow.DockOption.GroupedDragging)
        QApplication.instance().installEventFilter(self)

    @property
    def docks(self):
        return tuple(dock for dock in self._panels.values() if isValid(dock))

    def register(self, dock, return_callback=None):
        name = dock.objectName()
        if not name:
            raise ValueError('Un panneau doit avoir un identifiant stable.')
        if name in self._panels and self._panels[name] is not dock:
            raise ValueError('Identifiant de panneau déjà utilisé : ' + name)
        if self._panels.get(name) is dock:
            return dock
        self._panels[name] = dock
        self._returns[name] = return_callback
        dock.setAttribute(Qt.WidgetAttribute.WA_WindowPropagation)
        area = self.window.dockWidgetArea(dock)
        self._areas[name] = area if area != Qt.DockWidgetArea.NoDockWidgetArea else Qt.DockWidgetArea.RightDockWidgetArea
        dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable |
                         QDockWidget.DockWidgetFeature.DockWidgetMovable |
                         QDockWidget.DockWidgetFeature.DockWidgetFloatable)
        dock.setTitleBarWidget(DockTitleBar(dock, self, return_callback))
        dock.destroyed.connect(lambda _=None, key=name, panel=dock: self._forget(key, panel))
        return dock

    def _forget(self, name, expected=None):
        if expected is not None and self._panels.get(name) is not expected:
            return
        self._panels.pop(name, None)
        self._returns.pop(name, None)
        self._areas.pop(name, None)

    def unregister(self, dock):
        if self._press and self._press['dock'] is dock:
            self.cancel_drag()
        if self.focused is dock:
            self.reset_focus()
        self._forget(dock.objectName(), dock)

    def return_callback(self, dock):
        return self._returns.get(dock.objectName())

    def show(self, dock):
        if self._focus_state is not None and self.focused is not dock:
            self.reset_focus()
        dock.show()
        dock.raise_()
        if dock.isFloating():
            self.ensure_visible(dock)

    def ensure_visible(self, dock):
        if not dock.isFloating() or dock.isMaximized():
            return
        rect = dock.geometry()
        screen = QApplication.screenAt(rect.center()) or self.window.screen()
        if screen is None:
            return
        bounds = screen.availableGeometry().adjusted(4, 4, -4, -4)
        rect.setSize(QSize(min(max(280, rect.width()), bounds.width()),
                           min(max(180, rect.height()), bounds.height())))
        rect.moveLeft(max(bounds.left(), min(rect.left(), bounds.right() - rect.width() + 1)))
        rect.moveTop(max(bounds.top(), min(rect.top(), bounds.bottom() - rect.height() + 1)))
        dock.setGeometry(rect)

    def set_floating(self, dock, floating):
        self.reset_focus()
        if floating:
            area = self.window.dockWidgetArea(dock)
            if area != Qt.DockWidgetArea.NoDockWidgetArea:
                self._areas[dock.objectName()] = area
            dock.setFloating(True)
            dock.showNormal()
            self.ensure_visible(dock)
        else:
            dock.showNormal()
            dock.setFloating(False)
            if self.window.dockWidgetArea(dock) == Qt.DockWidgetArea.NoDockWidgetArea:
                self.window.addDockWidget(self._areas.get(dock.objectName(),
                                          Qt.DockWidgetArea.RightDockWidgetArea), dock)
        dock.show()
        dock.raise_()
        self.user_layout = True
        self._sync_titles()

    def dock(self, dock, area, relative=None, tabify=False):
        self.reset_focus()
        if area == Qt.DockWidgetArea.NoDockWidgetArea:
            area = self._areas.get(dock.objectName(), Qt.DockWidgetArea.RightDockWidgetArea)
        dock.showNormal()
        dock.setFloating(False)
        if relative is not None and isValid(relative) and relative is not dock:
            if relative.isFloating():
                self.set_floating(relative, False)
            relative.show()
            if tabify:
                self.window.tabifyDockWidget(relative, dock)
            else:
                orientation = (Qt.Orientation.Horizontal if area in (
                    Qt.DockWidgetArea.LeftDockWidgetArea, Qt.DockWidgetArea.RightDockWidgetArea)
                    else Qt.Orientation.Vertical)
                self.window.splitDockWidget(relative, dock, orientation)
                if area in (Qt.DockWidgetArea.LeftDockWidgetArea, Qt.DockWidgetArea.TopDockWidgetArea):
                    self.window.splitDockWidget(dock, relative, orientation)
        else:
            self.window.addDockWidget(area, dock)
        actual = self.window.dockWidgetArea(dock)
        self._areas[dock.objectName()] = actual
        dock.show()
        dock.raise_()
        self.user_layout = True
        self._sync_titles()

    def focus(self, dock=None):
        if dock is not None and dock.isFloating():
            dock.showNormal() if dock.isMaximized() else dock.showMaximized()
            self._sync_titles()
            return
        if self._focus_state is not None:
            same = self.focused is dock
            self.reset_focus()
            if same:
                return
        central = self.window.centralWidget()
        self._focus_state = (central.isVisible(), {d.objectName(): d.isVisible() for d in self.docks})
        self.focused = dock
        central.setVisible(dock is None)
        for panel in self.docks:
            panel.setVisible(panel is dock)
        self._sync_titles()

    def reset_focus(self, hidden=None):
        if self._focus_state is None:
            return
        central_visible, visible = self._focus_state
        self._focus_state = None
        self.focused = None
        self.window.centralWidget().setVisible(central_visible)
        for panel in self.docks:
            panel.setVisible(panel is not hidden and visible.get(panel.objectName(), False))
        self._sync_titles()

    def _sync_titles(self):
        for dock in self.docks:
            bar = dock.titleBarWidget()
            if isinstance(bar, DockTitleBar):
                bar.sync()

    def panel_at(self, position, excluding=None):
        candidates = [dock for dock in self.docks if dock is not excluding and
                      not dock.isFloating() and dock.isVisible() and
                      not dock.visibleRegion().isEmpty() and
                      QRect(dock.mapToGlobal(QPoint()), dock.size()).contains(position)]
        return min(candidates, key=lambda d: d.width() * d.height(), default=None)

    def begin_drag(self, dock, position):
        self.reset_focus()
        self.cancel_drag()
        self._press = {'dock': dock, 'position': QPoint(position),
                       'offset': position - dock.mapToGlobal(QPoint()),
                       'state': self.window.saveState(LAYOUT_VERSION),
                       'geometry': dock.normalGeometry() if dock.isMaximized() else dock.geometry(),
                       'maximized': dock.isMaximized(), 'width': dock.width(),
                       'floating': dock.isFloating(),
                       'user_layout': self.user_layout}

    def move_drag(self, position):
        if self._press is None:
            return
        dock = self._press['dock']
        if not isValid(dock):
            self._finish_drag()
            return
        if not self._dragging:
            if (position - self._press['position']).manhattanLength() < QApplication.startDragDistance():
                return
            self._dragging = True
            self.set_floating(dock, True)
            if self._press['maximized']:
                fraction = self._press['offset'].x() / max(1, self._press['width'])
                self._press['offset'].setX(max(12, min(round(fraction * dock.width()), dock.width() - 24)))
            dock.titleBarWidget().grabMouse()
        dock.move(position - self._press['offset'])
        self.guides.update_target(position, dock)

    def end_drag(self, position):
        if self._press is None:
            return
        dock = self._press['dock']
        target = self.guides.update_target(position, dock) if self._dragging else None
        moved = self._dragging
        self._finish_drag()
        if target is not None:
            if target.reattach:
                callback = self.return_callback(dock)
                if callback:
                    callback()
            else:
                self.dock(dock, target.area, relative=target.relative, tabify=target.tabify)
        elif moved:
            self.ensure_visible(dock)

    def _finish_drag(self):
        if self._press is not None and isValid(self._press['dock']):
            bar = self._press['dock'].titleBarWidget()
            if bar is not None and QWidget.mouseGrabber() is bar:
                bar.releaseMouse()
        self._press = None
        self._dragging = False
        self.guides.active_target = None
        self.guides.hide()

    def cancel_drag(self):
        previous = self._press
        moved = self._dragging
        self._finish_drag()
        if previous is not None and moved and isValid(previous['dock']):
            self.window.restoreState(previous['state'], LAYOUT_VERSION)
            self.user_layout = previous['user_layout']
            if previous['floating']:
                dock = previous['dock']
                dock.showNormal()
                dock.setGeometry(previous['geometry'])
                if previous['maximized']:
                    dock.showMaximized()

    def shutdown(self):
        if self._closed:
            return
        self.cancel_drag()
        self.reset_focus()
        self._closed = True
        QApplication.instance().removeEventFilter(self)

    def eventFilter(self, watched, event):
        if self._closed:
            return False
        kind = event.type()
        if kind in (QEvent.Type.Close, QEvent.Type.Hide) and watched is self.focused:
            self.reset_focus(hidden=watched)
        if self._press is not None:
            if kind == QEvent.Type.MouseMove:
                self.move_drag(event.globalPosition().toPoint())
                return True
            if kind == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
                self.end_drag(event.globalPosition().toPoint())
                return True
            if kind == QEvent.Type.ApplicationDeactivate:
                self.cancel_drag()
        if kind == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            if self._press is not None:
                self.cancel_drag()
                return True
            if (self._focus_state is not None and isinstance(watched, QWidget) and
                    (watched is self.window or self.window.isAncestorOf(watched))):
                self.reset_focus()
                return True
        if kind == QEvent.Type.WindowStateChange and watched in self.docks:
            self._sync_titles()
        if (kind == QEvent.Type.Resize and watched in self.docks and not self._dragging and
                QApplication.mouseButtons() & Qt.MouseButton.LeftButton):
            self.user_layout = True
        return False
