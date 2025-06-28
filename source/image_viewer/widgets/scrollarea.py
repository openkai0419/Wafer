from PySide6.QtWidgets import QScrollArea
from PySide6.QtCore import QTimer

class InertialScrollArea(QScrollArea):
    def __init__(self):
        super().__init__()
        self._velocity = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_scroll)
        self._friction = 0.88  # 摩擦係数
        self._min_velocity = 0.2  # 停止閾値

    def wheelEvent(self, event):
        delta = event.pixelDelta().y() or event.angleDelta().y()
        self._velocity += -delta * 0.2  # 入力をスケーリング
        if not self._timer.isActive():
            self._timer.start(16)  # 約60FPS
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

class AutoScrollArea(QScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._scroll_step)
        self.scroll_speed = 1  # ピクセル単位のスクロール量
        self.scroll_interval = 30  # ms 単位

    def start_auto_scroll(self, speed: int = 1, interval: int = 30):
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
