from PySide6 import QtCore, QtGui, QtWidgets
from ....utils.formatting import dpix
from ....core.color.theme import ThemeManager
from ....core.lang.manager import t
from ....core.profile import PROFILE_COLORS


class ColorPalette(QtWidgets.QWidget):
    color_selected = QtCore.Signal(str)

    def __init__(self, current: str = "", parent=None):
        super().__init__(parent)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(dpix(4), dpix(4), dpix(4), dpix(4))
        layout.setSpacing(dpix(4))
        p = ThemeManager.instance().palette
        for c in PROFILE_COLORS:
            btn = QtWidgets.QPushButton()
            btn.setFixedSize(dpix(20), dpix(20))
            border = f"{dpix(2)}px solid {p.text_primary}" if c == current else f"{dpix(2)}px solid transparent"
            btn.setStyleSheet(f"QPushButton {{ background: {c}; border: {border}; border-radius: {dpix(10)}px; }}QPushButton:hover {{ border: {dpix(2)}px solid {p.border_default}; }}")
            btn.setCursor(QtCore.Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, color=c: self.color_selected.emit(color))
            layout.addWidget(btn)
        btn_none = QtWidgets.QPushButton("\u2715")
        btn_none.setFixedSize(dpix(20), dpix(20))
        btn_none.setToolTip(t("No color"))
        btn_none.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {p.text_muted}; border: {dpix(1)}px solid {p.border_default};"
            f"  border-radius: {dpix(10)}px; font-size: {dpix(10)}px; }}"
            f"QPushButton:hover {{ color: {p.text_primary}; border-color: {p.border_default}; }}"
        )
        btn_none.setCursor(QtCore.Qt.PointingHandCursor)
        btn_none.clicked.connect(lambda: self.color_selected.emit(""))
        layout.addWidget(btn_none)


class ClickableColorDot(QtWidgets.QWidget):
    clicked = QtCore.Signal()

    def __init__(self, color: str, size: int = 12, parent=None):
        super().__init__(parent)
        self._color = color
        self._size = dpix(size)
        self.setFixedSize(self._size, self._size)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setToolTip(t("Color"))

    def set_color(self, color: str):
        self._color = color
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        if self._color:
            painter.setBrush(QtGui.QColor(self._color))
            painter.setPen(QtCore.Qt.NoPen)
        else:
            p = ThemeManager.instance().palette
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.setPen(QtGui.QPen(QtGui.QColor(p.text_muted), 1.5))
        painter.drawEllipse(1, 1, self._size - 2, self._size - 2)

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class ProfileItemWidget(QtWidgets.QWidget):
    rename_requested = QtCore.Signal(str)
    delete_requested = QtCore.Signal(str)
    open_requested = QtCore.Signal(str)
    open_new_window_requested = QtCore.Signal(str)
    color_requested = QtCore.Signal(str)

    @staticmethod
    def _hover_bg():
        return ThemeManager.instance().palette.bg_hover

    @staticmethod
    def _press_bg():
        return ThemeManager.instance().palette.bg_pressed

    def __init__(self, profile_id: str, name: str, color: str = "", current: bool = False, parent=None):
        super().__init__(parent)
        self.profile_id = profile_id
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setAttribute(QtCore.Qt.WA_StyledBackground)
        self._radius = dpix(4)
        self.setStyleSheet(f"border-radius: {self._radius}px;")

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(dpix(8), dpix(3), dpix(4), dpix(3))
        layout.setSpacing(dpix(6))

        p = ThemeManager.instance().palette

        self.color_dot = ClickableColorDot(color, size=12)
        self.color_dot.clicked.connect(lambda: self.color_requested.emit(self.profile_id))
        layout.addWidget(self.color_dot)

        self._label = QtWidgets.QLabel(name)
        self._label.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        label_color = p.text_accent if current else p.text_primary
        self._label.setStyleSheet(f"color: {label_color}; font-size: {dpix(13)}px; background: transparent;")
        layout.addWidget(self._label)

        btn_open_new = QtWidgets.QPushButton("\u2750")
        btn_open_new.setFixedSize(dpix(22), dpix(22))
        btn_open_new.setToolTip(t("Open in new window"))
        btn_open_new.setCursor(QtCore.Qt.PointingHandCursor)
        btn_open_new.setStyleSheet(self._btn_style())
        btn_open_new.clicked.connect(lambda: self.open_new_window_requested.emit(self.profile_id))
        layout.addWidget(btn_open_new)

        btn_rename = QtWidgets.QPushButton("\u270e")
        btn_rename.setFixedSize(dpix(22), dpix(22))
        btn_rename.setToolTip(t("Rename"))
        btn_rename.setCursor(QtCore.Qt.PointingHandCursor)
        btn_rename.setStyleSheet(self._btn_style())
        btn_rename.clicked.connect(lambda: self.rename_requested.emit(self.profile_id))
        layout.addWidget(btn_rename)

        btn_delete = QtWidgets.QPushButton("\u2715")
        btn_delete.setFixedSize(dpix(22), dpix(22))
        btn_delete.setToolTip(t("Delete"))
        btn_delete.setCursor(QtCore.Qt.PointingHandCursor)
        btn_delete.setStyleSheet(self._btn_style())
        btn_delete.clicked.connect(lambda: self.delete_requested.emit(self.profile_id))
        layout.addWidget(btn_delete)

    def enterEvent(self, event):
        self.setStyleSheet(f"background: {self._hover_bg()}; border-radius: {self._radius}px;")
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setStyleSheet(f"border-radius: {self._radius}px;")
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self.setStyleSheet(f"background: {self._press_bg()}; border-radius: {self._radius}px;")
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self.setStyleSheet(f"background: {self._hover_bg()}; border-radius: {self._radius}px;")
            self.open_requested.emit(self.profile_id)
        super().mouseReleaseEvent(event)

    @staticmethod
    def _btn_style():
        p = ThemeManager.instance().palette
        fs = dpix(13)
        return (
            f"QPushButton {{ background: transparent; color: {p.text_secondary}; border: none; font-size: {fs}px; }}"
            f"QPushButton:hover {{ color: {p.text_primary}; background: {p.bg_hover}; border-radius: {dpix(3)}px; }}"
        )


class ProfilePopup(QtWidgets.QFrame):
    profile_create = QtCore.Signal()
    profile_open = QtCore.Signal(str)
    profile_open_new_window = QtCore.Signal(str)
    profile_rename = QtCore.Signal(str)
    profile_delete = QtCore.Signal(str)
    profile_color_changed = QtCore.Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(QtCore.Qt.Popup | QtCore.Qt.FramelessWindowHint)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setMinimumWidth(dpix(260))

        self._outer = QtWidgets.QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)

        self._container = QtWidgets.QWidget()
        self._container.setObjectName("profile_popup_container")
        p = ThemeManager.instance().palette
        self._container.setStyleSheet(f"#profile_popup_container {{  background: {p.bg_elevated};  border: 1px solid {p.border_default};  border-radius: 6px;}}")
        self._outer.addWidget(self._container)

        self._layout = QtWidgets.QVBoxLayout(self._container)
        self._layout.setContentsMargins(dpix(4), dpix(6), dpix(4), dpix(6))
        self._layout.setSpacing(0)

        self._list_layout = QtWidgets.QVBoxLayout()
        self._list_layout.setSpacing(0)
        self._layout.addLayout(self._list_layout)

        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.HLine)
        sep.setStyleSheet(f"color: {p.border_subtle};")
        self._layout.addWidget(sep)

        action_style = (
            f"QPushButton {{ background: transparent; color: {p.text_accent}; border: none;"
            f"  font-size: {dpix(13)}px; padding: {dpix(6)}px {dpix(8)}px; text-align: left; }}"
            f"QPushButton:hover {{ background: {p.bg_hover}; border-radius: {dpix(4)}px; }}"
            f"QPushButton:pressed {{ background: {p.bg_pressed}; border-radius: {dpix(4)}px; }}"
        )

        btn_new_profile = QtWidgets.QPushButton(f"+ {t('New Profile')}")
        btn_new_profile.setCursor(QtCore.Qt.PointingHandCursor)
        btn_new_profile.setStyleSheet(action_style)
        btn_new_profile.clicked.connect(self._on_create)
        self._layout.addWidget(btn_new_profile)

    def populate(self, profiles, current_profile_id=None):
        self._active_palette = None
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for entry in profiles:
            row = ProfileItemWidget(
                entry.profile_id,
                entry.name,
                color=entry.color,
                current=entry.profile_id == current_profile_id,
            )
            row.open_requested.connect(self._on_open)
            row.open_new_window_requested.connect(self._on_open_new_window)
            row.rename_requested.connect(self.profile_rename.emit)
            row.delete_requested.connect(self.profile_delete.emit)
            row.color_requested.connect(self._on_color_requested)
            self._list_layout.addWidget(row)
        if not profiles:
            empty = QtWidgets.QLabel(t("No saved profiles"))
            p = ThemeManager.instance().palette
            empty.setStyleSheet(f"color: {p.text_muted}; font-size: {dpix(12)}px; padding: {dpix(8)}px;")
            empty.setAlignment(QtCore.Qt.AlignCenter)
            self._list_layout.addWidget(empty)

    def show_below(self, widget: QtWidgets.QWidget):
        pos = widget.mapToGlobal(QtCore.QPoint(0, widget.height()))
        self.move(pos)
        self.show()

    def _on_create(self):
        self.close()
        self.profile_create.emit()

    def _on_open(self, pid):
        self.close()
        self.profile_open.emit(pid)

    def _on_open_new_window(self, pid):
        self.close()
        self.profile_open_new_window.emit(pid)

    def _on_color_requested(self, pid):
        row = self._find_row(pid)
        if not row:
            return
        if self._active_palette:
            self._active_palette.deleteLater()
            self._active_palette = None
            return
        idx = self._list_layout.indexOf(row)
        palette = ColorPalette(current=row.color_dot._color, parent=self)
        self._active_palette = palette

        def _apply(color):
            palette.deleteLater()
            self._active_palette = None
            row.color_dot.set_color(color)
            self.profile_color_changed.emit(pid, color)

        palette.color_selected.connect(_apply)
        self._list_layout.insertWidget(idx + 1, palette)

    def _find_row(self, pid):
        for i in range(self._list_layout.count()):
            w = self._list_layout.itemAt(i).widget()
            if isinstance(w, ProfileItemWidget) and w.profile_id == pid:
                return w
        return None
