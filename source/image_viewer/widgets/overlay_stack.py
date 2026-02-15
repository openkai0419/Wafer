from PySide6 import QtCore, QtGui, QtWidgets
from ...common.funcs import uipx


class OverlayItem(QtWidgets.QWidget):

    dismissed = QtCore.Signal(object)

    LEVEL_STYLES = {
        "info": (QtGui.QColor(30, 30, 30, 210), QtGui.QColor(255, 255, 255)),
        "warning": (QtGui.QColor(30, 30, 30, 210), QtGui.QColor(255, 255, 255)),
        "error": (QtGui.QColor(120, 10, 10, 230), QtGui.QColor(255, 255, 255)),
    }

    def __init__(self, text: str, level: str = "warning", duration: int = 3000, parent=None):
        super().__init__(parent)
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint)
        self._label_prefix = {"error": "Error"}.get(level)
        self._display_text = f"{self._label_prefix}:\n{text}" if self._label_prefix else text
        self._level = level
        self._bg_color, self._text_color = self.LEVEL_STYLES.get(level, self.LEVEL_STYLES["warning"])
        self._opacity = 1.0
        self._fade_anim = None
        self._padding = uipx(6)
        font = self.font()
        font.setPointSizeF(font.pointSizeF() * 1.2)
        self.setFont(font)
        self._update_size()
        if duration > 0:
            QtCore.QTimer.singleShot(duration, self._start_fade_out)

    def _update_size(self):
        fm = QtGui.QFontMetrics(self.font())
        text_rect = fm.boundingRect(0, 0, 9999, 9999, QtCore.Qt.AlignLeft, self._display_text)
        self.setFixedSize(text_rect.width() + self._padding * 4, text_rect.height() + self._padding * 2)

    def _get_opacity(self):
        return self._opacity

    def _set_opacity(self, val):
        self._opacity = val
        self.update()

    opacity_prop = QtCore.Property(float, _get_opacity, _set_opacity)

    def _start_fade_out(self):
        self._fade_anim = QtCore.QPropertyAnimation(self, b"opacity_prop", self)
        self._fade_anim.setDuration(300)
        self._fade_anim.setStartValue(1.0)
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.setEasingCurve(QtCore.QEasingCurve.OutCubic)
        self._fade_anim.finished.connect(self._on_fade_finished)
        self._fade_anim.start()

    def _on_fade_finished(self):
        self.dismissed.emit(self)

    def dismiss(self):
        if self._fade_anim and self._fade_anim.state() == QtCore.QAbstractAnimation.Running:
            return
        self._start_fade_out()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setOpacity(self._opacity)
        bg = QtGui.QColor(self._bg_color)
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(self.rect(), uipx(4), uipx(4))
        painter.setPen(self._text_color)
        painter.drawText(self.rect(), QtCore.Qt.AlignCenter, self._display_text)
        painter.end()


class OverlayStack(QtWidgets.QWidget):

    def __init__(self, parent: QtWidgets.QWidget, max_transient: int = 10):
        super().__init__(parent)
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        self.setAttribute(QtCore.Qt.WA_NoSystemBackground)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint)
        self._parent = parent
        self._max_transient = max_transient
        self._persistent: list[tuple[str, QtWidgets.QWidget]] = []
        self._transient: list[OverlayItem] = []
        self._margin = uipx(8)
        self._spacing = uipx(4)
        self._pos_anim_group: list[QtCore.QPropertyAnimation] = []
        parent.installEventFilter(self)
        self.resize(parent.size())
        self.show()
        self.raise_()

    def eventFilter(self, watched, event):
        if not isinstance(event, QtCore.QEvent):
            return False
        if watched == self._parent and event.type() == QtCore.QEvent.Resize:
            self.resize(self._parent.size())
        return super().eventFilter(watched, event)

    def push_persistent(self, widget: QtWidgets.QWidget, key: str) -> QtWidgets.QWidget:
        for k, w in self._persistent:
            if k == key:
                return w
        widget.setParent(self)
        self._persistent.append((key, widget))
        self._relayout(animated=False)
        return widget

    def remove_persistent(self, key: str):
        for i, (k, w) in enumerate(self._persistent):
            if k == key:
                self._persistent.pop(i)
                w.hide()
                self._relayout(animated=True)
                return

    def show_persistent(self, key: str):
        for k, w in self._persistent:
            if k == key:
                w.show()
                self._relayout(animated=True)
                return

    def hide_persistent(self, key: str):
        for k, w in self._persistent:
            if k == key:
                w.hide()
                self._relayout(animated=True)
                return

    def push(self, text: str, level: str = "info", duration: int = 3000) -> OverlayItem:
        while len(self._transient) >= self._max_transient:
            oldest = self._transient[0]
            self._remove_transient(oldest)
        item = OverlayItem(text, level, duration, parent=self)
        item.dismissed.connect(self._on_item_dismissed)
        self._transient.append(item)
        item.show()
        self._relayout(animated=True)
        return item

    def _on_item_dismissed(self, item: OverlayItem):
        self._remove_transient(item)

    def _remove_transient(self, item: OverlayItem):
        if item in self._transient:
            self._transient.remove(item)
            item.hide()
            item.deleteLater()
            self._relayout(animated=True)

    def _relayout(self, animated: bool = False):
        for anim in self._pos_anim_group:
            anim.stop()
        self._pos_anim_group.clear()
        y = self._margin
        x = self._margin
        for _key, w in self._persistent:
            if not w.isVisible():
                continue
            target = QtCore.QPoint(x, y)
            if animated and w.pos() != target and w.pos() != QtCore.QPoint(0, 0):
                self._animate_move(w, target)
            else:
                w.move(target)
            y += w.height() + self._spacing
        for item in self._transient:
            target = QtCore.QPoint(x, y)
            if animated and item.pos() != target and item.pos() != QtCore.QPoint(0, 0):
                self._animate_move(item, target)
            else:
                item.move(target)
            y += item.height() + self._spacing

    def _animate_move(self, widget: QtWidgets.QWidget, target: QtCore.QPoint):
        anim = QtCore.QPropertyAnimation(widget, b"pos", self)
        anim.setDuration(200)
        anim.setStartValue(widget.pos())
        anim.setEndValue(target)
        anim.setEasingCurve(QtCore.QEasingCurve.OutCubic)
        self._pos_anim_group.append(anim)
        anim.start()
