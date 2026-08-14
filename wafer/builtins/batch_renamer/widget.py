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
from ...ui.geometry import screen_geometry_for
from ...ui.popups import PopupBase
from ...utils.formatting import dpix, natural_key
from ...utils.logs import AppLogger
from ...utils.paths import safe_is_file
from .engine import RenameColumn, RenameEngine, RenameResult
from .overlay import ThumbnailOverlay
from .layout import OrientedSplitter, DIRECTIONS, DIRECTION_ICONS
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
    THUMB_FIT_COVER = "cover"
    THUMB_FIT_CONTAIN = "contain"
    THUMB_FIT_MODES = {THUMB_FIT_COVER, THUMB_FIT_CONTAIN}
    THUMB_RESOLUTIONS = (256, 512, 1024, 2048, 4096)
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
        self._pending_select_rows: list[int] | None = None
        self._thumb_cache: collections.OrderedDict[str, QtGui.QPixmap] = collections.OrderedDict()
        self._row_thumb_fit_mode = self.THUMB_FIT_COVER
        self._sel_thumb_fit_mode = self.THUMB_FIT_COVER
        self._thumb_resolution = 512
        self._scroll_sync_enabled = True
        self._display_offset = 0
        self._thumb_settings_popup: PopupBase | None = None
        self._outer_dir = "TB"
        self._inner_dir = "LR"
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

        self._init_segment_table()
        self._init_preview_table()

        self._split = OrientedSplitter(self._inner_split, self._seg_frame, self._outer_dir, parent=self._rename_page)
        self._split.setStretchFactor(0, 1)
        self._split.setStretchFactor(1, 1)
        rename_lay.addWidget(self._split, stretch=1)

        self._connect_view_sync()
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
        self._paths = list(paths)
        self._keys = list(keys) if keys else [str(p).replace("\\", "/") for p in paths]
        self._initial_keys = list(self._keys)
        self._initial_paths = list(self._paths)
        self._metadata = {}
        self._thumb_cache.clear()
        self._thumb_visible.clear()
        self._reset_columns()
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

    def _init_preview_table(self):
        p = self._p
        row_h = dpix(20)

        self._preview_model = PreviewModel(self)
        colors = ColorSet(p, self._mono)
        self._preview_model.set_colors(colors)
        self._seg_model.set_colors(colors)

        self._orig_view = self._build_preview_view(visible_column=0, header_bg=p.bg_secondary)
        self._result_view = self._build_preview_view(visible_column=1, header_bg=p.bg_secondary)
        self._preview_views = (self._orig_view, self._result_view)
        self._view_column = {self._orig_view: 0, self._result_view: 1}
        for view in self._preview_views:
            view.verticalHeader().setDefaultSectionSize(row_h)

        self._orig_frame = self._wrap_in_frame(self._orig_view)
        self._result_frame = self._wrap_in_frame(self._result_view)
        self._inner_split = OrientedSplitter(self._orig_frame, self._result_frame, self._inner_dir, parent=self._rename_page)
        self._preview_frame = self._inner_split

        self._orig_overlay = ThumbnailOverlay(self, self._orig_view, ThumbnailOverlay.ROLE_ROW, 0, parent=self._orig_view.viewport())
        self._result_overlay = ThumbnailOverlay(self, self._result_view, ThumbnailOverlay.ROLE_SEL, 1, parent=self._result_view.viewport())
        self._overlays = (self._orig_overlay, self._result_overlay)
        self._overlay = self._orig_overlay
        for view in self._preview_views:
            view.viewport().installEventFilter(self)

    def _wrap_in_frame(self, view):
        frame = QtWidgets.QFrame()
        frame.setStyleSheet(self._frame_stylesheet())
        lay = QtWidgets.QVBoxLayout(frame)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(view)
        return frame

    def _build_preview_view(self, visible_column, header_bg):
        p = self._p
        view = SyncedView(row_wheel=True, parent=self)
        view.setModel(self._preview_model)
        view.setColumnHidden(0 if visible_column == 1 else 1, True)
        view.setFont(self._mono)
        view.setShowGrid(False)
        view.verticalHeader().setVisible(False)
        view.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        view.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        view.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        view.setFocusPolicy(Qt.StrongFocus)
        view.setAutoScroll(False)
        view.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
        view.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        header = view.horizontalHeader()
        header.setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        header.setFixedHeight(dpix(22))
        header.setSectionsClickable(True)
        header.setHighlightSections(False)
        header.setStyleSheet(self._header_stylesheet(header_bg, p.text_muted))
        view.setStyleSheet(f"QTableView {{ background: {p.bg_primary}; border: none; color: {p.text_primary}; }}QTableView::item {{ padding: 0 {dpix(4)}px; border: none; }}")
        view.setItemDelegate(PreviewDelegate(p.border_subtle, view))
        return view

    def _init_segment_table(self):
        p = self._p
        row_h = dpix(20)

        seg_frame = QtWidgets.QFrame()
        seg_frame.setStyleSheet(self._frame_stylesheet())
        sf_lay = QtWidgets.QVBoxLayout(seg_frame)
        sf_lay.setContentsMargins(0, 0, 0, 0)
        sf_lay.setSpacing(0)

        self._seg_table = SyncedView(parent=self, vertical_tab_navigation=True)
        self._seg_model = SegmentModel(self)
        self._seg_table.setModel(self._seg_model)

        self._seg_table.setFont(self._mono)
        self._seg_table.setShowGrid(True)
        self._seg_table.verticalHeader().setVisible(False)
        self._seg_table.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self._seg_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectItems)
        self._seg_table.setEditTriggers(QtWidgets.QAbstractItemView.DoubleClicked | QtWidgets.QAbstractItemView.EditKeyPressed)
        self._seg_table.setFocusPolicy(Qt.ClickFocus)
        self._seg_table.setAutoScroll(False)
        self._seg_table.verticalHeader().setDefaultSectionSize(row_h)
        self._seg_table.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollPerItem)
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

    def _connect_view_sync(self):
        for view in self._preview_views:
            view.verticalScrollBar().valueChanged.connect(lambda _v, src=view: self._sync_preview_scroll(src))
            view.selectionModel().selectionChanged.connect(lambda _s, _d, src=view: self._on_view_selection(src))
            view.setContextMenuPolicy(Qt.CustomContextMenu)
            view.customContextMenuRequested.connect(lambda pos, src=view: self._on_row_context_preview(src, pos))
            view.rows_reordered.connect(self._reorder_rows)
        self._seg_table.verticalScrollBar().valueChanged.connect(self._sync_from_seg)
        self._seg_model.dataChanged.connect(self._on_seg_data_changed)
        self._seg_table.doubleClicked.connect(self._on_seg_dblclick)
        self._seg_table.selectionModel().selectionChanged.connect(self._on_seg_selection)
        self._seg_table.editing_finished.connect(self._schedule_pending_update)
        self._seg_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self._seg_table.customContextMenuRequested.connect(self._on_row_context)
        self._seg_table.rows_reordered.connect(self._reorder_rows)

    def _init_bottom_bar(self, root):
        p = self._p

        bar = QtWidgets.QHBoxLayout()
        self._bottom_bar = bar
        bar.setContentsMargins(0, dpix(2), 0, 0)

        self._thumb_settings_content = self._build_thumb_settings_content()

        gear_btn = QtWidgets.QToolButton()
        gear_btn.setIcon(themed_icon("gear_small"))
        gear_btn.setIconSize(QtCore.QSize(dpix(16), dpix(16)))
        gear_btn.setCursor(Qt.PointingHandCursor)
        gear_btn.setToolTip(t("Thumbnail settings"))
        gear_btn.setStyleSheet(
            f"QToolButton {{ background: {p.bg_secondary}; color: {p.text_primary}; "
            f"border: 1px solid {p.border_default}; border-radius: {dpix(2)}px; "
            f"padding: {dpix(3)}px; }}"
            f"QToolButton:hover {{ background: {p.bg_hover}; }}"
        )
        gear_btn.clicked.connect(self._toggle_thumb_settings_popup)
        self._thumb_settings_btn = gear_btn
        bar.addWidget(gear_btn)
        bar.addSpacing(dpix(4))

        self._status = QtWidgets.QLabel()
        self._status.setStyleSheet(f"color: {p.text_muted}; font-size: {dpix(11)}px;")
        self._status.installEventFilter(self)
        bar.addWidget(self._status)

        bar.addSpacing(dpix(8))
        reorder_hint = QtWidgets.QLabel(t("Middle-drag to reorder"))
        reorder_hint.setStyleSheet(f"color: {p.text_muted}; font-size: {dpix(10)}px;")
        bar.addWidget(reorder_hint)
        bar.addStretch(1)

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

    def _build_thumb_settings_content(self):
        p = self._p

        slider_ss = (
            f"QSlider::groove:horizontal {{ background: {p.bg_hover}; "
            f"height: {dpix(4)}px; border-radius: {dpix(2)}px; }}"
            f"QSlider::handle:horizontal {{ background: {p.text_muted}; "
            f"width: {dpix(10)}px; margin: -{dpix(3)}px 0; "
            f"border-radius: {dpix(5)}px; }}"
        )

        def make_slider(tooltip, on_changed, value=20, minimum=0, maximum=100):
            slider = QtWidgets.QSlider(Qt.Horizontal)
            slider.setRange(minimum, maximum)
            slider.setValue(value)
            slider.setMinimumWidth(dpix(120))
            slider.setToolTip(t(tooltip))
            slider.setStyleSheet(slider_ss)
            slider.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            slider.valueChanged.connect(on_changed)
            return slider

        content = QtWidgets.QWidget()
        grid = QtWidgets.QGridLayout(content)
        grid.setContentsMargins(dpix(8), dpix(6), dpix(8), dpix(6))
        grid.setHorizontalSpacing(dpix(6))
        grid.setVerticalSpacing(dpix(6))

        def label(text):
            lbl = QtWidgets.QLabel(t(text))
            lbl.setStyleSheet(f"color: {p.text_muted}; font-size: {dpix(11)}px;")
            return lbl

        self._row_thumb_fit_btn = self._create_thumb_fit_button("row")
        self._apply_thumb_fit_button("row")
        self._row_opacity_slider = make_slider("Row thumbnail opacity", self._on_row_opacity_changed)
        grid.addWidget(label("Original"), 0, 0)
        grid.addWidget(self._row_thumb_fit_btn, 0, 1)
        grid.addWidget(self._row_opacity_slider, 0, 2)

        self._sel_thumb_fit_btn = self._create_thumb_fit_button("sel")
        self._apply_thumb_fit_button("sel")
        self._sel_opacity_slider = make_slider("Selected thumbnail opacity", self._on_sel_opacity_changed)
        grid.addWidget(label("Result"), 1, 0)
        grid.addWidget(self._sel_thumb_fit_btn, 1, 1)
        grid.addWidget(self._sel_opacity_slider, 1, 2)

        self._preview_row_height_slider = make_slider(
            "Preview row height",
            self._on_preview_row_height_changed,
            value=0,
            minimum=0,
            maximum=200,
        )
        grid.addWidget(label("Preview row height"), 2, 0)
        grid.addWidget(self._preview_row_height_slider, 2, 2)

        grid.addWidget(label("Panel layout"), 3, 0)
        grid.addWidget(self._create_direction_selector("outer"), 3, 2)
        grid.addWidget(label("Preview layout"), 4, 0)
        grid.addWidget(self._create_direction_selector("inner"), 4, 2)

        self._scroll_sync_check = QtWidgets.QCheckBox()
        self._scroll_sync_check.setChecked(self._scroll_sync_enabled)
        self._scroll_sync_check.setCursor(Qt.PointingHandCursor)
        self._scroll_sync_check.setStyleSheet(f"QCheckBox {{ color: {p.text_muted}; font-size: {dpix(11)}px; }}")
        self._scroll_sync_check.toggled.connect(self._on_scroll_sync_toggled)
        grid.addWidget(label("Sync scroll with editor"), 5, 0)
        grid.addWidget(self._scroll_sync_check, 5, 2)

        self._thumb_res_slider = make_slider(
            "Thumbnail load resolution",
            self._on_thumb_resolution_changed,
            value=self.THUMB_RESOLUTIONS.index(self._thumb_resolution),
            minimum=0,
            maximum=len(self.THUMB_RESOLUTIONS) - 1,
        )
        self._thumb_res_slider.setSingleStep(1)
        self._thumb_res_slider.setPageStep(1)
        self._thumb_res_value = label(f"{self._thumb_resolution}px")
        res_holder = QtWidgets.QWidget()
        res_row = QtWidgets.QHBoxLayout(res_holder)
        res_row.setContentsMargins(0, 0, 0, 0)
        res_row.setSpacing(dpix(6))
        res_row.addWidget(self._thumb_res_slider, 1)
        res_row.addWidget(self._thumb_res_value)
        grid.addWidget(label("Thumbnail resolution"), 6, 0)
        grid.addWidget(res_holder, 6, 2)

        return content

    def _create_direction_selector(self, scope: str):
        p = self._p
        holder = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(dpix(4))
        group = QtWidgets.QButtonGroup(holder)
        group.setExclusive(True)
        buttons = {}
        current = self._outer_dir if scope == "outer" else self._inner_dir
        for token in DIRECTIONS:
            button = QtWidgets.QToolButton()
            button.setCheckable(True)
            button.setIconSize(QtCore.QSize(dpix(16), dpix(16)))
            button.setIcon(themed_icon(DIRECTION_ICONS[token], margin=0.0))
            button.setCursor(Qt.PointingHandCursor)
            button.setChecked(token == current)
            button.setStyleSheet(
                f"QToolButton {{ background: {p.bg_secondary}; "
                f"border: 1px solid {p.border_default}; border-radius: {dpix(2)}px; "
                f"padding: {dpix(3)}px; }}"
                f"QToolButton:hover {{ background: {p.bg_hover}; }}"
                f"QToolButton:checked {{ background: {p.bg_hover}; border-color: {p.text_accent}; }}"
            )
            button.clicked.connect(lambda _c, s=scope, tk=token: self._set_split_direction(s, tk))
            group.addButton(button)
            row.addWidget(button)
            buttons[token] = button
        row.addStretch(1)
        setattr(self, f"_{scope}_dir_buttons", buttons)
        return holder

    def _set_split_direction(self, scope: str, token: str):
        splitter = self._split if scope == "outer" else self._inner_split
        splitter.set_direction(token)
        if scope == "outer":
            self._outer_dir = splitter.direction
        else:
            self._inner_dir = splitter.direction
        buttons = getattr(self, f"_{scope}_dir_buttons", None)
        if buttons:
            active = self._outer_dir if scope == "outer" else self._inner_dir
            for tk, button in buttons.items():
                old = button.blockSignals(True)
                button.setChecked(tk == active)
                button.blockSignals(old)
        self._refresh_overlays()

    def _toggle_thumb_settings_popup(self):
        popup = self._thumb_settings_popup
        if popup is not None and popup.isVisible():
            popup.close()
            return
        if popup is None:
            popup = PopupBase(self)
            p = self._p
            popup.setStyleSheet(f"PopupBase {{ background: {p.bg_elevated}; border: 1px solid {p.border_default}; border-radius: {dpix(6)}px; }}")
            QtWidgets.QVBoxLayout(popup).setContentsMargins(0, 0, 0, 0)
            popup.set_content_widget(self._thumb_settings_content)
            self._thumb_settings_popup = popup
        popup.show_below(self._thumb_settings_btn, align=Qt.AlignRight)

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
            "preview_row_ratio": self._preview_row_height_slider.value(),
            "scroll_sync_enabled": self._scroll_sync_enabled,
            "thumb_resolution": self._thumb_resolution,
            "outer_dir": self._split.direction,
            "outer_sizes": self._split.ordered_sizes(),
            "inner_dir": self._inner_split.direction,
            "inner_sizes": self._inner_split.ordered_sizes(),
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
        if "preview_row_ratio" in state:
            self._preview_row_height_slider.setValue(state["preview_row_ratio"])
        if "scroll_sync_enabled" in state:
            self._scroll_sync_check.setChecked(bool(state["scroll_sync_enabled"]))
        if "thumb_resolution" in state and state["thumb_resolution"] in self.THUMB_RESOLUTIONS:
            self._thumb_res_slider.setValue(self.THUMB_RESOLUTIONS.index(state["thumb_resolution"]))
        if state.get("outer_dir"):
            self._set_split_direction("outer", state["outer_dir"])
        if state.get("inner_dir"):
            self._set_split_direction("inner", state["inner_dir"])
        if state.get("outer_sizes"):
            self._split.apply_ordered_sizes(state["outer_sizes"])
        if state.get("inner_sizes"):
            self._inner_split.apply_ordered_sizes(state["inner_sizes"])
        self._apply_preview_row_height()

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
        vp = self._orig_view.viewport()
        first = self._orig_view.indexAt(vp.rect().topLeft()).row()
        last = self._orig_view.indexAt(vp.rect().bottomLeft()).row()
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
            self._orig_view.viewport()
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
        self._request_thumbs(entering_need_load)

    def _reset_thumb_requests(self):
        for token in self._thumb_tokens.values():
            token.cancel()
        self._thumb_tokens.clear()
        self._thumb_visible = set()

    def _request_thumbs(self, rows):
        rows_tokens = []
        for r in rows:
            if not (0 <= r < len(self._paths)):
                continue
            old = self._thumb_tokens.pop(r, None)
            if old:
                old.cancel()
            token = CancelToken()
            self._thumb_tokens[r] = token
            rows_tokens.append((r, self._paths[r], token))
        if not rows_tokens:
            return
        thumb_size = QtCore.QSize(dpix(self._thumb_resolution), dpix(self._thumb_resolution))

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
                self._dispatcher.invoke(lambda r=_r, k=key, im=img, t=tok: t.is_cancelled() or self._on_thumbnail_loaded(r, k, im))

        self._dispatcher.post(task)

    def _on_thumbnail_loaded(self, row, key, img):
        if 0 <= row < len(self._paths) and str(self._paths[row]) == key:
            self._thumb_tokens.pop(row, None)
        self._thumb_cache[key] = QtGui.QPixmap.fromImage(img) if img and not img.isNull() else QtGui.QPixmap()
        while len(self._thumb_cache) > self.THUMB_CACHE_LIMIT:
            self._thumb_cache.popitem(last=False)
        self._refresh_overlays()

    def _refresh_overlays(self):
        for overlay in self._overlays:
            overlay.update()

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
        current = table.currentIndex()
        if current.isValid() and 0 <= current.row() < len(self._paths):
            return current.row()
        if selected is not None:
            indexes = [index for index in selected.indexes() if index.isValid()]
            if indexes:
                return indexes[-1].row()
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

    def _select_view_rows(self, view, rows, anchor=None):
        selection_model = view.selectionModel()
        if selection_model is None:
            return
        if not rows:
            selection_model.clearSelection()
            return
        column = self._view_column.get(view, 0)
        selection = self._build_row_selection(self._preview_model, rows, column)
        current_row = anchor if anchor is not None and anchor >= 0 else rows[-1]
        selection_model.select(selection, QtCore.QItemSelectionModel.ClearAndSelect)
        selection_model.setCurrentIndex(self._preview_model.index(current_row, column), QtCore.QItemSelectionModel.NoUpdate)

    def _select_preview_rows(self, rows, anchor=None, exclude=None):
        for view in self._preview_views:
            if view is exclude:
                continue
            self._select_view_rows(view, rows, anchor)

    def _select_segment_rows(self, rows, anchor=None):
        selection_model = self._seg_table.selectionModel()
        if selection_model is None:
            return
        if not rows:
            selection_model.clearSelection()
            return
        selection = self._build_row_selection(self._seg_model, rows, 0, 0)
        current_row = anchor if anchor is not None and anchor >= 0 else rows[-1]
        selection_model.select(selection, QtCore.QItemSelectionModel.ClearAndSelect)
        selection_model.setCurrentIndex(self._seg_model.index(current_row, 0), QtCore.QItemSelectionModel.NoUpdate)

    def _scroll_anchor_into_view(self, anchor):
        if not self._scroll_sync_enabled:
            return
        if anchor is None or anchor < 0 or anchor >= len(self._paths):
            return
        bar = self._orig_view.verticalScrollBar()
        row_h = self._orig_view.verticalHeader().defaultSectionSize() or 1
        vp_h = self._orig_view.viewport().height()
        top = anchor * row_h
        bottom = top + row_h
        view_top = bar.value()
        if top >= view_top and bottom <= view_top + vp_h:
            return
        target = top if top < view_top else bottom - vp_h
        bar.setValue(max(0, min(target, bar.maximum())))

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
            elif row not in self._thumb_tokens:
                self._request_thumbs([row])
            return pix
        return None

    def _on_view_selection(self, source):
        if self._syncing_selection:
            return
        self._syncing_selection = True
        try:
            rows = self._selected_rows(source)
            self._selected_row = self._selection_anchor_row(source) if rows else -1
            self._select_preview_rows(rows, self._selected_row, exclude=source)
            self._select_segment_rows(rows, self._selected_row)
        finally:
            self._syncing_selection = False
            self._scroll_anchor_into_view(self._selected_row)
            self._refresh_overlays()

    def eventFilter(self, obj, event):
        for view in self._preview_views:
            if obj is view.viewport():
                if event.type() in (QtCore.QEvent.Resize, QtCore.QEvent.Paint):
                    overlay = self._orig_overlay if view is self._orig_view else self._result_overlay
                    overlay.setGeometry(view.viewport().rect())
                    overlay.raise_()
                    if event.type() == QtCore.QEvent.Resize:
                        overlay.update()
                        self._apply_preview_row_height()
                        self._update_visible_thumbnails()
                break
        if obj is self._status and event.type() == QtCore.QEvent.MouseButtonPress:
            self._scroll_to_next_issue()
            return True
        return super().eventFilter(obj, event)

    def _sync_preview_scroll(self, source):
        if self._syncing:
            return
        self._syncing = True
        try:
            val = source.verticalScrollBar().value()
            for view in self._preview_views:
                if view is not source:
                    view.verticalScrollBar().setValue(val)
            row_h = source.verticalHeader().defaultSectionSize() or 1
            self._display_offset = val - self._seg_table.verticalScrollBar().value() * row_h
        finally:
            self._syncing = False
        self._refresh_overlays()
        self._update_visible_thumbnails()

    def _sync_from_seg(self, val):
        if self._syncing or not self._scroll_sync_enabled:
            return
        self._syncing = True
        try:
            row_h = self._orig_view.verticalHeader().defaultSectionSize() or 1
            target = val * row_h + self._display_offset
            for view in self._preview_views:
                bar = view.verticalScrollBar()
                bar.setValue(max(bar.minimum(), min(target, bar.maximum())))
        finally:
            self._syncing = False
        self._refresh_overlays()
        self._update_visible_thumbnails()

    def _on_seg_selection(self, selected=None, _deselected=None):
        if self._syncing_selection:
            return
        self._syncing_selection = True
        try:
            rows = self._selected_rows(self._seg_table)
            self._selected_row = self._selection_anchor_row(self._seg_table, selected) if rows else -1
            self._select_preview_rows(rows, self._selected_row)
        finally:
            self._syncing_selection = False
            self._scroll_anchor_into_view(self._selected_row)
            self._refresh_overlays()

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
            for view in self._preview_views:
                column = self._view_column.get(view, 0)
                index = self._preview_model.index(target, column)
                if index.isValid():
                    view.setCurrentIndex(index)
                    view.scrollTo(index, QtWidgets.QAbstractItemView.EnsureVisible)
            seg_index = self._seg_model.index(target, 0)
            if seg_index.isValid():
                self._seg_table.setCurrentIndex(seg_index)
                self._seg_table.scrollTo(seg_index, QtWidgets.QAbstractItemView.EnsureVisible)
        finally:
            self._syncing_selection = False
            self._refresh_overlays()

    def _on_row_opacity_changed(self, value):
        for overlay in self._overlays:
            overlay.set_row_opacity(value / 100.0)

    def _on_sel_opacity_changed(self, value):
        for overlay in self._overlays:
            overlay.set_sel_opacity(value / 100.0)

    def _on_preview_row_height_changed(self, value):
        self._apply_preview_row_height()

    def _on_scroll_sync_toggled(self, checked):
        self._scroll_sync_enabled = checked
        if checked:
            row_h = self._orig_view.verticalHeader().defaultSectionSize() or 1
            val = self._orig_view.verticalScrollBar().value()
            self._display_offset = val - self._seg_table.verticalScrollBar().value() * row_h

    def _on_thumb_resolution_changed(self, index):
        index = max(0, min(index, len(self.THUMB_RESOLUTIONS) - 1))
        res = self.THUMB_RESOLUTIONS[index]
        if res == self._thumb_resolution:
            return
        self._thumb_resolution = res
        self._thumb_res_value.setText(f"{res}px")
        for token in self._thumb_tokens.values():
            token.cancel()
        self._thumb_tokens.clear()
        self._thumb_cache.clear()
        self._thumb_visible.clear()
        self._update_visible_thumbnails()
        self._refresh_overlays()

    def _apply_preview_row_height(self):
        col_w = self._orig_view.viewport().width()
        ratio = self._preview_row_height_slider.value() / 100.0
        height = max(dpix(20), round(col_w * ratio))
        for view in self._preview_views:
            view.verticalHeader().setDefaultSectionSize(height)
            view.updateGeometries()
        self._refresh_overlays()
        self._update_visible_thumbnails()

    def _normalise_thumb_fit_mode(self, fit_mode):
        return fit_mode if fit_mode in self.THUMB_FIT_MODES else self.THUMB_FIT_COVER

    def _set_thumb_fit_mode(self, side, fit_mode):
        normalised = self._normalise_thumb_fit_mode(fit_mode)
        if side == "row":
            self._row_thumb_fit_mode = normalised
            for overlay in self._overlays:
                overlay.set_row_fit_mode(normalised)
        elif side == "sel":
            self._sel_thumb_fit_mode = normalised
            for overlay in self._overlays:
                overlay.set_sel_fit_mode(normalised)
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
    def _sort_key_fn(kind, section):
        if kind == "preview":
            if section == 0:
                return lambda r: natural_key(r.original)
            if section == 1:
                return lambda r: natural_key(r.new_name)
            return None
        if kind == "segment" and section >= 0:
            return lambda r: natural_key(r.segments[section] if section < len(r.segments) else "")
        return None

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
            self._update_visible_thumbnails()
        finally:
            self._refreshing = False
        for view in self._preview_views:
            view.updateGeometries()
        if self._pending_select_rows is not None:
            rows = [r for r in self._pending_select_rows if 0 <= r < len(self._paths)]
            self._pending_select_rows = None
            if rows:
                self._select_preview_rows(rows)
                self._select_segment_rows(rows)

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

    def _reorder_rows(self, source_rows, target):
        if self._is_segment_editing():
            return
        n = len(self._paths)
        src = sorted({r for r in source_rows if 0 <= r < n})
        if not src:
            return
        insert_at = target - sum(1 for r in src if r < target)
        triples = list(zip(self._paths, self._keys, self._results))
        src_set = set(src)
        moving = [triples[r] for r in src]
        rest = [item for i, item in enumerate(triples) if i not in src_set]
        new = rest[:insert_at] + moving + rest[insert_at:]
        if new == triples:
            return
        self._paths = [p for p, _, _ in new]
        self._keys = [k for _, k, _ in new]
        self._results = [r for _, _, r in new]
        self._pending_select_rows = list(range(insert_at, insert_at + len(moving)))
        self._reset_thumb_requests()
        self._refresh(auto_size=False)

    def _apply_sort(self, kind, section, ascending):
        if not self._results:
            return
        key_fn = self._sort_key_fn(kind, section)
        if key_fn is None:
            return
        triples = sorted(
            zip(self._paths, self._keys, self._results),
            key=lambda item: key_fn(item[2]),
            reverse=not ascending,
        )
        self._paths = [p for p, _, _ in triples]
        self._keys = [k for _, k, _ in triples]
        self._results = [r for _, _, r in triples]
        self._reset_thumb_requests()
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
            popup.move_requested.connect(lambda d, s=section: QtCore.QTimer.singleShot(0, lambda: self._move_column(s, d)))
            popup.remove_requested.connect(lambda s=section: QtCore.QTimer.singleShot(0, lambda: self._remove_column(s)))
            popup.sort_requested.connect(
                lambda asc, s=section: (
                    self._close_popup(),
                    self._apply_sort("segment", s, asc),
                )
            )
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
        geo = screen_geometry_for(below, header)
        if geo is None:
            return below
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
        self._columns.pop(idx)
        self._rebuild()

    def _move_column(self, idx, direction):
        new_idx = idx + direction
        if 0 <= new_idx < len(self._columns):
            self._columns[idx], self._columns[new_idx] = (
                self._columns[new_idx],
                self._columns[idx],
            )
            self._rebuild()

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

    def _on_row_context_preview(self, view, pos):
        index = view.indexAt(pos)
        if not index.isValid():
            return
        self._ensure_index_selected(view, index)
        self._show_row_menu(view, view.viewport().mapToGlobal(pos), clicked_index=index)

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
        items.extend(self._sort_menu_items(table, clicked_index))
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

    def _sort_target(self, table, clicked_index):
        if clicked_index is None or not clicked_index.isValid():
            return None
        if table in self._view_column:
            col = self._view_column[table]
            return "preview", col, PreviewModel.HEADERS[col]
        if table is self._seg_table and clicked_index.column() < len(self._columns):
            col = clicked_index.column()
            return "segment", col, self._columns[col].source.DISPLAY
        return None

    def _sort_menu_items(self, table, clicked_index):
        target = self._sort_target(table, clicked_index)
        if target is None or not self._results:
            return []
        kind, section, label = target
        return [
            "-",
            ActionKit.Action(
                path="inline.renamer.sort_asc",
                display=t('Sort by "{column}" ascending', column=label),
                translate=False,
                func=lambda ctx, k=kind, s=section: self._apply_sort(k, s, True),
            ),
            ActionKit.Action(
                path="inline.renamer.sort_desc",
                display=t('Sort by "{column}" descending', column=label),
                translate=False,
                func=lambda ctx, k=kind, s=section: self._apply_sort(k, s, False),
            ),
        ]

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
        inst = BatchRenameWidget._instance_ref
        if inst is not None:
            try:
                inst._restore_source_defaults()
                inst._restore_ui_from_state()
            except RuntimeError as e:
                AppLogger.warning("[BatchRenamer] restore_state failed", exc=e)

    def create_widget(self):
        widget = BatchRenameWidget()
        widget._restore_ui_from_state()
        return widget
