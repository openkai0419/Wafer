from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from pathlib import Path

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from wafer.core.common.paths import db_name_from_path, normalize_path, safe_is_file
from wafer.core.db.path_values import PathValue, fetch_path_values, fetch_sources
from wafer.core.lang.manager import t
from wafer.builtins.commands.panel import open_panel
from wafer.core.logs import AppLogger
from wafer.qt.commands.binding.instance_registry import InstanceRegistry
from wafer.qt.common.dispatcher import CancelSlot, Dispatcher
from wafer.qt.common.dpi import dpix
from wafer.qt.common.icon_engine import themed_icon
from wafer.qt.common.rate_limit import qt_debounce
from wafer.qt.common.thread import utility_pool
from wafer.qt.theme import ThemeManager

from . import projection
from .file_list import FileList
from .map_host import MapHost
from .map_toolbar import MapToolbar
from .map_view import MapView
from .session import MapError, MapResult, SpaceLayout
from .space import Preset, load_preset, space_groups
from .view_settings import GroupingStore, ViewSettings

COMPUTE_PRIORITY = 7
WARM_UP_PRIORITY = 1
RECOMPUTE_DELAY_MS = 300
MIN_DRILL_FILES = 3
ELLIPSIS = "\N{HORIZONTAL ELLIPSIS}"
SEPARATOR = "\N{MIDDLE DOT}"
CRUMB_ARROW = "\N{SINGLE RIGHT-POINTING ANGLE QUOTATION MARK}"
SPACE_PANEL_NAME = "Mapping Space"
STAGE_NAMES = {"encode": "Encoding", "layout": "Laying out (the first run takes longer)", "cluster": "Grouping"}


def local_file_paths(mime: QtCore.QMimeData | None) -> list[str]:
    if mime is None or not mime.hasUrls():
        return []
    return [normalize_path(url.toLocalFile()) for url in mime.urls() if url.isLocalFile() and safe_is_file(Path(url.toLocalFile()))]


def group_color(group: int) -> QtGui.QColor:
    return QtGui.QColor.fromHsvF((group * 0.618034) % 1.0, 0.55, 0.92)


def result_colors(result: MapResult, palette) -> list[QtGui.QColor]:
    neutral = QtGui.QColor(palette.text_secondary)
    if result.labels is None:
        return [neutral] * len(result.paths)
    table = {group: group_color(group) for group in np.unique(result.labels).tolist() if group >= 0}
    noise = QtGui.QColor(palette.text_muted)
    return [table.get(label, noise) for label in result.labels.tolist()]


def same_layout(shown: MapResult | None, result: MapResult) -> bool:
    return shown is not None and shown.paths == result.paths and np.array_equal(shown.positions, result.positions, equal_nan=True) and np.array_equal(shown.outliers, result.outliers)


def prepare_layout_engine(dispatcher: Dispatcher) -> None:
    dispatcher.post(lambda: projection.warm_up(), priority=WARM_UP_PRIORITY)


def cancel_work(*slots: CancelSlot) -> None:
    for slot in slots:
        slot.cancel()


@dataclass
class MapLevel:
    paths: list[str]
    result: MapResult | None = None
    layout: SpaceLayout | None = None


class MappingWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        InstanceRegistry.instance().register("MappingWidget", self)
        self.palette_colors = ThemeManager.instance().palette
        self.dispatcher = Dispatcher(pool=utility_pool, parent=self)
        prepare_layout_engine(self.dispatcher)
        self.fetch_cancel = CancelSlot()
        self.compute_cancel = CancelSlot()
        self.db_path = None
        self.db_name = ""
        self.preset: Preset | None = None
        self.paths: list[str] = []
        self.values: dict[str, dict[str, PathValue]] = {}
        self.settings = ViewSettings.instance()
        self.levels: list[MapLevel] = []
        self.shown: MapResult | None = None
        self.grouping = False
        self.host = MapHost(self)
        self.build_ui()
        self.host.map_views = [self.map_view]
        self.host.list_views = [self.file_list]
        self.setAcceptDrops(True)
        self.settings.changed.connect(self.on_view_settings)
        GroupingStore.instance().changed.connect(self.on_grouping_changed)
        self.destroyed.connect(partial(cancel_work, self.fetch_cancel, self.compute_cancel))

    @classmethod
    def instance(cls) -> MappingWidget | None:
        return InstanceRegistry.instance().get_one("MappingWidget")

    def build_ui(self):
        palette = self.palette_colors
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.stack = QtWidgets.QStackedWidget()
        root.addWidget(self.stack)
        empty = QtWidgets.QLabel(t("Select files and run Mapping\nor drop files here"))
        empty.setAlignment(Qt.AlignCenter)
        empty.setStyleSheet(f"color: {palette.text_muted}; font-size: {dpix(13)}px;")
        self.stack.addWidget(empty)
        self.page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(self.page)
        layout.setContentsMargins(dpix(6), dpix(6), dpix(6), dpix(6))
        toolbar = QtWidgets.QHBoxLayout()
        self.edit_space_button = QtWidgets.QToolButton()
        self.edit_space_button.setText(t("Edit in Mapping Space"))
        self.edit_space_button.setToolTip(t("Change the keys and retrain in the Mapping Space panel."))
        self.edit_space_button.clicked.connect(self.open_space_panel)
        toolbar.addWidget(self.edit_space_button)
        toolbar.addStretch(1)
        self.toolbar = MapToolbar()
        toolbar.addWidget(self.toolbar)
        refresh = QtWidgets.QToolButton()
        refresh.setIcon(themed_icon("refresh"))
        refresh.setToolTip(t("Recompute"))
        refresh.clicked.connect(self.refresh)
        toolbar.addWidget(refresh)
        layout.addLayout(toolbar)
        status = QtWidgets.QHBoxLayout()
        self.crumbs = QtWidgets.QHBoxLayout()
        status.addLayout(self.crumbs)
        status.addStretch(1)
        self.message = QtWidgets.QLabel()
        self.message.setStyleSheet(f"color: {palette.text_secondary};")
        status.addWidget(self.message)
        self.cancel_button = QtWidgets.QToolButton()
        self.cancel_button.setIcon(themed_icon("cross"))
        self.cancel_button.setToolTip(t("Cancel"))
        self.cancel_button.setAutoRaise(True)
        self.cancel_button.hide()
        self.cancel_button.clicked.connect(self.cancel_compute)
        status.addWidget(self.cancel_button)
        layout.addLayout(status)
        self.splitter = QtWidgets.QSplitter(Qt.Horizontal)
        self.file_list = FileList(self)
        self.map_view = MapView(self)
        self.splitter.addWidget(self.file_list)
        self.splitter.addWidget(self.map_view)
        self.splitter.setStretchFactor(1, 3)
        layout.addWidget(self.splitter, stretch=1)
        self.stack.addWidget(self.page)
        self.map_view.selection_changed.connect(self.on_map_selection)
        self.file_list.selection_changed.connect(self.on_list_selection)

    def on_grouping_changed(self, db_name: str) -> None:
        if db_name == self.db_name:
            self.on_view_settings(True)

    def on_view_settings(self, relayout: bool) -> None:
        if relayout:
            if self.shown is not None:
                self.grouping = True
                self.show_counts(self.shown)
            self.schedule_recompute()
        else:
            self.settings.apply(self.map_view, self.host)

    def message_text(self) -> str:
        return self.message.text()

    def current_result(self) -> MapResult | None:
        return self.levels[-1].result if self.levels else None

    def set_files(self, paths: list[str], db_path) -> None:
        self.db_path = db_path
        self.db_name = db_name_from_path(db_path) if db_path else ""
        self.paths = list(dict.fromkeys(paths))
        self.levels = []
        self.stack.setCurrentWidget(self.page)
        self.fetch()

    def add_files(self, paths: list[str], db_path) -> None:
        if not self.paths or db_path != self.db_path:
            self.set_files(paths, db_path)
            return
        known = set(self.paths)
        self.set_files(self.paths + [p for p in paths if p not in known], db_path)

    def remove_files(self, paths: list[str]) -> None:
        removed = set(paths) & set(self.paths)
        if not removed:
            return
        self.paths = [p for p in self.paths if p not in removed]
        if not self.paths:
            self.reset()
            return
        changed = []
        for level in self.levels:
            kept = [p for p in level.paths if p not in removed]
            if len(kept) != len(level.paths):
                level.paths, level.result, level.layout = kept, None, None
                changed.append(level)
        self.update_crumbs()
        if self.levels and self.levels[-1] in changed:
            self.recompute()

    def reset(self) -> None:
        cancel_work(self.fetch_cancel, self.compute_cancel)
        self.paths, self.values, self.levels, self.shown = [], {}, [], None
        self.host.clear()
        self.map_view.clear_map()
        self.file_list.clear_rows()
        self.update_crumbs()
        self.cancel_button.hide()
        self.set_message("")
        self.stack.setCurrentIndex(0)

    def fetch(self, keep_levels: bool = False):
        cancel = self.fetch_cancel.renew()
        self.compute_cancel.cancel()
        paths, db_path, db_name = list(self.paths), self.db_path, self.db_name
        self.set_message(t("Loading values") + ELLIPSIS)

        def task():
            try:
                values = fetch_path_values(db_path, paths)
                sources = fetch_sources(db_path, paths)
                preset = load_preset(db_name) if db_name else None
                GroupingStore.instance().get(db_name)
            except Exception as e:
                AppLogger.error("[Mapping] Loading values failed", exc=e)
                self.dispatcher.invoke(lambda: cancel.is_cancelled() or self.finish(t("Mapping failed. See the log for details.")))
                return
            self.dispatcher.invoke(lambda: cancel.is_cancelled() or self.on_values(values, sources, preset, keep_levels))

        self.dispatcher.post(task, priority=COMPUTE_PRIORITY, cancel=cancel)

    def on_values(self, values, sources, preset: Preset | None = None, keep_levels: bool = False):
        self.values, self.host.sources = values, sources
        self.preset = preset if preset is not None and preset.features and preset.version > 0 else None
        if keep_levels and self.levels:
            for level in self.levels:
                level.result, level.layout = None, None
        else:
            self.levels = [MapLevel(list(self.paths))]
        self.update_crumbs()
        self.recompute()

    def refresh(self) -> None:
        if self.levels:
            self.fetch(keep_levels=True)

    def open_space_panel(self) -> None:
        open_panel(name=SPACE_PANEL_NAME, toggle=False)

    @qt_debounce(RECOMPUTE_DELAY_MS)
    def schedule_recompute(self):
        self.recompute()

    def recompute(self) -> None:
        if not self.levels:
            return
        if self.preset is None:
            self.compute_cancel.cancel()
            self.finish(t("This database has no Mapping Space yet. Train one in Mapping Space."))
            return
        level, params = self.levels[-1], self.settings.params
        grouping, share = GroupingStore.instance().get(self.db_name), params.subgroup_size
        if level.layout is None or level.layout.preset is not self.preset:
            level.layout = SpaceLayout(level.paths, self.values, self.preset, load_groups=partial(space_groups, self.db_path, self.preset))
        layout = level.layout
        cancel = self.compute_cancel.renew()
        self.cancel_button.show()

        def task():
            try:
                if not layout.is_grouped():
                    plain = layout.run(params, grouping=grouping, share=share, grouped=False, cancelled=cancel.is_cancelled)
                    if plain is None:
                        return
                    self.dispatcher.invoke(lambda: cancel.is_cancelled() or self._apply_result(level, plain, final=False))
                result = layout.run(params, grouping=grouping, share=share, cancelled=cancel.is_cancelled)
                if result is None:
                    return
            except MapError as e:
                self.dispatcher.invoke(lambda m=str(e): cancel.is_cancelled() or self.finish(t(m)))
                return
            except Exception as e:
                AppLogger.error("[Mapping] Map computation failed", exc=e)
                self.dispatcher.invoke(lambda: cancel.is_cancelled() or self.finish(t("Mapping failed. See the log for details.")))
                return
            self.dispatcher.invoke(lambda: cancel.is_cancelled() or self._apply_result(level, result, final=True))

        self.dispatcher.post(task, priority=COMPUTE_PRIORITY, cancel=cancel)

    def cancel_compute(self):
        self.compute_cancel.cancel()
        self.finish(t("Cancelled"))

    def finish(self, message: str):
        self.cancel_button.hide()
        self.set_message(message)

    def _apply_result(self, level: MapLevel, result: MapResult, final: bool):
        if final:
            self.cancel_button.hide()
            level.result = result
        if not self.levels or level is not self.levels[-1]:
            return
        self.grouping = not final
        if same_layout(self.shown, result):
            self.apply_groups(result)
        else:
            self.show_result(result)

    def apply_groups(self, result: MapResult) -> None:
        colors = self.colors_for(result)
        self.map_view.set_groups(result, colors)
        self.file_list.set_groups(result.order, colors)
        self.shown = result
        self.show_counts(result)

    def show_result(self, result: MapResult):
        selected = set(self.selected_paths())
        keep_view = self.shown is not None and self.shown.paths == result.paths
        colors = self.colors_for(result)
        self.settings.apply(self.map_view, self.host)
        self.map_view.show_result(result, colors, keep_view)
        self.file_list.set_rows(result.paths, result.order, colors)
        self.shown = result
        rows = [row for row, path in enumerate(result.paths) if path in selected]
        self.map_view.select_rows(rows)
        self.file_list.select_rows(rows)
        self.show_counts(result)

    def show_counts(self, result: MapResult) -> None:
        groups = t("Grouping") + ELLIPSIS if self.grouping else t("{count} groups", count=result.diagnostics.groups)
        parts = [t("{count} files", count=len(result.paths)), groups]
        if result.diagnostics.unset:
            parts.append(t("{count} waiting for placement", count=result.diagnostics.unset))
        self.set_message(f" {SEPARATOR} ".join(parts))

    def colors_for(self, result: MapResult) -> list[QtGui.QColor]:
        return result_colors(result, self.palette_colors)

    def set_message(self, text: str):
        self.message.setText(text)

    def selected_paths(self) -> list[str]:
        if self.shown is None:
            return []
        return [self.shown.paths[row] for row in self.map_view.selected_rows()]

    def context_for_selection(self) -> dict:
        return {**self.host.context_for(self.selected_paths()), "map_panel": self}

    def select_all(self) -> None:
        if self.shown is None:
            return
        rows = list(range(len(self.shown.paths)))
        self.map_view.select_rows(rows)
        self.file_list.select_rows(rows)

    def on_map_selection(self):
        self.file_list.select_rows(self.map_view.selected_rows())

    def on_list_selection(self):
        rows = self.file_list.selected_rows()
        if self.settings.selection_mode == "group":
            expanded = self.map_view.expand_to_groups(rows)
            if expanded != rows:
                rows = expanded
                self.file_list.select_rows(rows)
        self.map_view.select_rows(rows)
        if rows:
            self.map_view.reveal(rows[-1])
        self.map_view.viewport().update()

    def drill_down(self) -> None:
        if not self.levels:
            return
        paths = self.selected_paths()
        if len(paths) < MIN_DRILL_FILES:
            self.set_message(t("Select at least 3 files."))
            return
        self.levels.append(MapLevel(paths))
        self.update_crumbs()
        self.recompute()

    def drill_up(self, level: int | None = None) -> None:
        target = len(self.levels) - 2 if level is None else level
        if target < 0 or target >= len(self.levels) - 1:
            return
        self.compute_cancel.cancel()
        del self.levels[target + 1 :]
        self.update_crumbs()
        result = self.levels[-1].result
        if result is None:
            self.recompute()
        else:
            self.show_result(result)

    def update_crumbs(self):
        while self.crumbs.count():
            widget = self.crumbs.takeAt(0).widget()
            if widget is not None:
                widget.deleteLater()
        for index, level in enumerate(self.levels):
            if index:
                self.crumbs.addWidget(QtWidgets.QLabel(CRUMB_ARROW))
            name = t("All") if index == 0 else t("Selection")
            button = QtWidgets.QToolButton()
            button.setText(f"{name} ({len(level.paths):,})")
            button.setAutoRaise(True)
            button.setEnabled(index < len(self.levels) - 1)
            button.clicked.connect(lambda _=False, i=index: self.drill_up(i))
            self.crumbs.addWidget(button)

    def thumbnail(self, path: str) -> QtGui.QPixmap | None:
        return self.host.thumbnail(path)

    def map_thumbnails(self, paths: list[str], size: float) -> list[QtGui.QPixmap | None]:
        return self.host.map_thumbnails(paths, size)

    def show_hover(self, path: str, global_pos: QtCore.QPoint) -> None:
        self.host.show_hover(path, global_pos)

    def hide_hover(self) -> None:
        self.host.hide_hover()

    def hideEvent(self, event: QtGui.QHideEvent) -> None:
        self.host.hide_hover()
        super().hideEvent(event)

    def handle_drag_enter(self, event):
        if local_file_paths(event.mimeData()):
            event.setDropAction(Qt.CopyAction)
            event.accept()
        else:
            event.ignore()

    def handle_drop(self, event):
        paths = local_file_paths(event.mimeData())
        db_path = getattr(InstanceRegistry.instance().get_host_window(), "database_path", None) or self.db_path
        if not paths or db_path is None:
            event.ignore()
            return
        event.setDropAction(Qt.IgnoreAction)
        event.accept()
        self.add_files(paths, db_path)

    def dragEnterEvent(self, event):
        self.handle_drag_enter(event)

    def dragMoveEvent(self, event):
        self.handle_drag_enter(event)

    def dropEvent(self, event):
        self.handle_drop(event)

    def save_state(self) -> dict:
        return {"splitter": bytes(self.splitter.saveState().toHex()).decode("ascii")}

    def restore_state(self, state: dict) -> None:
        splitter = state.get("splitter")
        if isinstance(splitter, str) and splitter:
            self.splitter.restoreState(QtCore.QByteArray.fromHex(splitter.encode("ascii")))
