from __future__ import annotations

import os
import time
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass, field
from functools import partial
from typing import Any

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from wafer.core.common.paths import data_db_path, list_data_db_names, safe_getsize, setting_db_path
from wafer.core.db.db_utils import open_readonly
from wafer.core.db.path_values import PathValue, fetch_path_values, fetch_sources
from wafer.core.db.query import STANDARD_KEYS, SYSTEM_FILE_HASH_KEY, FileSearchEngine
from wafer.core.db.recollect import Recollect
from wafer.core.db.setting_db import SettingDB
from wafer.core.lang.manager import t
from wafer.core.logs import AppLogger
from wafer.plugin.query.composer import SearchComposer
from wafer.plugin.settings import PluginSettings
from wafer.qt.commands.binding.instance_registry import InstanceRegistry
from wafer.qt.common.dispatcher import CancelSlot, CancelToken, Dispatcher
from wafer.qt.common.dpi import dpix
from wafer.qt.common.rate_limit import qt_debounce
from wafer.qt.common.thread import utility_pool
from wafer.qt.theme import ThemeManager

from .encoders import detect_encoder, value_input
from .feature_bar import FeatureBar
from .map_host import MapHost
from .map_toolbar import MapToolbar
from .map_view import MapView
from .params import TrainParams, ViewParams
from .session import KEY_MODEL, OUTPUT_PREFIX, SPACE_KEYS, MapError, MapResult, SpaceLayout
from .space import Preset, SpaceModel, SpaceStatus, count_placed, load_preset, model_dir, read_status, save_preset, space_model
from .tuning import TuningPanel
from .view_settings import RELAYOUT_PARAMS, GroupingStore, TabSettings, ViewSettings
from .widget import cancel_work, local_file_paths, prepare_layout_engine, result_colors, same_layout

LOAD_PRIORITY = 7
STATUS_REFRESH_MS = 1000
PREVIEW_FILES = 5000
PREVIEW_RANGE = (100, 200_000)
RESAMPLE_DELAY_MS = 300
FORM_MIN_WIDTH = 300
MAP_MIN_WIDTH = 360
QUICK_TRAIN_FILES = 3000
QUICK_TRAIN_RANGE = (100, 100_000)
DETECT_SAMPLE = 300
RETRAIN_RATIO = 0.2
MEGABYTE = 1024 * 1024
ELLIPSIS = "\N{HORIZONTAL ELLIPSIS}"
SEPARATOR = "\N{MIDDLE DOT}"
PROVISIONAL_ENCODER = "text"
STAGE_NAMES = {"encode": "Encoding", "layout": "Laying out (the first run takes longer)", "cluster": "Grouping"}
WAITING_SQL = "SELECT COUNT(*) FROM collection_status WHERE collector = ? AND status IN ('pending', 'dispatched')"
FILE_KEYS = frozenset((*STANDARD_KEYS, SYSTEM_FILE_HASH_KEY))


def status_text(status: SpaceStatus, total: int, placed: int, waiting: int = 0, model_bytes: int = 0) -> str:
    if status.state == "ready":
        state = t("Ready")
    elif status.state == "training":
        state = t("Training") + ELLIPSIS
    elif status.state == "unreadable":
        state = t("The model cannot be read. Retrain.")
    elif status.state == "failed":
        state = t("Training failed: {error}", error=status.error)
    else:
        state = t("Not trained yet.")
    lines = [f"{t('Space')} v{status.version} {SEPARATOR} {state}"]
    if status.trained:
        lines.append(t("Trained on {count} files", count=f"{status.trained:,}"))
    if status.version:
        lines.append(t("{placed} of {total} files placed", placed=f"{placed:,}", total=f"{total:,}"))
        if waiting:
            lines.append(t("{count} waiting for placement", count=f"{waiting:,}"))
    added = max(total - status.sources_at_training, 0)
    if status.state == "ready" and status.sources_at_training and added:
        lines.append(t("{count} files added since training", count=f"{added:,}"))
        if added > status.sources_at_training * RETRAIN_RATIO:
            lines.append(t("Retraining is recommended."))
    if model_bytes > 0:
        lines.append(t("Model size: {size} MB", size=f"{model_bytes / MEGABYTE:.1f}"))
    return "\n".join(lines)


def parser_enabled(db_name: str) -> bool:
    enabled = SettingDB(setting_db_path(db_name)).get_enabled_collectors()
    if enabled is None:
        enabled = PluginSettings().resolve_default_collectors()
    return OUTPUT_PREFIX in enabled


def current_status(status: SpaceStatus, version: int) -> SpaceStatus:
    if version and status.version != version and status.state != "none":
        return SpaceStatus("training", version)
    return status


@dataclass
class SpaceSnapshot:
    preset: Preset
    status: SpaceStatus
    total: int = 0
    placed: int = 0
    waiting: int = 0
    model_bytes: int = 0
    result: MapResult | None = None
    layout: SpaceLayout | None = None
    sources: dict[str, str] = field(default_factory=dict)
    problem: str = ""


def has_saved_space(preset: Preset) -> bool:
    return bool(preset.version and preset.features)


def read_space_status(db_name: str) -> SpaceSnapshot:
    preset = load_preset(db_name) or Preset([], TrainParams(), 0)
    directory = model_dir(db_name)
    status = current_status(read_status(directory), preset.version)
    snapshot = SpaceSnapshot(preset, status)
    snapshot.model_bytes = sum(safe_getsize(path) or 0 for path in directory.glob(f"model-v{preset.version}.*"))
    db_path = data_db_path(db_name)
    if not os.path.isfile(db_path):
        return snapshot
    with closing(open_readonly(db_path)) as conn:
        snapshot.total = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        snapshot.waiting = conn.execute(WAITING_SQL, (OUTPUT_PREFIX,)).fetchone()[0]
        if has_saved_space(preset):
            snapshot.placed = count_placed(db_path, preset)
    return snapshot


def file_count_box(value_range: tuple[int, int], value: int) -> QtWidgets.QSpinBox:
    box = QtWidgets.QSpinBox()
    box.setRange(*value_range)
    box.setSingleStep(1000)
    box.setGroupSeparatorShown(True)
    box.setValue(value)
    box.setSuffix(" " + t("files"))
    return box


class DatabaseBox(QtWidgets.QComboBox):
    def __init__(self, can_open: Callable[[str], bool], parent=None):
        super().__init__(parent)
        self.can_open = can_open

    def showPopup(self) -> None:
        self.reload()
        super().showPopup()

    def add_name(self, name: str) -> None:
        self.addItem(name)
        self.model().item(self.count() - 1).setEnabled(self.can_open(name))

    def reload(self) -> None:
        current = self.currentText()
        names = sorted(set(list_data_db_names()) | ({current} if current else set()))
        self.blockSignals(True)
        self.clear()
        for name in names:
            self.add_name(name)
        self.setCurrentText(current)
        self.blockSignals(False)

    def show_quietly(self, name: str) -> None:
        if not name:
            return
        self.blockSignals(True)
        if self.findText(name) < 0:
            self.add_name(name)
        self.setCurrentText(name)
        self.blockSignals(False)


def section_title(text: str) -> QtWidgets.QLabel:
    label = QtWidgets.QLabel(t(text))
    font = label.font()
    font.setBold(True)
    label.setFont(font)
    return label


def labelled_row(text: str, widget: QtWidgets.QWidget, tooltip: str = "") -> QtWidgets.QHBoxLayout:
    row = QtWidgets.QHBoxLayout()
    label = QtWidgets.QLabel(t(text))
    if tooltip:
        label.setToolTip(t(tooltip))
        widget.setToolTip(t(tooltip))
    row.addWidget(label)
    row.addWidget(widget, stretch=1)
    return row


def read_snapshot(db_name: str, view: ViewParams, size: int = PREVIEW_FILES) -> SpaceSnapshot:
    snapshot = read_space_status(db_name)
    preset = snapshot.preset
    db_path = data_db_path(db_name)
    if not os.path.isfile(db_path):
        return snapshot
    model = space_model(db_name, preset) if has_saved_space(preset) and snapshot.status.state == "ready" else None
    if snapshot.status.state == "training":
        snapshot.problem = "Training. The whole map appears when it finishes."
        return snapshot
    space = None if model is None else model.whole_space()
    if space is None or not space.size:
        return snapshot
    rows = np.random.default_rng().choice(space.size, min(size, space.size), replace=False)
    sample = [space.paths[row] for row in rows]
    values = fetch_path_values(db_path, sample, keys=preset.value_keys())
    snapshot.sources = fetch_sources(db_path, sample)
    snapshot.layout = SpaceLayout(sample, values, preset, model)
    snapshot.result, snapshot.problem = run_preview(snapshot.layout, view, db_name, grouped=False)
    return snapshot


def run_preview(layout: SpaceLayout, view: ViewParams, db_name: str, grouped: bool = True, cancelled=lambda: False) -> tuple[MapResult | None, str]:
    try:
        return layout.run(view, grouping=GroupingStore.instance().get(db_name), grouped=grouped, cancelled=cancelled), ""
    except MapError as e:
        return None, str(e)
    except Exception as e:
        AppLogger.warning(f"[Mapping] Laying out the whole map of {db_name} failed", exc=e)
        return None, str(e) or type(e).__name__


@dataclass
class QuickTrainSample:
    db_name: str
    size: int
    keys: frozenset[str]
    paths: list[str]
    values: dict[str, dict[str, PathValue]]
    sources: dict[str, str]

    def covers(self, db_name: str, size: int, keys: frozenset[str]) -> bool:
        return self.db_name == db_name and self.size == size and keys <= self.keys


def read_quick_train_sample(db_name: str, size: int, keys: frozenset[str]) -> QuickTrainSample:
    db_path = data_db_path(db_name)
    with closing(open_readonly(db_path)) as conn:
        paths = [row[0] for row in conn.execute("SELECT source FROM sources ORDER BY RANDOM() LIMIT ?", (size,))]
    values = fetch_path_values(db_path, paths, keys=sorted(keys))
    return QuickTrainSample(db_name, size, keys, paths, values, fetch_sources(db_path, paths))


def read_key_catalog(db_name: str) -> list[tuple[str, int]]:
    engine = FileSearchEngine(data_db_path(db_name))
    try:
        results = SearchComposer().list_all_keys(engine, [], sort_by_freq=True)
    finally:
        engine.close()
    return [(key, count) for key, count in results if not key.startswith(OUTPUT_PREFIX + ".")]


def sample_paths_with_key(conn, key: str, limit: int) -> list[str]:
    if key in FILE_KEYS:
        return [row[0] for row in conn.execute("SELECT path FROM files LIMIT ?", (limit,))]
    paths = [row[0] for row in conn.execute("SELECT path FROM meta_info WHERE key = ? LIMIT ?", (key, limit))]
    if len(paths) < limit:
        tagged = conn.execute(
            "SELECT f.path FROM tags AS t JOIN sources AS s ON s.file_hash = t.file_hash JOIN files AS f ON f.source = s.source WHERE t.key = ? LIMIT ?",
            (key, limit - len(paths)),
        )
        paths += [row[0] for row in tagged]
    return list(dict.fromkeys(paths))


def detect_key_encoder(db_name: str, key: str) -> str | None:
    db_path = data_db_path(db_name)
    if not os.path.isfile(db_path):
        return None
    with closing(open_readonly(db_path)) as conn:
        paths = sample_paths_with_key(conn, key, DETECT_SAMPLE)
    values = fetch_path_values(db_path, paths, keys=[key])
    present = [value for value in (value_input(entry.get(key)) for entry in values.values()) if value is not None]
    return detect_encoder(present) if present else None


def cancel_tokens(tokens: dict[str, CancelToken]) -> None:
    for token in tokens.values():
        token.cancel()


class MappingSpaceWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.palette_colors = ThemeManager.instance().palette
        self.dispatcher = Dispatcher(pool=utility_pool, parent=self)
        prepare_layout_engine(self.dispatcher)
        self.refresh_cancel = CancelSlot()
        self.keys_cancel = CancelSlot()
        self.status_cancel = CancelSlot()
        self.db_name = ""
        self.keys_db: str | None = None
        self.saved = Preset([], TrainParams(), 0)
        self.status = SpaceStatus("none", 0)
        self.total = 0
        self.placed = 0
        self.waiting = 0
        self.model_bytes = 0
        self.notice = ""
        self.detecting: dict[str, CancelToken] = {}
        self.shown: MapResult | None = None
        self.preview_layout: SpaceLayout | None = None
        self.preview_sources: dict[str, str] = {}
        self.quick_sample: QuickTrainSample | None = None
        self.quick_layout: SpaceLayout | None = None
        self.quick_cancel = CancelSlot()
        self.quick_running = False
        self.showing_quick = False
        self.preview_loading = False
        self.preview_mark: tuple[str, int] | None = None
        self.preview_key: tuple[str, int] | None = None
        self.on_drop: Callable[[Any], None] | None = None
        self.host = MapHost(self)
        self.settings = ViewSettings.instance()
        self.tab = TabSettings(self)
        self.build_ui()
        self.host.map_views = [self.map_view]
        self.settings.changed.connect(self.on_view_settings)
        self.tab.changed.connect(lambda _changed: self.tab.apply(self.map_view))
        GroupingStore.instance().changed.connect(self.on_grouping_changed)
        self.default_db()
        self.update_buttons()
        self.destroyed.connect(partial(cancel_work, self.refresh_cancel, self.keys_cancel, self.status_cancel, self.quick_cancel))
        self.destroyed.connect(partial(cancel_tokens, self.detecting))
        self.status_timer = QtCore.QTimer(self)
        self.status_timer.setSingleShot(True)
        self.status_timer.setInterval(STATUS_REFRESH_MS)
        self.status_timer.timeout.connect(self.refresh_status)
        self.connect_indexer_updates()

    def build_ui(self):
        palette = self.palette_colors
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        top = QtWidgets.QHBoxLayout()
        top.setContentsMargins(dpix(8), dpix(6), dpix(8), dpix(2))
        top.addWidget(section_title("Database"))
        self.db_box = DatabaseBox(self.can_open)
        self.db_box.setToolTip(t("The database whose map you train and view here."))
        self.db_box.currentTextChanged.connect(self.choose_db)
        top.addWidget(self.db_box, stretch=1)
        root.addLayout(top)
        self.content = QtWidgets.QStackedWidget()
        root.addWidget(self.content, stretch=1)
        self.splitter = QtWidgets.QSplitter(Qt.Horizontal)
        self.content.addWidget(self.splitter)
        self.blocked = QtWidgets.QLabel(t("Enable the Mapping parser for this database in Plugin Manager."))
        self.blocked.setAlignment(Qt.AlignCenter)
        self.blocked.setWordWrap(True)
        self.blocked.setStyleSheet(f"color: {palette.text_muted}; font-size: {dpix(13)}px;")
        self.content.addWidget(self.blocked)
        form = QtWidgets.QWidget()
        form_layout = QtWidgets.QVBoxLayout(form)
        form_layout.setContentsMargins(dpix(8), dpix(8), dpix(8), dpix(8))
        form_layout.addWidget(section_title("Keys"))
        self.feature_bar = FeatureBar(self.detect)
        self.feature_bar.features_changed.connect(self.update_buttons)
        form_layout.addWidget(self.feature_bar)
        form_layout.addWidget(section_title("Training"))
        self.tuning = TuningPanel(TrainParams)
        self.tuning.params_changed.connect(self.update_buttons)
        form_layout.addWidget(self.tuning)
        form_layout.addWidget(section_title("Saved map"))
        self.status_label = QtWidgets.QLabel()
        self.status_label.setWordWrap(True)
        self.status_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.status_label.setStyleSheet(f"color: {palette.text_secondary};")
        form_layout.addWidget(self.status_label)
        buttons = QtWidgets.QHBoxLayout()
        self.save_button = QtWidgets.QPushButton(t("Save and Retrain"))
        self.save_button.setToolTip(t("Save the keys and settings, then rebuild the space."))
        self.save_button.clicked.connect(self.save_and_retrain)
        self.revert_button = QtWidgets.QPushButton(t("Revert"))
        self.revert_button.setToolTip(t("Discard unsaved changes."))
        self.revert_button.clicked.connect(self.revert)
        for button in (self.save_button, self.revert_button):
            buttons.addWidget(button)
        form_layout.addLayout(buttons)
        self.preview_size = file_count_box(PREVIEW_RANGE, PREVIEW_FILES)
        self.preview_size.valueChanged.connect(self.resample)
        form_layout.addLayout(labelled_row("Files on the whole map", self.preview_size, "Number of files on the whole map."))
        self.whole_map_button = QtWidgets.QPushButton(t("Show whole map"))
        self.whole_map_button.setToolTip(t("Show random files of the saved map on the right. It also appears by itself when this tab opens."))
        self.whole_map_button.clicked.connect(self.show_space)
        form_layout.addWidget(self.whole_map_button)
        form_layout.addWidget(section_title("Quick Train"))
        hint = QtWidgets.QLabel(t("Train on random files with the current settings for a rough check. Nothing is saved."))
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {palette.text_muted};")
        form_layout.addWidget(hint)
        self.quick_size = file_count_box(QUICK_TRAIN_RANGE, QUICK_TRAIN_FILES)
        form_layout.addLayout(labelled_row("Files to train on", self.quick_size))
        self.quick_button = QtWidgets.QPushButton(t("Quick Train"))
        self.quick_button.clicked.connect(self.toggle_quick_train)
        form_layout.addWidget(self.quick_button)
        form_layout.addStretch(1)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setWidget(form)
        scroll.setMinimumWidth(dpix(FORM_MIN_WIDTH))
        self.splitter.addWidget(scroll)
        preview = QtWidgets.QWidget()
        preview_layout = QtWidgets.QVBoxLayout(preview)
        preview_layout.setContentsMargins(dpix(6), dpix(6), dpix(6), dpix(6))
        self.toolbar = self.bar = MapToolbar(self.tab, edits_space_groups=True)
        preview_layout.addWidget(self.bar)
        self.map_view = MapView(self)
        self.map_view.setMinimumSize(dpix(MAP_MIN_WIDTH) // 2, dpix(MAP_MIN_WIDTH) // 2)
        preview_layout.addWidget(self.map_view, stretch=1)
        self.splitter.addWidget(preview)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setStretchFactor(1, 3)

    def default_db(self) -> None:
        if self.db_name:
            return
        name = getattr(InstanceRegistry.instance().get_host_window(), "database_name", None) or self.db_box.currentText()
        if not name:
            return
        self.db_name = name
        self.db_box.show_quietly(name)
        self.toolbar.set_db(name)

    def can_open(self, db_name: str) -> bool:
        return bool(db_name) and parser_enabled(db_name)

    def update_access(self) -> bool:
        opened = self.can_open(self.db_name)
        self.content.setCurrentWidget(self.splitter if opened else self.blocked)
        return opened

    def choose_db(self, name: str) -> None:
        if not name or name == self.db_name:
            return
        self.db_name = name
        self.toolbar.set_db(name)
        self.notice = ""
        self.preview_key = None
        if self.update_access():
            self.refresh()

    def connect_indexer_updates(self) -> None:
        from wafer.app.viewer.ipc_bridge import ViewerIpcBridge

        bridge = ViewerIpcBridge.instance()
        if bridge is not None:
            bridge.db_content_updated.connect(self.on_db_updated)

    def on_db_updated(self, db: str) -> None:
        if (db and db != self.db_name) or not self.isVisible() or self.status_timer.isActive():
            return
        self.status_timer.start()

    def refresh_status(self) -> None:
        if not self.db_name:
            return
        db_name = self.db_name
        cancel = self.status_cancel.renew()

        def task():
            try:
                snapshot = read_space_status(db_name)
            except Exception as e:
                AppLogger.warning(f"[Mapping] Reading the space status of {db_name} failed", exc=e)
                return
            self.dispatcher.invoke(lambda: cancel.is_cancelled() or db_name != self.db_name or self.on_status(snapshot))

        self.dispatcher.post(task, priority=LOAD_PRIORITY, cancel=cancel)

    def on_status(self, snapshot: SpaceSnapshot) -> None:
        self.apply_status(snapshot)
        if self.preview_outdated(snapshot):
            self.refresh()

    def preview_outdated(self, snapshot: SpaceSnapshot) -> bool:
        if self.showing_quick or self.preview_loading:
            return False
        return (snapshot.status.state, snapshot.status.version) != self.preview_mark

    def apply_status(self, snapshot: SpaceSnapshot) -> None:
        self.status, self.total, self.placed, self.waiting = snapshot.status, snapshot.total, snapshot.placed, snapshot.waiting
        self.model_bytes = snapshot.model_bytes
        self.render_status()

    def selected_paths(self) -> list[str]:
        if self.shown is None:
            return []
        return [self.shown.paths[row] for row in self.map_view.selected_rows()]

    def select_all(self) -> None:
        if self.shown is not None:
            self.map_view.select_rows(range(len(self.shown.paths)))

    def map_thumbnails(self, paths: list[str], size: float) -> list[QtGui.QPixmap | None]:
        return self.host.map_thumbnails(paths, size)

    def show_hover(self, path: str, global_pos: QtCore.QPoint) -> None:
        self.host.show_hover(path, global_pos)

    def hide_hover(self) -> None:
        self.host.hide_hover()

    def context_for_selection(self) -> dict:
        return {**self.host.context_for(self.selected_paths()), "map_panel": self}

    def handle_drag_enter(self, event) -> None:
        if self.on_drop is not None and local_file_paths(event.mimeData()):
            event.setDropAction(Qt.CopyAction)
            event.accept()
        else:
            event.ignore()

    def handle_drop(self, event) -> None:
        if self.on_drop is None:
            event.ignore()
            return
        self.on_drop(event)

    def dragEnterEvent(self, event):
        self.handle_drag_enter(event)

    def dragMoveEvent(self, event):
        self.handle_drag_enter(event)

    def dropEvent(self, event):
        self.handle_drop(event)

    def on_grouping_changed(self, db_name: str) -> None:
        if db_name == self.db_name:
            self.regroup()

    def on_view_settings(self, changed: frozenset[str]) -> None:
        self.settings.apply(self.map_view, self.host)
        if changed & RELAYOUT_PARAMS:
            self.regroup()

    def regroup(self) -> None:
        if self.showing_quick:
            self.regroup_quick_train()
        elif self.preview_layout is not None and not self.preview_loading:
            self.relayout_preview(self.preview_layout)
        else:
            self.refresh()

    def relayout_preview(self, layout: SpaceLayout) -> None:
        cancel = self.refresh_cancel.renew()
        db_name, view = self.db_name, self.settings.params

        self.map_view.set_caption(t("Grouping") + ELLIPSIS)

        def task():
            result, problem = run_preview(layout, view, db_name, cancelled=cancel.is_cancelled)
            if result is None and not problem:
                return
            self.dispatcher.invoke(lambda: cancel.is_cancelled() or self.showing_quick or self.quick_running or self.show_space_result(result, problem))

        self.dispatcher.post(task, priority=LOAD_PRIORITY, cancel=cancel)

    def detect(self, key: str) -> str:
        if self.db_name:
            self.detect_later(self.db_name, key)
        return PROVISIONAL_ENCODER

    def detect_later(self, db_name: str, key: str) -> None:
        previous = self.detecting.get(key)
        if previous is not None:
            previous.cancel()
        cancel = self.detecting[key] = CancelToken()
        self.update_buttons()

        def task():
            try:
                encoder = detect_key_encoder(db_name, key)
            except Exception as e:
                AppLogger.warning(f"[Mapping] Detecting how to compare {key} in {db_name} failed; using {PROVISIONAL_ENCODER}", exc=e)
                encoder = None
            self.dispatcher.invoke(lambda: cancel.is_cancelled() or self.on_detected(db_name, key, encoder, cancel))

        self.dispatcher.post(task, priority=LOAD_PRIORITY, cancel=cancel)

    def on_detected(self, db_name: str, key: str, encoder: str | None, cancel: CancelToken) -> None:
        if self.detecting.get(key) is cancel:
            del self.detecting[key]
        if encoder is not None and db_name == self.db_name:
            self.feature_bar.set_encoder(key, encoder)
        self.update_buttons()

    def apply_preset(self, preset: Preset) -> None:
        self.saved = preset
        self.feature_bar.set_features(list(preset.features))
        self.tuning.set_params(preset.params)
        self.update_buttons()

    def is_dirty(self) -> bool:
        if [f.to_dict() for f in self.feature_bar.features()] != [f.to_dict() for f in self.saved.features]:
            return True
        return self.tuning.params() != self.saved.params

    def update_buttons(self) -> None:
        ready = bool(self.db_name) and bool(self.feature_bar.features()) and not self.detecting
        self.save_button.setEnabled(ready)
        self.quick_button.setEnabled(ready or self.quick_running)
        self.quick_button.setText(t("Cancel") if self.quick_running else t("Quick Train"))
        self.revert_button.setEnabled(self.is_dirty())

    def revert(self) -> None:
        self.apply_preset(self.saved)

    def save_and_retrain(self) -> None:
        db_name = self.db_name
        features = self.feature_bar.features()
        if not db_name or not features:
            return
        preset = Preset(features, self.tuning.params(), self.saved.version + 1)
        try:
            save_preset(db_name, preset)
        except Exception as e:
            AppLogger.error(f"[Mapping] Saving the space settings for {db_name} failed", exc=e)
            self.notice = t("Could not save the settings. See the log for details.")
            self.render_status()
            return
        self.apply_preset(preset)
        self.status = SpaceStatus("training", preset.version)
        if Recollect.reset(collector=OUTPUT_PREFIX, db_scope=db_name) == 0:
            AppLogger.warning(f"[Mapping] Saved space preset v{preset.version} for {db_name}, but no indexer received the retraining request; save again to retry")
            self.notice = t("Could not reach the indexer; try again.")
        else:
            AppLogger.info(f"[Mapping] Saved space preset v{preset.version} for {db_name} and requested retraining")
            self.notice = ""
        self.render_status()
        self.show_space()

    def toggle_quick_train(self) -> None:
        if self.quick_running:
            self.quick_cancel.cancel()
            self.finish_quick_train(t("Cancelled"))
            return
        features = self.feature_bar.features()
        if not self.db_name or not features:
            return
        db_name, size, view = self.db_name, self.quick_size.value(), self.settings.params
        preset = Preset(features, self.tuning.params(), 0)
        grouping = GroupingStore.instance().get(db_name)
        keys = frozenset(preset.value_keys())
        reusable = self.quick_sample if self.quick_sample is not None and self.quick_sample.covers(db_name, size, keys) else None
        cancel = self.quick_cancel.renew()
        self.quick_running = True
        self.update_buttons()
        self.map_view.set_caption(t("Picking {count} files", count=f"{size:,}") + ELLIPSIS)

        def progress(stage):
            text = t(STAGE_NAMES.get(stage, stage)) + ELLIPSIS
            self.dispatcher.invoke(lambda: cancel.is_cancelled() or self.map_view.set_caption(text))

        def task():
            try:
                sample = reusable or read_quick_train_sample(db_name, size, keys)
                layout = SpaceModel.fit(preset, sample.values, cancelled=cancel.is_cancelled, progress=progress).layout(sample.values)
                progress("cluster")
                result = layout.run(view, grouping=grouping, cancelled=cancel.is_cancelled)
            except MapError as e:
                self.dispatcher.invoke(lambda m=str(e): cancel.is_cancelled() or self.finish_quick_train(t(m)))
                return
            except Exception as e:
                AppLogger.error(f"[Mapping] Quick training on {db_name} failed", exc=e)
                self.dispatcher.invoke(lambda: cancel.is_cancelled() or self.finish_quick_train(t("Mapping failed. See the log for details.")))
                return
            if result is not None:
                self.dispatcher.invoke(lambda: cancel.is_cancelled() or self.apply_quick_train(sample, layout, result))

        self.dispatcher.post(task, priority=LOAD_PRIORITY, cancel=cancel)

    def regroup_quick_train(self) -> None:
        sample, layout = self.quick_sample, self.quick_layout
        if sample is None or layout is None:
            return
        cancel = self.quick_cancel.renew()
        view = self.settings.params
        self.map_view.set_caption(t("Grouping") + ELLIPSIS)

        def task():
            result, problem = run_preview(layout, view, sample.db_name, cancelled=cancel.is_cancelled)
            if result is None and not problem:
                return
            self.dispatcher.invoke(lambda: cancel.is_cancelled() or not self.showing_quick or self.show_quick_train(sample, result, problem))

        self.dispatcher.post(task, priority=LOAD_PRIORITY, cancel=cancel)

    def finish_quick_train(self, message: str) -> None:
        self.quick_running = False
        self.update_buttons()
        self.map_view.set_caption(message)

    def apply_quick_train(self, sample: QuickTrainSample, layout: SpaceLayout, result: MapResult) -> None:
        self.quick_sample, self.quick_layout = sample, layout
        self.quick_running = False
        self.update_buttons()
        if sample.db_name != self.db_name:
            return
        self.showing_quick = True
        self.show_quick_train(sample, result, "")

    def show_quick_train(self, sample: QuickTrainSample, result: MapResult | None, problem: str) -> None:
        if result is None:
            self.map_view.set_caption(t(problem))
            return
        self.show_preview(result, sample.sources, t("Quick train: {count} files (not saved)", count=f"{len(result.paths):,}"))

    def show_space(self) -> None:
        self.quick_cancel.cancel()
        if self.quick_running:
            self.quick_running = False
            self.update_buttons()
        self.showing_quick = False
        self.refresh()

    def render_status(self) -> None:
        text = status_text(self.status, self.total, self.placed, self.waiting, self.model_bytes)
        if self.db_name and self.notice:
            text += "\n" + self.notice
        self.status_label.setText(text if self.db_name else t("No database is open."))

    @qt_debounce(RESAMPLE_DELAY_MS)
    def resample(self, *_) -> None:
        self.refresh()

    def refresh(self) -> None:
        self.update_buttons()
        if not self.db_name:
            self.render_status()
            return
        if not self.update_access():
            return
        db_name = self.db_name
        if self.keys_db != db_name:
            self.load_keys(db_name)
        if self.quick_sample is not None and self.quick_sample.db_name != db_name:
            self.quick_sample, self.quick_layout, self.showing_quick = None, None, False
        cancel = self.refresh_cancel.renew()
        params, size = self.settings.params, self.preview_size.value()
        self.preview_key = (db_name, size)
        self.preview_loading = True
        if not self.showing_quick and not self.quick_running:
            self.map_view.set_caption(t("Loading values") + ELLIPSIS)

        def task():
            try:
                snapshot = read_snapshot(db_name, params, size)
            except Exception as e:
                AppLogger.error(f"[Mapping] Reading the space state of {db_name} failed", exc=e)
                self.dispatcher.invoke(lambda: cancel.is_cancelled() or self.preview_failed())
                return
            self.dispatcher.invoke(lambda: cancel.is_cancelled() or self.apply_snapshot(snapshot))
            if snapshot.layout is None or snapshot.result is None or cancel.is_cancelled():
                return
            result, problem = run_preview(snapshot.layout, params, db_name)
            self.dispatcher.invoke(lambda: cancel.is_cancelled() or self.showing_quick or self.quick_running or self.preview_layout is not snapshot.layout or self.show_space_result(result, problem))

        self.dispatcher.post(task, priority=LOAD_PRIORITY, cancel=cancel)

    def load_keys(self, db_name: str) -> None:
        self.keys_db = db_name
        cancel = self.keys_cancel.renew()

        def task():
            try:
                keys = read_key_catalog(db_name)
            except Exception as e:
                AppLogger.error(f"[Mapping] Reading the key list of {db_name} failed", exc=e)
                self.dispatcher.invoke(lambda: cancel.is_cancelled() or setattr(self, "keys_db", None))
                return
            self.dispatcher.invoke(lambda: cancel.is_cancelled() or self.feature_bar.set_keys(keys))

        self.dispatcher.post(task, priority=LOAD_PRIORITY, cancel=cancel)

    def preview_failed(self) -> None:
        self.preview_loading = False
        if not self.showing_quick and not self.quick_running:
            self.map_view.set_caption(t("Mapping failed. See the log for details."))

    def apply_snapshot(self, snapshot: SpaceSnapshot) -> None:
        dirty = self.is_dirty()
        if dirty:
            self.saved = snapshot.preset
        else:
            self.apply_preset(snapshot.preset)
        self.apply_status(snapshot)
        self.update_buttons()
        self.preview_loading = False
        self.preview_mark = (snapshot.status.state, snapshot.status.version)
        self.preview_layout, self.preview_sources = snapshot.layout, snapshot.sources
        if self.showing_quick or self.quick_running:
            return
        self.show_space_result(snapshot.result, snapshot.problem)

    def show_space_result(self, result: MapResult | None, problem: str) -> None:
        if result is None:
            self.clear_preview()
            self.map_view.set_caption(t(problem) if problem else t("Nothing to preview yet."))
            return
        placed = len(result.paths) - result.diagnostics.unset
        self.show_preview(result, self.preview_sources, t("Whole map: {count} files", count=f"{placed:,}"))

    def clear_preview(self) -> None:
        self.shown = None
        self.host.clear()
        self.map_view.clear_map()

    def show_preview(self, result: MapResult, sources: dict[str, str], caption: str) -> None:
        self.host.sources = sources
        colors = result_colors(result, self.palette_colors)
        if same_layout(self.shown, result):
            self.map_view.set_groups(result, colors)
        else:
            keep_view = self.shown is not None and self.shown.paths == result.paths
            self.settings.apply(self.map_view, self.host)
            self.tab.apply(self.map_view)
            self.map_view.show_result(result, colors, keep_view)
        self.shown = result
        self.map_view.set_caption(caption)

    def showEvent(self, event: QtGui.QShowEvent) -> None:
        super().showEvent(event)
        self.default_db()
        if not self.update_access():
            return
        if self.preview_key is not None and self.preview_key == (self.db_name, self.preview_size.value()):
            self.refresh_status()
        else:
            self.refresh()

    def hideEvent(self, event: QtGui.QHideEvent) -> None:
        self.status_timer.stop()
        self.host.hide_hover()
        super().hideEvent(event)

    def save_state(self) -> dict[str, Any]:
        return {
            "splitter": bytes(self.splitter.saveState().toHex()).decode("ascii"),
            "quick_train_files": self.quick_size.value(),
            "preview_files": self.preview_size.value(),
            "toolbar": self.tab.to_dict(),
        }

    def restore_state(self, state: dict[str, Any]) -> None:
        toolbar = state.get("toolbar")
        if isinstance(toolbar, dict):
            self.tab.load(toolbar)
        splitter = state.get("splitter")
        if isinstance(splitter, str) and splitter:
            self.splitter.restoreState(QtCore.QByteArray.fromHex(splitter.encode("ascii")))
        files = state.get("quick_train_files")
        if isinstance(files, int):
            self.quick_size.setValue(files)
        preview = state.get("preview_files")
        if isinstance(preview, int):
            self.preview_size.blockSignals(True)
            self.preview_size.setValue(preview)
            self.preview_size.blockSignals(False)
