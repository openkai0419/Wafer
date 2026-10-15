from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from functools import partial
from pathlib import Path

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from wafer.core.common.paths import db_name_from_path, normalize_path, safe_is_file
from wafer.core.db.path_values import PathValue, fetch_path_values, fetch_sources
from wafer.core.lang.manager import t
from wafer.core.logs import AppLogger
from wafer.qt.commands.binding.instance_registry import InstanceRegistry
from wafer.qt.common.dispatcher import CancelSlot, Dispatcher
from wafer.qt.common.dpi import dpix
from wafer.qt.common.icon_engine import themed_icon
from wafer.qt.common.rate_limit import qt_debounce
from wafer.qt.common.thread import utility_pool
from wafer.qt.theme import ThemeManager
from wafer.qt.widgets.popup import PopupBase

from .encoders import detect_encoder, value_input
from .feature_bar import FeatureBar
from .file_list import FileList
from .map_host import MapHost
from .map_view import MapView
from .params import MapParams
from .session import SPACE_KEYS, FeatureSpec, MapError, MapPipeline, MapRequest, MapResult, layout_from_space
from .space import Preset, load_preset
from .tuning import TuningPanel

COMPUTE_PRIORITY = 7
RECOMPUTE_DELAY_MS = 300
MIN_DRILL_FILES = 3
ELLIPSIS = "\N{HORIZONTAL ELLIPSIS}"
SEPARATOR = "\N{MIDDLE DOT}"
CRUMB_ARROW = "\N{SINGLE RIGHT-POINTING ANGLE QUOTATION MARK}"
SPACE_PANEL_NAME = "Mapping Space"
SPACE_MODES = ("space", "live")
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
    noise = QtGui.QColor(palette.text_muted)
    return [group_color(int(label)) if label >= 0 else noise for label in result.labels]


def cancel_work(*slots: CancelSlot) -> None:
    for slot in slots:
        slot.cancel()


@dataclass
class MapLevel:
    paths: list[str]
    pipeline: MapPipeline
    result: MapResult | None = None
    mode: str = "live"


class MappingWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        InstanceRegistry.instance().register("MappingWidget", self)
        self.palette_colors = ThemeManager.instance().palette
        self.dispatcher = Dispatcher(pool=utility_pool, parent=self)
        self.fetch_cancel = CancelSlot()
        self.compute_cancel = CancelSlot()
        self.db_path = None
        self.db_name = ""
        self.preset: Preset | None = None
        self.space_mode = "space"
        self.live_features: list[FeatureSpec] = []
        self.bar_state: tuple[bool, list[FeatureSpec] | None] | None = None
        self.paths: list[str] = []
        self.values: dict[str, dict[str, PathValue]] = {}
        self.params = MapParams()
        self.grouping_enabled = True
        self.levels: list[MapLevel] = []
        self.shown: MapResult | None = None
        self.host = MapHost(self)
        self.tuning_popup: PopupBase | None = None
        self.build_ui()
        self.host.map_views = [self.map_view]
        self.host.list_views = [self.file_list]
        self.setAcceptDrops(True)
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
        self.feature_bar = FeatureBar(self.detect)
        self.feature_bar.features_changed.connect(self.on_features_changed)
        toolbar.addWidget(self.feature_bar, stretch=1)
        self.edit_space_button = QtWidgets.QToolButton()
        self.edit_space_button.setText(t("Edit in Mapping Space"))
        self.edit_space_button.setToolTip(t("Change the keys and retrain in the Mapping Space panel."))
        self.edit_space_button.clicked.connect(self.open_space_panel)
        self.edit_space_button.hide()
        toolbar.addWidget(self.edit_space_button)
        self.space_buttons = {}
        space_group = QtWidgets.QButtonGroup(self)
        for mode, text in (("space", t("Precomputed")), ("live", t("Live"))):
            button = QtWidgets.QToolButton()
            button.setText(text)
            button.setCheckable(True)
            button.setToolTip(t("Use the saved space. Fast.") if mode == "space" else t("Lay out these files from scratch."))
            space_group.addButton(button)
            toolbar.addWidget(button)
            self.space_buttons[mode] = button
        self.precomputed_button = self.space_buttons["space"]
        self.space_buttons["live"].setChecked(True)
        for mode, button in self.space_buttons.items():
            button.toggled.connect(partial(self.on_space_toggled, mode))
        self.precomputed_button.setEnabled(False)
        self.group_check = QtWidgets.QCheckBox(t("Groups"))
        self.group_check.setChecked(True)
        self.group_check.setToolTip(t("Show group colors and labels."))
        self.group_check.toggled.connect(self.set_grouping)
        toolbar.addWidget(self.group_check)
        self.mode_buttons = {}
        mode_group = QtWidgets.QButtonGroup(self)
        for mode, text in (("single", t("Single")), ("group", t("Group"))):
            button = QtWidgets.QToolButton()
            button.setText(text)
            button.setCheckable(True)
            button.setChecked(mode == "single")
            button.setToolTip(t("Select one file at a time.") if mode == "single" else t("Select whole groups."))
            button.toggled.connect(partial(self.on_mode_toggled, mode))
            mode_group.addButton(button)
            toolbar.addWidget(button)
            self.mode_buttons[mode] = button
        self.tuning_button = QtWidgets.QToolButton()
        self.tuning_button.setIcon(themed_icon("gear_small"))
        self.tuning_button.setToolTip(t("Tuning"))
        self.tuning_button.clicked.connect(self.toggle_tuning)
        toolbar.addWidget(self.tuning_button)
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
        self.tuning = TuningPanel()
        self.tuning.params_changed.connect(self.on_params)
        self.map_view.selection_changed.connect(self.on_map_selection)
        self.file_list.selection_changed.connect(self.on_list_selection)

    def message_text(self) -> str:
        return self.message.text()

    def current_result(self) -> MapResult | None:
        return self.levels[-1].result if self.levels else None

    @property
    def grouping(self) -> bool:
        return self.grouping_enabled

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
                level.paths = kept
                level.pipeline = MapPipeline()
                level.result = None
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
            except Exception as e:
                AppLogger.error("[Mapping] Loading values failed", exc=e)
                self.dispatcher.invoke(lambda: cancel.is_cancelled() or self.finish(t("Mapping failed. See the log for details.")))
                return
            self.dispatcher.invoke(lambda: cancel.is_cancelled() or self.on_values(values, sources, preset, keep_levels))

        self.dispatcher.post(task, priority=COMPUTE_PRIORITY, cancel=cancel)

    def on_values(self, values, sources, preset: Preset | None = None, keep_levels: bool = False):
        self.values, self.host.sources = values, sources
        self.preset = preset if preset is not None and preset.features and preset.version > 0 else None
        self.sync_space_buttons()
        counts = Counter(key for entry in values.values() for key, value in entry.items() if key not in SPACE_KEYS and value_input(value) is not None)
        self.feature_bar.set_keys(counts.most_common())
        if keep_levels and self.levels and self.effective_mode() == "space":
            for level in self.levels:
                level.pipeline, level.result = MapPipeline(), None
        else:
            self.levels = [MapLevel(list(self.paths), MapPipeline(), mode=self.effective_mode())]
        self.update_crumbs()
        self.recompute()

    def refresh(self) -> None:
        if self.levels and self.levels[-1].mode == "space":
            self.fetch(keep_levels=True)
        else:
            self.recompute()

    def effective_mode(self) -> str:
        return "space" if self.space_mode == "space" and self.preset is not None else "live"

    def sync_space_buttons(self) -> None:
        self.precomputed_button.setEnabled(self.preset is not None)
        button = self.space_buttons[self.effective_mode()]
        if not button.isChecked():
            button.blockSignals(True)
            button.setChecked(True)
            button.blockSignals(False)

    def on_space_toggled(self, mode: str, checked: bool) -> None:
        if checked:
            self.set_space_mode(mode)

    def set_space_mode(self, mode: str) -> None:
        if mode not in SPACE_MODES:
            return
        previous = self.effective_mode()
        self.space_mode = mode
        self.sync_space_buttons()
        if self.effective_mode() == previous:
            return
        if not self.levels:
            self.sync_features(self.effective_mode())
            return
        self.levels = [MapLevel(list(self.paths), MapPipeline(), mode=self.effective_mode())]
        self.update_crumbs()
        self.recompute()

    def sync_features(self, mode: str) -> None:
        read_only = mode == "space" and self.preset is not None
        shown = list(self.preset.features) if read_only else None
        if self.bar_state == (read_only, shown):
            return
        self.bar_state = (read_only, shown)
        self.feature_bar.set_features(shown if read_only else self.live_features)
        self.feature_bar.set_read_only(read_only)
        self.edit_space_button.setVisible(read_only)

    def on_features_changed(self) -> None:
        self.live_features = self.feature_bar.features()
        self.schedule_recompute()

    def open_space_panel(self) -> None:
        manager = getattr(self.window(), "_layout_manager", None)
        if manager is not None and SPACE_PANEL_NAME in manager.panel_names():
            manager.ensure_panel_visible(SPACE_PANEL_NAME)

    def detect(self, key: str) -> str:
        values = [value_input(self.values.get(path, {}).get(key)) for path in self.paths]
        return detect_encoder([value for value in values if value is not None])

    @qt_debounce(RECOMPUTE_DELAY_MS)
    def schedule_recompute(self):
        self.recompute()

    def recompute(self) -> None:
        if not self.levels:
            return
        level = self.levels[-1]
        preset = self.preset if level.mode == "space" else None
        self.sync_features("space" if preset is not None else "live")
        features = preset.features if preset is not None else self.feature_bar.features()
        if not features:
            self.compute_cancel.cancel()
            self.finish(t("Add a key to start."))
            return
        paths, values, params, grouping = list(level.paths), self.values, self.params, self.grouping_enabled
        cancel = self.compute_cancel.renew()
        self.cancel_button.show()

        def progress(stage, fraction):
            name = t(STAGE_NAMES.get(stage, stage)) + ELLIPSIS
            text = f"{name} {fraction:.0%}" if fraction else name
            self.dispatcher.invoke(lambda: cancel.is_cancelled() or self.set_message(text))

        def compute():
            if preset is not None:
                return layout_from_space(paths, values, preset, params, grouping)
            request = MapRequest(paths, values, features, params, grouping)
            return level.pipeline.run(request, cancelled=cancel.is_cancelled, progress=progress)

        def task():
            try:
                result = compute()
            except MapError as e:
                self.dispatcher.invoke(lambda m=str(e): cancel.is_cancelled() or self.finish(t(m)))
                return
            except Exception as e:
                AppLogger.error("[Mapping] Map computation failed", exc=e)
                self.dispatcher.invoke(lambda: cancel.is_cancelled() or self.finish(t("Mapping failed. See the log for details.")))
                return
            if result is not None:
                self.dispatcher.invoke(lambda: cancel.is_cancelled() or self._apply_result(level, result))

        self.dispatcher.post(task, priority=COMPUTE_PRIORITY, cancel=cancel)

    def cancel_compute(self):
        self.compute_cancel.cancel()
        self.finish(t("Cancelled"))

    def finish(self, message: str):
        self.cancel_button.hide()
        self.set_message(message)

    def _apply_result(self, level: MapLevel, result: MapResult):
        self.cancel_button.hide()
        level.result = result
        if not self.levels or level is not self.levels[-1]:
            return
        self.show_result(result)

    def show_result(self, result: MapResult):
        self.host.set_hover_size(self.params.hover_size)
        selected = set(self.selected_paths())
        keep_view = self.shown is not None and self.shown.paths == result.paths
        colors = self.colors_for(result)
        self.map_view.set_thumbnail_zoom(self.params.thumbnail_zoom)
        self.map_view.set_image_limit(self.params.max_images)
        self.map_view.set_image_spacing(self.params.image_spacing)
        self.map_view.show_result(result, colors, self.grouping_enabled, keep_view)
        self.file_list.set_rows(result.paths, result.order, colors)
        self.shown = result
        rows = [row for row, path in enumerate(result.paths) if path in selected]
        self.map_view.select_rows(rows)
        self.file_list.select_rows(rows)
        self.tuning.set_diagnostics(result.diagnostics)
        self.cancel_button.hide()
        parts = [t("{count} files", count=len(result.paths))]
        if self.grouping_enabled:
            parts.append(t("{count} groups", count=result.diagnostics.groups))
        if result.diagnostics.unset and self.levels and self.levels[-1].mode == "space":
            parts.append(t("{count} waiting for placement", count=result.diagnostics.unset))
        self.set_message(f" {SEPARATOR} ".join(parts))

    def colors_for(self, result: MapResult) -> list[QtGui.QColor]:
        return result_colors(result, self.palette_colors)

    def set_message(self, text: str):
        self.message.setText(text)

    def set_grouping(self, enabled: bool) -> None:
        self.grouping_enabled = bool(enabled)
        if self.group_check.isChecked() != self.grouping_enabled:
            self.group_check.setChecked(self.grouping_enabled)
            return
        self.mode_buttons["group"].setEnabled(self.grouping_enabled)
        self.recompute()

    def on_params(self, params: MapParams):
        self.params = params
        self.host.set_hover_size(params.hover_size)
        self.schedule_recompute()

    def toggle_tuning(self):
        popup = self.tuning_popup
        if popup is not None and popup.isVisible():
            popup.close()
            return
        if popup is None:
            palette = self.palette_colors
            popup = PopupBase(self)
            popup.setStyleSheet(f"PopupBase {{ background: {palette.bg_elevated}; border: 1px solid {palette.border_default}; border-radius: {dpix(6)}px; }}")
            QtWidgets.QVBoxLayout(popup).setContentsMargins(0, 0, 0, 0)
            scroll = QtWidgets.QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(self.tuning)
            popup.set_content_widget(scroll)
            self.tuning_popup = popup
        popup.show_below(self.tuning_button, align=Qt.AlignRight, max_height=dpix(600))

    def selected_paths(self) -> list[str]:
        if self.shown is None:
            return []
        return [self.shown.paths[row] for row in self.map_view.selected_rows()]

    def context_for_selection(self) -> dict:
        return self.host.context_for(self.selected_paths())

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
        if self.selection_mode == "group":
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
        self.levels.append(MapLevel(paths, MapPipeline(), mode=self.levels[-1].mode))
        self.update_crumbs()
        self.recompute()

    def relayout_selection(self) -> None:
        if not self.levels:
            return
        paths = self.selected_paths()
        if len(paths) < MIN_DRILL_FILES:
            self.set_message(t("Select at least 3 files."))
            return
        if self.levels[-1].mode == "space" and self.preset is not None and not self.live_features:
            self.live_features = list(self.preset.features)
        self.levels.append(MapLevel(paths, MapPipeline(), mode="live"))
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
            self.sync_features(self.levels[-1].mode)
            self.show_result(result)

    def update_crumbs(self):
        while self.crumbs.count():
            widget = self.crumbs.takeAt(0).widget()
            if widget is not None:
                widget.deleteLater()
        for index, level in enumerate(self.levels):
            if index:
                self.crumbs.addWidget(QtWidgets.QLabel(CRUMB_ARROW))
            if index == 0:
                name = t("All")
            else:
                name = t("Selection (live)") if level.mode != self.levels[0].mode else t("Selection")
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

    def set_image_scale(self, scale: float) -> None:
        self.map_view.set_image_scale(scale)

    def image_scale_up(self, ratio: float = 1.1) -> None:
        self.set_image_scale(self.map_view.image_scale * ratio)

    def image_scale_down(self, ratio: float = 1.1) -> None:
        self.set_image_scale(self.map_view.image_scale / ratio)

    @property
    def selection_mode(self) -> str:
        return self.map_view.selection_mode

    def set_selection_mode(self, mode: str) -> None:
        self.map_view.set_selection_mode(mode)
        button = self.mode_buttons[self.map_view.selection_mode]
        if not button.isChecked():
            button.blockSignals(True)
            button.setChecked(True)
            button.blockSignals(False)

    def on_mode_toggled(self, mode: str, checked: bool) -> None:
        if checked:
            self.set_selection_mode(mode)

    def handle_drag_enter(self, event):
        if local_file_paths(event.mimeData()):
            event.setDropAction(Qt.CopyAction)
            event.accept()
        else:
            event.ignore()

    def handle_drop(self, event):
        paths = local_file_paths(event.mimeData())
        db_path = getattr(self.window(), "database_path", None) or self.db_path
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
        return {
            "features": [feature.to_dict() for feature in self.live_features],
            "space_mode": self.space_mode,
            "params": self.params.to_dict(),
            "grouping": self.grouping_enabled,
            "image_scale": self.map_view.image_scale,
            "selection_mode": self.selection_mode,
            "splitter": bytes(self.splitter.saveState().toHex()).decode("ascii"),
        }

    def restore_state(self, state: dict) -> None:
        features = [FeatureSpec.from_dict(item) for item in state.get("features", []) if isinstance(item, dict)]
        self.live_features = [feature for feature in features if feature is not None]
        self.space_mode = "live" if state.get("space_mode") == "live" else "space"
        self.bar_state = None
        self.sync_features(self.effective_mode())
        self.sync_space_buttons()
        self.params = MapParams.from_dict(state.get("params") or {})
        self.tuning.set_params(self.params)
        self.grouping_enabled = bool(state.get("grouping", True))
        self.group_check.blockSignals(True)
        self.group_check.setChecked(self.grouping_enabled)
        self.group_check.blockSignals(False)
        self.mode_buttons["group"].setEnabled(self.grouping_enabled)
        scale = state.get("image_scale", 1.0)
        self.set_image_scale(float(scale) if isinstance(scale, (int, float)) and math.isfinite(scale) else 1.0)
        mode = state.get("selection_mode")
        self.set_selection_mode(mode if mode in ("single", "group") else "single")
        splitter = state.get("splitter")
        if isinstance(splitter, str) and splitter:
            self.splitter.restoreState(QtCore.QByteArray.fromHex(splitter.encode("ascii")))
