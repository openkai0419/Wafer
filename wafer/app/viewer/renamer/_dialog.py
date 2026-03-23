from __future__ import annotations

import os
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from ....builtins.rename_sources import FixedSource, ExtSource, NameSource
from ....core.color.theme import ThemeManager
from ....core.platform.file_operations import FileExecutor
from ....utils.formatting import dpix, natural_key
from ....utils.logs import AppLogger
from ....utils.notifier import Notifier
from ....utils.paths import normalize_path
from ._engine import RenameColumn, RenameEngine, RenameResult
from ._overlay import ThumbnailOverlay
from ._popup import ColumnSettingsPopup
from ._table import PreviewDelegate, SyncedTable
from ....plugin.rename.handler import rename_source_registry


class BatchRenameDialog(QtWidgets.QDialog):
    _ADD_COL_LABEL = '+'

    def __init__(
        self,
        paths: list[Path],
        metadata: dict[str, dict[str, str]] | None = None,
        file_stats: dict[str, os.stat_result] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle('Batch Rename')

        self._paths = list(paths)
        self._initial_paths = list(paths)
        self._metadata: dict[str, dict[str, str]] = {
            normalize_path(k): v for k, v in (metadata or {}).items()
        }
        self._file_stats: dict[str, os.stat_result] = {
            normalize_path(k): v for k, v in (file_stats or {}).items()
        }
        for p in self._paths:
            key = normalize_path(p)
            if key not in self._file_stats:
                try:
                    self._file_stats[key] = p.stat()
                except OSError:
                    pass

        self._columns: list[RenameColumn] = [RenameColumn(NameSource())]
        self._ext_column = RenameColumn(ExtSource())
        self._excluded: list[Path] = []
        self._results: list[RenameResult] = []
        self._popup: ColumnSettingsPopup | None = None
        self._syncing = False
        self._refreshing = False
        self._selected_row = -1
        self._thumb_cache: dict[str, QtGui.QPixmap] = {}
        self._load_thumbnails()

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

        self._seg_table = SyncedTable(parent=self)
        self._preview = SyncedTable(forward_target=self._seg_table, parent=self)

        self._preview.setColumnCount(2)
        self._preview.setHorizontalHeaderLabels(['Original', 'Result'])
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
            f"QTableWidget {{ background: {p.bg_primary}; border: none; "
            f"color: {p.text_primary}; }}"
            f"QTableWidget::item {{ padding: 0 {dpix(4)}px; border: none; }}"
        )
        self._preview.setItemDelegate(PreviewDelegate(p.border_subtle, self._preview))
        self._preview.itemSelectionChanged.connect(self._on_preview_selection)
        pf_lay.addWidget(self._preview)
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
        self._seg_table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self._seg_table.setEditTriggers(QtWidgets.QAbstractItemView.DoubleClicked)
        self._seg_table.setFocusPolicy(Qt.NoFocus)
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
            f"QTableWidget {{ background: {p.bg_primary}; "
            f"gridline-color: {p.border_subtle}; border: none; "
            f"color: {p.text_primary}; }}"
            f"QTableWidget::item {{ padding: 0 {dpix(2)}px; }}"
        )
        sf_lay.addWidget(self._seg_table)
        root.addWidget(seg_frame, stretch=1)

        self._seg_table.verticalScrollBar().valueChanged.connect(self._sync_from_seg)
        self._preview.verticalScrollBar().valueChanged.connect(self._sync_from_preview)
        self._seg_table.cellChanged.connect(self._on_seg_cell_changed)
        self._seg_table.cellDoubleClicked.connect(self._on_seg_cell_dblclick)
        self._seg_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self._seg_table.customContextMenuRequested.connect(self._on_row_context)
        self._preview.setContextMenuPolicy(Qt.CustomContextMenu)
        self._preview.customContextMenuRequested.connect(self._on_row_context_preview)

        bar = QtWidgets.QHBoxLayout()
        bar.setContentsMargins(0, dpix(2), 0, 0)

        self._status = QtWidgets.QLabel()
        self._status.setStyleSheet(f"color: {p.text_muted}; font-size: {dpix(11)}px;")
        bar.addWidget(self._status)
        bar.addStretch()

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
        cancel_btn.clicked.connect(self.reject)
        bar.addWidget(cancel_btn)
        root.addLayout(bar)

        self._rebuild()
        self._resize_to_content()

    def _title_text(self):
        t = f'Batch Rename \u2014 {len(self._paths)} files'
        if self._excluded:
            t += f'  ({len(self._excluded)} excluded)'
        return t

    def _load_thumbnails(self):
        try:
            from ....plugin import load_thumbnail
            from PySide6.QtCore import QSize
            size = QSize(dpix(256), dpix(256))
            for p in self._paths:
                key = str(p)
                if key in self._thumb_cache:
                    continue
                img = load_thumbnail(key, size)
                if img and not img.isNull():
                    self._thumb_cache[key] = QtGui.QPixmap.fromImage(img)
                else:
                    self._thumb_cache[key] = QtGui.QPixmap()
        except Exception:
            pass

    def _thumb_for_row(self, row):
        if 0 <= row < len(self._paths):
            return self._thumb_cache.get(str(self._paths[row]))
        return None

    def _on_preview_selection(self):
        rows = self._preview.selectionModel().selectedRows()
        self._selected_row = rows[0].row() if rows else -1
        self._overlay.update()

    def eventFilter(self, obj, event):
        if obj is self._preview.viewport():
            if event.type() in (QtCore.QEvent.Resize, QtCore.QEvent.Paint):
                self._overlay.setGeometry(self._preview.viewport().rect())
                self._overlay.raise_()
                if event.type() == QtCore.QEvent.Resize:
                    self._overlay.update()
        return super().eventFilter(obj, event)

    def _sync_from_preview(self, val):
        if not self._syncing:
            self._syncing = True
            self._seg_table.verticalScrollBar().setValue(val)
            self._syncing = False
            self._overlay.update()

    def _sync_from_seg(self, val):
        if not self._syncing:
            self._syncing = True
            self._preview.verticalScrollBar().setValue(val)
            self._syncing = False
            self._overlay.update()

    def _on_seg_cell_changed(self, row, col):
        if self._refreshing:
            return
        if col < len(self._columns) and isinstance(self._columns[col].source, FixedSource):
            item = self._seg_table.item(row, col)
            if item and row < len(self._paths):
                path_key = str(self._paths[row])
                self._columns[col].source.overrides[path_key] = item.text()
                self._refresh()

    def _on_seg_cell_dblclick(self, row, col):
        if col < len(self._columns) and isinstance(self._columns[col].source, FixedSource):
            return
        self._on_seg_header_click(col)

    @property
    def _add_section(self):
        return len(self._columns)

    @property
    def _ext_section(self):
        return len(self._columns) + 1

    def _rebuild(self):
        self._close_popup()

        n = len(self._paths)
        seg_n = len(self._columns)
        total_cols = seg_n + 2

        self._preview.setRowCount(n)
        self._seg_table.setColumnCount(total_cols)
        self._seg_table.setRowCount(n)

        labels = []
        for col in self._columns:
            prefix = '' if col.enabled else '\u25cc '
            labels.append(f'{prefix}{col.source.DISPLAY} \u25bc')
        labels.append(self._ADD_COL_LABEL)
        labels.append(f'{self._ext_column.source.DISPLAY} \u25bc')
        self._seg_table.setHorizontalHeaderLabels(labels)

        self._refresh()

    def _refresh(self):
        self._refreshing = True
        self._results = RenameEngine.preview(
            self._paths,
            self._columns,
            self._ext_column,
            self._metadata,
            self._file_stats,
            initial_paths=self._initial_paths,
        )

        p = self._p
        muted = QtGui.QColor(p.text_muted)
        warn = QtGui.QColor(p.warning)
        ok = QtGui.QColor(p.text_primary)
        accent = QtGui.QColor(p.text_accent)
        err_bg = QtGui.QBrush(QtGui.QColor(p.bg_hover))
        disabled_fg = QtGui.QColor(p.text_muted)
        ext_bg = QtGui.QBrush(QtGui.QColor(p.bg_secondary))
        seg_n = len(self._columns)

        for row, r in enumerate(self._results):
            oi = QtWidgets.QTableWidgetItem(r.original)
            oi.setForeground(muted)
            self._preview.setItem(row, 0, oi)

            has_issue = r.conflict or r.errors
            text = f'\u26a0 {r.new_name}' if has_issue else r.new_name
            ri = QtWidgets.QTableWidgetItem(text)
            ri.setForeground(warn if has_issue else accent)
            if has_issue:
                ri.setBackground(err_bg)
            self._preview.setItem(row, 1, ri)

            for si in range(seg_n):
                val = r.segments[si] if si < len(r.segments) else ''
                it = QtWidgets.QTableWidgetItem(val)
                col_enabled = self._columns[si].enabled
                if not col_enabled:
                    it.setForeground(disabled_fg)
                else:
                    it.setForeground(warn if has_issue else ok)
                if isinstance(self._columns[si].source, FixedSource):
                    it.setFlags(it.flags() | Qt.ItemIsEditable)
                else:
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                self._seg_table.setItem(row, si, it)

            ext_val = r.segments[-1] if r.segments else ''
            ei = QtWidgets.QTableWidgetItem(ext_val)
            ei.setForeground(warn if has_issue else ok)
            ei.setBackground(ext_bg)
            self._seg_table.setItem(row, self._ext_section, ei)

            ai = QtWidgets.QTableWidgetItem('')
            ai.setFlags(Qt.NoItemFlags)
            self._seg_table.setItem(row, self._add_section, ai)

        self._auto_size_segments()
        self._update_status()
        self._refreshing = False

    def _auto_size_segments(self):
        fm = QtGui.QFontMetrics(self._mono)
        hdr_font = self._seg_table.horizontalHeader().font()
        hfm = QtGui.QFontMetrics(hdr_font)
        total = self._seg_table.columnCount()
        for col in range(total):
            if col == self._add_section:
                self._seg_table.setColumnWidth(col, dpix(24))
                continue
            hi = self._seg_table.horizontalHeaderItem(col)
            max_w = hfm.horizontalAdvance(hi.text()) if hi else 0
            for row in range(self._seg_table.rowCount()):
                item = self._seg_table.item(row, col)
                if item:
                    max_w = max(max_w, fm.horizontalAdvance(item.text()))
            self._seg_table.setColumnWidth(col, max(max_w + dpix(14), dpix(28)))

    def _resize_to_content(self):
        row_h = dpix(20)
        n = min(len(self._paths), 18)
        table_h = n * row_h + dpix(26)
        seg_w = sum(
            self._seg_table.columnWidth(c)
            for c in range(self._seg_table.columnCount())
        )
        w = min(max(seg_w + dpix(350), dpix(550)), dpix(1400))
        h = min(max(2 * table_h + dpix(80), dpix(300)), dpix(900))
        self.resize(w, h)

    def _update_status(self):
        p = self._p
        conflicts = sum(1 for r in self._results if r.conflict)
        errors = sum(1 for r in self._results if r.errors)
        issues = conflicts + errors
        if issues:
            parts = []
            if conflicts:
                parts.append(f'{conflicts} conflict(s)')
            if errors:
                parts.append(f'{errors} invalid name(s)')
            self._status.setText(f'\u26a0 {" / ".join(parts)}')
            self._status.setStyleSheet(
                f"color: {p.warning}; font-size: {dpix(11)}px;"
            )
        else:
            ex = f' ({len(self._excluded)} excluded)' if self._excluded else ''
            self._status.setText(f'\u2713 {len(self._results)} files ready{ex}')
            self._status.setStyleSheet(
                f"color: {p.success}; font-size: {dpix(11)}px;"
            )
        self._rename_btn.setEnabled(not issues and bool(self._results))

    def _on_preview_sort(self, section):
        if not self._results:
            return
        pairs = list(zip(self._paths, self._results))
        if section == 0:
            pairs.sort(key=lambda x: natural_key(x[0].name))
        else:
            pairs.sort(key=lambda x: natural_key(x[1].new_name))
        self._paths = [pp for pp, _ in pairs]
        self._refresh()

    def _sort_by_segment(self, section, ascending):
        if not self._results:
            return
        pairs = list(zip(self._paths, self._results))
        pairs.sort(
            key=lambda x: natural_key(
                x[1].segments[section] if section < len(x[1].segments) else ''
            ),
            reverse=not ascending,
        )
        self._paths = [pp for pp, _ in pairs]
        self._refresh()

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
        self._refresh()

    def _exclude_row(self, row):
        if 0 <= row < len(self._paths):
            self._excluded.append(self._paths.pop(row))
            self._rebuild()
            self._title.setText(self._title_text())

    def _on_row_context(self, pos):
        row = self._seg_table.rowAt(pos.y())
        self._show_row_menu(row, self._seg_table.viewport().mapToGlobal(pos))

    def _on_row_context_preview(self, pos):
        row = self._preview.rowAt(pos.y())
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
            self.accept()

    def _do_rename(self, rename_map: dict[str, str]):
        executor = FileExecutor()
        failed = []
        for old, new in rename_map.items():
            result = executor.rename(Path(old), Path(new).name)
            if result.status != "ok":
                AppLogger.warning(f'Rename failed: {old} -> {new} ({result.error})')
                failed.append(Path(old).name)
        if failed:
            Notifier.warning(f'Failed to rename {len(failed)} file(s): {", ".join(failed[:3])}')
        else:
            Notifier.info(f'Renamed {len(rename_map)} file(s)')

    def get_rename_map(self) -> dict[str, str]:
        return {
            str(p): str(p.parent / r.new_name)
            for p, r in zip(self._paths, self._results)
            if p.name != r.new_name
        }
