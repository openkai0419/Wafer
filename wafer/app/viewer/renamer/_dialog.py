from __future__ import annotations

import dataclasses
import os
from pathlib import Path
from typing import Any

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from ....builtins.rename_sources import ExtSource, NameSource
from ....core.color.theme import ThemeManager
from ....core.platform.file_operations import FileExecutor
from ....core.qt.dispatcher import Dispatcher, CancelToken
from ....core.qt.rate_limit import qt_throttle
from ....core.qt.thread import utility_pool
from ....utils.formatting import dpix, natural_key
from ....utils.logs import AppLogger
from ....utils.notifier import Notifier
from ._engine import PostProcess, RenameColumn, RenameEngine, RenameResult
from ._overlay import ThumbnailOverlay
from ._popup import ColumnSettingsPopup
from ._table import (
    PreviewModel, SegmentModel, PreviewDelegate, SyncedView, _ColorSet,
)
from ....plugin.rename.handler import rename_source_registry


_SQL_CHUNK_SIZE = 4000


def _fetch_metadata_sync(db_path, paths_str):
    import sqlite3
    result: dict[str, dict[str, str]] = {}
    if not db_path or not os.path.isfile(str(db_path)):
        return result
    try:
        uri = Path(db_path).resolve().as_uri()
        conn = sqlite3.connect(f'{uri}?mode=ro', uri=True, timeout=1.0)
        try:
            for start in range(0, len(paths_str), _SQL_CHUNK_SIZE):
                chunk = paths_str[start:start + _SQL_CHUNK_SIZE]
                placeholders = ','.join('?' * len(chunk))
                rows = conn.execute(
                    f'SELECT path, key, value FROM kv_all WHERE path IN ({placeholders})',
                    chunk,
                ).fetchall()
                for path, key, value in rows:
                    result.setdefault(path, {})[key] = value or ''
        finally:
            conn.close()
    except Exception as e:
        AppLogger.warning(f'Failed to fetch metadata for rename', exc=e)
    return result


_POST_FIELDS = frozenset(f.name for f in dataclasses.fields(PostProcess))


class BatchRenameDialog(QtWidgets.QDialog):
    _ADD_COL_LABEL = '+'
    _instance: BatchRenameDialog | None = None
    _saved_state: dict[str, Any] = {}
    _registered: bool = False

    @classmethod
    def open(
        cls,
        paths: list[Path],
        keys: list[str] | None = None,
        db_path: Any = None,
        parent: QtWidgets.QWidget | None = None,
    ) -> BatchRenameDialog:
        if cls._instance is not None:
            cls._instance.close()
            cls._instance = None
        dlg = cls(paths, keys=keys, db_path=db_path, parent=parent)
        cls._instance = dlg
        dlg.show()
        return dlg

    @classmethod
    def _ensure_registered(cls):
        if cls._registered:
            return
        cls._registered = True
        from ....core.state import StateStore
        StateStore.instance().register(
            'batch_rename',
            lambda: dict(cls._saved_state),
            cls._on_state_restore,
        )

    @classmethod
    def _on_state_restore(cls, state: dict):
        cls._saved_state = state

    def __init__(
        self,
        paths: list[Path],
        keys: list[str] | None = None,
        db_path: Any = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle('Batch Rename')
        self.setWindowFlags(self.windowFlags() | Qt.Tool)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.destroyed.connect(self._on_destroyed)

        self._dispatcher = Dispatcher(pool=utility_pool)
        self._init_cancel: CancelToken | None = None
        self._thumb_tokens: dict[int, CancelToken] = {}
        self._thumb_visible: set[int] = set()
        self._rename_cancel: CancelToken | None = None

        self._paths = list(paths)
        self._keys = list(keys) if keys else [str(p).replace('\\', '/') for p in paths]
        self._initial_keys = list(self._keys)
        self._initial_paths = list(paths)
        self._db_path = db_path
        self._metadata: dict[str, dict[str, str]] = {}

        self._columns: list[RenameColumn] = [RenameColumn(NameSource())]
        self._ext_column = RenameColumn(ExtSource())
        self._ensure_registered()
        self._restore_columns_from_state()
        self._excluded: list[Path] = []
        self._results: list[RenameResult] = []
        self._popup: ColumnSettingsPopup | None = None
        self._syncing = False
        self._syncing_selection = False
        self._refreshing = False
        self._refresh_cancel: CancelToken | None = None
        self._init_done = False
        self._selected_row = -1
        self._thumb_cache: dict[str, QtGui.QPixmap] = {}

        p = ThemeManager.instance().palette
        self._p = p

        self._mono = QtGui.QFont('Consolas')
        self._mono.setStyleHint(QtGui.QFont.Monospace)
        self._mono.setPixelSize(dpix(12))

        self.setStyleSheet(f"QDialog {{ background: {p.bg_primary}; }}")

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(dpix(8), dpix(8), dpix(8), dpix(8))
        root.setSpacing(dpix(6))

        title = QtWidgets.QLabel(self._title_text())
        self._title = title
        title.setStyleSheet(
            f"color: {p.text_primary}; font-size: {dpix(13)}px; font-weight: bold;"
        )
        root.addWidget(title)

        row_h = dpix(20)
        frame_ss = (
            f"QFrame {{ background: {p.bg_primary}; "
            f"border: 1px solid {p.border_default}; "
            f"border-radius: {dpix(4)}px; }}"
        )

        preview_frame = QtWidgets.QFrame()
        preview_frame.setStyleSheet(frame_ss)
        pf_lay = QtWidgets.QVBoxLayout(preview_frame)
        pf_lay.setContentsMargins(0, 0, 0, 0)
        pf_lay.setSpacing(0)

        self._seg_table = SyncedView(parent=self)
        self._preview = SyncedView(forward_target=self._seg_table, parent=self)

        self._preview_model = PreviewModel(self)
        self._seg_model = SegmentModel(self)
        colors = _ColorSet(p, self._mono)
        self._preview_model.set_colors(colors)
        self._seg_model.set_colors(colors)
        self._preview.setModel(self._preview_model)
        self._seg_table.setModel(self._seg_model)

        self._preview.setFont(self._mono)
        self._preview.setShowGrid(False)
        self._preview.verticalHeader().setVisible(False)
        self._preview.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self._preview.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
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
        ph.setStyleSheet(
            f"QHeaderView::section {{ background: {p.bg_secondary}; "
            f"color: {p.text_muted}; border: none; "
            f"border-bottom: 1px solid {p.border_subtle}; "
            f"font-size: {dpix(11)}px; padding: 0 {dpix(4)}px; }}"
            f"QHeaderView::section:hover {{ background: {p.bg_hover}; }}"
        )
        self._preview.setStyleSheet(
            f"QTableView {{ background: {p.bg_primary}; border: none; "
            f"color: {p.text_primary}; }}"
            f"QTableView::item {{ padding: 0 {dpix(4)}px; border: none; }}"
        )
        self._preview.setItemDelegate(PreviewDelegate(p.border_subtle, self._preview))
        self._preview.selectionModel().selectionChanged.connect(self._on_preview_selection)
        pf_lay.addWidget(self._preview)
        self._preview_frame = preview_frame
        root.addWidget(preview_frame, stretch=1)

        self._overlay = ThumbnailOverlay(self, self._preview,
                                         parent=self._preview.viewport())
        self._preview.viewport().installEventFilter(self)

        seg_frame = QtWidgets.QFrame()
        seg_frame.setStyleSheet(frame_ss)
        sf_lay = QtWidgets.QVBoxLayout(seg_frame)
        sf_lay.setContentsMargins(0, 0, 0, 0)
        sf_lay.setSpacing(0)

        self._seg_table.setFont(self._mono)
        self._seg_table.setShowGrid(True)
        self._seg_table.verticalHeader().setVisible(False)
        self._seg_table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self._seg_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self._seg_table.setEditTriggers(QtWidgets.QAbstractItemView.DoubleClicked)
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
            f"QHeaderView::section {{ background: {p.bg_elevated}; "
            f"color: {p.text_primary}; border: none; "
            f"border-right: 1px solid {p.border_subtle}; "
            f"border-bottom: 1px solid {p.border_default}; "
            f"font-size: {dpix(11)}px; font-weight: bold; "
            f"padding: 0 {dpix(4)}px; }}"
            f"QHeaderView::section:hover {{ background: {p.bg_hover}; }}"
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
        self._seg_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self._seg_table.customContextMenuRequested.connect(self._on_row_context)
        self._preview.setContextMenuPolicy(Qt.CustomContextMenu)
        self._preview.customContextMenuRequested.connect(self._on_row_context_preview)

        bar = QtWidgets.QHBoxLayout()
        bar.setContentsMargins(0, dpix(2), 0, 0)

        self._status = QtWidgets.QLabel()
        self._status.setStyleSheet(f"color: {p.text_muted}; font-size: {dpix(11)}px;")
        self._status.installEventFilter(self)
        bar.addWidget(self._status)
        bar.addStretch()

        opacity_slider = QtWidgets.QSlider(Qt.Horizontal)
        opacity_slider.setRange(0, 100)
        opacity_slider.setValue(20)
        opacity_slider.setFixedWidth(dpix(60))
        opacity_slider.setToolTip('Thumbnail opacity')
        opacity_slider.setStyleSheet(
            f"QSlider::groove:horizontal {{ background: {p.bg_hover}; "
            f"height: {dpix(4)}px; border-radius: {dpix(2)}px; }}"
            f"QSlider::handle:horizontal {{ background: {p.text_muted}; "
            f"width: {dpix(10)}px; margin: -{dpix(3)}px 0; "
            f"border-radius: {dpix(5)}px; }}"
        )
        opacity_slider.valueChanged.connect(self._on_opacity_changed)
        self._opacity_slider = opacity_slider
        bar.addWidget(opacity_slider)

        self._rename_btn = QtWidgets.QPushButton('Rename')
        self._rename_btn.setStyleSheet(
            f"QPushButton {{ background: {p.accent}; color: {p.accent_text}; "
            f"border: none; border-radius: {dpix(4)}px; "
            f"padding: {dpix(5)}px {dpix(16)}px; font-size: {dpix(12)}px; }}"
            f"QPushButton:hover {{ background: {p.accent}cc; }}"
            f"QPushButton:disabled {{ background: {p.bg_hover}; color: {p.text_muted}; }}"
        )
        self._rename_btn.clicked.connect(self._execute)
        bar.addWidget(self._rename_btn)

        cancel_btn = QtWidgets.QPushButton('Cancel')
        cancel_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {p.text_secondary}; "
            f"border: 1px solid {p.border_default}; border-radius: {dpix(4)}px; "
            f"padding: {dpix(5)}px {dpix(12)}px; font-size: {dpix(12)}px; }}"
            f"QPushButton:hover {{ background: {p.bg_hover}; }}"
        )
        cancel_btn.clicked.connect(self.close)
        bar.addWidget(cancel_btn)
        root.addLayout(bar)

        self._resize_to_content()

    @staticmethod
    def _on_destroyed():
        BatchRenameDialog._instance = None

    def _serialise_columns(self) -> dict[str, Any]:
        columns = []
        for col in self._columns:
            src_data = col.source.serialise()
            src_data.pop('overrides', None)
            columns.append({
                'source': src_data,
                'post': dataclasses.asdict(col.post),
                'enabled': col.enabled,
            })
        return {
            'columns': columns,
            'ext_post': dataclasses.asdict(self._ext_column.post),
            'ext_enabled': self._ext_column.enabled,
        }

    def _restore_columns_from_state(self):
        state = self._saved_state
        if not state or 'columns' not in state:
            return
        columns = []
        for col_data in state.get('columns', []):
            try:
                source = rename_source_registry.deserialise(col_data['source'])
                post_raw = col_data.get('post', {})
                post = PostProcess(**{k: v for k, v in post_raw.items() if k in _POST_FIELDS})
                columns.append(RenameColumn(source, post, col_data.get('enabled', True)))
            except Exception as e:
                AppLogger.warning(f'Failed to restore rename column: {e}', exc=e)
        if columns:
            self._columns = columns
        ext_raw = state.get('ext_post', {})
        if ext_raw:
            self._ext_column.post = PostProcess(**{k: v for k, v in ext_raw.items() if k in _POST_FIELDS})
        if 'ext_enabled' in state:
            self._ext_column.enabled = state['ext_enabled']

    def showEvent(self, event):
        super().showEvent(event)
        if not self._init_done:
            self._init_done = True
            self._rebuild()
            self._start_async_init()

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
            self._dispatcher.invoke(
                lambda: cancel.is_cancelled() or self._on_data_ready(metadata)
            )

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
        entering_need_load = [
            r for r in entering
            if 0 <= r < len(self._paths) and str(self._paths[r]) not in self._thumb_cache
        ]
        if not entering_need_load:
            return
        visible = self._visible_row_range()
        center = (visible.start + visible.stop) // 2
        entering_need_load.sort(key=lambda r: abs(r - center))
        cancel = CancelToken()
        rows_paths = [(r, self._paths[r]) for r in entering_need_load]
        for r, _ in rows_paths:
            old = self._thumb_tokens.pop(r, None)
            if old:
                old.cancel()
            self._thumb_tokens[r] = cancel
        thumb_size = QtCore.QSize(dpix(256), dpix(256))

        def task():
            from ....plugin import load_thumbnail
            for r, p in rows_paths:
                if cancel.is_cancelled():
                    return
                key = str(p)
                if key in self._thumb_cache:
                    continue
                try:
                    img = load_thumbnail(key, thumb_size)
                except Exception:
                    img = None
                if cancel.is_cancelled():
                    return
                self._dispatcher.invoke(
                    lambda k=key, im=img: cancel.is_cancelled() or self._on_thumbnail_loaded(k, im)
                )

        self._dispatcher.post(task, cancel=cancel)

    def _on_thumbnail_loaded(self, key, img):
        self._thumb_cache[key] = QtGui.QPixmap.fromImage(img) if img and not img.isNull() else QtGui.QPixmap()
        self._overlay.update()

    def closeEvent(self, event):
        BatchRenameDialog._saved_state = self._serialise_columns()
        if self._init_cancel:
            self._init_cancel.cancel()
        if self._refresh_cancel:
            self._refresh_cancel.cancel()
        for token in self._thumb_tokens.values():
            token.cancel()
        self._thumb_tokens.clear()
        if self._rename_cancel:
            self._rename_cancel.cancel()
        self._close_popup()
        super().closeEvent(event)

    def _title_text(self):
        t = f'Batch Rename \u2014 {len(self._paths)} files'
        if self._excluded:
            t += f'  ({len(self._excluded)} excluded)'
        return t

    def _thumb_for_row(self, row):
        if 0 <= row < len(self._paths):
            return self._thumb_cache.get(str(self._paths[row]))
        return None

    def _on_preview_selection(self):
        if self._syncing_selection:
            return
        rows = self._preview.selectionModel().selectedRows()
        self._selected_row = rows[0].row() if rows else -1
        self._syncing_selection = True
        if rows:
            self._seg_table.selectRow(rows[0].row())
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

    def _on_seg_selection(self):
        if self._syncing_selection:
            return
        rows = self._seg_table.selectionModel().selectedRows()
        if not rows:
            return
        row = rows[0].row()
        self._selected_row = row
        self._syncing_selection = True
        self._preview.selectRow(row)
        self._syncing_selection = False
        self._overlay.update()

    def _scroll_to_next_issue(self):
        if not self._results:
            return
        issue_rows = [
            i for i, r in enumerate(self._results)
            if r.conflict or r.errors or r.missing
        ]
        if not issue_rows:
            return
        current = self._selected_row
        target = next((r for r in issue_rows if r > current), issue_rows[0])
        self._preview.selectRow(target)
        self._seg_table.selectRow(target)

    def _on_opacity_changed(self, value):
        self._overlay.set_opacity(value / 100.0)

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
        self._refresh()

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

    def _rebuild(self):
        self._close_popup()
        self._seg_model.configure(
            self._columns,
            self._ADD_COL_LABEL,
            self._ext_column.source.DISPLAY,
        )
        self._refresh()

    def _refresh(self, prepare=None):
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
            if cancel.is_cancelled():
                return
            if prepare:
                paths, keys = prepare(paths, keys, results_snapshot)
            if cancel.is_cancelled():
                return
            results = RenameEngine.preview(
                paths, columns, ext_column, metadata,
                keys=keys, initial_keys=initial_keys,
            )
            if cancel.is_cancelled():
                return
            conflicts = sum(1 for r in results if r.conflict)
            errors = sum(1 for r in results if r.errors)
            missing = sum(1 for r in results if r.missing)
            self._dispatcher.invoke(
                lambda: cancel.is_cancelled() or self._on_refresh_done(
                    results, paths, keys, (conflicts, errors, missing),
                )
            )

        self._dispatcher.post(task, cancel=cancel)

    def _on_refresh_done(self, results, paths=None, keys=None, stats=None):
        self._refreshing = True
        if paths is not None:
            self._paths = paths
            self._keys = keys
        self._results = results
        self._preview_model.refresh(self._results)
        self._seg_model.refresh(self._results, self._paths)
        self._auto_size_segments()
        if stats:
            self._apply_status(*stats)
        self._update_visible_thumbnails()
        self._refreshing = False

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

    def _resize_to_content(self):
        row_h = dpix(20)
        n = min(len(self._paths), 18)
        table_h = n * row_h + dpix(26)
        seg_w = sum(
            self._seg_table.columnWidth(c)
            for c in range(self._seg_model.columnCount())
        )
        w = min(max(seg_w + dpix(350), dpix(550)), dpix(1400))
        h = min(max(2 * table_h + dpix(80), dpix(300)), dpix(900))
        self.resize(w, h)

    def _apply_status(self, conflicts, errors, missing):
        p = self._p
        issues = conflicts + errors + missing
        if issues:
            parts = []
            if conflicts:
                parts.append(f'{conflicts} conflict(s)')
            if errors:
                parts.append(f'{errors} invalid name(s)')
            if missing:
                parts.append(f'{missing} missing file(s)')
            self._status.setText(f'\u26a0 {" / ".join(parts)}')
            self._status.setStyleSheet(
                f"color: {p.warning}; font-size: {dpix(11)}px;"
            )
            self._status.setCursor(Qt.PointingHandCursor)
        else:
            ex = f' ({len(self._excluded)} excluded)' if self._excluded else ''
            self._status.setText(f'\u2713 {len(self._results)} files ready{ex}')
            self._status.setStyleSheet(
                f"color: {p.success}; font-size: {dpix(11)}px;"
            )
            self._status.setCursor(Qt.ArrowCursor)
        self._rename_btn.setEnabled(not issues and bool(self._results))

    def _on_preview_sort(self, section):
        if not self._results:
            return
        col = section

        def prepare(paths, keys, results):
            pairs = list(zip(paths, keys, results))
            if col == 0:
                pairs.sort(key=lambda x: natural_key(x[0].name))
            else:
                pairs.sort(key=lambda x: natural_key(x[2].new_name))
            return [p for p, _, _ in pairs], [k for _, k, _ in pairs]

        self._refresh(prepare=prepare)

    def _sort_by_segment(self, section, ascending):
        if not self._results:
            return
        sec, asc = section, ascending

        def prepare(paths, keys, results):
            pairs = list(zip(paths, keys, results))
            pairs.sort(
                key=lambda x: natural_key(
                    x[2].segments[sec] if sec < len(x[2].segments) else ''
                ),
                reverse=not asc,
            )
            return [p for p, _, _ in pairs], [k for _, k, _ in pairs]

        self._refresh(prepare=prepare)

    def _on_seg_header_click(self, section):
        if section == self._add_section:
            self._show_add_menu(section)
            return
        self._close_popup()

        is_ext = section == self._ext_section
        if section > self._ext_section:
            return

        column = self._ext_column if is_ext else self._columns[section]

        meta_keys = set()
        for m in self._metadata.values():
            meta_keys.update(m.keys())

        popup = ColumnSettingsPopup(
            column, is_ext=is_ext, meta_keys=sorted(meta_keys), parent=self,
        )
        popup.changed.connect(self._deferred_refresh)
        if not is_ext:
            popup.sort_requested.connect(
                lambda asc, s=section: (
                    self._close_popup(),
                    self._sort_by_segment(s, asc),
                )
            )
            popup.move_requested.connect(
                lambda d, s=section: QtCore.QTimer.singleShot(
                    0, lambda: self._move_column(s, d)
                )
            )
            popup.remove_requested.connect(
                lambda s=section: QtCore.QTimer.singleShot(
                    0, lambda: self._remove_column(s)
                )
            )
            popup.resequence_requested.connect(
                lambda: (
                    self._close_popup(),
                    self._resequence(),
                )
            )

        header = self._seg_table.horizontalHeader()
        sec_x = header.sectionPosition(section) - header.offset()
        gp = header.mapToGlobal(QtCore.QPoint(sec_x, header.height()))
        popup.adjustSize()
        popup.move(gp)
        popup._resize_and_clamp()
        self._popup = popup
        popup.show()

    def _deferred_refresh(self):
        QtCore.QTimer.singleShot(0, self._refresh)

    def _close_popup(self):
        popup = self._popup
        self._popup = None
        if popup:
            popup.close()

    def _show_add_menu(self, section):
        menu = QtWidgets.QMenu(self)
        for src_cls in rename_source_registry.list_all():
            if src_cls.NAME == 'ext':
                continue
            act = menu.addAction(src_cls.DISPLAY)
            act.triggered.connect(
                lambda _, c=src_cls: self._add_column(c)
            )
        header = self._seg_table.horizontalHeader()
        sec_x = header.sectionPosition(section) - header.offset()
        gp = header.mapToGlobal(QtCore.QPoint(sec_x, header.height()))
        menu.exec(gp)

    def _add_column(self, src_cls):
        self._columns.append(RenameColumn(src_cls()))
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
        self._refresh()

    def _exclude_row(self, row):
        if 0 <= row < len(self._paths):
            self._excluded.append(self._paths.pop(row))
            self._keys.pop(row)
            self._rebuild()
            self._title.setText(self._title_text())

    def _on_row_context(self, pos):
        row = self._seg_table.indexAt(pos).row()
        self._show_row_menu(row, self._seg_table.viewport().mapToGlobal(pos))

    def _on_row_context_preview(self, pos):
        row = self._preview.indexAt(pos).row()
        self._show_row_menu(row, self._preview.viewport().mapToGlobal(pos))

    def _show_row_menu(self, row, gpos):
        if row < 0 or row >= len(self._paths):
            return
        menu = QtWidgets.QMenu(self)
        act = menu.addAction(f'Exclude "{self._paths[row].name}"')
        act.triggered.connect(lambda: self._exclude_row(row))
        menu.exec(gpos)

    def _execute(self):
        if any(r.conflict or r.errors for r in self._results):
            return
        missing = [p for p, r in zip(self._paths, self._results) if not p.exists()]
        if missing:
            self._refresh()
            Notifier.warning(f'{len(missing)} file(s) no longer exist')
            return
        rename_map = self.get_rename_map()
        if not rename_map:
            return
        msg = QtWidgets.QMessageBox(self)
        msg.setWindowTitle('Confirm Rename')
        msg.setText(f'Rename {len(rename_map)} file(s)?')
        msg.setDetailedText(
            '\n'.join(f'{Path(o).name} \u2192 {Path(n).name}' for o, n in rename_map.items())
        )
        msg.setStandardButtons(QtWidgets.QMessageBox.Ok | QtWidgets.QMessageBox.Cancel)
        msg.setDefaultButton(QtWidgets.QMessageBox.Ok)
        if msg.exec() == QtWidgets.QMessageBox.Ok:
            self._do_rename(rename_map)

    def _do_rename(self, rename_map: dict[str, str]):
        self._rename_btn.setEnabled(False)
        self._rename_btn.setText('Renaming...')
        cancel = CancelToken()
        self._rename_cancel = cancel
        total = len(rename_map)
        items = list(rename_map.items())
        stride = max(1, total // 50)

        def task():
            executor = FileExecutor()
            failed = []
            for i, (old, new) in enumerate(items, 1):
                if cancel.is_cancelled():
                    break
                result = executor.rename(Path(old), Path(new).name)
                if result.status != "ok":
                    AppLogger.warning(f'Rename failed: {old} -> {new} ({result.error})')
                    failed.append(Path(old).name)
                if i % stride == 0 or i == total:
                    self._dispatcher.invoke(
                        lambda d=i: cancel.is_cancelled() or self._status.setText(f'Renaming... {d} / {total}')
                    )
            self._dispatcher.invoke(lambda: cancel.is_cancelled() or self._on_rename_complete(failed, total))

        self._dispatcher.post(task, cancel=cancel)

    def _on_rename_complete(self, failed, total):
        self._rename_cancel = None
        if failed:
            Notifier.warning(f'Failed to rename {len(failed)} file(s): {", ".join(failed[:3])}')
        else:
            Notifier.info(f'Renamed {total} file(s)')
        self.close()

    def get_rename_map(self) -> dict[str, str]:
        return {
            str(p): str(p.parent / r.new_name)
            for p, r in zip(self._paths, self._results)
            if p.name != r.new_name
        }
