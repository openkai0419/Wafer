from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from ...core.lang.manager import t
from ...core.qt.icon_engine import themed_icon
from ...ui.popups import PopupBase
from ...utils.formatting import dpix
from . import dialogs
from .registry import MarkRegistry


_BUTTON_HEIGHT = 22


class _MarkButton(QtWidgets.QToolButton):
    def __init__(self, mark_id: str, parent=None):
        super().__init__(parent)
        self.mark_id = mark_id
        self._count: int = 0
        self.setCheckable(True)
        self.setAutoRaise(True)
        self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.setFixedHeight(dpix(_BUTTON_HEIGHT))
        self.refresh()

    def set_count(self, count: int):
        self._count = max(0, int(count))
        self._update_label()

    def refresh(self):
        m = MarkRegistry.instance().get(self.mark_id)
        if m is None:
            return
        size = dpix(_BUTTON_HEIGHT) - dpix(4)
        self.setIcon(MarkRegistry.instance().swatch_icon(self.mark_id, size))
        self.setIconSize(QtCore.QSize(size, size))
        self.setToolTip(m.name)
        self._update_label()

    def _update_label(self):
        m = MarkRegistry.instance().get(self.mark_id)
        if m is None:
            return
        self.setText(f"{m.name} ({self._count})")


class _MarkSettingsPopup(PopupBase):
    changed = QtCore.Signal()

    def __init__(self, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(t("Mark Filter Options"))

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(dpix(8), dpix(8), dpix(8), dpix(8))
        layout.setSpacing(dpix(6))

        title = QtWidgets.QLabel(t("Mark Filter Options"))
        title.setStyleSheet(f"font-weight: bold; padding-bottom: {dpix(2)}px;")
        layout.addWidget(title)

        self.overlay_check = QtWidgets.QCheckBox(t("Show mark overlay on grid"))
        self.overlay_check.toggled.connect(self._on_overlay_toggled)
        layout.addWidget(self.overlay_check)

        radius_row = QtWidgets.QHBoxLayout()
        radius_row.setSpacing(dpix(4))
        radius_row.addWidget(QtWidgets.QLabel(t("Overlay size:")))
        self.radius_spin = QtWidgets.QSpinBox()
        from ...app.viewer.grid.mark_overlay_service import MIN_RADIUS, MAX_RADIUS
        from ...core.commands.binding.instance_registry import InstanceRegistry

        self.radius_spin.setRange(MIN_RADIUS, MAX_RADIUS)
        self.radius_spin.setSuffix(" px")
        svc = InstanceRegistry.instance().get_one("MarkOverlayService")
        self.radius_spin.setValue(svc.radius() if svc is not None else 8)
        self.radius_spin.valueChanged.connect(self._on_radius_changed)
        radius_row.addWidget(self.radius_spin)
        radius_row.addStretch()
        layout.addLayout(radius_row)

        mode_row = QtWidgets.QHBoxLayout()
        mode_row.setSpacing(dpix(4))
        mode_row.addWidget(QtWidgets.QLabel(t("Match:")))
        self.mode_group = QtWidgets.QButtonGroup(self)
        self.or_radio = QtWidgets.QRadioButton("OR")
        self.and_radio = QtWidgets.QRadioButton("AND")
        self.or_radio.setChecked(True)
        self.mode_group.addButton(self.or_radio)
        self.mode_group.addButton(self.and_radio)
        self.or_radio.toggled.connect(lambda _c: self.changed.emit())
        self.and_radio.toggled.connect(lambda _c: self.changed.emit())
        mode_row.addWidget(self.or_radio)
        mode_row.addWidget(self.and_radio)
        mode_row.addStretch()
        layout.addLayout(mode_row)

        add_btn = QtWidgets.QPushButton(t("Add new mark..."))
        add_btn.setIcon(themed_icon("plus"))
        add_btn.clicked.connect(lambda: dialogs.prompt_new_mark(self))
        layout.addWidget(add_btn)

    def mode(self) -> str:
        return "AND" if self.and_radio.isChecked() else "OR"

    def set_mode(self, mode: str):
        radio = self.and_radio if str(mode).upper() == "AND" else self.or_radio
        radio.blockSignals(True)
        radio.setChecked(True)
        radio.blockSignals(False)

    def overlay_visible(self) -> bool:
        return self.overlay_check.isChecked()

    def set_overlay_visible(self, visible: bool):
        self.overlay_check.blockSignals(True)
        self.overlay_check.setChecked(bool(visible))
        self.overlay_check.blockSignals(False)

    def set_overlay_radius(self, radius: int):
        self.radius_spin.blockSignals(True)
        self.radius_spin.setValue(int(radius))
        self.radius_spin.blockSignals(False)

    def _on_overlay_toggled(self, checked: bool):
        from ...core.commands.binding.instance_registry import InstanceRegistry

        svc = InstanceRegistry.instance().get_one("MarkOverlayService")
        if svc is not None:
            svc.set_visible(bool(checked))

    def _on_radius_changed(self, value: int):
        from ...core.commands.binding.instance_registry import InstanceRegistry

        svc = InstanceRegistry.instance().get_one("MarkOverlayService")
        if svc is not None:
            svc.set_radius(int(value))

class MarkFilterWidget(QtWidgets.QWidget):
    changed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._buttons: dict[str, _MarkButton] = {}
        self._key_store = None
        self._build_ui()
        MarkRegistry.instance().changed.connect(self._sync_buttons)
        self._restore_state()

    def _build_ui(self):
        root = QtWidgets.QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(dpix(2))

        self._option_btn = QtWidgets.QToolButton()
        self._option_btn.setIcon(themed_icon("gear_small"))
        self._option_btn.setToolTip(t("Mark filter options"))
        self._option_btn.setFixedSize(dpix(28), dpix(_BUTTON_HEIGHT))
        self._option_btn.clicked.connect(self._toggle_popup)
        root.addWidget(self._option_btn)

        self._buttons_container = QtWidgets.QWidget()
        self._buttons_layout = QtWidgets.QHBoxLayout(self._buttons_container)
        self._buttons_layout.setContentsMargins(0, 0, 0, 0)
        self._buttons_layout.setSpacing(dpix(2))
        self._buttons_layout.addStretch(1)
        root.addWidget(self._buttons_container, 1)

        self._popup = _MarkSettingsPopup(self)
        self._popup.changed.connect(self.changed)

        svc = self._overlay_service()
        if svc is not None:
            svc.changed.connect(self._sync_overlay_controls)

        self._sync_buttons()

    def _toggle_popup(self):
        if self._popup.isVisible():
            self._popup.hide()
        else:
            self._popup.show_below(self._option_btn, align=QtCore.Qt.AlignRight)

    def bind_key_store(self, key_store):
        prev = self._key_store
        if prev is not None:
            try:
                prev.updated.disconnect(self._on_key_store_updated)
            except (TypeError, RuntimeError):
                pass
        self._key_store = key_store
        if key_store is None:
            return
        key_store.updated.connect(self._on_key_store_updated)
        if key_store.data:
            self._on_key_store_updated(key_store.data)

    def _on_key_store_updated(self, data: list[tuple[str, int]]):
        counts: dict[str, int] = {}
        prefix = MarkRegistry.tag_prefix() + "."
        for key, count in data or []:
            if isinstance(key, str) and key.startswith(prefix):
                counts[key[len(prefix) :]] = int(count)
        for mid, btn in self._buttons.items():
            btn.set_count(counts.get(mid, 0))

    def _add_button(self, mark_id: str, checked: bool = False):
        btn = _MarkButton(mark_id, self._buttons_container)
        btn.setChecked(checked)
        btn.toggled.connect(lambda _c: self.changed.emit())
        btn.customContextMenuRequested.connect(lambda pos, m=mark_id, b=btn: dialogs.show_mark_context_menu(b, m, b.mapToGlobal(pos)))
        self._buttons[mark_id] = btn
        self._buttons_layout.insertWidget(self._buttons_layout.count() - 1, btn)

    def _sync_buttons(self):
        current_ids = MarkRegistry.instance().ids()
        current_set = set(current_ids)
        existing_set = set(self._buttons.keys())
        for mid in existing_set - current_set:
            btn = self._buttons.pop(mid, None)
            if btn is not None:
                self._buttons_layout.removeWidget(btn)
                btn.setParent(None)
                btn.deleteLater()
        for mid in current_ids:
            if mid not in self._buttons:
                self._add_button(mid)
        for i, mid in enumerate(current_ids):
            btn = self._buttons.get(mid)
            if btn is None:
                continue
            self._buttons_layout.removeWidget(btn)
            self._buttons_layout.insertWidget(i, btn)
            btn.refresh()
        if current_set != existing_set:
            self.changed.emit()

    def _overlay_service(self):
        from ...core.commands.binding.instance_registry import InstanceRegistry

        return InstanceRegistry.instance().get_one("MarkOverlayService")

    def _restore_state(self):
        self._sync_overlay_controls()

    def _sync_overlay_controls(self):
        svc = self._overlay_service()
        self._popup.set_overlay_visible(svc.is_visible() if svc is not None else True)
        self._popup.set_overlay_radius(svc.radius() if svc is not None else 8)

    def read_params(self) -> dict:
        ids = [mid for mid, b in self._buttons.items() if b.isChecked()]
        return {"mark_ids": ids, "mode": self._popup.mode()}

    def write_params(self, params: dict):
        ids = set(str(x) for x in (params.get("mark_ids") or []))
        for mid, b in self._buttons.items():
            b.blockSignals(True)
            b.setChecked(mid in ids)
            b.blockSignals(False)
        mode = params.get("mode") or "OR"
        self._popup.set_mode(mode)
