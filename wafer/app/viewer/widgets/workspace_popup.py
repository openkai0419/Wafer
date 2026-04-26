from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from ....core.color.theme import ThemeManager
from ....core.commands.bridge import Command
from ....core.lang.manager import t
from ....core.qt.icon_engine import themed_icon
from ....core.workspace import UI_PRESET_COLORS, WorkspaceStore
from ....ui.widgets.color_picker import ColorPickerDialog
from ....utils.formatting import dpix


_KIND_UI = "ui"
_KIND_PATH = "path"
_KIND_QUERY = "query"


class _PresetItem(QtWidgets.QWidget):
    apply_requested = QtCore.Signal(str, str, str)  # kind, preset_id, mode
    rename_requested = QtCore.Signal(str, str)
    delete_requested = QtCore.Signal(str, str)
    color_requested = QtCore.Signal(str, str)

    def __init__(self, kind: str, preset_id: str, name: str, color: str = "", mode_provider=None, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.preset_id = preset_id
        self.name = name
        self.color = color
        self._mode_provider = mode_provider
        self._build_ui()

    def _build_ui(self):
        p = ThemeManager.instance().palette
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(dpix(4), dpix(2), dpix(4), dpix(2))
        layout.setSpacing(dpix(4))

        if self.kind == _KIND_UI:
            self._dot = _ColorDot(self.color)
            self._dot.clicked.connect(lambda: self.color_requested.emit(self.preset_id, self._dot.color))
            layout.addWidget(self._dot)

        self._label = QtWidgets.QToolButton()
        self._label.setText(self.name)
        self._label.setToolButtonStyle(QtCore.Qt.ToolButtonTextOnly)
        self._label.setCursor(QtCore.Qt.PointingHandCursor)
        self._label.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        self._label.setStyleSheet(
            f"QToolButton {{ background: transparent; color: {p.text_primary}; border: none; text-align: left; padding: {dpix(2)}px {dpix(4)}px; font-size: {dpix(12)}px; }}"
            f"QToolButton:hover {{ background: {p.bg_hover}; border-radius: {dpix(3)}px; }}"
        )
        self._label.clicked.connect(self._on_apply_click)
        layout.addWidget(self._label, 1)

        rn = QtWidgets.QToolButton()
        rn.setIcon(themed_icon("pencil"))
        rn.setFixedSize(dpix(20), dpix(20))
        rn.setToolTip(t("Rename"))
        rn.clicked.connect(lambda: self.rename_requested.emit(self.kind, self.preset_id))
        layout.addWidget(rn)

        dl = QtWidgets.QToolButton()
        dl.setIcon(themed_icon("trash"))
        dl.setFixedSize(dpix(20), dpix(20))
        dl.setToolTip(t("Delete"))
        dl.clicked.connect(lambda: self.delete_requested.emit(self.kind, self.preset_id))
        layout.addWidget(dl)

    def _on_apply_click(self):
        mode = self._mode_provider() if self._mode_provider else "replace"
        self.apply_requested.emit(self.kind, self.preset_id, mode)


class _ColorDot(QtWidgets.QToolButton):
    clicked = QtCore.Signal()

    def __init__(self, color: str = "", parent=None):
        super().__init__(parent)
        self.color = color or ""
        self.setFixedSize(dpix(14), dpix(14))
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self._refresh()

    def _refresh(self):
        c = self.color or "transparent"
        self.setStyleSheet(
            f"QToolButton {{ background: {c}; border: 1px solid {ThemeManager.instance().palette.border_default}; border-radius: {dpix(7)}px; }}"
        )

    def set_color(self, color: str):
        self.color = color
        self._refresh()

    def mousePressEvent(self, ev: QtGui.QMouseEvent):
        if ev.button() == QtCore.Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(ev)


class _Column(QtWidgets.QWidget):
    save_requested = QtCore.Signal(str)
    apply_requested = QtCore.Signal(str, str, str)
    rename_requested = QtCore.Signal(str, str)
    delete_requested = QtCore.Signal(str, str)
    color_requested = QtCore.Signal(str, str)

    def __init__(self, kind: str, title: str, parent=None):
        super().__init__(parent)
        self.kind = kind
        self._build_ui(title)

    def _build_ui(self, title: str):
        p = ThemeManager.instance().palette
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(dpix(6), dpix(6), dpix(6), dpix(6))
        layout.setSpacing(dpix(4))

        header = QtWidgets.QLabel(title)
        header.setStyleSheet(f"color: {p.text_primary}; font-weight: bold; font-size: {dpix(13)}px;")
        layout.addWidget(header)

        if self.kind == _KIND_QUERY:
            mode_row = QtWidgets.QHBoxLayout()
            mode_row.setContentsMargins(0, 0, 0, 0)
            mode_row.setSpacing(dpix(4))
            self._mode_combo = QtWidgets.QComboBox()
            self._mode_combo.addItem(t("Replace"), "replace")
            self._mode_combo.addItem(t("Append"), "append")
            mode_row.addWidget(QtWidgets.QLabel(t("Apply:")))
            mode_row.addWidget(self._mode_combo, 1)
            layout.addLayout(mode_row)
            self._include_sort_cb = QtWidgets.QCheckBox(t("Save sort with preset"))
            layout.addWidget(self._include_sort_cb)

        save_btn = QtWidgets.QPushButton(f"+ {t('Save current')}")
        save_btn.setCursor(QtCore.Qt.PointingHandCursor)
        save_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {p.text_accent}; border: 1px dashed {p.border_default};"
            f"  border-radius: {dpix(4)}px; padding: {dpix(4)}px; font-size: {dpix(12)}px; }}"
            f"QPushButton:hover {{ background: {p.bg_hover}; }}"
        )
        save_btn.clicked.connect(self._on_save)
        layout.addWidget(save_btn)

        self._list_layout = QtWidgets.QVBoxLayout()
        self._list_layout.setSpacing(0)
        layout.addLayout(self._list_layout)
        layout.addStretch(1)

    def query_mode(self) -> str:
        if self.kind != _KIND_QUERY:
            return "replace"
        return self._mode_combo.currentData()

    def include_sort(self) -> bool:
        return self.kind == _KIND_QUERY and self._include_sort_cb.isChecked()

    def populate(self, items: list[tuple[str, str, str]]):
        while self._list_layout.count():
            it = self._list_layout.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        mode_provider = self.query_mode if self.kind == _KIND_QUERY else None
        for preset_id, name, color in items:
            row = _PresetItem(self.kind, preset_id, name, color, mode_provider=mode_provider, parent=self)
            row.apply_requested.connect(self.apply_requested.emit)
            row.rename_requested.connect(self.rename_requested.emit)
            row.delete_requested.connect(self.delete_requested.emit)
            row.color_requested.connect(self.color_requested.emit)
            self._list_layout.addWidget(row)
        if not items:
            empty = QtWidgets.QLabel(t("(empty)"))
            empty.setAlignment(QtCore.Qt.AlignCenter)
            empty.setStyleSheet(f"color: {ThemeManager.instance().palette.text_muted}; font-size: {dpix(11)}px; padding: {dpix(4)}px;")
            self._list_layout.addWidget(empty)

    def _on_save(self):
        self.save_requested.emit(self.kind)


class WorkspacePopup(QtWidgets.QFrame):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self._ctx = ctx
        self.setWindowFlags(QtCore.Qt.Popup | QtCore.Qt.FramelessWindowHint)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setMinimumWidth(dpix(540))
        self._build_ui()
        self._refresh()

    def _build_ui(self):
        p = ThemeManager.instance().palette
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        container = QtWidgets.QWidget()
        container.setObjectName("workspace_popup_container")
        container.setStyleSheet(
            f"#workspace_popup_container {{ background: {p.bg_elevated}; border: 1px solid {p.border_default}; border-radius: {dpix(6)}px; }}"
        )
        outer.addWidget(container)

        cols = QtWidgets.QHBoxLayout(container)
        cols.setContentsMargins(dpix(4), dpix(6), dpix(4), dpix(6))
        cols.setSpacing(dpix(4))

        self._ui_col = _Column(_KIND_UI, t("UI"))
        self._path_col = _Column(_KIND_PATH, t("Path"))
        self._query_col = _Column(_KIND_QUERY, t("Filter"))

        for i, col in enumerate((self._ui_col, self._path_col, self._query_col)):
            col.save_requested.connect(self._on_save)
            col.apply_requested.connect(self._on_apply)
            col.rename_requested.connect(self._on_rename)
            col.delete_requested.connect(self._on_delete)
            col.color_requested.connect(self._on_color)
            cols.addWidget(col, 1)
            if i < 2:
                sep = QtWidgets.QFrame()
                sep.setFrameShape(QtWidgets.QFrame.VLine)
                sep.setStyleSheet(f"color: {p.border_subtle};")
                cols.addWidget(sep)

    def _refresh(self):
        ui_presets, path_presets, query_presets = WorkspaceStore.instance().snapshot()
        self._ui_col.populate([(p.preset_id, p.name, p.color) for p in ui_presets])
        self._path_col.populate([(p.preset_id, p.name, "") for p in path_presets])
        self._query_col.populate([(p.preset_id, p.name, "") for p in query_presets])

    def show_below(self, widget: QtWidgets.QWidget):
        pos = widget.mapToGlobal(QtCore.QPoint(0, widget.height()))
        self.move(pos)
        self.show()

    def _cmd(self, kind: str, action: str) -> str:
        return f"{kind}_preset.{action}"

    def _on_save(self, kind: str):
        if kind == _KIND_QUERY:
            Command.invoke(self._cmd(kind, "save_current"), include_sort=self._query_col.include_sort())
        else:
            Command.invoke(self._cmd(kind, "save_current"))
        self._refresh()

    def _on_apply(self, kind: str, preset_id: str, mode: str):
        if kind == _KIND_QUERY:
            Command.invoke(self._cmd(kind, "apply"), preset_id=preset_id, mode=mode)
        else:
            Command.invoke(self._cmd(kind, "apply"), preset_id=preset_id)
        self.close()

    def _on_rename(self, kind: str, preset_id: str):
        Command.invoke(self._cmd(kind, "rename"), preset_id=preset_id)
        self._refresh()

    def _on_delete(self, kind: str, preset_id: str):
        Command.invoke(self._cmd(kind, "delete"), preset_id=preset_id)
        self._refresh()

    def _on_color(self, preset_id: str, current_color: str):
        initial = QtGui.QColor(current_color) if current_color else QtGui.QColor(UI_PRESET_COLORS[0])
        color = ColorPickerDialog.get_color(initial, self, t("Choose color"), with_alpha=False, scope="ui_preset")
        if color is None:
            return
        Command.invoke("ui_preset.set_color", preset_id=preset_id, color=color.name())
        self._refresh()
