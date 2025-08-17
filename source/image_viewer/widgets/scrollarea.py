from PySide6 import QtCore, QtWidgets, QtGui

from PySide6 import QtCore, QtGui, QtWidgets

class ScrollBarColorStyle(QtWidgets.QProxyStyle):
    def drawComplexControl(self, control, option, painter, widget=None):
        if control == QtWidgets.QStyle.CC_ScrollBar:
            opt = QtWidgets.QStyleOptionSlider(option)

            # 通常描画（背景やボタンなど）
            super().drawComplexControl(control, option, painter, widget)

            # ハンドル部分を上書き描画
            if opt.subControls & QtWidgets.QStyle.SC_ScrollBarSlider:
                rect = self.subControlRect(control, opt, QtWidgets.QStyle.SC_ScrollBarSlider, widget)
                if rect.isValid():
                    is_hover = opt.state & QtWidgets.QStyle.State_MouseOver
                    color = QtGui.QColor(79, 158, 255) if is_hover else QtGui.QColor(39, 98, 225)

                    if opt.orientation == QtCore.Qt.Vertical:
                        if is_hover:
                            rect.adjust(2, 0, -2, 0)
                        else:
                            rect.adjust(3, 0, -3, 0)
                    else:
                        if is_hover:
                            rect.adjust(0, 2, 0, -2)
                        else:
                            rect.adjust(0, 4, 0, -4)

                    # 角丸の塗りつぶし
                    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
                    painter.setPen(QtCore.Qt.NoPen)
                    painter.setBrush(color)
                    painter.drawRoundedRect(rect, 4, 4)

            return

        super().drawComplexControl(control, option, painter, widget)

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
        #self.change_style()

    def change_style(self):
        app = QtWidgets.QApplication.instance()
        base = app.style()
        proxy = ScrollBarColorStyle(base)
        for sb in (self.verticalScrollBar(), self.horizontalScrollBar()):
            sb.setStyle(proxy)
            sb.setAttribute(QtCore.Qt.WidgetAttribute.WA_Hover, True)

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
