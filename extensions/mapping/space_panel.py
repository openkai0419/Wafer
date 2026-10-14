from __future__ import annotations

import os
from contextlib import closing
from dataclasses import dataclass, field
from functools import partial
from typing import Any

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from wafer.core.common.paths import data_db_path, safe_getsize, setting_db_path
from wafer.core.db.db_utils import open_readonly
from wafer.core.db.path_values import PathValue, fetch_path_values, fetch_sources
from wafer.core.db.query import STANDARD_KEYS, SYSTEM_FILE_HASH_KEY, FileSearchEngine
from wafer.core.db.recollect import Recollect
from wafer.core.db.setting_db import SettingDB
from wafer.core.lang.manager import t
from wafer.core.logs import AppLogger
from wafer.plugin import BasePanelPlugin
from wafer.plugin.query.composer import SearchComposer
from wafer.plugin.settings import PluginSettings
from wafer.qt.commands.binding.instance_registry import InstanceRegistry
from wafer.qt.common.dispatcher import CancelSlot, CancelToken, Dispatcher
from wafer.qt.common.dpi import dpix
from wafer.qt.common.thread import utility_pool
from wafer.qt.theme import ThemeManager

from .encoders import detect_encoder, value_input
from .feature_bar import FeatureBar
from .map_host import MapHost
from .map_view import MapView
from .params import MapParams
from .session import OUTPUT_PREFIX, SPACE_KEYS, MapError, MapResult, layout_from_space
from .space import Preset, SpaceStatus, load_preset, model_dir, read_status, save_preset
from .tuning import TuningPanel
from .widget import cancel_work, result_colors

LOAD_PRIORITY = 7
PREVIEW_SAMPLE = 5000
DETECT_SAMPLE = 300
RETRAIN_RATIO = 0.2
MEGABYTE = 1024 * 1024
TUNING_STAGES = ("encode", "reduce", "layout")
MODEL_KEY = SPACE_KEYS[2]
ELLIPSIS = "\N{HORIZONTAL ELLIPSIS}"
SEPARATOR = "\N{MIDDLE DOT}"
PROVISIONAL_ENCODER = "text"
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
    parser_enabled: bool = True
    result: MapResult | None = None
    sources: dict[str, str] = field(default_factory=dict)
    problem: str = ""


def read_snapshot(db_name: str) -> SpaceSnapshot:
    preset = load_preset(db_name) or Preset([], MapParams(), 0)
    directory = model_dir(db_name)
    status = current_status(read_status(directory), preset.version)
    snapshot = SpaceSnapshot(preset, status, parser_enabled=parser_enabled(db_name))
    snapshot.model_bytes = sum(safe_getsize(path) or 0 for path in directory.glob(f"model-v{preset.version}.*"))
    db_path = data_db_path(db_name)
    if not os.path.isfile(db_path):
        return snapshot
    sample: list[str] = []
    with closing(open_readonly(db_path)) as conn:
        snapshot.total = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        snapshot.waiting = conn.execute(WAITING_SQL, (OUTPUT_PREFIX,)).fetchone()[0]
        if preset.version and preset.features:
            version = str(preset.version)
            snapshot.placed = conn.execute("SELECT COUNT(*) FROM meta_info WHERE key = ? AND value = ?", (MODEL_KEY, version)).fetchone()[0]
            sample = [row[0] for row in conn.execute("SELECT path FROM meta_info WHERE key = ? AND value = ? ORDER BY RANDOM() LIMIT ?", (MODEL_KEY, version, PREVIEW_SAMPLE))]
    if not sample:
        return snapshot
    values = fetch_path_values(db_path, sample, keys=[*preset.value_keys(), *SPACE_KEYS])
    snapshot.sources = fetch_sources(db_path, sample)
    try:
        snapshot.result = layout_from_space(sample, values, preset, MapParams(), grouping=True)
    except MapError as e:
        snapshot.problem = str(e)
    except Exception as e:
        AppLogger.warning(f"[Mapping] Laying out the Mapping Space preview of {db_name} failed", exc=e)
        snapshot.problem = str(e) or type(e).__name__
    return snapshot


def read_key_catalog(db_name: str) -> list[tuple[str, int]]:
    engine = FileSearchEngine(data_db_path(db_name))
    try:
        results = SearchComposer().list_all_keys(engine, [], sort_by_freq=True)
    finally:
        engine.close()
    return [(key, count) for key, count in results if key not in SPACE_KEYS]


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


class PreviewOwner:
    def __init__(self, host: MapHost, selected_paths):
        self.host = host
        self.selected_paths = selected_paths

    def thumbnail(self, path: str) -> QtGui.QPixmap | None:
        return self.host.thumbnail(path)

    def show_hover(self, path: str, global_pos: QtCore.QPoint) -> None:
        self.host.show_hover(path, global_pos)

    def hide_hover(self) -> None:
        self.host.hide_hover()

    def context_for_selection(self) -> dict:
        return self.host.context_for(self.selected_paths())

    def handle_drag_enter(self, event) -> None:
        event.ignore()

    def handle_drop(self, event) -> None:
        event.ignore()


class MappingSpaceWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        InstanceRegistry.instance().register("MappingSpaceWidget", self)
        self.palette_colors = ThemeManager.instance().palette
        self.dispatcher = Dispatcher(pool=utility_pool, parent=self)
        self.refresh_cancel = CancelSlot()
        self.keys_cancel = CancelSlot()
        self.db_name = ""
        self.keys_db: str | None = None
        self.saved = Preset([], MapParams(), 0)
        self.status = SpaceStatus("none", 0)
        self.total = 0
        self.placed = 0
        self.waiting = 0
        self.model_bytes = 0
        self.parser_on = True
        self.notice = ""
        self.detecting: dict[str, CancelToken] = {}
        self.shown: MapResult | None = None
        self.host = MapHost(self)
        self.build_ui()
        self.host.views = [self.map_view]
        self.sync_host()
        self.update_buttons()
        self.destroyed.connect(partial(cancel_work, self.refresh_cancel, self.keys_cancel))
        self.destroyed.connect(partial(cancel_tokens, self.detecting))

    @classmethod
    def instance(cls) -> MappingSpaceWidget | None:
        return InstanceRegistry.instance().get_one("MappingSpaceWidget")

    def build_ui(self):
        palette = self.palette_colors
        root = QtWidgets.QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.splitter = QtWidgets.QSplitter(Qt.Horizontal)
        root.addWidget(self.splitter)
        form = QtWidgets.QWidget()
        form_layout = QtWidgets.QVBoxLayout(form)
        form_layout.setContentsMargins(dpix(8), dpix(8), dpix(8), dpix(8))
        self.feature_bar = FeatureBar(self.detect)
        self.feature_bar.features_changed.connect(self.update_buttons)
        form_layout.addWidget(self.feature_bar)
        self.tuning = TuningPanel(stages=TUNING_STAGES)
        self.tuning.params_changed.connect(self.update_buttons)
        form_layout.addWidget(self.tuning)
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
        self.refresh_button = QtWidgets.QPushButton(t("Refresh"))
        self.refresh_button.clicked.connect(self.refresh)
        for button in (self.save_button, self.revert_button, self.refresh_button):
            buttons.addWidget(button)
        form_layout.addLayout(buttons)
        form_layout.addStretch(1)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setWidget(form)
        self.splitter.addWidget(scroll)
        preview = QtWidgets.QWidget()
        preview_layout = QtWidgets.QVBoxLayout(preview)
        preview_layout.setContentsMargins(dpix(6), dpix(6), dpix(6), dpix(6))
        self.count_label = QtWidgets.QLabel()
        self.count_label.setStyleSheet(f"color: {palette.text_secondary};")
        preview_layout.addWidget(self.count_label)
        self.map_view = MapView(PreviewOwner(self.host, self.selected_paths))
        preview_layout.addWidget(self.map_view, stretch=1)
        self.splitter.addWidget(preview)
        self.splitter.setStretchFactor(1, 3)

    def sync_host(self) -> None:
        host = InstanceRegistry.instance().get_host_window()
        name = getattr(host, "database_name", None)
        if name:
            self.db_name = name

    def selected_paths(self) -> list[str]:
        if self.shown is None:
            return []
        return [self.shown.paths[row] for row in self.map_view.selected_rows()]

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
        edited = self.tuning.params()
        return any(edited.values_for(stage) != self.saved.params.values_for(stage) for stage in TUNING_STAGES)

    def update_buttons(self) -> None:
        self.save_button.setEnabled(bool(self.db_name) and bool(self.feature_bar.features()) and not self.detecting)
        self.revert_button.setEnabled(self.is_dirty())

    def revert(self) -> None:
        self.apply_preset(self.saved)

    def save_and_retrain(self) -> None:
        db_name = self.db_name
        self.sync_host()
        if self.db_name != db_name:
            AppLogger.info(f"[Mapping] The open database changed from {db_name} to {self.db_name}; reloading Mapping Space without saving")
            self.refresh()
            return
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
        self.refresh()

    def render_status(self) -> None:
        text = status_text(self.status, self.total, self.placed, self.waiting, self.model_bytes)
        if self.db_name and not self.parser_on:
            text += "\n" + t("Enable the Mapping parser for this database in Plugin Manager.")
        if self.db_name and self.notice:
            text += "\n" + self.notice
        self.status_label.setText(text if self.db_name else t("No database is open."))

    def refresh(self) -> None:
        self.sync_host()
        self.update_buttons()
        if not self.db_name:
            self.render_status()
            return
        db_name = self.db_name
        if self.keys_db != db_name:
            self.load_keys(db_name)
        cancel = self.refresh_cancel.renew()
        self.count_label.setText(t("Loading values") + ELLIPSIS)

        def task():
            try:
                snapshot = read_snapshot(db_name)
            except Exception as e:
                AppLogger.error(f"[Mapping] Reading the space state of {db_name} failed", exc=e)
                self.dispatcher.invoke(lambda: cancel.is_cancelled() or self.count_label.setText(t("Mapping failed. See the log for details.")))
                return
            self.dispatcher.invoke(lambda: cancel.is_cancelled() or self.apply_snapshot(snapshot))

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

    def apply_snapshot(self, snapshot: SpaceSnapshot) -> None:
        dirty = self.is_dirty()
        if dirty:
            self.saved = snapshot.preset
        else:
            self.apply_preset(snapshot.preset)
        self.status, self.total, self.placed, self.waiting = snapshot.status, snapshot.total, snapshot.placed, snapshot.waiting
        self.model_bytes, self.parser_on = snapshot.model_bytes, snapshot.parser_enabled
        self.render_status()
        self.update_buttons()
        if snapshot.result is None:
            self.clear_preview()
            self.count_label.setText(t(snapshot.problem) if snapshot.problem else t("Nothing to preview yet."))
            return
        self.show_preview(snapshot.result, snapshot.sources)

    def clear_preview(self) -> None:
        self.shown = None
        self.host.clear()
        self.map_view.clear_map()

    def show_preview(self, result: MapResult, sources: dict[str, str]) -> None:
        params = MapParams()
        self.host.sources = sources
        self.host.set_display_size(self.map_view.display_size())
        self.host.set_hover_size(params.hover_size)
        keep_view = self.shown is not None and self.shown.paths == result.paths
        self.map_view.set_thumbnail_zoom(params.thumbnail_zoom)
        self.map_view.show_result(result, result_colors(result, self.palette_colors), True, keep_view)
        self.shown = result
        placed = len(result.paths) - result.diagnostics.unset
        self.count_label.setText(t("Preview: {count} files", count=f"{placed:,}"))

    def showEvent(self, event: QtGui.QShowEvent) -> None:
        super().showEvent(event)
        self.refresh()

    def hideEvent(self, event: QtGui.QHideEvent) -> None:
        self.host.hide_hover()
        super().hideEvent(event)

    def save_state(self) -> dict[str, Any]:
        return {"splitter": bytes(self.splitter.saveState().toHex()).decode("ascii")}

    def restore_state(self, state: dict[str, Any]) -> None:
        splitter = state.get("splitter")
        if isinstance(splitter, str) and splitter:
            self.splitter.restoreState(QtCore.QByteArray.fromHex(splitter.encode("ascii")))


class MappingSpacePlugin(BasePanelPlugin):
    NAME = "mapping_space"
    DISPLAY_NAME = "Mapping Space"
    PRIORITY = 0
    DEFAULT_ENABLED = True
    STANDALONE_AVAILABLE = True
    STANDALONE_SIZE = (1100, 700)
    saved_state: dict[str, Any] = {}

    def save_ui_state(self) -> dict[str, Any]:
        widget = MappingSpaceWidget.instance()
        if widget is not None:
            try:
                MappingSpacePlugin.saved_state = widget.save_state()
            except RuntimeError as e:
                AppLogger.warning("[Mapping] Saving the Mapping Space panel state failed", exc=e)
        return dict(MappingSpacePlugin.saved_state)

    def restore_ui_state(self, state: dict[str, Any]) -> None:
        MappingSpacePlugin.saved_state = dict(state or {})
        widget = MappingSpaceWidget.instance()
        if widget is not None:
            widget.restore_state(MappingSpacePlugin.saved_state)

    def create_widget(self):
        widget = MappingSpaceWidget()
        widget.restore_state(MappingSpacePlugin.saved_state)
        return widget
