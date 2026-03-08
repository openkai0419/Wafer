from PySide6 import QtCore, QtGui, QtWidgets
from ....utils.formatting import dpix
from ....core.lang.manager import TranslatorMixin
from ..session import SESSION_COLORS


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

    def __init__(self, current: str = '', parent=None):
        super().__init__(parent)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(dpix(4), dpix(4), dpix(4), dpix(4))
        layout.setSpacing(dpix(4))
        for c in SESSION_COLORS:
            btn = QtWidgets.QPushButton()
            btn.setFixedSize(dpix(20), dpix(20))
            border = '2px solid white' if c == current else '2px solid transparent'
            btn.setStyleSheet(
                f"QPushButton {{ background: {c}; border: {border}; border-radius: {dpix(10)}px; }}"
                f"QPushButton:hover {{ border: 2px solid #ccc; }}"
            )
            btn.setCursor(QtCore.Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, color=c: self.color_selected.emit(color))
            layout.addWidget(btn)
        btn_none = QtWidgets.QPushButton('\u2715')
        btn_none.setFixedSize(dpix(20), dpix(20))
        btn_none.setToolTip("No color")
        btn_none.setStyleSheet(
            "QPushButton { background: transparent; color: #888; border: 1px solid #555;"
            f"  border-radius: {dpix(10)}px; font-size: 10px; }}"
            "QPushButton:hover { color: white; border-color: #ccc; }"
        )
        btn_none.setCursor(QtCore.Qt.PointingHandCursor)
        btn_none.clicked.connect(lambda: self.color_selected.emit(''))
        layout.addWidget(btn_none)


class SessionItemWidget(QtWidgets.QWidget):

    rename_requested = QtCore.Signal(str)
    delete_requested = QtCore.Signal(str)
    open_requested = QtCore.Signal(str)
    color_requested = QtCore.Signal(str)

    def __init__(self, session_id: str, name: str, color: str = '',
                 alive: bool = False, current: bool = False, parent=None):
        super().__init__(parent)
        self.session_id = session_id
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(dpix(8), dpix(3), dpix(4), dpix(3))
        layout.setSpacing(dpix(4))

        if color:
            layout.addWidget(ColorDot(color, 10))

        display = f'{name}' if current else name
        self._label = QtWidgets.QLabel(display)
        self._label.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        self._label.setCursor(QtCore.Qt.PointingHandCursor)
        label_color = '#7cb3ff' if current else 'white'
        self._label.setStyleSheet(f"color: {label_color}; font-size: 13px;")
        self._label.mousePressEvent = lambda _: self.open_requested.emit(self.session_id)
        layout.addWidget(self._label)

        if alive:
            dot = QtWidgets.QLabel("\u25CF")
            dot.setStyleSheet("color: #4CAF50; font-size: 10px;")
            dot.setToolTip("Running")
            layout.addWidget(dot)

        btn_color = QtWidgets.QPushButton("\u25CF")
        btn_color.setFixedSize(dpix(22), dpix(22))
        btn_color.setToolTip("Color")
        btn_color.setCursor(QtCore.Qt.PointingHandCursor)
        btn_color.setStyleSheet(self._btn_style())
        btn_color.clicked.connect(lambda: self.color_requested.emit(self.session_id))
        layout.addWidget(btn_color)

        btn_rename = QtWidgets.QPushButton("\u270E")
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

    @staticmethod
    def _btn_style():
        return (
            "QPushButton { background: transparent; color: #aaa; border: none; font-size: 13px; }"
            "QPushButton:hover { color: white; background: rgba(255,255,255,0.1); border-radius: 3px; }"
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
        self._container.setStyleSheet(
            "#session_popup_container {"
            "  background: #2b2b2b;"
            "  border: 1px solid #555;"
            "  border-radius: 6px;"
            "}"
        )
        self._outer.addWidget(self._container)

        self._layout = QtWidgets.QVBoxLayout(self._container)
        self._layout.setContentsMargins(dpix(4), dpix(6), dpix(4), dpix(6))
        self._layout.setSpacing(0)

        btn_new = QtWidgets.QPushButton(f"+ {self.t.tr('New Window')}")
        btn_new.setCursor(QtCore.Qt.PointingHandCursor)
        btn_new.setStyleSheet(
            "QPushButton { background: transparent; color: #7cb3ff; border: none;"
            "  font-size: 13px; padding: 6px 8px; text-align: left; }"
            "QPushButton:hover { background: rgba(255,255,255,0.08); border-radius: 4px; }"
        )
        btn_new.clicked.connect(self._on_create)
        self._layout.addWidget(btn_new)

        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.HLine)
        sep.setStyleSheet("color: #444;")
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
                entry.session_id, entry.name,
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
            empty.setStyleSheet("color: #888; font-size: 12px; padding: 8px;")
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
