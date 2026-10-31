"""Capture the actual dynamic desktop using the portable demonstration data.

The default matrix covers 1100x750 and 1440x940 in both themes. Each case moves
the existing parameters and result widgets, records their geometry, then
returns to the initial arrangement. Settings are isolated in a temporary
directory. No user project, network download or processing suite is needed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import platform
from statistics import median
import tempfile
import time
import traceback
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLBACKEND", "Agg")

from PySide6 import __version__ as PYSIDE_VERSION
from PySide6.QtCore import QEventLoop, QPoint, QSettings, QTimer, Qt, qVersion
from PySide6.QtGui import QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import cartomize
from cartomize.desktop import CartomizeWindow


def wait_for(predicate, description, seconds=30):
    loop = QEventLoop()
    timer = QTimer()
    deadline = time.monotonic() + seconds
    timer.timeout.connect(lambda: loop.quit()
                          if predicate() or time.monotonic() >= deadline else None)
    timer.start(10)
    try:
        if not predicate():
            loop.exec()
    finally:
        timer.stop()
    if not predicate():
        raise RuntimeError(f"Timed out waiting for {description}")


def rectangle(rect):
    return [rect.x(), rect.y(), rect.width(), rect.height()]


def widget_geometry(widget):
    origin = widget.mapToGlobal(QPoint(0, 0))
    return {
        "geometry": rectangle(widget.geometry()),
        "global_client_geometry": [origin.x(), origin.y(), widget.width(), widget.height()],
        "visible": widget.isVisible(),
        "minimum_size": [widget.minimumWidth(), widget.minimumHeight()],
        "device_pixel_ratio": widget.devicePixelRatioF(),
    }


def dock_geometry(window, dock):
    return {
        **widget_geometry(dock),
        "object_name": dock.objectName(),
        "title": dock.windowTitle(),
        "floating": dock.isFloating(),
        "area": window.dockWidgetArea(dock).name,
        "frame_geometry": rectangle(dock.frameGeometry()),
    }


def make_inputs(output):
    helper_path = Path(__file__).resolve().parents[1] / "examples" / "create_imagery_demo.py"
    spec = importlib.util.spec_from_file_location("cartomize_capture_demo_inputs", helper_path)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    destination = Path(tempfile.mkdtemp(prefix="fixtures-", dir=output)) / "imagery"
    demo = helper.create_demo(destination)
    raster = next(Path(path) for path in demo["selected_band_paths"] if path.endswith("SR_B4.TIF"))
    vector = Path(demo["zones"]["one_scene"])
    return demo, raster, vector


def settle(app, document):
    app.processEvents()
    QTest.qWait(120)
    try:
        wait_for(lambda: document.canvas.last_render is not None
                 and not document.canvas._busy, "the raster rendering", seconds=15)
    except RuntimeError:
        # A dock/viewport transition may coalesce the initial zero-delay render
        # request before Xvfb exposes the final viewport. Trigger one explicit
        # refresh and wait for that generation instead of relying on timing.
        document.canvas.refresh()
        app.processEvents()
        QTest.qWait(120)
        wait_for(lambda: document.canvas.last_render is not None
                 and not document.canvas._busy, "the refreshed raster rendering", seconds=30)
    app.processEvents()


def assert_initial_layout(window):
    expected = (
        (window.project_explorer, Qt.DockWidgetArea.LeftDockWidgetArea),
        (window.tools_dock, Qt.DockWidgetArea.LeftDockWidgetArea),
        (window.parameters_dock, Qt.DockWidgetArea.RightDockWidgetArea),
        (window.bottom_dock, Qt.DockWidgetArea.BottomDockWidgetArea),
    )
    for dock, area in expected:
        assert dock.isVisible() and not dock.isFloating(), dock.objectName()
        assert window.dockWidgetArea(dock) == area, (dock.objectName(), window.dockWidgetArea(dock))
    assert window.project_explorer.mapTo(window, QPoint()).y() < window.tools_dock.mapTo(window, QPoint()).y()
    assert window.workspace.isVisible()


def assert_controls_reachable(window):
    for button in (window.run_button,):
        origin = button.mapTo(window.controls_panel, QPoint())
        assert button.isVisible(), button.text()
        assert window.controls_panel.rect().contains(origin), button.text()
        assert window.controls_panel.rect().contains(origin + QPoint(button.width() - 1, button.height() - 1)), button.text()


def inspect_dock_icons(window):
    """Inspect the real icon pixels, including after a theme change."""
    ink = window.palette().windowText().color()
    observed = {}
    groups = {}
    for dock in (window.project_explorer, window.tools_dock,
                 window.parameters_dock, window.bottom_dock):
        bar = dock.titleBarWidget()
        groups[dock.objectName()] = {name: getattr(bar, name + "_button")
                                    for name in ("position", "float", "focus", "close")}
    groups["result_tabs"] = {"detach": window.workspace.detach_button,
                             "focus": window.workspace.focus_button}
    for group, buttons in groups.items():
        observed[group] = {}
        for name, button in buttons.items():
            image = button.icon().pixmap(button.iconSize()).toImage()
            assert button.isEnabled() and not image.isNull()
            matches = 0
            for y in range(image.height()):
                for x in range(image.width()):
                    pixel = image.pixelColor(x, y)
                    if pixel.alpha() >= 64 and max(abs(pixel.red() - ink.red()),
                            abs(pixel.green() - ink.green()), abs(pixel.blue() - ink.blue())) <= 8:
                        matches += 1
            assert matches, (group, name, ink.name())
            observed[group][name] = {"theme_ink_pixels": matches,
                                      "button": widget_geometry(button),
                                      "accessible_name": button.accessibleName()}
            if group == "result_tabs":
                rendered = button.grab().toImage()
                pixels = [(x, y, rendered.pixelColor(x, y)) for y in range(rendered.height())
                          for x in range(rendered.width())]
                background = [median(getattr(color, channel)() for _, _, color in pixels)
                              for channel in ("red", "green", "blue")]
                delta = [value - base for value, base in zip(ink.getRgb()[:3], background)]
                magnitude = sum(value * value for value in delta)
                assert magnitude > 0
                points = []
                for x, y, pixel in pixels:
                    rgb = pixel.getRgb()[:3]
                    alpha = sum((value - base) * step for value, base, step in zip(rgb, background, delta)) / magnitude
                    residual = max(abs(value - (base + alpha * step))
                                   for value, base, step in zip(rgb, background, delta))
                    if alpha >= .35 and residual <= 12:
                        points.append((x, y))
                assert points, (group, name, "The actual button must visibly paint its icon.")
                left = min(point[0] for point in points)
                top = min(point[1] for point in points)
                bounds = [left, top, max(point[0] for point in points) - left + 1,
                          max(point[1] for point in points) - top + 1]
                assert min(bounds[2:]) >= 6 * button.devicePixelRatioF(), (
                    name, bounds, "Button padding must not shrink the result glyph.")
                observed[group][name].update(rendered_ink_pixels=len(points), rendered_ink_bounds=bounds)
    return {"status": "passed", "expected_ink": ink.name(),
            "window_background": window.palette().window().color().name(), "icons": observed}


def capture(output, case, stage, app, window, document, floating=None):
    settle(app, document)
    record = {
        "status": "passed", "window": widget_geometry(window),
        "font_size_px": window._workbench.font_size.value(),
        "effective_theme": window._effective_theme,
        "map_viewport": widget_geometry(document.canvas.viewport()),
        "docks": {key: dock_geometry(window, dock) for key, dock in (
            ("explorer", window.project_explorer), ("tools", window.tools_dock),
            ("parameters", window.parameters_dock), ("console", window.bottom_dock))},
        "tab_count": window.workspace.tabs.count(),
        "detached_document_count": len(window.workspace.detached_docks),
        "images": {},
    }
    widgets = {"main": window}
    if floating is not None:
        widgets["floating"] = floating
        record["floating_window"] = dock_geometry(window, floating)
    for name, widget in widgets.items():
        path = output / f"{case}-{stage}-{name}.png"
        pixmap = widget.grab()
        if not pixmap.save(str(path)):
            raise RuntimeError(f"Unable to save {path}")
        record["images"][name] = {"file": path.name, "pixels": [pixmap.width(), pixmap.height()]}
    return record


def exercise_pointer_drag(output, case, app, window, document, stages):
    """Use actual Qt mouse events and capture the manager's live guide widget."""
    manager = window.dock_manager
    dock = window.parameters_dock
    bar = dock.titleBarWidget()
    panel = window.controls_panel
    page = window.tool("vector")
    values = [page.source.edit.text(), page.operation.currentData(), page.distance.value()]
    released = False
    try:
        QTest.mousePress(bar, Qt.MouseButton.LeftButton, pos=QPoint(40, 12))
        center = window.centralWidget().mapToGlobal(window.centralWidget().rect().center())
        QTest.mouseMove(bar, bar.mapFromGlobal(center), delay=10)
        app.processEvents()
        guides = manager.guides
        assert dock.isFloating() and guides.isVisible()
        assert {"left", "right", "top", "bottom", "outer_bottom"} <= set(guides.targets)
        target = window.mapToGlobal(guides.targets["outer_bottom"][0].center())
        QTest.mouseMove(bar, bar.mapFromGlobal(target), delay=10)
        app.processEvents()
        assert guides.active_target is not None and not guides.preview.isEmpty()
        assert guides.active_target.area == Qt.DockWidgetArea.BottomDockWidgetArea
        record = capture(output, case, "drag-guides", app, window, document, dock)
        stages["drag-guides"] = record
        guide_pixmap = guides.grab()
        guide_path = output / f"{case}-drag-guides-overlay.png"
        assert guide_pixmap.save(str(guide_path))
        record["images"]["guides_widget"] = {
            "file": guide_path.name, "pixels": [guide_pixmap.width(), guide_pixmap.height()]}
        origin = window.mapToGlobal(QPoint())
        composite = window.grab()
        layers = []
        painter = QPainter(composite)
        try:
            for name, widget, pixmap in (("dragged_parameters", dock, dock.grab()),
                                         ("live_placement_guides", guides, guide_pixmap)):
                point = widget.mapToGlobal(QPoint()) - origin
                painter.drawPixmap(point, pixmap)
                layers.append({"widget": name, "offset_from_main_window": [point.x(), point.y()]})
        finally:
            painter.end()
        composite_path = output / f"{case}-drag-guides-composite.png"
        assert composite.save(str(composite_path))
        record["images"]["qt_widget_composite"] = {
            "file": composite_path.name, "pixels": [composite.width(), composite.height()],
            "method": "Actual Qt widget grabs composited at their observed global positions and clipped to the main window; useful for the offscreen platform.",
            "layers": layers,
        }
        record["guide_state"] = {
            "visible": guides.isVisible(), "geometry": widget_geometry(guides),
            "targets": {name: rectangle(rect) for name, (rect, _) in guides.targets.items()},
            "preview": rectangle(guides.preview),
            "active_area": guides.active_target.area.name,
            "pointer_global": [target.x(), target.y()],
        }
        QTest.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=bar.mapFromGlobal(target))
        released = True
        app.processEvents()
        assert not guides.isVisible() and not dock.isFloating()
        assert window.dockWidgetArea(dock) == Qt.DockWidgetArea.BottomDockWidgetArea
        assert window.controls_panel is panel
        assert [page.source.edit.text(), page.operation.currentData(), page.distance.value()] == values
        assert_controls_reachable(window)
        stages["drag-docked-bottom"] = capture(output, case, "drag-docked-bottom", app, window, document)
        window._workbench.reset_layout()
        settle(app, document)
        assert_initial_layout(window)
        stages["drag-layout-restored"] = capture(output, case, "drag-layout-restored", app, window, document)
        return {"status": "passed", "events": ["mousePress", "mouseMove", "mouseMove", "mouseRelease"],
                "guides_captured": True, "drop_area": "BottomDockWidgetArea",
                "same_parameter_panel": True, "parameter_values_preserved": True,
                "initial_layout_restored": True}
    finally:
        if not released:
            manager.cancel_drag()
            QTest.mouseRelease(bar, Qt.MouseButton.LeftButton)


def exercise_case(output, size, theme, app, window, document, vector, cases, targeted=False):
    name = f"{size[0]}x{size[1]}-{theme}"
    result = {"requested_size": list(size), "theme": theme, "stages": {}}
    cases[name] = result
    stages = result["stages"]
    manager = window.dock_manager
    manager.reset_focus()
    window._workbench.reset_layout()
    window.resize(*size)
    window.theme_selector.setCurrentIndex(window.theme_selector.findData(theme))
    window.show()
    window.workspace.tabs.setCurrentWidget(document)
    window._workbench.select_tool("vector")
    page = window.tool("vector")
    page.source.edit.setText(str(vector))
    page.operation.setCurrentIndex(page.operation.findData("buffer"))
    page.distance.setValue(200)
    settle(app, document)
    assert [window.width(), window.height()] == list(size), widget_geometry(window)
    assert_initial_layout(window)
    assert_controls_reachable(window)
    stages["initial"] = capture(output, name, "initial", app, window, document)
    result["icon_palette"] = inspect_dock_icons(window)
    if targeted:
        result["pointer_drag"] = exercise_pointer_drag(output, name, app, window, document, stages)
        result["status"] = "passed"
        return name, result

    parameters = window.parameters_dock
    original_panel = window.controls_panel
    parameter_state = [page.source.edit.text(), page.operation.currentData(), page.distance.value()]
    manager.set_floating(parameters, True)
    wait_for(parameters.isFloating, "floating parameters")
    parameters.show()
    stages["parameters-detached"] = capture(output, name, "parameters-detached", app, window, document, parameters)
    parameters.resize(540, 620)
    stages["parameters-resized"] = capture(output, name, "parameters-resized", app, window, document, parameters)
    assert parameters.width() >= 540 and parameters.height() >= 620
    assert_controls_reachable(window)
    manager.dock(parameters, Qt.DockWidgetArea.RightDockWidgetArea)
    wait_for(lambda: not parameters.isFloating(), "redocked parameters")
    assert window.controls_panel is original_panel
    assert [page.source.edit.text(), page.operation.currentData(), page.distance.value()] == parameter_state
    stages["parameters-redocked"] = capture(output, name, "parameters-redocked", app, window, document)

    canvas = document.canvas
    document_path = document.path
    display = {key: canvas.capture()[key] for key in ("bands", "palette", "resampling", "page")}
    original_tab_count = window.workspace.tabs.count()
    result_dock = window.workspace.detach_document(document)
    assert result_dock is not None
    wait_for(result_dock.isFloating, "the detached result")
    assert window.workspace.detached_docks.get(document) is result_dock
    assert window.workspace.tabs.indexOf(document) < 0
    stages["result-detached"] = capture(output, name, "result-detached", app, window, document, result_dock)
    result_dock.resize(840, 620)
    stages["result-resized"] = capture(output, name, "result-resized", app, window, document, result_dock)
    restored = window.workspace.reattach_document(document)
    assert restored is document
    assert window.workspace.tabs.widget(window.workspace.tabs.indexOf(document)) is document
    assert document not in window.workspace.detached_docks
    assert window.workspace.tabs.count() == original_tab_count
    assert document.canvas is canvas and document.path == document_path
    assert {key: canvas.capture()[key] for key in display} == display
    assert not document._closed and not canvas._closed
    stages["result-reattached"] = capture(output, name, "result-reattached", app, window, document)
    result["preservation"] = {"same_parameter_panel": True, "parameter_values": parameter_state,
                              "same_document": True, "same_canvas": True, "display_options": display}

    window._workbench.reset_layout()
    settle(app, document)
    assert_initial_layout(window)
    assert_controls_reachable(window)
    stages["layout-restored"] = capture(output, name, "layout-restored", app, window, document)
    result["pointer_drag"] = exercise_pointer_drag(output, name, app, window, document, stages)
    if size[0] == 1100:
        control = window._workbench.font_size
        previous = control.value()
        control.setValue(control.minimum())
        settle(app, document)
        assert_controls_reachable(window)
        assert document.canvas.viewport().width() >= 100 and document.canvas.viewport().height() >= 100
        stages["minimum-text"] = capture(output, name, "minimum-text", app, window, document)
        control.setValue(previous)
    result["status"] = "passed"
    return name, result


def parse_size(value):
    try:
        width, height = (int(part) for part in value.lower().split("x"))
        if width < 400 or height < 300:
            raise ValueError
        return width, height
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Use WIDTHxHEIGHT, for example 1100x750.") from exc


def parse_case(value):
    try:
        size, theme = value.rsplit(":", 1)
        if theme not in ("light", "dark"):
            raise ValueError
        return parse_size(size), theme
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Use WIDTHxHEIGHT:THEME, for example 1100x750:dark.") from exc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--size", action="append", type=parse_size,
                        help="Repeat to select sizes; default: 1100x750 and 1440x940.")
    parser.add_argument("--theme", action="append", choices=("light", "dark"))
    parser.add_argument("--case", action="append", type=parse_case,
                        help="Capture explicit size/theme pairs instead of the full matrix.")
    parser.add_argument("--targeted", action="store_true",
                        help="Capture initial appearance, themed icons and a real pointer drag only.")
    args = parser.parse_args()
    if args.case and (args.size or args.theme):
        parser.error("--case cannot be combined with --size or --theme.")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if (output / "capture.json").exists():
        parser.error("Use a new output directory to preserve the previous evidence.")
    demo, raster, vector = make_inputs(output)
    report = {
        "schema": "cartomize.dynamic-workspace.capture.v1", "status": "running",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "version": cartomize.__version__, "platform": platform.platform(),
        "source_commit": os.environ.get("GITHUB_SHA"),
        "python": platform.python_version(), "pyside": PYSIDE_VERSION, "qt": qVersion(),
        "data_origin": demo["data_origin"], "raster": str(raster), "vector": str(vector),
        "capture_method": "QWidget.grab of the actual application and floating dock widgets",
        "settings": "temporary isolated INI directory",
        "capture_scope": "appearance-and-pointer-drag" if args.targeted else "full-dynamic-workspace",
        "drag_guides": {"status": "pending", "method": "QTest mouse press, moves and release on the actual dock title bar"},
        "cases": {},
    }
    window = None
    previous_format = QSettings.defaultFormat()
    # The organization/application QSettings constructor uses NativeFormat even
    # after setDefaultFormat(IniFormat). Bind only this persistence boundary to
    # an explicit temporary INI file; all application widgets remain real.
    with tempfile.TemporaryDirectory(prefix="cartomize-dynamic-settings-") as settings, patch(
        "cartomize.desktop.QSettings",
        lambda *_args, **_kwargs: QSettings(str(Path(settings) / "preferences.ini"), QSettings.Format.IniFormat),
    ):
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        for scope in (QSettings.Scope.UserScope, QSettings.Scope.SystemScope):
            QSettings.setPath(QSettings.Format.IniFormat, scope, settings)
        app = QApplication.instance() or QApplication([])
        report["qt_platform"] = app.platformName()
        screen = app.primaryScreen()
        if screen is not None:
            report["screen"] = {"geometry": rectangle(screen.geometry()),
                                "available_geometry": rectangle(screen.availableGeometry()),
                                "logical_dpi": screen.logicalDotsPerInch(),
                                "device_pixel_ratio": screen.devicePixelRatio()}
        try:
            window = CartomizeWindow()
            assert Path(window._preferences.fileName()).resolve().is_relative_to(Path(settings).resolve())
            report["settings_file"] = window._preferences.fileName()
            report["settings_isolation_verified"] = True
            assert hasattr(window, "dock_manager") and hasattr(window, "parameters_dock"), "The dynamic docking API is required."
            assert callable(getattr(window.workspace, "detach_document", None)), "Result detachment API is required."
            assert callable(getattr(window.workspace, "reattach_document", None)), "Result reattachment API is required."
            window.resize(1440, 940)
            window.show()
            app.processEvents()
            window.project_explorer.set_directory(vector.parent)
            assert window.project_explorer.open_path(vector) is not None
            document = window.project_explorer.open_path(raster)
            assert document is not None
            document.palette.setCurrentIndex(document.palette.findData("terrain"))
            report["font_range_px"] = [window._workbench.font_size.minimum(), window._workbench.font_size.maximum()]
            report["tool_count"] = len(window.tool_pages)
            cases = args.case or [(size, theme)
                                 for size in args.size or [(1100, 750), (1440, 940)]
                                 for theme in args.theme or ["light", "dark"]]
            for size, theme in cases:
                exercise_case(output, size, theme, app, window, document, vector, report["cases"], args.targeted)
                (output / "capture.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
            report["drag_guides"]["status"] = "passed"
            report["status"] = "passed"
        except Exception as exc:
            report.update(status="failed", error=str(exc), traceback=traceback.format_exc())
            raise
        finally:
            if window is not None:
                window.close()
                app.processEvents()
            QSettings.setDefaultFormat(previous_format)
            (output / "capture.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"status": report["status"], "report": str(output / "capture.json"),
                      "cases": len(report["cases"]),
                      "png_files": sum(len(stage["images"]) for case in report["cases"].values()
                                       for stage in case["stages"].values()),
                      "qt_platform": report["qt_platform"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
