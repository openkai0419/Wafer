from PySide6 import QtCore, QtGui, QtWidgets

class ScrollBarColorStyle(QtWidgets.QProxyStyle):
    def drawComplexControl(self, control, option, painter, widget=None):
        if control == QtWidgets.QStyle.CC_ScrollBar:
            opt = QtWidgets.QStyleOptionSlider(option)
            super().drawComplexControl(control, option, painter, widget)

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
        vbar = self.verticalScrollBar()
        self.animation = QtCore.QPropertyAnimation(vbar, b"value")
        self.animation.setEasingCurve(QtCore.QEasingCurve.Linear)
        vbar.sliderPressed.connect(self._on_user_interaction)
        vbar.actionTriggered.connect(self._on_user_interaction)
        self._scroll_speed = 100
        self._speed_callback = None

    def change_style(self):
        app = QtWidgets.QApplication.instance()
        base = app.style()
        proxy = ScrollBarColorStyle(base)
        for sb in (self.verticalScrollBar(), self.horizontalScrollBar()):
            sb.setStyle(proxy)
            sb.setAttribute(QtCore.Qt.WidgetAttribute.WA_Hover, True)

    def set_speed_callback(self, callback):
        self._speed_callback = callback

    def start_auto_scroll(self, speed=100):
        self._scroll_speed = speed
        self._start_animation_from_current()

    def stop_auto_scroll(self):
        self.animation.stop()

    def isscrolling(self):
        return self.animation.state() == QtCore.QAbstractAnimation.Running

    def _start_animation_from_current(self):
        bar = self.verticalScrollBar()
        start_value = bar.value()
        end_value = bar.maximum()
        
        if start_value >= end_value:
            self.stop_auto_scroll()
            return
        
        if self._speed_callback:
            self._scroll_speed = self._speed_callback()
        
        distance = end_value - start_value
        duration = min(int(distance / self._scroll_speed * 1000), 2147483647)
        
        self.animation.stop()
        self.animation.setStartValue(start_value)
        self.animation.setEndValue(end_value)
        self.animation.setDuration(duration)
        self.animation.start()

    def _on_user_interaction(self):
        if self.isscrolling():
            self._start_animation_from_current()

    def _handle_user_event(self, event, super_handler):
        if not self.isscrolling():
            super_handler(event)
            return
        self.animation.stop()
        super_handler(event)
        self._start_animation_from_current()

    def wheelEvent(self, event):
        self._handle_user_event(event, super().wheelEvent)

    def keyPressEvent(self, event):
        self._handle_user_event(event, super().keyPressEvent)

    def mousePressEvent(self, event):
        self._handle_user_event(event, super().mousePressEvent)
