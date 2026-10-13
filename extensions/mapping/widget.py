from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from functools import partial
from pathlib import Path

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from wafer.core.common.paths import normalize_path, safe_is_file
from wafer.core.db.path_values import PathValue, fetch_path_values, fetch_sources
from wafer.core.lang.manager import t
from wafer.core.logs import AppLogger
from wafer.plugin.grid.handler import load_thumbnail
from wafer.plugin.grid.thumbnail_loader import ThumbnailLoader
from wafer.qt.commands.binding.instance_registry import InstanceRegistry
from wafer.qt.common.dispatcher import CancelSlot, Dispatcher
from wafer.qt.common.dpi import dpix
from wafer.qt.common.icon_engine import themed_icon
from wafer.qt.common.rate_limit import qt_debounce
from wafer.qt.common.thread import utility_pool
from wafer.qt.theme import ThemeManager
from wafer.qt.widgets.popup import PopupBase

from .encoders import detect_encoder
from .feature_bar import FeatureBar
from .file_list import FileList
from .map_view import THUMB_SIZE, MapView
from .params import MapParams
from .session import FeatureSpec, MapError, MapPipeline, MapRequest, MapResult, value_input
from .tuning import TuningPanel

PIXEL_SIZE = 64
COMPUTE_PRIORITY = 7
THUMB_CACHE = 3000
RECOMPUTE_DELAY_MS = 300
MIN_DRILL_FILES = 3
ELLIPSIS = "\N{HORIZONTAL ELLIPSIS}"
SEPARATOR = "\N{MIDDLE DOT}"
CRUMB_ARROW = "\N{SINGLE RIGHT-POINTING ANGLE QUOTATION MARK}"
STAGE_NAMES = {"images": "Loading images", "encode": "Encoding", "layout": "Laying out (the first run takes longer)", "cluster": "Grouping"}


def qimage_to_rgb(image: QtGui.QImage) -> np.ndarray:
    image = image.convertToFormat(QtGui.QImage.Format_RGB888)
    width, height, stride = image.width(), image.height(), image.bytesPerLine()
    data = np.frombuffer(image.constBits(), dtype=np.uint8, count=stride * height).reshape(height, stride)
    return data[:, : width * 3].reshape(height, width, 3).copy()


def load_pixels(path: str) -> np.ndarray | None:
    try:
        image = load_thumbnail(path, QtCore.QSize(PIXEL_SIZE, PIXEL_SIZE))
    except Exception as e:
        AppLogger.warning(f"[Mapping] Thumbnail failed: {path}", exc=e)
        return None
    if image is None or image.isNull():
        return None
    return qimage_to_rgb(image)


def local_file_paths(mime: QtCore.QMimeData | None) -> list[str]:
    if mime is None or not mime.hasUrls():
        return []
    return [normalize_path(url.toLocalFile()) for url in mime.urls() if url.isLocalFile() and safe_is_file(Path(url.toLocalFile()))]


def group_color(group: int) -> QtGui.QColor:
    return QtGui.QColor.fromHsvF((group * 0.618034) % 1.0, 0.55, 0.92)


def cancel_work(fetch_cancel: CancelSlot, compute_cancel: CancelSlot, thumbs: ThumbnailLoader) -> None:
    fetch_cancel.cancel()
    compute_cancel.cancel()
    thumbs.cancel_all()


@dataclass
class MapLevel:
    paths: list[str]
    pipeline: MapPipeline
    result: MapResult | None = None


class MappingWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        InstanceRegistry.instance().register("MappingWidget", self)
        self.palette_colors = ThemeManager.instance().palette
        self.dispatcher = Dispatcher(pool=utility_pool, parent=self)
        self.fetch_cancel = CancelSlot()
        self.compute_cancel = CancelSlot()
        self.db_path = None
        self.paths: list[str] = []
        self.values: dict[str, dict[str, PathValue]] = {}
        self.sources: dict[str, str] = {}
        self.params = MapParams()
        self.grouping_enabled = True
        self.pixels: dict[str, np.ndarray | None] = {}
        self.levels: list[MapLevel] = []
        self.shown: MapResult | None = None
        self.thumbs = ThumbnailLoader(self.on_thumbnail, size=THUMB_SIZE, cache_limit=THUMB_CACHE, dispatcher=self.dispatcher)
        self.tuning_popup: PopupBase | None = None
        self.build_ui()
        self.setAcceptDrops(True)
        self.destroyed.connect(partial(cancel_work, self.fetch_cancel, self.compute_cancel, self.thumbs))

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
        self.feature_bar.features_changed.connect(self.schedule_recompute)
        toolbar.addWidget(self.feature_bar, stretch=1)
        self.group_check = QtWidgets.QCheckBox(t("Groups"))
        self.group_check.setChecked(True)
        self.group_check.setToolTip(t("Show group colors and labels."))
        self.group_check.toggled.connect(self.set_grouping)
        toolbar.addWidget(self.group_check)
        self.tuning_button = QtWidgets.QToolButton()
        self.tuning_button.setIcon(themed_icon("gear_small"))
        self.tuning_button.setToolTip(t("Tuning"))
        self.tuning_button.clicked.connect(self.toggle_tuning)
        toolbar.addWidget(self.tuning_button)
        refresh = QtWidgets.QToolButton()
        refresh.setIcon(themed_icon("refresh"))
        refresh.setToolTip(t("Recompute"))
        refresh.clicked.connect(self.recompute)
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
        self.paths = list(dict.fromkeys(paths))
        self.levels = []
        keep = set(self.paths)
        self.pixels = {path: pixels for path, pixels in self.pixels.items() if path in keep}
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
                level.pipeline = MapPipeline(load_pixels, self.pixels)
                level.result = None
                changed.append(level)
        self.update_crumbs()
        if self.levels and self.levels[-1] in changed:
            self.recompute()

    def reset(self) -> None:
        cancel_work(self.fetch_cancel, self.compute_cancel, self.thumbs)
        self.paths, self.values, self.sources, self.levels, self.shown = [], {}, {}, [], None
        self.pixels = {}
        self.thumbs.clear()
        self.map_view.clear_map()
        self.file_list.clear_rows()
        self.update_crumbs()
        self.cancel_button.hide()
        self.set_message("")
        self.stack.setCurrentIndex(0)

    def fetch(self):
        cancel = self.fetch_cancel.renew()
        self.compute_cancel.cancel()
        paths, db_path = list(self.paths), self.db_path
        self.set_message(t("Loading values") + ELLIPSIS)

        def task():
            try:
                values = fetch_path_values(db_path, paths)
                sources = fetch_sources(db_path, paths)
            except Exception as e:
                AppLogger.error("[Mapping] Loading values failed", exc=e)
                self.dispatcher.invoke(lambda: cancel.is_cancelled() or self.finish(t("Mapping failed. See the log for details.")))
                return
            self.dispatcher.invoke(lambda: cancel.is_cancelled() or self.on_values(values, sources))

        self.dispatcher.post(task, priority=COMPUTE_PRIORITY, cancel=cancel)

    def on_values(self, values, sources):
        self.values, self.sources = values, sources
        counts = Counter(key for entry in values.values() for key, value in entry.items() if value_input(value) is not None)
        self.feature_bar.set_keys(counts.most_common())
        self.levels = [MapLevel(list(self.paths), MapPipeline(load_pixels, self.pixels))]
        self.update_crumbs()
        self.recompute()

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
        features = self.feature_bar.features()
        if not features:
            self.compute_cancel.cancel()
            self.finish(t("Add a key to start."))
            return
        pipeline = level.pipeline
        request = MapRequest(list(level.paths), self.values, features, self.params, self.grouping_enabled)
        cancel = self.compute_cancel.renew()
        self.cancel_button.show()

        def progress(stage, fraction):
            name = t(STAGE_NAMES.get(stage, stage)) + ELLIPSIS
            text = f"{name} {fraction:.0%}" if fraction else name
            self.dispatcher.invoke(lambda: cancel.is_cancelled() or self.set_message(text))

        def task():
            try:
                result = pipeline.run(request, cancelled=cancel.is_cancelled, progress=progress)
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
        self.thumbs.cache_limit = max(THUMB_CACHE, len(result.paths))
        selected = set(self.selected_paths())
        keep_view = self.shown is not None and self.shown.paths == result.paths
        colors = self.colors_for(result)
        self.map_view.set_thumbnail_zoom(self.params.thumbnail_zoom)
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
        self.set_message(f" {SEPARATOR} ".join(parts))

    def colors_for(self, result: MapResult) -> list[QtGui.QColor]:
        neutral = QtGui.QColor(self.palette_colors.text_secondary)
        if result.labels is None:
            return [neutral] * len(result.paths)
        noise = QtGui.QColor(self.palette_colors.text_muted)
        return [group_color(int(label)) if label >= 0 else noise for label in result.labels]

    def set_message(self, text: str):
        self.message.setText(text)

    def set_grouping(self, enabled: bool) -> None:
        self.grouping_enabled = bool(enabled)
        if self.group_check.isChecked() != self.grouping_enabled:
            self.group_check.setChecked(self.grouping_enabled)
            return
        self.recompute()

    def on_params(self, params: MapParams):
        self.params = params
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
        paths = self.selected_paths()
        if not paths:
            return {}
        sources = list(dict.fromkeys(self.sources.get(path, path) for path in paths))
        return {"path": paths[-1], "paths": paths, "source": sources[-1], "sources": sources}

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
        self.levels.append(MapLevel(paths, MapPipeline(load_pixels, self.pixels)))
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
        pixmap = self.thumbs.get(path)
        if pixmap is None:
            self.thumbs.request([path])
        return pixmap

    def on_thumbnail(self, path: str):
        self.map_view.update_path(path)
        self.file_list.update_path(path)

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
            "features": [feature.to_dict() for feature in self.feature_bar.features()],
            "params": self.params.to_dict(),
            "grouping": self.grouping_enabled,
            "splitter": bytes(self.splitter.saveState().toHex()).decode("ascii"),
        }

    def restore_state(self, state: dict) -> None:
        features = [FeatureSpec.from_dict(item) for item in state.get("features", []) if isinstance(item, dict)]
        self.feature_bar.set_features([feature for feature in features if feature is not None])
        self.params = MapParams.from_dict(state.get("params") or {})
        self.tuning.set_params(self.params)
        self.grouping_enabled = bool(state.get("grouping", True))
        self.group_check.blockSignals(True)
        self.group_check.setChecked(self.grouping_enabled)
        self.group_check.blockSignals(False)
        splitter = state.get("splitter")
        if isinstance(splitter, str) and splitter:
            self.splitter.restoreState(QtCore.QByteArray.fromHex(splitter.encode("ascii")))
