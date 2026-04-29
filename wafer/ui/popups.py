from __future__ import annotations

from PySide6 import QtCore, QtWidgets


class PopupBase(QtWidgets.QFrame):
    closed = QtCore.Signal()

    def __init__(self, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent, QtCore.Qt.Popup | QtCore.Qt.FramelessWindowHint)
        self.setAutoFillBackground(True)
        self._content_widget: QtWidgets.QWidget | None = None

    def set_content_widget(self, widget: QtWidgets.QWidget):
        layout = self.layout()
        if self._content_widget is not None and layout is not None:
            layout.removeWidget(self._content_widget)
        self._content_widget = widget
        if layout is not None:
            layout.addWidget(widget)

    def content_widget(self) -> QtWidgets.QWidget | None:
        return self._content_widget

    def popup_size_hint(self) -> QtCore.QSize:
        return self.sizeHint().expandedTo(self.minimumSizeHint())

    def show_below(self, anchor: QtWidgets.QWidget, *, align: QtCore.Qt.AlignmentFlag = QtCore.Qt.AlignLeft, max_height: int | None = None):
        self.position_below(anchor, align=align, max_height=max_height)
        self.show()

    def show_at(self, global_pos: QtCore.QPoint, *, max_height: int | None = None):
        self.position_at(global_pos, max_height=max_height)
        self.show()

    def position_below(self, anchor: QtWidgets.QWidget, *, align: QtCore.Qt.AlignmentFlag = QtCore.Qt.AlignLeft, max_height: int | None = None):
        self.adjustSize()
        size = self._target_size(max_height)
        pos = anchor.mapToGlobal(QtCore.QPoint(0, anchor.height()))
        if align & QtCore.Qt.AlignRight:
            pos.setX(pos.x() + anchor.width() - size.width())
        self.resize(size)
        self.move(self._clamped_pos(pos, size, anchor))

    def position_at(self, global_pos: QtCore.QPoint, *, max_height: int | None = None):
        self.adjustSize()
        size = self._target_size(max_height)
        self.resize(size)
        self.move(self._clamped_pos(global_pos, size, None))

    def _target_size(self, max_height: int | None) -> QtCore.QSize:
        size = self.popup_size_hint()
        width = max(size.width(), self.minimumWidth())
        height = max(size.height(), self.minimumHeight())
        if max_height is not None:
            height = min(height, max_height)
        return QtCore.QSize(width, height)

    def _clamped_pos(self, pos: QtCore.QPoint, size: QtCore.QSize, anchor: QtWidgets.QWidget | None) -> QtCore.QPoint:
        screen = QtWidgets.QApplication.screenAt(pos)
        if screen is None and anchor is not None:
            screen = anchor.screen()
        if screen is None:
            screen = QtWidgets.QApplication.primaryScreen()
        if screen is None:
            return pos
        geo = screen.availableGeometry()
        max_x = geo.left() + max(0, geo.width() - size.width())
        max_y = geo.top() + max(0, geo.height() - size.height())
        return QtCore.QPoint(
            min(max(pos.x(), geo.left()), max_x),
            min(max(pos.y(), geo.top()), max_y),
        )

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    def hideEvent(self, event):
        self._emit_closed()
        super().hideEvent(event)

    def _emit_closed(self):
        self.closed.emit()
