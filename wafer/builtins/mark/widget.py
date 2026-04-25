from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from ...utils.formatting import dpix
from .registry import MarkRegistry


_BUTTON_SIZE = 20


class _ColorMarkButton(QtWidgets.QToolButton):
    def __init__(self, mark_id: str, parent=None):
        super().__init__(parent)
        self.mark_id = mark_id
        self.setCheckable(True)
        self.setAutoRaise(True)
        sz = dpix(_BUTTON_SIZE)
        self.setFixedSize(sz, sz)
        self.setToolTip(f"Mark {mark_id}")
        self._refresh_icon()

    def _refresh_icon(self):
        sz = dpix(_BUTTON_SIZE)
        pm = QtGui.QPixmap(sz, sz)
        pm.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(pm)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        color = MarkRegistry.instance().qcolor_for(self.mark_id)
        pen = QtGui.QPen(QtGui.QColor(0, 0, 0, 160), max(1, dpix(1)))
        painter.setPen(pen)
        painter.setBrush(color)
        margin = max(2, dpix(3))
        painter.drawEllipse(QtCore.QRect(margin, margin, sz - margin * 2, sz - margin * 2))
        painter.end()
        self.setIcon(QtGui.QIcon(pm))
        self.setIconSize(QtCore.QSize(sz, sz))


class MarkFilterWidget(QtWidgets.QWidget):
    changed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._buttons: dict[str, _ColorMarkButton] = {}
        self._build_ui()
        MarkRegistry.instance().changed.connect(self._rebuild)

    def _build_ui(self):
        self._layout = QtWidgets.QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(dpix(2))
        self._mode = QtWidgets.QComboBox()
        self._mode.addItems(["OR", "AND"])
        self._mode.currentTextChanged.connect(lambda _t: self.changed.emit())
        self._layout.addWidget(self._mode)
        self._buttons_container = QtWidgets.QWidget()
        self._buttons_layout = QtWidgets.QHBoxLayout(self._buttons_container)
        self._buttons_layout.setContentsMargins(0, 0, 0, 0)
        self._buttons_layout.setSpacing(dpix(1))
        self._layout.addWidget(self._buttons_container, 1)
        self._populate_buttons()

    def _populate_buttons(self):
        for mid in MarkRegistry.instance().ids():
            btn = _ColorMarkButton(mid, self._buttons_container)
            btn.toggled.connect(lambda _c: self.changed.emit())
            self._buttons[mid] = btn
            self._buttons_layout.addWidget(btn)
        self._buttons_layout.addStretch(1)

    def _rebuild(self):
        checked = {mid for mid, b in self._buttons.items() if b.isChecked()}
        for b in self._buttons.values():
            self._buttons_layout.removeWidget(b)
            b.setParent(None)
            b.deleteLater()
        self._buttons.clear()
        while self._buttons_layout.count():
            item = self._buttons_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        for mid in MarkRegistry.instance().ids():
            btn = _ColorMarkButton(mid, self._buttons_container)
            btn.setChecked(mid in checked)
            btn.toggled.connect(lambda _c: self.changed.emit())
            self._buttons[mid] = btn
            self._buttons_layout.addWidget(btn)
        self._buttons_layout.addStretch(1)
        self.changed.emit()

    def read_params(self) -> dict:
        ids = [mid for mid, b in self._buttons.items() if b.isChecked()]
        return {"mark_ids": ids, "mode": self._mode.currentText()}

    def write_params(self, params: dict):
        ids = set(str(x) for x in (params.get("mark_ids") or []))
        for mid, b in self._buttons.items():
            b.blockSignals(True)
            b.setChecked(mid in ids)
            b.blockSignals(False)
        mode = params.get("mode") or "OR"
        i = self._mode.findText(mode)
        if i >= 0:
            self._mode.blockSignals(True)
            self._mode.setCurrentIndex(i)
            self._mode.blockSignals(False)
