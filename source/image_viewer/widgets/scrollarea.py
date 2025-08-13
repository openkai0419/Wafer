from PySide6 import QtCore, QtWidgets

class ScrollAreaBase(QtWidgets.QScrollArea):
    resized = QtCore.Signal()

    def resizeEvent(self, arg__1):
        self.resized.emit()
        return super().resizeEvent(arg__1)

class InertialScrollArea(ScrollAreaBase):

    def __init__(self):
        super().__init__()
        self._velocity = 0.0
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._update_scroll)
        self._friction = 0.88
        self._min_velocity = 0.2

    def wheelEvent(self, event):
        delta = event.pixelDelta().y() or event.angleDelta().y()
        self._velocity += -delta * 0.2
        if not self._timer.isActive():
            self._timer.start(16)
        event.accept()

    def _update_scroll(self):
        if abs(self._velocity) < self._min_velocity:
            self._velocity = 0
            self._timer.stop()
            return
        bar = self.verticalScrollBar()
        new_val = bar.value() + self._velocity
        bar.setValue(round(new_val))
        self._velocity *= self._friction

class AutoScrollArea(ScrollAreaBase):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._scroll_step)
        self.scroll_speed = 1
        self.scroll_interval = 30

    def start_auto_scroll(self, speed=1, interval=30):
        self.scroll_speed = speed
        self.scroll_interval = interval
        self.timer.setInterval(self.scroll_interval)
        self.timer.start()

    def stop_auto_scroll(self):
        self.timer.stop()

    def isscrolling(self):
        return self.timer.isActive()

    def _scroll_step(self):
        bar = self.verticalScrollBar()
        max_scroll = bar.maximum()
        next_value = bar.value() + self.scroll_speed
        if next_value >= max_scroll:
            self.timer.stop()
        else:
            bar.setValue(next_value)
