from __future__ import annotations

from pathlib import Path

from PySide6 import QtWidgets, QtCore, QtGui

from wafer.plugin import BasePanelPlugin, KeyFilter
from wafer.plugin.key_filter_dialog import FilterSaveConfirmDialog
from wafer.core.db.recollect import Recollect
from wafer.utils.formatting import dpix
from wafer.utils.logs import AppLogger
from wafer.utils.notifier import Notifier
from wafer.core.lang.manager import t
from wafer.core.qt.dispatcher import Dispatcher, CancelSlot
from wafer.core.qt.icon_engine import themed_icon
from wafer.core.qt.image import numpy_to_qimage
from wafer.plugin.imageloader.handler import image_loader_resolver
from wafer.utils.paths import list_setting_db_names

_PREFIX = "exiftool"


class ExifSettingsPanelPlugin(BasePanelPlugin):
    NAME = "exiftool_settings"
    DISPLAY_NAME = "ExifTool Preview"
    DEFAULT_ENABLED = True
    CLOSABLE = True
    PRIORITY = 50

    def create_widget(self) -> QtWidgets.QWidget:
        from .settings import migrate_legacy_filter

        migrate_legacy_filter()
        return ExifSettingsWidget()


class _ContainImageLabel(QtWidgets.QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(QtCore.Qt.AlignCenter)
        self._source: QtGui.QPixmap | None = None

    def set_source(self, pixmap: QtGui.QPixmap):
        self._source = pixmap
        self._update_scaled()

    def clear(self):
        self._source = None
        super().clear()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_scaled()

    def _update_scaled(self):
        if self._source is None or self._source.isNull():
            return
        self.setPixmap(self._source.scaled(self.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))


class ExifSettingsWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._dispatcher = Dispatcher()
        self._cancel = CancelSlot()
        self._meta: dict[str, str] = {}
        self._pending: dict[str, bool] = {}
        self._current_path: str | None = None
        self.setAcceptDrops(True)

        self._drop_label = QtWidgets.QLabel(t("Drop a file here to preview ExifTool tags"))
        self._drop_label.setAlignment(QtCore.Qt.AlignCenter)
        self._drop_label.setMinimumHeight(dpix(60))
        self._drop_label.setStyleSheet(f"border: {dpix(2)}px dashed palette(mid); border-radius: {dpix(6)}px; padding: {dpix(12)}px;")

        self._thumb = _ContainImageLabel()
        self._thumb.setMinimumWidth(dpix(160))
        self._thumb.setMinimumHeight(dpix(120))

        self._table = QtWidgets.QTableWidget()
        self._table.setColumnCount(3)
        self._table.setHorizontalHeaderLabels([t("Use"), t("Key"), t("Value")])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.Interactive)
        self._table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.Stretch)
        self._table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.cellChanged.connect(self._on_cell_changed)

        self._pending_group = QtWidgets.QGroupBox()
        self._pending_group.setMinimumWidth(dpix(220))
        self._pending_table = QtWidgets.QTableWidget()
        self._pending_table.setColumnCount(3)
        self._pending_table.setHorizontalHeaderLabels([t("Key"), t("State"), ""])
        self._pending_table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        self._pending_table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        self._pending_table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
        self._pending_table.verticalHeader().setVisible(False)
        self._pending_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self._pending_table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        pending_layout = QtWidgets.QVBoxLayout(self._pending_group)
        pending_layout.setContentsMargins(dpix(4), dpix(4), dpix(4), dpix(4))
        pending_layout.addWidget(self._pending_table)

        details_splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        details_splitter.setChildrenCollapsible(False)
        details_splitter.addWidget(self._thumb)
        details_splitter.addWidget(self._table)
        details_splitter.setStretchFactor(0, 0)
        details_splitter.setStretchFactor(1, 1)
        details_splitter.setSizes([dpix(220), dpix(780)])
        self._details_splitter = details_splitter

        content_splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        content_splitter.setChildrenCollapsible(False)
        content_splitter.addWidget(details_splitter)
        content_splitter.addWidget(self._pending_group)
        content_splitter.setStretchFactor(0, 1)
        content_splitter.setStretchFactor(1, 0)
        content_splitter.setSizes([dpix(520), dpix(220)])
        content_splitter.setVisible(False)
        self._content_splitter = content_splitter

        self._save_btn = QtWidgets.QPushButton(t("Save"))
        self._save_btn.clicked.connect(self._on_save)
        self._revert_btn = QtWidgets.QPushButton(t("Revert"))
        self._revert_btn.clicked.connect(self._on_revert)
        button_row = QtWidgets.QHBoxLayout()
        button_row.addStretch()
        button_row.addWidget(self._save_btn)
        button_row.addWidget(self._revert_btn)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(dpix(8), dpix(8), dpix(8), dpix(8))
        layout.setSpacing(dpix(4))
        layout.addWidget(self._drop_label)
        layout.addWidget(content_splitter, 1)
        layout.addLayout(button_row)
        self._rebuild_pending_table()
        self._update_buttons()

    def _update_buttons(self):
        dirty = bool(self._pending)
        self._save_btn.setEnabled(dirty)
        self._revert_btn.setEnabled(dirty)

    def _rebuild_pending_table(self):
        from wafer.core.color.theme import ThemeManager

        accent = QtGui.QColor(ThemeManager.instance().palette.text_accent)
        self._pending_group.setTitle(t("Edited keys ({n})").format(n=len(self._pending)))
        self._pending_table.setRowCount(0)
        self._pending_table.setRowCount(len(self._pending))
        for row, key in enumerate(sorted(self._pending)):
            enabled = self._pending[key]
            state_item = QtWidgets.QTableWidgetItem(t("Use") if enabled else t("Block"))
            state_item.setForeground(accent)
            self._pending_table.setItem(row, 0, QtWidgets.QTableWidgetItem(key))
            self._pending_table.setItem(row, 1, state_item)
            btn = QtWidgets.QToolButton()
            btn.setIcon(themed_icon("cross"))
            btn.setAutoRaise(True)
            btn.clicked.connect(lambda _=False, k=key: self._remove_pending(k))
            self._pending_table.setCellWidget(row, 2, btn)

    def _remove_pending(self, key: str):
        if self._pending.pop(key, None) is None:
            return
        self._rebuild_table()
        self._rebuild_pending_table()
        self._update_drop_label()
        self._update_buttons()

    def _effective_enabled(self, key: str) -> bool:
        if key in self._pending:
            return self._pending[key]
        return KeyFilter.is_enabled(_PREFIX, key)

    def dragEnterEvent(self, event: QtGui.QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event: QtGui.QDragMoveEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QtGui.QDropEvent):
        urls = event.mimeData().urls()
        if not urls:
            return
        path = urls[0].toLocalFile()
        if path:
            self._preview_file(path)

    def _preview_file(self, path: str):
        cancel = self._cancel.renew()

        def task():
            if cancel.is_cancelled():
                return
            try:
                from .parser import ExifToolProcess, flatten
                from ._downloader import get_exiftool_path

                exe = get_exiftool_path()
                if exe is None:
                    self._dispatcher.invoke(lambda: Notifier.warning("ExifTool not found"))
                    return
                proc = ExifToolProcess(exe)
                proc.start()
                try:
                    data = proc.query(path)
                finally:
                    proc.stop()
                if data is None:
                    self._dispatcher.invoke(lambda: Notifier.warning("ExifTool returned no data"))
                    return
                meta, _ = flatten(data)
            except Exception as e:
                AppLogger.warning(f"[ExifToolSettings] Preview failed: {e}", exc=e)
                msg = str(e)
                self._dispatcher.invoke(lambda: Notifier.warning(f"Preview failed: {msg}"))
                return
            if cancel.is_cancelled():
                return
            arr = image_loader_resolver.load(path, 512)
            qimage = numpy_to_qimage(arr) if arr is not None else None
            if cancel.is_cancelled():
                return
            self._dispatcher.invoke(lambda: self._apply_preview(path, meta, qimage, cancel))

        self._dispatcher.post(task)

    def _apply_preview(self, path: str, meta: dict, qimage: QtGui.QImage | None, cancel):
        if cancel.is_cancelled():
            return
        self._current_path = path
        self._meta = meta
        if qimage is not None:
            self._thumb.set_source(QtGui.QPixmap.fromImage(qimage))
        else:
            self._thumb.clear()
        self._rebuild_table()
        self._content_splitter.setVisible(True)
        self._update_drop_label()

    def _blocked_count(self) -> int:
        return sum(1 for k in self._meta if not self._effective_enabled(k))

    def _update_drop_label(self):
        if self._current_path:
            edited = len(self._pending)
            summary = f"{len(self._meta)} keys, {self._blocked_count()} blocked"
            if edited:
                summary += f", {edited} edited"
            self._drop_label.setText(f"Previewing: {Path(self._current_path).name} ({summary})")

    def _rebuild_table(self):
        from wafer.core.color.theme import ThemeManager

        palette = ThemeManager.instance().palette
        muted_fg = QtGui.QColor(palette.text_muted)
        edited_fg = QtGui.QColor(palette.text_accent)

        self._table.blockSignals(True)
        self._table.setRowCount(0)
        self._table.setRowCount(len(self._meta))
        for row, (key, value) in enumerate(sorted(self._meta.items())):
            enabled = self._effective_enabled(key)
            edited = key in self._pending
            check_item = QtWidgets.QTableWidgetItem()
            check_item.setFlags(check_item.flags() | QtCore.Qt.ItemIsUserCheckable)
            check_item.setCheckState(QtCore.Qt.Checked if enabled else QtCore.Qt.Unchecked)
            check_item.setData(QtCore.Qt.UserRole, key)
            key_item = QtWidgets.QTableWidgetItem(key)
            val_str = str(value) if value is not None else ""
            val_item = QtWidgets.QTableWidgetItem(val_str[:300])
            if not enabled:
                for item in (key_item, val_item):
                    font = item.font()
                    font.setStrikeOut(True)
                    item.setFont(font)
            if edited:
                for item in (key_item, val_item):
                    item.setForeground(edited_fg)
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
            elif not enabled:
                for item in (key_item, val_item):
                    item.setForeground(muted_fg)
            self._table.setItem(row, 0, check_item)
            self._table.setItem(row, 1, key_item)
            self._table.setItem(row, 2, val_item)
        self._table.blockSignals(False)

    def _on_cell_changed(self, row: int, column: int):
        if column != 0:
            return
        check_item = self._table.item(row, 0)
        if not check_item:
            return
        key = check_item.data(QtCore.Qt.UserRole)
        if not key:
            return
        enabled = check_item.checkState() == QtCore.Qt.Checked
        if enabled == KeyFilter.is_enabled(_PREFIX, key):
            self._pending.pop(key, None)
        else:
            self._pending[key] = enabled
        self._rebuild_table()
        self._rebuild_pending_table()
        self._update_drop_label()
        self._update_buttons()

    def _on_save(self):
        if not self._pending:
            return
        disabling = any(not enabled for enabled in self._pending.values())
        enabling = any(self._pending.values())
        dlg = FilterSaveConfirmDialog(
            [_PREFIX],
            parent=self,
            delete_label="Delete existing data",
            delete_default=disabling,
            recollect_default=enabling,
        )
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        changed = len(self._pending)
        KeyFilter.reload()
        delete_keys = [f"{_PREFIX}.{k}" for k, enabled in self._pending.items() if not enabled] if dlg.delete_data() else []
        KeyFilter.apply_key_states(_PREFIX, self._pending)
        db_names = list_setting_db_names()
        if (dlg.delete_data() or dlg.recollect()) and db_names and (delete_keys or dlg.recollect()):
            Recollect.reset(db_scope=list(db_names), collector=_PREFIX, keys=delete_keys, re_collect=dlg.recollect())
        self._pending.clear()
        self._rebuild_table()
        self._rebuild_pending_table()
        self._update_drop_label()
        self._update_buttons()
        Notifier.info(t("Filter settings saved ({n} changed)").format(n=changed))

    def _on_revert(self):
        if not self._pending:
            return
        self._pending.clear()
        self._rebuild_table()
        self._rebuild_pending_table()
        self._update_drop_label()
        self._update_buttons()
