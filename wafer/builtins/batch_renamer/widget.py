from __future__ import annotations

import collections
import os
from pathlib import Path
from typing import Any

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from ..rename_sources import ExtSource, NameSource
from ...core.color.theme import ThemeManager
from ...core.qt.icon_engine import themed_icon
from ...core.platform.file_operations import PastePlanItem
from ...core.platform.paste import execute_paste_plans_with_ui
from ...core.qt.dispatcher import Dispatcher, CancelToken
from ...core.qt.rate_limit import qt_throttle
from ...core.qt.thread import utility_pool
from ...utils.formatting import dpix, natural_key
from ...utils.logs import AppLogger
from ...utils.paths import safe_is_file
from .engine import RenameColumn, RenameEngine, RenameResult
from .overlay import ThumbnailOverlay
from .popup import ColumnSettingsPopup
from .table import (
    PreviewModel,
    SegmentModel,
    PreviewDelegate,
    SyncedView,
    ColorSet,
)
from ...plugin.rename.handler import rename_source_registry
from ...plugin.panel.base import BasePanelPlugin
from ...core.lang.manager import t
from ...core.commands.bridge import ActionKit, Context, Menu


_SQL_CHUNK_SIZE = 4000


def _fetch_metadata_sync(db_path, paths_str):
    import sqlite3

    result: dict[str, dict[str, str]] = {}
    if not db_path or not os.path.isfile(str(db_path)):
        return result
    try:
        uri = Path(db_path).resolve().as_uri()
        conn = sqlite3.connect(f"{uri}?mode=ro", uri=True, timeout=1.0)
        try:
            for start in range(0, len(paths_str), _SQL_CHUNK_SIZE):
                chunk = paths_str[start : start + _SQL_CHUNK_SIZE]
                placeholders = ",".join("?" * len(chunk))
                rows = conn.execute(
                    f"SELECT path, key, value FROM meta_info WHERE path IN ({placeholders})",
                    chunk,
                ).fetchall()
                for path, key, value in rows:
                    result.setdefault(path, {})[key] = value or ""
                rows = conn.execute(
                    f"SELECT i.path, t.key, t.value FROM tags AS t JOIN sources AS s ON s.file_hash = t.file_hash JOIN files AS i ON i.source = s.source WHERE i.path IN ({placeholders})",
                    chunk,
                ).fetchall()
                for path, key, value in rows:
                    result.setdefault(path, {})[key] = value or ""
                rows = conn.execute(
                    f"""SELECT i.path, i.name, s.size, s.modified, s.created, s.collected
                    FROM files AS i JOIN sources AS s ON s.source = i.source
                    WHERE i.path IN ({placeholders})""",
                    chunk,
                ).fetchall()
                for path, name, size, modified, created, collected in rows:
                    entry = result.setdefault(path, {})
                    entry["path"] = path or ""
                    if name is not None:
                        entry["name"] = str(name)
                    for key, value in (
                        ("size", size),
                        ("modified", modified),
                        ("created", created),
                        ("collected", collected),
                    ):
                        if value is not None:
                            entry[key] = str(value)
        finally:
            conn.close()
    except Exception as e:
        AppLogger.warning("Failed to fetch metadata for rename", exc=e)
    return result


def _fill_fs_timestamps(paths, keys, metadata):
    _TS_KEYS = ("modified", "created")
    for path, key in zip(paths, keys):
        entry = metadata.get(key)
        if entry and all(k in entry for k in _TS_KEYS):
            continue
        try:
            st = os.stat(path)
        except OSError:
            continue
        d = metadata.setdefault(key, {})
        if "modified" not in d:
            d["modified"] = str(st.st_mtime)
        if "created" not in d:
            d["created"] = str(st.st_ctime)


class BatchRenameWidget(QtWidgets.QWidget):
    _ADD_COL_LABEL = "+"
    THUMB_CACHE_LIMIT = 200
    DEFAULT_SORT_INDICATOR = ("segment", 0, True)
    THUMB_FIT_COVER = "cover"
    THUMB_FIT_CONTAIN = "contain"
    THUMB_FIT_MODES = {THUMB_FIT_COVER, THUMB_FIT_CONTAIN}
    _saved_state: dict[str, Any] = {}
    _instance_ref: BatchRenameWidget | None = None

    def __init__(self, parent=None):
        super().__init__(parent)
        BatchRenameWidget._instance_ref = self

        self._dispatcher = Dispatcher(pool=utility_pool)
        self._init_cancel: CancelToken | None = None
        self._thumb_tokens: dict[int, CancelToken] = {}
        self._thumb_visible: set[int] = set()

        self._paths: list[Path] = []
        self._keys: list[str] = []
        self._initial_keys: list[str] = []
        self._initial_paths: list[Path] = []
        self._db_path: Any = None
        self._metadata: dict[str, dict[str, str]] = {}

        self._columns: list[RenameColumn] = [RenameColumn(NameSource())]
        self._ext_column = RenameColumn(ExtSource())
        self._source_defaults: dict[str, dict] = {}
        self._restore_source_defaults()
        self._results: list[RenameResult] = []
        self._global_errors: list[str] = []
        self._popup: ColumnSettingsPopup | None = None
        self._popup_request_id = 0
        self._syncing = False
        self._syncing_selection = False
        self._refreshing = False
        self._refresh_cancel: CancelToken | None = None
        self._pending_rebuild_callback = None
        self._pending_refresh_callback = None
        self._pending_apply_callback = None
        self._pending_update_scheduled = False
        self._selected_row = -1
        self._thumb_cache: collections.OrderedDict[str, QtGui.QPixmap] = collections.OrderedDict()
        self._sort_indicator: tuple[str, int, bool] | None = None
        self._row_thumb_fit_mode = self.THUMB_FIT_COVER
        self._sel_thumb_fit_mode = self.THUMB_FIT_COVER

        p = ThemeManager.instance().palette
        self._p = p

        self._mono = QtGui.QFont("Consolas")
        self._mono.setStyleHint(QtGui.QFont.Monospace)
        self._mono.setPixelSize(dpix(12))

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._stack = QtWidgets.QStackedWidget()
        root.addWidget(self._stack)

        self._empty_page = self._build_empty_page(p)
        self._stack.addWidget(self._empty_page)

        self._rename_page = QtWidgets.QWidget()
        self._rename_page.setStyleSheet(f"background: {p.bg_primary};")
        rename_lay = QtWidgets.QVBoxLayout(self._rename_page)
        rename_lay.setContentsMargins(dpix(8), dpix(8), dpix(8), dpix(8))
        rename_lay.setSpacing(dpix(6))

        title = QtWidgets.QLabel(self._title_text())
        self._title = title
        title.setStyleSheet(f"color: {p.text_primary}; font-size: {dpix(13)}px; font-weight: bold;")
        rename_lay.addWidget(title)

        self._init_preview_table(rename_lay)
        self._init_segment_table(rename_lay)
        self._init_bottom_bar(rename_lay)

        self._stack.addWidget(self._rename_page)
        self._stack.setCurrentWidget(self._empty_page)

        self.setAcceptDrops(True)

    def dragEnterEvent(self, event: QtGui.QDragEnterEvent):
        mime = event.mimeData()
        if mime and mime.hasUrls():
            for url in mime.urls():
                if url.isLocalFile():
                    event.setDropAction(Qt.DropAction.CopyAction)
                    event.accept()
                    return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QtGui.QDragMoveEvent):
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()

    def dropEvent(self, event: QtGui.QDropEvent):
        mime = event.mimeData()
        if not mime or not mime.hasUrls():
            return
        paths = []
        for url in mime.urls():
            if url.isLocalFile():
                p = Path(url.toLocalFile())
                if safe_is_file(p):
                    paths.append(p)
        if not paths:
            return
        event.setDropAction(Qt.DropAction.IgnoreAction)
        event.accept()
        win = self.window()
        db_path = getattr(win, "database_path", None)
        if not self._paths or self._db_path != db_path:
            self.set_files(paths, db_path=db_path)
        else:
            self.add_files(paths)

    def _build_empty_page(self, p):
        page = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(page)
        lay.setAlignment(Qt.AlignCenter)
        msg = QtWidgets.QLabel(t("Select files and run Batch Renamer\nor drop files here"))
        msg.setStyleSheet(f"color: {p.text_muted}; font-size: {dpix(13)}px;")
        msg.setAlignment(Qt.AlignCenter)
        lay.addWidget(msg)
        return page

    def set_files(self, paths: list[Path], keys: list[str] | None = None, db_path: Any = None):
        self._cancel_all_pending()
        self._db_path = db_path
        sorted_paths, sorted_keys = self._sort_input_by_name(list(paths), list(keys) if keys else [str(p).replace("\\", "/") for p in paths])
        self._paths = sorted_paths
        self._keys = sorted_keys
        self._initial_keys = list(self._keys)
        self._initial_paths = list(self._paths)
        self._metadata = {}
        self._thumb_cache.clear()
        self._thumb_visible.clear()
        self._reset_columns()
        self._sort_indicator = self.DEFAULT_SORT_INDICATOR
        self._title.setText(self._title_text())
        self._stack.setCurrentWidget(self._rename_page)
        self._rebuild()
        self._start_async_init()

    def add_files(self, paths: list[Path], keys: list[str] | None = None):
        if not self._paths:
            self.set_files(paths, keys, self._db_path)
            return
        existing = {str(p) for p in self._paths}
        new_paths = [p for p in paths if str(p) not in existing]
        if not new_paths:
            return
        if keys:
            path_to_key = dict(zip(paths, keys))
            new_keys = [path_to_key.get(p, str(p).replace("\\", "/")) for p in new_paths]
        else:
            new_keys = [str(p).replace("\\", "/") for p in new_paths]
        self._paths.extend(new_paths)
        self._keys.extend(new_keys)
        if self._sort_indicator == self.DEFAULT_SORT_INDICATOR:
            self._paths, self._keys = self._sort_input_by_name(self._paths, self._keys)
        self._initial_paths = list(self._paths)
        self._initial_keys = list(self._keys)
        self._title.setText(self._title_text())
        self._rebuild()
        self._start_async_init()

    def reset(self):
        self._cancel_all_pending()
        self._paths.clear()
        self._keys.clear()
        self._initial_paths.clear()
        self._initial_keys.clear()
        self._db_path = None
        self._metadata.clear()
        self._results.clear()
        self._global_errors.clear()
        self._thumb_cache.clear()
        self._thumb_visible.clear()
        self._reset_columns()
        self._close_popup()
        self._stack.setCurrentWidget(self._empty_page)

    def _clear_deferred_updates(self):
        self._pending_rebuild_callback = None
        self._pending_refresh_callback = None
        self._pending_apply_callback = None
        self._pending_update_scheduled = False

    def _cancel_all_pending(self):
        if self._init_cancel:
            self._init_cancel.cancel()
            self._init_cancel = None
        if self._refresh_cancel:
            self._refresh_cancel.cancel()
            self._refresh_cancel = None
        for token in self._thumb_tokens.values():
            token.cancel()
        self._thumb_tokens.clear()
        self._clear_deferred_updates()

    def _frame_stylesheet(self):
        p = self._p
        return f"QFrame {{ background: {p.bg_primary}; border: 1px solid {p.border_default}; border-radius: {dpix(4)}px; }}"

    def _header_stylesheet(self, bg, fg, *, bold=False, border_right=False):
        p = self._p
        borders = f"border-bottom: 1px solid {p.border_default}; "
        if border_right:
            borders = f"border-right: 1px solid {p.border_subtle}; " + borders
        weight = "font-weight: bold; " if bold else ""
        return (
            f"QHeaderView::section {{ background: {bg}; "
            f"color: {fg}; border: none; {borders}"
            f"font-size: {dpix(11)}px; {weight}"
            f"padding: 0 {dpix(4)}px; }}"
            f"QHeaderView::section:hover {{ background: {p.bg_hover}; }}"
        )

    def _init_preview_table(self, root):
        p = self._p
        row_h = dpix(20)

        preview_frame = QtWidgets.QFrame()
        preview_frame.setStyleSheet(self._frame_stylesheet())
        pf_lay = QtWidgets.QVBoxLayout(preview_frame)
        pf_lay.setContentsMargins(0, 0, 0, 0)
        pf_lay.setSpacing(0)

        self._seg_table = SyncedView(parent=self, vertical_tab_navigation=True)
        self._preview = SyncedView(forward_target=self._seg_table, parent=self)

        self._preview_model = PreviewModel(self)
        self._seg_model = SegmentModel(self)
        colors = ColorSet(p, self._mono)
        self._preview_model.set_colors(colors)
        self._seg_model.set_colors(colors)
        self._preview.setModel(self._preview_model)
        self._seg_table.setModel(self._seg_model)

        self._preview.setFont(self._mono)
        self._preview.setShowGrid(False)
        self._preview.verticalHeader().setVisible(False)
        self._preview.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self._preview.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectItems)
        self._preview.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self._preview.setFocusPolicy(Qt.StrongFocus)
        self._preview.verticalHeader().setDefaultSectionSize(row_h)
        self._preview.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._preview.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        ph = self._preview.horizontalHeader()
        ph.setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        ph.setFixedHeight(dpix(22))
        ph.setSectionsClickable(True)
        ph.setHighlightSections(False)
        ph.sectionClicked.connect(self._on_preview_sort)
        ph.setStyleSheet(self._header_stylesheet(p.bg_secondary, p.text_muted))
        self._preview.setStyleSheet(f"QTableView {{ background: {p.bg_primary}; border: none; color: {p.text_primary}; }}QTableView::item {{ padding: 0 {dpix(4)}px; border: none; }}")
        self._preview.setItemDelegate(PreviewDelegate(p.border_subtle, self._preview))
        self._preview.selectionModel().selectionChanged.connect(self._on_preview_selection)
        pf_lay.addWidget(self._preview)
        self._preview_frame = preview_frame
        root.addWidget(preview_frame, stretch=1)

        self._overlay = ThumbnailOverlay(self, self._preview, parent=self._preview.viewport())
        self._preview.viewport().installEventFilter(self)

    def _init_segment_table(self, root):
        p = self._p
        row_h = dpix(20)

        seg_frame = QtWidgets.QFrame()
        seg_frame.setStyleSheet(self._frame_stylesheet())
        sf_lay = QtWidgets.QVBoxLayout(seg_frame)
        sf_lay.setContentsMargins(0, 0, 0, 0)
        sf_lay.setSpacing(0)

        self._seg_table.setFont(self._mono)
        self._seg_table.setShowGrid(True)
        self._seg_table.verticalHeader().setVisible(False)
        self._seg_table.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self._seg_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectItems)
        self._seg_table.setEditTriggers(QtWidgets.QAbstractItemView.DoubleClicked | QtWidgets.QAbstractItemView.EditKeyPressed)
        self._seg_table.setFocusPolicy(Qt.ClickFocus)
        self._seg_table.verticalHeader().setDefaultSectionSize(row_h)
        self._seg_table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._seg_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        sh = self._seg_table.horizontalHeader()
        sh.setFixedHeight(dpix(24))
        sh.setSectionsClickable(True)
        sh.setHighlightSections(False)
        sh.setMinimumSectionSize(dpix(16))
        sh.sectionClicked.connect(self._on_seg_header_click)
        sh.setStyleSheet(
            self._header_stylesheet(
                p.bg_elevated,
                p.text_primary,
                bold=True,
                border_right=True,
            )
        )
        self._seg_table.setStyleSheet(
            f"QTableView {{ background: {p.bg_primary}; "
            f"gridline-color: {p.border_subtle}; border: none; "
            f"color: {p.text_primary}; }}"
            f"QTableView::item {{ padding: 0 {dpix(2)}px; }}"
            f"QTableView::item:selected {{ background: {p.bg_hover}; }}"
        )
        self._seg_frame = seg_frame
        sf_lay.addWidget(self._seg_table)
        root.addWidget(seg_frame, stretch=1)

        self._seg_table.verticalScrollBar().valueChanged.connect(self._sync_from_seg)
        self._preview.verticalScrollBar().valueChanged.connect(self._sync_from_preview)
        self._seg_model.dataChanged.connect(self._on_seg_data_changed)
        self._seg_table.doubleClicked.connect(self._on_seg_dblclick)
        self._seg_table.selectionModel().selectionChanged.connect(self._on_seg_selection)
        self._seg_table.editing_finished.connect(self._schedule_pending_update)
        self._seg_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self._seg_table.customContextMenuRequested.connect(self._on_row_context)
        self._preview.setContextMenuPolicy(Qt.CustomContextMenu)
        self._preview.customContextMenuRequested.connect(self._on_row_context_preview)

    def _init_bottom_bar(self, root):
        p = self._p

        spacing_size = 4
        bar = QtWidgets.QHBoxLayout()
        self._bottom_bar = bar
        bar.setContentsMargins(0, dpix(2), 0, 0)

        self._status = QtWidgets.QLabel()
        self._status.setStyleSheet(f"color: {p.text_muted}; font-size: {dpix(11)}px;")
        self._status.installEventFilter(self)
        bar.addWidget(self._status)
        bar.addSpacing(dpix(spacing_size))

        slider_ss = (
            f"QSlider::groove:horizontal {{ background: {p.bg_hover}; "
            f"height: {dpix(4)}px; border-radius: {dpix(2)}px; }}"
            f"QSlider::handle:horizontal {{ background: {p.text_muted}; "
            f"width: {dpix(10)}px; margin: -{dpix(3)}px 0; "
            f"border-radius: {dpix(5)}px; }}"
        )

        row_fit_btn = self._create_thumb_fit_button("row")
        self._row_thumb_fit_btn = row_fit_btn
        self._apply_thumb_fit_button("row")
        bar.addWidget(row_fit_btn)

        row_slider = QtWidgets.QSlider(Qt.Horizontal)
        row_slider.setRange(0, 100)
        row_slider.setValue(20)
        row_slider.setMinimumWidth(dpix(40))
        row_slider.setToolTip(t("Row thumbnail opacity"))
        row_slider.setStyleSheet(slider_ss)
        row_slider.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        row_slider.valueChanged.connect(self._on_row_opacity_changed)
        self._row_opacity_slider = row_slider
        bar.addWidget(row_slider)
        bar.addSpacing(dpix(spacing_size))

        sel_fit_btn = self._create_thumb_fit_button("sel")
        self._sel_thumb_fit_btn = sel_fit_btn
        self._apply_thumb_fit_button("sel")
        bar.addWidget(sel_fit_btn)

        sel_slider = QtWidgets.QSlider(Qt.Horizontal)
        sel_slider.setRange(0, 100)
        sel_slider.setValue(20)
        sel_slider.setMinimumWidth(dpix(40))
        sel_slider.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        sel_slider.setToolTip(t("Selected thumbnail opacity"))
        sel_slider.setStyleSheet(slider_ss)
        sel_slider.valueChanged.connect(self._on_sel_opacity_changed)
        self._sel_opacity_slider = sel_slider
        bar.addWidget(sel_slider)
        bar.addSpacing(dpix(4))

        self._rename_btn = QtWidgets.QPushButton(t("Rename"))
        self._rename_btn.setStyleSheet(
            f"QPushButton {{ background: {p.accent}; color: {p.accent_text}; "
            f"border: none; border-radius: {dpix(4)}px; "
            f"padding: {dpix(5)}px {dpix(16)}px; font-size: {dpix(12)}px; }}"
            f"QPushButton:hover {{ background: {p.accent}cc; }}"
            f"QPushButton:disabled {{ background: {p.bg_hover}; color: {p.text_muted}; }}"
        )
        self._rename_btn.clicked.connect(self._execute)
        bar.addWidget(self._rename_btn)

        root.addLayout(bar)

    def _create_thumb_fit_button(self, side: str):
        p = self._p
        button = QtWidgets.QToolButton()
        button.setText("")
        button.setCheckable(True)
        button.setIconSize(QtCore.QSize(dpix(14), dpix(14)))
        button.setCursor(Qt.PointingHandCursor)
        button.setStyleSheet(
            f"QToolButton {{ background: {p.bg_secondary}; color: {p.text_primary}; "
            f"border: 1px solid {p.border_default}; border-radius: {dpix(2)}px; }}"
            f"QToolButton:hover {{ background: {p.bg_hover}; }}"
            f"QToolButton:checked {{ background: {p.bg_hover}; border-color: {p.text_accent}; }}"
        )
        button.toggled.connect(lambda checked, s=side: self._set_thumb_fit_mode(s, self.THUMB_FIT_CONTAIN if checked else self.THUMB_FIT_COVER))
        return button

    def _update_source_defaults(self):
        for col in self._columns:
            src_data = col.source.serialise()
            src_data.pop("overrides", None)
            self._source_defaults[src_data.get("type", col.source.NAME)] = src_data
        ext_data = self._ext_column.source.serialise()
        ext_data.pop("overrides", None)
        self._source_defaults[ext_data.get("type", self._ext_column.source.NAME)] = ext_data

    def _serialise_columns(self) -> dict[str, Any]:
        self._update_source_defaults()
        return {
            "source_defaults": dict(self._source_defaults),
            "row_opacity": self._row_opacity_slider.value(),
            "sel_opacity": self._sel_opacity_slider.value(),
            "row_thumb_fit_mode": self._row_thumb_fit_mode,
            "sel_thumb_fit_mode": self._sel_thumb_fit_mode,
        }

    def _restore_source_defaults(self):
        state = self._saved_state
        if not state:
            return
        self._source_defaults = dict(state.get("source_defaults", {}))

    def _restore_ui_from_state(self):
        state = self._saved_state
        if not state:
            return
        if "row_opacity" in state:
            self._row_opacity_slider.setValue(state["row_opacity"])
        if "sel_opacity" in state:
            self._sel_opacity_slider.setValue(state["sel_opacity"])
        if "thumb_fit_mode" in state:
            self._set_thumb_fit_mode("row", state["thumb_fit_mode"])
            self._set_thumb_fit_mode("sel", state["thumb_fit_mode"])
        if "row_thumb_fit_mode" in state:
            self._set_thumb_fit_mode("row", state["row_thumb_fit_mode"])
        if "sel_thumb_fit_mode" in state:
            self._set_thumb_fit_mode("sel", state["sel_thumb_fit_mode"])

    @staticmethod
    def _sort_input_by_name(paths: list[Path], keys: list[str]) -> tuple[list[Path], list[str]]:
        pairs = list(zip(paths, keys))
        pairs.sort(key=lambda item: natural_key(item[0].stem))
        return [p for p, _ in pairs], [k for _, k in pairs]

    def _start_async_init(self):
        cancel = CancelToken()
        self._init_cancel = cancel
        paths = list(self._paths)
        keys = list(self._keys)
        db_path = self._db_path

        def task():
            if cancel.is_cancelled():
                return
            metadata = _fetch_metadata_sync(db_path, keys) if db_path else {}
            if cancel.is_cancelled():
                return
            _fill_fs_timestamps(paths, keys, metadata)
            if cancel.is_cancelled():
                return
            self._dispatcher.invoke(lambda: cancel.is_cancelled() or self._on_data_ready(metadata))

        self._dispatcher.post(task, cancel=cancel)

    def _on_data_ready(self, metadata):
        self._metadata = metadata
        self._refresh()

    def _visible_row_range(self):
        vp = self._preview.viewport()
        first = self._preview.indexAt(vp.rect().topLeft()).row()
        last = self._preview.indexAt(vp.rect().bottomLeft()).row()
        if first < 0:
            first = 0
        total = len(self._paths)
        if last < 0:
            last = total - 1
        buffer = max(last - first + 1, 10)
        start = max(0, first - buffer)
        end = min(total, last + buffer + 1)
        return range(start, end)

    @qt_throttle(50, 150)
    def _update_visible_thumbnails(self):
        try:
            self._preview.viewport()
        except RuntimeError:
            return
        if not self._results:
            return
        new_visible = set(self._visible_row_range())
        leaving = self._thumb_visible - new_visible
        entering = new_visible - self._thumb_visible
        for row in leaving:
            token = self._thumb_tokens.pop(row, None)
            if token:
                token.cancel()
        self._thumb_visible = new_visible
        entering_need_load = [r for r in entering if 0 <= r < len(self._paths) and str(self._paths[r]) not in self._thumb_cache]
        if not entering_need_load:
            return
        visible = self._visible_row_range()
        center = (visible.start + visible.stop) // 2
        entering_need_load.sort(key=lambda r: abs(r - center))
        rows_tokens = []
        for r in entering_need_load:
            old = self._thumb_tokens.pop(r, None)
            if old:
                old.cancel()
            token = CancelToken()
            self._thumb_tokens[r] = token
            rows_tokens.append((r, self._paths[r], token))
        thumb_size = QtCore.QSize(dpix(512), dpix(512))

        def task():
            from ...plugin.grid.handler import load_thumbnail

            for _r, p, tok in rows_tokens:
                if tok.is_cancelled():
                    continue
                key = str(p)
                if key in self._thumb_cache:
                    continue
                try:
                    img = load_thumbnail(key, thumb_size)
                except (OSError, RuntimeError):
                    img = None
                if tok.is_cancelled():
                    continue
                self._dispatcher.invoke(lambda k=key, im=img, t=tok: t.is_cancelled() or self._on_thumbnail_loaded(k, im))

        self._dispatcher.post(task)

    def _on_thumbnail_loaded(self, key, img):
        self._thumb_cache[key] = QtGui.QPixmap.fromImage(img) if img and not img.isNull() else QtGui.QPixmap()
        while len(self._thumb_cache) > self.THUMB_CACHE_LIMIT:
            self._thumb_cache.popitem(last=False)
        self._overlay.update()

    def hideEvent(self, event):
        self._cancel_all_pending()
        BatchRenameWidget._saved_state = self._serialise_columns()
        super().hideEvent(event)

    def _title_text(self):
        return f"Batch Renamer \u2014 {len(self._paths)} files"

    @property
    def selected_row(self) -> int:
        return self._selected_row

    def _selected_rows(self, table):
        selection_model = table.selectionModel()
        if selection_model is None:
            return []
        return sorted({index.row() for index in selection_model.selectedIndexes() if index.isValid() and 0 <= index.row() < len(self._paths)})

    def _selected_segment_cells(self):
        selection_model = self._seg_table.selectionModel()
        if selection_model is None:
            return []
        cells = []
        seen = set()
        for index in selection_model.selectedIndexes():
            if not index.isValid():
                continue
            row = index.row()
            section = index.column()
            if row < 0 or row >= len(self._paths) or section == self._add_section:
                continue
            key = (row, section)
            if key in seen:
                continue
            seen.add(key)
            cells.append(key)
        cells.sort()
        return cells

    def _selection_anchor_row(self, table, selected=None):
        if selected is not None:
            indexes = [index for index in selected.indexes() if index.isValid()]
            if indexes:
                return indexes[-1].row()
        current = table.currentIndex()
        if current.isValid() and 0 <= current.row() < len(self._paths):
            return current.row()
        rows = self._selected_rows(table)
        return rows[-1] if rows else -1

    @staticmethod
    def _build_row_selection(model, rows, start_column, end_column=None):
        selection = QtCore.QItemSelection()
        if model is None:
            return selection
        if end_column is None:
            end_column = start_column
        for row in rows:
            start = model.index(row, start_column)
            end = model.index(row, end_column)
            if start.isValid() and end.isValid():
                selection.select(start, end)
        return selection

    def _select_preview_rows(self, rows):
        selection_model = self._preview.selectionModel()
        if selection_model is None:
            return
        if not rows:
            selection_model.clearSelection()
            return
        selection = self._build_row_selection(
            self._preview_model,
            rows,
            0,
            max(0, self._preview_model.columnCount() - 1),
        )
        selection_model.select(selection, QtCore.QItemSelectionModel.ClearAndSelect)

    def _select_segment_rows(self, rows):
        selection_model = self._seg_table.selectionModel()
        if selection_model is None:
            return
        if not rows:
            selection_model.clearSelection()
            return
        selection = self._build_row_selection(self._seg_model, rows, 0, 0)
        selection_model.select(selection, QtCore.QItemSelectionModel.ClearAndSelect)

    @staticmethod
    def _ensure_index_selected(table, index):
        if not index.isValid():
            return
        selection_model = table.selectionModel()
        if selection_model is None:
            return
        if selection_model.isSelected(index):
            selection_model.setCurrentIndex(index, QtCore.QItemSelectionModel.NoUpdate)
            return
        selection_model.select(index, QtCore.QItemSelectionModel.ClearAndSelect)
        selection_model.setCurrentIndex(index, QtCore.QItemSelectionModel.NoUpdate)

    def thumb_for_row(self, row):
        if 0 <= row < len(self._paths):
            key = str(self._paths[row])
            pix = self._thumb_cache.get(key)
            if pix is not None:
                self._thumb_cache.move_to_end(key)
            return pix
        return None

    def _on_preview_selection(self, selected=None, _deselected=None):
        if self._syncing_selection:
            return
        self._syncing_selection = True
        try:
            rows = self._selected_rows(self._preview)
            self._selected_row = self._selection_anchor_row(self._preview, selected) if rows else -1
            self._select_segment_rows(rows)
        finally:
            self._syncing_selection = False
            self._overlay.update()

    def eventFilter(self, obj, event):
        if obj is self._preview.viewport():
            if event.type() in (QtCore.QEvent.Resize, QtCore.QEvent.Paint):
                self._overlay.setGeometry(self._preview.viewport().rect())
                self._overlay.raise_()
                if event.type() == QtCore.QEvent.Resize:
                    self._overlay.update()
                    self._update_visible_thumbnails()
        if obj is self._status and event.type() == QtCore.QEvent.MouseButtonPress:
            self._scroll_to_next_issue()
            return True
        return super().eventFilter(obj, event)

    def _sync_from_preview(self, val):
        if not self._syncing:
            self._syncing = True
            self._seg_table.verticalScrollBar().setValue(val)
            self._syncing = False
            self._overlay.update()
            self._update_visible_thumbnails()

    def _sync_from_seg(self, val):
        if not self._syncing:
            self._syncing = True
            self._preview.verticalScrollBar().setValue(val)
            self._syncing = False
            self._overlay.update()
            self._update_visible_thumbnails()

    def _on_seg_selection(self, selected=None, _deselected=None):
        if self._syncing_selection:
            return
        self._syncing_selection = True
        try:
            rows = self._selected_rows(self._seg_table)
            self._selected_row = self._selection_anchor_row(self._seg_table, selected) if rows else -1
            self._select_preview_rows(rows)
        finally:
            self._syncing_selection = False
            self._overlay.update()

    def _scroll_to_next_issue(self):
        if not self._results:
            return
        issue_rows = [i for i, r in enumerate(self._results) if r.conflict or r.errors or r.missing]
        if not issue_rows:
            return
        current = self._selected_row
        target = next((r for r in issue_rows if r > current), issue_rows[0])
        self._syncing_selection = True
        try:
            self._selected_row = target
            self._select_preview_rows([target])
            self._select_segment_rows([target])
            preview_index = self._preview_model.index(target, 0)
            if preview_index.isValid():
                self._preview.setCurrentIndex(preview_index)
                self._preview.scrollTo(preview_index, QtWidgets.QAbstractItemView.EnsureVisible)
            seg_index = self._seg_model.index(target, 0)
            if seg_index.isValid():
                self._seg_table.setCurrentIndex(seg_index)
                self._seg_table.scrollTo(seg_index, QtWidgets.QAbstractItemView.EnsureVisible)
        finally:
            self._syncing_selection = False
            self._overlay.update()

    def _on_row_opacity_changed(self, value):
        self._overlay.set_row_opacity(value / 100.0)

    def _on_sel_opacity_changed(self, value):
        self._overlay.set_sel_opacity(value / 100.0)

    def _normalise_thumb_fit_mode(self, fit_mode):
        return fit_mode if fit_mode in self.THUMB_FIT_MODES else self.THUMB_FIT_COVER

    def _set_thumb_fit_mode(self, side, fit_mode):
        normalised = self._normalise_thumb_fit_mode(fit_mode)
        if side == "row":
            self._row_thumb_fit_mode = normalised
            self._overlay.set_row_fit_mode(normalised)
        elif side == "sel":
            self._sel_thumb_fit_mode = normalised
            self._overlay.set_sel_fit_mode(normalised)
        self._apply_thumb_fit_button(side)

    def _apply_thumb_fit_button(self, side):
        button = getattr(self, f"_{side}_thumb_fit_btn", None)
        if button is None:
            return
        fit_mode = self._row_thumb_fit_mode if side == "row" else self._sel_thumb_fit_mode
        contain = fit_mode == self.THUMB_FIT_CONTAIN
        prefix = t("Left thumbnail fit") if side == "row" else t("Right thumbnail fit")
        label = t("Contain") if contain else t("Cover")
        old = button.blockSignals(True)
        button.setChecked(contain)
        button.setIcon(themed_icon("fit_contain" if contain else "fit_cover", margin=0.04))
        button.setToolTip(f"{prefix}: {label}")
        button.blockSignals(old)

    def _on_seg_data_changed(self, top_left, bottom_right, roles):
        if self._refreshing:
            return
        col = top_left.column()
        row = top_left.row()
        if row >= len(self._paths):
            return
        value = self._seg_model.data(top_left, Qt.DisplayRole)
        if value is None:
            return
        path_key = str(self._paths[row])
        if col < len(self._columns):
            self._columns[col].overrides[path_key] = value
        elif col == self._ext_section:
            self._ext_column.overrides[path_key] = value
        else:
            return
        self._refresh(auto_size=False)

    def _on_seg_dblclick(self, index):
        col = index.column()
        if col == self._add_section:
            self._show_add_menu(col)

    @property
    def _add_section(self):
        return len(self._columns)

    @property
    def _ext_section(self):
        return len(self._columns) + 1

    def _is_segment_editing(self):
        try:
            return self._seg_table.is_editing()
        except RuntimeError:
            return False

    def _defer_update_if_editing(self, callback, kind="refresh"):
        if not callable(callback) or not self._is_segment_editing():
            return False
        self._rename_btn.setEnabled(False)
        if kind == "rebuild":
            self._pending_rebuild_callback = callback
        elif kind == "apply":
            self._pending_apply_callback = callback
        else:
            self._pending_refresh_callback = callback
        return True

    def _has_pending_update(self):
        return any(
            callback is not None
            for callback in (
                self._pending_rebuild_callback,
                self._pending_refresh_callback,
                self._pending_apply_callback,
            )
        )

    def _schedule_pending_update(self):
        if not self._has_pending_update() or self._pending_update_scheduled:
            return
        self._pending_update_scheduled = True
        QtCore.QTimer.singleShot(0, self._flush_pending_update)

    def _flush_pending_update(self):
        self._pending_update_scheduled = False
        if not self._has_pending_update():
            return
        if self._is_segment_editing():
            return
        callback = self._pending_rebuild_callback or self._pending_refresh_callback or self._pending_apply_callback
        self._pending_rebuild_callback = None
        self._pending_refresh_callback = None
        self._pending_apply_callback = None
        if callback is not None:
            callback()

    def _rebuild(self):
        if self._defer_update_if_editing(self._rebuild, kind="rebuild"):
            return
        self._close_popup()
        self._seg_model.configure(
            self._columns,
            self._ext_column,
            self._ADD_COL_LABEL,
            self._ext_column.source.DISPLAY,
        )
        self._refresh()

    def _refresh(self, prepare=None, auto_size=True):
        if self._defer_update_if_editing(lambda: self._refresh(prepare=prepare, auto_size=auto_size), kind="refresh"):
            return
        if self._refresh_cancel:
            self._refresh_cancel.cancel()
        self._rename_btn.setEnabled(False)
        cancel = CancelToken()
        self._refresh_cancel = cancel
        paths = list(self._paths)
        columns = list(self._columns)
        ext_column = self._ext_column
        metadata = dict(self._metadata)
        keys = list(self._keys)
        initial_keys = list(self._initial_keys)
        results_snapshot = list(self._results)
        sort_indicator = self._sort_indicator

        def task():
            nonlocal paths, keys
            try:
                if cancel.is_cancelled():
                    return
                if prepare:
                    paths, keys = prepare(paths, keys, results_snapshot)
                if cancel.is_cancelled():
                    return
                results, global_errors = RenameEngine.preview(
                    paths,
                    columns,
                    ext_column,
                    metadata,
                    keys=keys,
                    initial_keys=initial_keys,
                )
                paths, keys, results = self._sort_preview_rows(paths, keys, results, sort_indicator)
                if cancel.is_cancelled():
                    return
                conflicts = sum(1 for r in results if r.conflict)
                errors = sum(1 for r in results if r.errors)
                missing = sum(1 for r in results if r.missing)
                self._dispatcher.invoke(
                    lambda: (
                        cancel.is_cancelled()
                        or self._on_refresh_done(
                            results,
                            paths,
                            keys,
                            (conflicts, errors, missing, global_errors),
                            auto_size,
                        )
                    )
                )
            except Exception as e:
                AppLogger.warning(f"Rename preview failed: {e}", exc=e)
                self._dispatcher.invoke(lambda: cancel.is_cancelled() or self._rename_btn.setEnabled(True))

        self._dispatcher.post(task, cancel=cancel)

    @staticmethod
    def _sort_preview_rows(paths, keys, results, sort_indicator):
        if not sort_indicator or not results:
            return paths, keys, results
        kind, section, ascending = sort_indicator
        pairs = list(zip(paths, keys, results))
        if not pairs:
            return paths, keys, results
        if kind == "preview":
            if section == 0:
                key_fn = lambda item: natural_key(item[2].original)
            elif section == 1:
                key_fn = lambda item: natural_key(item[2].new_name)
            else:
                return paths, keys, results
        elif kind == "segment" and section >= 0:
            key_fn = lambda item: natural_key(item[2].segments[section] if section < len(item[2].segments) else "")
        else:
            return paths, keys, results
        pairs.sort(key=key_fn, reverse=not ascending)
        return [p for p, _, _ in pairs], [k for _, k, _ in pairs], [r for _, _, r in pairs]

    def _on_refresh_done(self, results, paths, keys, stats, auto_size=True):
        if self._defer_update_if_editing(
            lambda: self._apply_refresh_done(results, paths, keys, stats, auto_size),
            kind="apply",
        ):
            return
        self._apply_refresh_done(results, paths, keys, stats, auto_size)

    def _apply_refresh_done(self, results, paths, keys, stats, auto_size=True):
        self._refreshing = True
        try:
            self._paths = paths
            self._keys = keys
            self._results = results
            self._preview_model.refresh(self._results)
            self._seg_model.refresh(self._results, self._paths)
            if auto_size:
                self._auto_size_segments()
            self._apply_status(*stats)
            self._apply_sort_indicator()
            self._update_visible_thumbnails()
        finally:
            self._refreshing = False

    def _apply_sort_indicator(self):
        si = self._sort_indicator
        if si and si[0] == "preview":
            self._preview_model.set_sort_indicator(si[1])
            self._seg_model.set_sort_indicator(-1)
        elif si and si[0] == "segment":
            self._preview_model.set_sort_indicator(-1)
            self._seg_model.set_sort_indicator(si[1], si[2])
        else:
            self._preview_model.set_sort_indicator(-1)
            self._seg_model.set_sort_indicator(-1)

    def _auto_size_segments(self):
        fm = QtGui.QFontMetrics(self._mono)
        hdr_font = self._seg_table.horizontalHeader().font()
        hfm = QtGui.QFontMetrics(hdr_font)
        total = self._seg_model.columnCount()
        sample_rows = min(len(self._results), 200)
        for col in range(total):
            if col == self._add_section:
                self._seg_table.setColumnWidth(col, dpix(24))
                continue
            header_text = self._seg_model.headerData(col, Qt.Horizontal)
            max_w = hfm.horizontalAdvance(header_text) if header_text else 0
            for row in range(sample_rows):
                idx = self._seg_model.index(row, col)
                text = self._seg_model.data(idx, Qt.DisplayRole)
                if text:
                    max_w = max(max_w, fm.horizontalAdvance(text))
            self._seg_table.setColumnWidth(col, max(max_w + dpix(14), dpix(28)))

    def _apply_status(self, conflicts, errors, missing, global_errors=None):
        p = self._p
        self._global_errors = global_errors or []
        issues = conflicts + errors + missing + len(self._global_errors)
        if issues:
            parts = []
            if conflicts:
                parts.append(f"{conflicts} conflict(s)")
            if errors:
                parts.append(f"{errors} invalid name(s)")
            if missing:
                parts.append(f"{missing} missing file(s)")
            if self._global_errors:
                parts.append(f"{len(self._global_errors)} regex error(s)")
            self._status.setText(f"\u26a0 {' / '.join(parts)}")
            self._status.setStyleSheet(f"color: {p.warning}; font-size: {dpix(11)}px;")
            self._status.setCursor(Qt.PointingHandCursor)
        else:
            self._status.setText(f"\u2713 {len(self._results)} files ready")
            self._status.setStyleSheet(f"color: {p.success}; font-size: {dpix(11)}px;")
            self._status.setCursor(Qt.ArrowCursor)
        self._rename_btn.setEnabled(not issues and bool(self._results))

    def _on_preview_sort(self, section):
        if not self._results:
            return
        self._sort_indicator = ("preview", section, True)
        self._refresh(auto_size=False)

    def _sort_by_segment(self, section, ascending):
        if not self._results:
            return
        self._sort_indicator = ("segment", section, ascending)
        self._refresh(auto_size=False)

    def _on_seg_header_click(self, section):
        if section == self._add_section:
            self._close_popup()
            self._show_add_menu(section)
            return
        self._close_popup()
        popup = self._create_column_popup(section)
        if popup is None:
            return
        request_id = self._popup_request_id
        self._popup = popup
        QtCore.QTimer.singleShot(1, lambda r=request_id, p=popup, s=section: self._show_popup_if_current(r, p, s))

    def _create_column_popup(self, section):
        is_ext = section == self._ext_section
        if section > self._ext_section:
            return None

        column = self._ext_column if is_ext else self._columns[section]

        meta_keys = set()
        for m in self._metadata.values():
            meta_keys.update(m.keys())

        popup = ColumnSettingsPopup(
            column,
            is_ext=is_ext,
            meta_keys=sorted(meta_keys),
            parent=self,
        )
        popup.changed.connect(self._deferred_refresh)
        if not is_ext:
            popup.sort_requested.connect(
                lambda asc, s=section: (
                    self._close_popup(),
                    self._sort_by_segment(s, asc),
                )
            )
            popup.move_requested.connect(lambda d, s=section: QtCore.QTimer.singleShot(0, lambda: self._move_column(s, d)))
            popup.remove_requested.connect(lambda s=section: QtCore.QTimer.singleShot(0, lambda: self._remove_column(s)))
            popup.resequence_requested.connect(
                lambda: (
                    self._close_popup(),
                    self._resequence(),
                )
            )

        return popup

    def _show_popup_if_current(self, request_id, popup, section):
        if request_id != self._popup_request_id or self._popup is not popup:
            return
        header = self._seg_table.horizontalHeader()
        gp = self._column_popup_pos(header, section, popup.popup_size_hint())
        popup.show_at(gp)
        popup.closed.connect(lambda p=popup: self._on_popup_closed(p))

    def _column_popup_pos(self, header, section, size):
        sec_x = header.sectionPosition(section) - header.offset()
        below = header.mapToGlobal(QtCore.QPoint(sec_x, header.height()))
        screen = QtWidgets.QApplication.screenAt(below) or header.screen() or QtWidgets.QApplication.primaryScreen()
        if screen is None:
            return below
        geo = screen.availableGeometry()
        below_space = geo.bottom() + 1 - below.y()
        header_top = header.mapToGlobal(QtCore.QPoint(sec_x, 0))
        above_space = header_top.y() - geo.top()
        if below_space < size.height() + dpix(48) and above_space > below_space:
            return QtCore.QPoint(below.x(), max(geo.top(), header_top.y() - size.height()))
        return below

    def _on_popup_closed(self, popup):
        if self._popup is popup:
            self._popup = None

    def _deferred_refresh(self):
        self._update_source_defaults()
        QtCore.QTimer.singleShot(0, self._refresh)

    def _close_popup(self):
        self._popup_request_id += 1
        popup = self._popup
        self._popup = None
        if popup:
            popup.close()

    def _show_add_menu(self, section):
        header = self._seg_table.horizontalHeader()
        sec_x = header.sectionPosition(section) - header.offset()
        gp = header.mapToGlobal(QtCore.QPoint(sec_x, header.height()))
        uid = f"{id(self):x}"
        items = [":Add Column"]
        items.extend(
            ActionKit.Action(path=f"inline.renamer.{uid}.add_column.{src_cls.NAME}", display=src_cls.DISPLAY, func=lambda ctx, c=src_cls: self._add_column(c))
            for src_cls in rename_source_registry.list_all()
            if src_cls.NAME != "ext"
        )
        spec = Menu.session(self).menu(items)
        if spec is not None:
            spec.exec(gp)

    def _add_column(self, src_cls):
        source = src_cls()
        defaults = self._source_defaults.get(source.NAME)
        if defaults:
            source._apply(defaults)
        self._columns.append(RenameColumn(source))
        self._rebuild()

    def _remove_column(self, idx):
        if len(self._columns) <= 1 or not (0 <= idx < len(self._columns)):
            return
        self._on_column_removed(idx)
        self._columns.pop(idx)
        self._rebuild()

    def _move_column(self, idx, direction):
        new_idx = idx + direction
        if 0 <= new_idx < len(self._columns):
            self._on_columns_swapped(idx, new_idx)
            self._columns[idx], self._columns[new_idx] = (
                self._columns[new_idx],
                self._columns[idx],
            )
            self._rebuild()

    def _on_column_removed(self, idx):
        si = self._sort_indicator
        if not si or si[0] != "segment":
            return
        kind, section, ascending = si
        if section == idx:
            self._sort_indicator = None
        elif section > idx:
            self._sort_indicator = (kind, section - 1, ascending)

    def _on_columns_swapped(self, idx, new_idx):
        si = self._sort_indicator
        if not si or si[0] != "segment":
            return
        kind, section, ascending = si
        if section == idx:
            self._sort_indicator = (kind, new_idx, ascending)
        elif section == new_idx:
            self._sort_indicator = (kind, idx, ascending)

    def _resequence(self):
        self._initial_paths = list(self._paths)
        self._initial_keys = list(self._keys)
        self._refresh(auto_size=False)

    def _exclude_rows(self, rows):
        for row in sorted(rows, reverse=True):
            if 0 <= row < len(self._paths):
                self._paths.pop(row)
                self._keys.pop(row)
        if not self._paths:
            self.reset()
            return
        self._rebuild()
        self._title.setText(self._title_text())

    def remove_files(self, paths: list[Path]):
        remove_set = {str(p) for p in paths}
        indices = [i for i, p in enumerate(self._paths) if str(p) in remove_set]
        if not indices:
            return
        self._exclude_rows(indices)

    def _override_map_for_section(self, section):
        if 0 <= section < len(self._columns):
            return self._columns[section].overrides
        if section == self._ext_section:
            return self._ext_column.overrides
        return None

    def _has_cell_override(self, path_key: str, section: int) -> bool:
        overrides = self._override_map_for_section(section)
        return overrides is not None and path_key in overrides

    def _restore_cell_overrides(self, cells):
        restored = 0
        for path_key, section in cells:
            overrides = self._override_map_for_section(section)
            if overrides is None or path_key not in overrides:
                continue
            del overrides[path_key]
            restored += 1
        if restored:
            self._refresh(auto_size=False)
        return restored

    def _selected_override_cells(self):
        cells = []
        for row, section in self._selected_segment_cells():
            path_key = str(self._paths[row])
            if self._has_cell_override(path_key, section):
                cells.append((path_key, section))
        return cells

    def _restore_cell_override(self, path_key: str, section: int):
        self._restore_cell_overrides([(path_key, section)])

    def _on_row_context(self, pos):
        index = self._seg_table.indexAt(pos)
        if not index.isValid():
            return
        self._ensure_index_selected(self._seg_table, index)
        self._show_row_menu(
            self._seg_table,
            self._seg_table.viewport().mapToGlobal(pos),
            clicked_index=index,
        )

    def _on_row_context_preview(self, pos):
        index = self._preview.indexAt(pos)
        if not index.isValid():
            return
        self._ensure_index_selected(self._preview, index)
        self._show_row_menu(self._preview, self._preview.viewport().mapToGlobal(pos), clicked_index=index)

    def _show_row_menu(self, table, gpos, clicked_index=None):
        rows = self._selected_rows(table)
        if not rows:
            return
        paths = [self._keys[r] if r < len(self._keys) else str(self._paths[r]).replace("\\", "/") for r in rows]
        sources = [str(self._paths[r]) for r in rows]
        seed = Context.create_context(
            self,
            "*",
            source="menu",
            extras={
                "path": paths[0],
                "paths": paths,
                "source": sources[0],
                "sources": sources,
            },
        )
        if len(rows) == 1:
            remove_display = t('Remove "{filename}"', filename=self._paths[rows[0]].name)
        else:
            remove_display = t("Remove {count} file(s)", count=len(rows))
        frozen_rows = list(rows)
        items = [
            ":BatchRenamer",
            ActionKit.Action(
                path="inline.renamer.remove",
                display=remove_display,
                translate=False,
                func=lambda ctx: self._exclude_rows(frozen_rows),
            ),
        ]
        if table is self._seg_table and clicked_index is not None and clicked_index.isValid():
            items.append(
                ActionKit.Action(
                    path="inline.renamer.restore_cell",
                    display=t("Restore selected override(s)"),
                    translate=False,
                    func=lambda ctx: self._restore_cell_overrides(self._selected_override_cells()),
                )
            )
        items.extend(
            [
                "-",
                ":Path",
                "file.open",
                "file.show_explorer",
                "file.shell_context_menu",
                "-",
                "file.show_file",
                "file.select_path",
                "file.scroll_to_file",
            ]
        )
        Menu.session(self, seed_ctx=seed, pos=gpos).menu(items).exec()

    def _execute(self):
        if self._is_segment_editing():
            self._defer_update_if_editing(lambda: self._refresh(auto_size=False), kind="refresh")
            self._schedule_pending_update()
            return
        if self._has_pending_update():
            self._rename_btn.setEnabled(False)
            self._schedule_pending_update()
            return
        if self._global_errors or any(r.conflict or r.errors for r in self._results):
            return
        missing = [p for p, r in zip(self._paths, self._results) if not p.exists()]
        if missing:
            self._refresh(auto_size=False)
            QtWidgets.QMessageBox.warning(
                self,
                "Rename",
                f"{len(missing)} file(s) no longer exist",
            )
            return
        rename_map = self.get_rename_map()
        if not rename_map:
            return
        if not self._confirm_rename(rename_map):
            return
        self._do_rename(rename_map)

    def _confirm_rename(self, rename_map: dict[str, str]) -> bool:
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("Confirm Rename")
        dlg.setMinimumWidth(dpix(500))
        layout = QtWidgets.QVBoxLayout(dlg)
        label = QtWidgets.QLabel(f"Rename {len(rename_map)} file(s)?")
        label.setStyleSheet(f"font-size: {dpix(13)}px; font-weight: bold;")
        layout.addWidget(label)
        table = QtWidgets.QTableWidget(len(rename_map), 2)
        table.setHorizontalHeaderLabels(["Before", "After"])
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        table.verticalHeader().setVisible(False)
        for row, (old, new) in enumerate(rename_map.items()):
            table.setItem(row, 0, QtWidgets.QTableWidgetItem(Path(old).name))
            table.setItem(row, 1, QtWidgets.QTableWidgetItem(Path(new).name))
        layout.addWidget(table)
        btn_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
        )
        btn_box.accepted.connect(dlg.accept)
        btn_box.rejected.connect(dlg.reject)
        layout.addWidget(btn_box)
        return dlg.exec() == QtWidgets.QDialog.Accepted

    def _do_rename(self, rename_map: dict[str, str]):
        items = list(rename_map.items())
        plans = [
            PastePlanItem(
                index=i,
                src=Path(old),
                is_dir=False,
                action="cut",
                dst_default=Path(new),
                conflict=False,
                suggested_dst=None,
            )
            for i, (old, new) in enumerate(items)
        ]
        results = execute_paste_plans_with_ui(
            plans=plans,
            overwrite_mode="overwrite",
            parent=self,
        )
        succeeded: dict[str, str] = {}
        failed: list[tuple[str, str]] = []
        for (old, new), result in zip(items, results):
            if result.status == "ok":
                succeeded[old] = result.dst or new
            elif result.status != "skipped":
                AppLogger.warning(f"Rename failed: {old} -> {new} ({result.error})")
                failed.append((Path(old).name, result.error or "unknown error"))
        self._apply_rename_results(succeeded)
        total = len(succeeded) + len(failed)
        if failed and succeeded:
            text = f"Renamed {len(succeeded)}/{total} file(s). {len(failed)} failed."
        elif failed:
            text = f"All {len(failed)} rename(s) failed."
        elif succeeded:
            text = f"{len(succeeded)} file(s) renamed."
        else:
            return
        if failed:
            QtWidgets.QMessageBox.warning(self, "Rename Result", text)
        else:
            QtWidgets.QMessageBox.information(self, "Rename Result", text)

    def _apply_rename_results(self, succeeded: dict[str, str]):
        if not succeeded:
            return
        for i, p in enumerate(self._paths):
            sp = str(p)
            if sp in succeeded:
                new_path = Path(succeeded[sp])
                self._paths[i] = new_path
                self._keys[i] = str(new_path).replace("\\", "/")
        for i, p in enumerate(self._initial_paths):
            sp = str(p)
            if sp in succeeded:
                new_path = Path(succeeded[sp])
                self._initial_paths[i] = new_path
                self._initial_keys[i] = str(new_path).replace("\\", "/")
        new_meta: dict[str, dict[str, str]] = {}
        for key, meta in self._metadata.items():
            matched = next((new for old, new in succeeded.items() if key == old or key == old.replace("\\", "/")), None)
            if matched:
                new_meta[matched.replace("\\", "/")] = meta
            else:
                new_meta[key] = meta
        self._metadata = new_meta
        self._thumb_cache.clear()
        self._thumb_visible.clear()
        self._title.setText(self._title_text())
        self._status.setText(f"Renamed {len(succeeded)} file(s)")
        self._reset_columns(preserve_ext=True)
        self._sort_indicator = self.DEFAULT_SORT_INDICATOR
        self._rebuild()

    def _reset_columns(self, preserve_ext=False):
        name_src = NameSource()
        name_defaults = self._source_defaults.get(name_src.NAME)
        if name_defaults:
            name_src._apply(name_defaults)
        ext_src = ExtSource()
        if preserve_ext:
            ext_defaults = self._source_defaults.get(ext_src.NAME)
            if ext_defaults:
                ext_src._apply(ext_defaults)
        self._columns = [RenameColumn(name_src)]
        self._ext_column = RenameColumn(ext_src)
        self._sort_indicator = None

    def get_rename_map(self) -> dict[str, str]:
        return {str(p): str(p.parent / r.new_name) for p, r in zip(self._paths, self._results) if p.name != r.new_name}


class BatchRenamerPlugin(BasePanelPlugin):
    NAME = "batch_renamer"
    DISPLAY_NAME = "Batch Renamer"
    PRIORITY = 0
    SOURCE = "Builtin"

    def save_ui_state(self):
        inst = BatchRenameWidget._instance_ref
        if inst is not None:
            try:
                BatchRenameWidget._saved_state = inst._serialise_columns()
            except RuntimeError as e:
                AppLogger.warning("[BatchRenamer] save_state failed", exc=e)
        return dict(BatchRenameWidget._saved_state)

    def restore_ui_state(self, state):
        BatchRenameWidget._saved_state = state

    def create_widget(self):
        widget = BatchRenameWidget()
        widget._restore_ui_from_state()
        return widget
