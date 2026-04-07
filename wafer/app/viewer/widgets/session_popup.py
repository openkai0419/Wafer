from PySide6 import QtCore, QtGui, QtWidgets
from ....utils.formatting import dpix
from ....core.color.theme import ThemeManager
from ....core.lang.manager import TranslatorMixin
from ....core.session import SESSION_COLORS


class ColorDot(QtWidgets.QWidget):
    def __init__(self, color: str, size: int = 10, parent=None):
        super().__init__(parent)
        self._color = color
        self._size = dpix(size)
        self.setFixedSize(self._size, self._size)

    def paintEvent(self, event):
        if not self._color:
            return
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setBrush(QtGui.QColor(self._color))
        p.setPen(QtCore.Qt.NoPen)
        p.drawEllipse(0, 0, self._size, self._size)


class ColorPalette(QtWidgets.QWidget):
    color_selected = QtCore.Signal(str)

    def __init__(self, current: str = "", parent=None):
        super().__init__(parent)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(dpix(4), dpix(4), dpix(4), dpix(4))
        layout.setSpacing(dpix(4))
        p = ThemeManager.instance().palette
        for c in SESSION_COLORS:
            btn = QtWidgets.QPushButton()
            btn.setFixedSize(dpix(20), dpix(20))
            border = f"{dpix(2)}px solid {p.text_primary}" if c == current else f"{dpix(2)}px solid transparent"
            btn.setStyleSheet(f"QPushButton {{ background: {c}; border: {border}; border-radius: {dpix(10)}px; }}QPushButton:hover {{ border: {dpix(2)}px solid {p.border_default}; }}")
            btn.setCursor(QtCore.Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, color=c: self.color_selected.emit(color))
            layout.addWidget(btn)
        btn_none = QtWidgets.QPushButton("\u2715")
        btn_none.setFixedSize(dpix(20), dpix(20))
        btn_none.setToolTip("No color")
        btn_none.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {p.text_muted}; border: {dpix(1)}px solid {p.border_default};"
            f"  border-radius: {dpix(10)}px; font-size: {dpix(10)}px; }}"
            f"QPushButton:hover {{ color: {p.text_primary}; border-color: {p.border_default}; }}"
        )
        btn_none.setCursor(QtCore.Qt.PointingHandCursor)
        btn_none.clicked.connect(lambda: self.color_selected.emit(""))
        layout.addWidget(btn_none)


class SessionItemWidget(QtWidgets.QWidget):
    rename_requested = QtCore.Signal(str)
    delete_requested = QtCore.Signal(str)
    open_requested = QtCore.Signal(str)
    color_requested = QtCore.Signal(str)

    @staticmethod
    def _hover_bg():
        return ThemeManager.instance().palette.bg_hover

    @staticmethod
    def _press_bg():
        return ThemeManager.instance().palette.bg_pressed

    def __init__(self, session_id: str, name: str, color: str = "", alive: bool = False, current: bool = False, parent=None):
        super().__init__(parent)
        self.session_id = session_id
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setAttribute(QtCore.Qt.WA_StyledBackground)
        self._radius = dpix(4)
        self.setStyleSheet(f"border-radius: {self._radius}px;")

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(dpix(8), dpix(3), dpix(4), dpix(3))
        layout.setSpacing(dpix(4))

        p = ThemeManager.instance().palette

        if alive:
            dot = QtWidgets.QLabel("\u25cf")
            dot.setStyleSheet(f"color: {p.success}; font-size: {dpix(10)}px; background: transparent;")
            dot.setToolTip("Running")
            layout.addWidget(dot)

        display = f"{name}" if current else name
        self._label = QtWidgets.QLabel(display)
        self._label.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        label_color = p.text_accent if current else p.text_primary
        self._label.setStyleSheet(f"color: {label_color}; font-size: {dpix(13)}px; background: transparent;")
        layout.addWidget(self._label)

        btn_color = QtWidgets.QPushButton("\u25cf")
        btn_color.setFixedSize(dpix(22), dpix(22))
        btn_color.setToolTip("Color")
        btn_color.setCursor(QtCore.Qt.PointingHandCursor)
        btn_color.setStyleSheet(self._color_btn_style(color, p))
        btn_color.clicked.connect(lambda: self.color_requested.emit(self.session_id))
        layout.addWidget(btn_color)

        btn_rename = QtWidgets.QPushButton("\u270e")
        btn_rename.setFixedSize(dpix(22), dpix(22))
        btn_rename.setToolTip("Rename")
        btn_rename.setCursor(QtCore.Qt.PointingHandCursor)
        btn_rename.setStyleSheet(self._btn_style())
        btn_rename.clicked.connect(lambda: self.rename_requested.emit(self.session_id))
        layout.addWidget(btn_rename)

        btn_delete = QtWidgets.QPushButton("\u2715")
        btn_delete.setFixedSize(dpix(22), dpix(22))
        btn_delete.setToolTip("Delete")
        btn_delete.setCursor(QtCore.Qt.PointingHandCursor)
        btn_delete.setStyleSheet(self._btn_style())
        btn_delete.clicked.connect(lambda: self.delete_requested.emit(self.session_id))
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
            self.open_requested.emit(self.session_id)
        super().mouseReleaseEvent(event)

    @staticmethod
    def _btn_style():
        p = ThemeManager.instance().palette
        fs = dpix(13)
        return (
            f"QPushButton {{ background: transparent; color: {p.text_secondary}; border: none; font-size: {fs}px; }}"
            f"QPushButton:hover {{ color: {p.text_primary}; background: {p.bg_hover}; border-radius: {dpix(3)}px; }}"
        )

    @staticmethod
    def _color_btn_style(color: str, p):
        fs = dpix(13)
        text_color = color if color else p.text_secondary
        return (
            f"QPushButton {{ background: transparent; color: {text_color}; border: none; font-size: {fs}px; }}"
            f"QPushButton:hover {{ color: {text_color}; background: {p.bg_hover}; border-radius: {dpix(3)}px; }}"
        )


class SessionPopup(QtWidgets.QFrame, TranslatorMixin):
    session_create = QtCore.Signal()
    session_open = QtCore.Signal(str)
    session_rename = QtCore.Signal(str)
    session_delete = QtCore.Signal(str)
    session_color = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(QtCore.Qt.Popup | QtCore.Qt.FramelessWindowHint)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setMinimumWidth(dpix(260))

        self._outer = QtWidgets.QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)

        self._container = QtWidgets.QWidget()
        self._container.setObjectName("session_popup_container")
        p = ThemeManager.instance().palette
        self._container.setStyleSheet(f"#session_popup_container {{  background: {p.bg_elevated};  border: 1px solid {p.border_default};  border-radius: 6px;}}")
        self._outer.addWidget(self._container)

        self._layout = QtWidgets.QVBoxLayout(self._container)
        self._layout.setContentsMargins(dpix(4), dpix(6), dpix(4), dpix(6))
        self._layout.setSpacing(0)

        btn_new = QtWidgets.QPushButton(f"+ {self.t.tr('New Window')}")
        btn_new.setCursor(QtCore.Qt.PointingHandCursor)
        btn_new.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {p.text_accent}; border: none;"
            f"  font-size: {dpix(13)}px; padding: {dpix(6)}px {dpix(8)}px; text-align: left; }}"
            f"QPushButton:hover {{ background: {p.bg_hover}; border-radius: {dpix(4)}px; }}"
            f"QPushButton:pressed {{ background: {p.bg_pressed}; border-radius: {dpix(4)}px; }}"
        )
        btn_new.clicked.connect(self._on_create)
        self._layout.addWidget(btn_new)

        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.HLine)
        sep.setStyleSheet(f"color: {p.border_subtle};")
        self._layout.addWidget(sep)

        self._list_layout = QtWidgets.QVBoxLayout()
        self._list_layout.setSpacing(0)
        self._layout.addLayout(self._list_layout)

    def populate(self, sessions, alive_session_ids=None, current_session_id=None):
        alive = set(alive_session_ids or [])
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for entry in sessions:
            row = SessionItemWidget(
                entry.session_id,
                entry.name,
                color=entry.color,
                alive=entry.session_id in alive,
                current=entry.session_id == current_session_id,
            )
            row.open_requested.connect(self._on_open)
            row.rename_requested.connect(self.session_rename.emit)
            row.delete_requested.connect(self.session_delete.emit)
            row.color_requested.connect(self.session_color.emit)
            self._list_layout.addWidget(row)
        if not sessions:
            empty = QtWidgets.QLabel(self.t.tr("No saved sessions"))
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
        self.session_create.emit()

    def _on_open(self, sid):
        self.close()
        self.session_open.emit(sid)
