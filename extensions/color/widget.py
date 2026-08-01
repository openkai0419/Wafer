from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from wafer.core.color.theme import ThemeManager
from wafer.core.commands.binding.instance_registry import InstanceRegistry
from wafer.core.lang.manager import t
from wafer.core.qt.icon_engine import themed_icon
from wafer.plugin.key_filter_dialog import FilterSaveConfirmDialog
from wafer.ui.popups import PopupBase
from wafer.ui.widgets.color_picker import ColorPickerDialog
from wafer.utils.formatting import dpix
from wafer.utils.notifier import Notifier
from wafer.utils.paths import list_setting_db_names

from ._color import normalize_hex, normalize_tolerance
from .settings import MAX_PALETTE_SLOTS, MIN_PALETTE_SLOTS, ColorSettings

_DEFAULT_COLOR = "#808080"
_DEFAULT_TOLERANCE = 0.20
_ROW_HEIGHT = 28


class ColorFilterWidget(QtWidgets.QWidget):
    changed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[_ColorRow] = []
        self._selected_row: _ColorRow | None = None
        self._last_tolerance = _DEFAULT_TOLERANCE
        self._build_ui()
        self.add_color(_DEFAULT_COLOR, _DEFAULT_TOLERANCE, emit=False)

    def _build_ui(self):
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(dpix(3))

        self._option_btn = QtWidgets.QToolButton(self)
        self._option_btn.setIcon(themed_icon("gear_small"))
        self._option_btn.setToolTip(t("Color filter options"))
        self._option_btn.setFixedSize(dpix(28), dpix(24))
        self._option_btn.clicked.connect(self._toggle_popup)
        layout.addWidget(self._option_btn)

        self._row_box = QtWidgets.QWidget(self)
        self._row_layout = QtWidgets.QHBoxLayout(self._row_box)
        self._row_layout.setContentsMargins(0, 0, 0, 0)
        self._row_layout.setSpacing(dpix(2))
        self._row_layout.addStretch(1)
        layout.addWidget(self._row_box, 1)

        self._popup = _ColorSettingsPopup(self)
        self._popup.changed.connect(self.changed)
        self._popup.add_requested.connect(self._pick_new_color)

    def _toggle_popup(self):
        if self._popup.isVisible():
            self._popup.hide()
        else:
            self._popup.show_below(self._option_btn, align=QtCore.Qt.AlignRight)

    def _pick_new_color(self):
        color = ColorPickerDialog.get_color(_DEFAULT_COLOR, self, title=t("Pick search color"), scope="color")
        if color is None:
            return
        self.add_color(color.name(QtGui.QColor.HexRgb), self._last_tolerance)

    def add_color(self, hex_color: str, tolerance: int | float | None = None, *, emit: bool = True):
        if tolerance is None:
            tolerance = self._last_tolerance
        row = _ColorRow(hex_color, tolerance, self._row_box)
        row.changed.connect(lambda r=row: self._on_row_changed(r))
        row.selected.connect(self._select_row)
        row.reorder_requested.connect(self._reorder_row_at)
        row.remove_requested.connect(lambda r=row: self._remove_row(r))
        self._last_tolerance = row.tolerance()
        self._rows.append(row)
        self._row_layout.insertWidget(self._row_layout.count() - 1, row)
        if emit:
            self.changed.emit()

    def _reorder_row_at(self, row: object, global_pos: QtCore.QPoint):
        if not isinstance(row, _ColorRow) or row not in self._rows or len(self._rows) < 2:
            return
        target_index = self._drop_index_at(row, global_pos)
        current_index = self._rows.index(row)
        if target_index == current_index:
            return
        self._rows.pop(current_index)
        self._rows.insert(target_index, row)
        self._row_layout.removeWidget(row)
        self._row_layout.insertWidget(target_index, row)
        self.changed.emit()

    def _drop_index_at(self, dragged_row: _ColorRow, global_pos: QtCore.QPoint) -> int:
        local_pos = self._row_box.mapFromGlobal(global_pos)
        remaining_rows = [row for row in self._rows if row is not dragged_row]
        for index, row in enumerate(remaining_rows):
            center_x = row.x() + row.width() // 2
            if local_pos.x() < center_x:
                return index
        return len(remaining_rows)

    def _on_row_changed(self, row: object):
        if isinstance(row, _ColorRow) and row in self._rows:
            self._last_tolerance = row.tolerance()
        self.changed.emit()

    def _clear_peer_selections(self):
        search_container = InstanceRegistry.instance().get_one("SearchContainer")
        if search_container is None or not hasattr(search_container, "param_widgets"):
            return
        for widget in search_container.param_widgets("color") or []:
            if widget is self or not hasattr(widget, "clear_selection"):
                continue
            widget.clear_selection()

    def _select_row(self, row: object):
        if not isinstance(row, _ColorRow) or row not in self._rows:
            return
        if self._selected_row is row:
            row.set_selected(False)
            self._selected_row = None
            return
        if self._selected_row is not None and self._selected_row is not row:
            self._selected_row.set_selected(False)
        self._selected_row = row
        row.set_selected(True)
        self._clear_peer_selections()

    def clear_selection(self):
        if self._selected_row is None:
            return
        self._selected_row.set_selected(False)
        self._selected_row = None

    def has_selection(self) -> bool:
        return self._selected_row in self._rows

    def replace_selected_color(self, hex_color: str) -> bool:
        if self._selected_row not in self._rows:
            return False
        changed = self._selected_row.set_hex(hex_color)
        if changed:
            self.changed.emit()
        return changed

    def _remove_row(self, row):
        if row not in self._rows:
            return
        self._rows.remove(row)
        if self._selected_row is row:
            self._selected_row = None
        self._row_layout.removeWidget(row)
        row.setParent(None)
        row.deleteLater()
        self.changed.emit()

    def read_params(self) -> dict:
        return {
            "colors": [params for row in self._rows if (params := row.read_params()).get("hex")],
            "mode": self._popup.mode(),
        }

    def write_params(self, params: dict):
        self.blockSignals(True)
        self.clear_selection()
        for row in list(self._rows):
            self._discard_row(row)
        try:
            self._popup.set_mode(str(params.get("mode") or "OR"))
            colors = params.get("colors") or []
            for item in colors:
                if not isinstance(item, dict):
                    continue
                hex_color = normalize_hex(str(item.get("hex") or ""))
                if not hex_color:
                    continue
                self.add_color(hex_color, normalize_tolerance(item.get("tolerance", _DEFAULT_TOLERANCE)), emit=False)
            if not self._rows:
                self.add_color(_DEFAULT_COLOR, _DEFAULT_TOLERANCE, emit=False)
        finally:
            self.blockSignals(False)
        self.changed.emit()

    def _discard_row(self, row):
        if row not in self._rows:
            return
        self._rows.remove(row)
        if self._selected_row is row:
            self._selected_row = None
        self._row_layout.removeWidget(row)
        row.setParent(None)
        row.deleteLater()


class _ColorSettingsPopup(PopupBase):
    changed = QtCore.Signal()
    add_requested = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = ColorSettings.instance()
        self.setWindowTitle(t("Color Filter Options"))
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(dpix(12), dpix(8), dpix(12), dpix(8))
        layout.setSpacing(dpix(6))

        title = QtWidgets.QLabel(t("Color Filter Options"), self)
        title.setStyleSheet(f"font-weight: bold; padding-bottom: {dpix(3)}px;")
        layout.addWidget(title)

        mode_row = QtWidgets.QHBoxLayout()
        mode_row.setSpacing(dpix(4))
        mode_row.addWidget(QtWidgets.QLabel(t("Match:"), self))
        self._mode_group = QtWidgets.QButtonGroup(self)
        self._or_radio = QtWidgets.QRadioButton("OR", self)
        self._and_radio = QtWidgets.QRadioButton("AND", self)
        self._or_radio.setChecked(True)
        self._mode_group.addButton(self._or_radio)
        self._mode_group.addButton(self._and_radio)
        self._or_radio.toggled.connect(lambda _checked: self.changed.emit())
        self._and_radio.toggled.connect(lambda _checked: self.changed.emit())
        mode_row.addWidget(self._or_radio)
        mode_row.addWidget(self._and_radio)
        mode_row.addStretch()
        layout.addLayout(mode_row)

        slots_row = QtWidgets.QHBoxLayout()
        slots_row.setSpacing(dpix(4))
        slots_row.addWidget(QtWidgets.QLabel(t("Palette count:"), self))
        self._slots_spin = QtWidgets.QSpinBox(self)
        self._slots_spin.setRange(MIN_PALETTE_SLOTS, MAX_PALETTE_SLOTS)
        self._slots_spin.setValue(self._settings.palette_slots())
        self._slots_spin.setToolTip(t("Number of palette colors to collect and search"))
        slots_row.addWidget(self._slots_spin)
        slots_row.addStretch()
        layout.addLayout(slots_row)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.setSpacing(dpix(4))
        btn_row.addStretch()
        revert_btn = QtWidgets.QPushButton(t("Revert"), self)
        revert_btn.setIcon(themed_icon("refresh"))
        revert_btn.clicked.connect(self._on_revert)
        save_btn = QtWidgets.QPushButton(t("Save"), self)
        save_btn.setIcon(themed_icon("save"))
        save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(revert_btn)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

        add_btn = QtWidgets.QPushButton(t("Add color..."), self)
        add_btn.setIcon(themed_icon("plus"))
        add_btn.clicked.connect(self.add_requested.emit)
        layout.addWidget(add_btn)

        self._settings.changed.connect(self._sync_palette_slots)

    def mode(self) -> str:
        return "AND" if self._and_radio.isChecked() else "OR"

    def set_mode(self, mode: str):
        radio = self._and_radio if str(mode).upper() == "AND" else self._or_radio
        radio.blockSignals(True)
        radio.setChecked(True)
        radio.blockSignals(False)

    def _on_save(self):
        value = self._slots_spin.value()
        if value == self._settings.palette_slots():
            Notifier.info(t("No changes to save"))
            return

        dlg = FilterSaveConfirmDialog(
            ["color"],
            parent=self,
            title="Save Color Settings",
            intro="Settings have been modified.\nThis will apply to all databases.",
            delete_label="Delete existing Color data",
            delete_default=True,
            recollect_default=True,
        )
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        do_delete = dlg.delete_data()
        do_recollect = dlg.recollect()

        value = self._settings.save_palette_slots(value)

        if do_delete or do_recollect:
            db_names = list_setting_db_names()
            if db_names:
                self._send_delete_and_recollect(db_names, delete=do_delete, re_collect=do_recollect)

        if do_recollect:
            message = t("Color settings saved, deletion and re-collection requested (palette slots={slots})", slots=value)
        elif do_delete:
            message = t("Color settings saved, existing data deletion requested (palette slots={slots})", slots=value)
        else:
            message = t("Color settings saved (palette slots={slots})", slots=value)
        Notifier.info(message)

    def _on_revert(self):
        self._sync_palette_slots()

    @QtCore.Slot()
    def _sync_palette_slots(self):
        self._slots_spin.blockSignals(True)
        self._slots_spin.setValue(self._settings.palette_slots())
        self._slots_spin.blockSignals(False)

    @staticmethod
    def _send_delete_and_recollect(db_names: list[str], *, delete: bool, re_collect: bool):
        from wafer.core.db.recollect import Recollect

        Recollect.reset(db_scope=list(db_names), collector="color", delete=delete, re_collect=re_collect)


class _ColorRow(QtWidgets.QFrame):
    changed = QtCore.Signal()
    selected = QtCore.Signal(object)
    reorder_requested = QtCore.Signal(object, QtCore.QPoint)
    remove_requested = QtCore.Signal(object)

    def __init__(self, hex_color: str, tolerance: int | float, parent=None):
        super().__init__(parent)
        self.setObjectName("colorSearchRow")
        self._hex = normalize_hex(hex_color) or _DEFAULT_COLOR
        self._selected = False
        self._build_ui()
        self._tolerance.setValue(normalize_tolerance(tolerance) * 100.0)
        self._sync_swatch()

    def _build_ui(self):
        self.setFixedHeight(dpix(_ROW_HEIGHT))
        self.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(dpix(3), 0, dpix(3), 0)
        layout.setSpacing(dpix(2))

        self._handle = _ColorDragHandle(self)
        self._handle.selected.connect(lambda: self.selected.emit(self))
        self._handle.dragged.connect(lambda pos: self.reorder_requested.emit(self, pos))
        layout.addWidget(self._handle)
        layout.addSpacing(dpix(2))

        self._swatch = QtWidgets.QToolButton(self)
        self._swatch.setFixedSize(dpix(30), dpix(20))
        self._swatch.setCursor(QtCore.Qt.PointingHandCursor)
        self._swatch.clicked.connect(self._on_swatch_clicked)
        layout.addWidget(self._swatch)

        self._tolerance = QtWidgets.QDoubleSpinBox(self)
        self._tolerance.setRange(0.0, 100.0)
        self._tolerance.setDecimals(1)
        self._tolerance.setSingleStep(1.0)
        self._tolerance.setFixedHeight(dpix(22))
        self._tolerance.setPrefix(t("Tolerance: "))
        self._tolerance.setSuffix("%")
        self._tolerance.setToolTip(t("Color tolerance"))
        self._tolerance.valueChanged.connect(self._on_tolerance_changed)
        self._tolerance.installEventFilter(self)
        self._tolerance.lineEdit().installEventFilter(self)
        layout.addWidget(self._tolerance)

        self._remove = QtWidgets.QToolButton(self)
        self._remove.setIcon(themed_icon("cross"))
        self._remove.setToolTip(t("Remove color"))
        self._remove.setFixedSize(dpix(20), dpix(20))
        self._remove.installEventFilter(self)
        self._remove.clicked.connect(lambda: self.remove_requested.emit(self))
        layout.addWidget(self._remove)
        self.installEventFilter(self)

    def eventFilter(self, obj, event):
        targets = (self, getattr(self, "_tolerance", None), self._tolerance.lineEdit() if hasattr(self, "_tolerance") else None, getattr(self, "_remove", None))
        if obj in targets and event.type() == QtCore.QEvent.MouseButtonPress:
            self.selected.emit(self)
        return super().eventFilter(obj, event)

    def _on_swatch_clicked(self):
        self.selected.emit(self)
        self._pick_color()

    def _on_tolerance_changed(self, value: float = 0.0):
        self._sync_swatch()
        self.changed.emit()

    def set_selected(self, selected: bool):
        selected = bool(selected)
        if self._selected == selected:
            return
        self._selected = selected
        self._sync_swatch()

    def set_hex(self, hex_color: str) -> bool:
        hex_color = normalize_hex(hex_color)
        if not hex_color or hex_color == self._hex:
            return False
        self._hex = hex_color
        self._sync_swatch()
        return True

    def tolerance(self) -> float:
        return normalize_tolerance(self._tolerance.value() / 100.0)

    def _pick_color(self):
        color = ColorPickerDialog.get_color(self._hex, self, title=t("Pick search color"), scope="color")
        if color is None:
            return
        if self.set_hex(color.name(QtGui.QColor.HexRgb)):
            self.changed.emit()

    def _sync_swatch(self):
        p = ThemeManager.instance().palette
        row_border = p.accent if self._selected else "transparent"
        row_border_width = dpix(1)
        self._swatch.setToolTip(f"{self._hex} / {self._tolerance.value():.0f}%")
        self.setStyleSheet(f"QFrame#colorSearchRow {{ border: {row_border_width}px solid {row_border}; border-radius: {dpix(3)}px; }}")
        self._swatch.setStyleSheet(
            f"QToolButton {{ background: {self._hex}; border: 1px solid {p.border_default}; border-radius: {dpix(3)}px; }}QToolButton:hover {{ border: {dpix(2)}px solid {p.text_primary}; }}"
        )

    def read_params(self) -> dict:
        self._sync_swatch()
        return {"hex": self._hex, "tolerance": self.tolerance(), "enabled": True}


class _ColorDragHandle(QtWidgets.QWidget):
    selected = QtCore.Signal()
    dragged = QtCore.Signal(QtCore.QPoint)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._press_pos = QtCore.QPoint()
        self._dragging = False
        self.setFixedSize(dpix(14), dpix(20))
        self.setCursor(QtCore.Qt.OpenHandCursor)

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self._press_pos = event.position().toPoint()
            self._dragging = False
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & QtCore.Qt.LeftButton:
            delta = event.position().toPoint() - self._press_pos
            if self._dragging or delta.manhattanLength() >= QtWidgets.QApplication.startDragDistance():
                self._dragging = True
                self.setCursor(QtCore.Qt.ClosedHandCursor)
                self.dragged.emit(event.globalPosition().toPoint())
                event.accept()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        was_dragging = self._dragging
        self._dragging = False
        self.setCursor(QtCore.Qt.OpenHandCursor)
        if event.button() == QtCore.Qt.LeftButton and not was_dragging:
            self.selected.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        p = ThemeManager.instance().palette
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        pen = QtGui.QPen(QtGui.QColor(p.text_muted))
        pen.setWidth(dpix(1))
        painter.setPen(pen)
        left = dpix(3)
        right = self.width() - dpix(3)
        for y in (dpix(6), dpix(10), dpix(14)):
            painter.drawLine(left, y, right, y)
