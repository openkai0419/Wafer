from PySide6 import QtCore, QtGui, QtWidgets
from ...common.funcs import uipx

class HoverProxy(QtWidgets.QWidget):

    def __init__(self, target_widget, margin=None):
        if margin is None:
            margin = uipx(10)
        super().__init__(target_widget.parent())
        self._target = target_widget
        self._margin = margin
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, False)
        self.setMouseTracking(True)
        self.setVisible(True)
        self.raise_()
        self._target.installEventFilter(self)
        self.updateGeometry()

    def updateGeometry(self):
        geom = self._target.geometry()
        expanded = geom.adjusted(-self._margin, -self._margin, self._margin, self._margin)
        self.setGeometry(expanded)

    def eventFilter(self, watched, event):
        if not isinstance(event, QtCore.QEvent):
            return False
        if watched is self._target and event.type() == QtCore.QEvent.Move:
            self.updateGeometry()
        return False

    def mouseMoveEvent(self, event):
        center_event = QtGui.QMouseEvent(event.type(), self._target.mapFromParent(event.position().toPoint()), QtCore.Qt.NoButton, QtCore.Qt.NoButton, QtCore.Qt.NoModifier)
        QtWidgets.QApplication.sendEvent(self._target, center_event)

    def leaveEvent(self, event):
        leave_evt = QtCore.QEvent(QtCore.QEvent.Leave)
        QtWidgets.QApplication.sendEvent(self._target, leave_evt)

class PopupWindow(QtWidgets.QWidget):

    def __init__(self, parent, *args, **kwargs):
        super().__init__(*args, parent=parent, **kwargs)
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint | QtCore.Qt.ToolTip)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setStyleSheet('background-color: white; border: 1px solid gray;')

    def setText(self, text):
        pass

class TooltipPopup(PopupWindow):

    def __init__(self, text, parent=None):
        super().__init__(parent=parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, uipx(4), uipx(8), uipx(4))
        self.label = QtWidgets.QLabel(text)
        self.label.setStyleSheet('color: white; background: black; padding: 2px; border-radius: 3px;')
        layout.addWidget(self.label)

    def setText(self, text):
        self.label.setText(text)

class ThinProgressBar(QtWidgets.QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0
        self._maximum = 0
        self.setFixedHeight(3)
        self.setMinimumWidth(100)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self._color_opacity = 0.0
        self._opacity_animation = QtCore.QVariantAnimation()
        self._opacity_animation.setDuration(200)
        self._opacity_animation.valueChanged.connect(self.setColorOpacity)
        self._value_animation = QtCore.QVariantAnimation()
        self._value_animation.setDuration(300)
        self._value_animation.valueChanged.connect(self._setAnimatedValue)
        self._animated_value = 0
        self._glow_offset = 0.0
        self._glow_timer = QtCore.QTimer(self)
        self._glow_timer.timeout.connect(self._updateGlow)
        self._glow_timer.start(15)
        self._base_color = QtGui.QColor(0, 255, 0)
        self._tooltip = None
        self.setMouseTracking(True)
        QtCore.QTimer.singleShot(0, self._installHoverProxy)

    def _installHoverProxy(self):
        self._hover_proxy = HoverProxy(self, margin=uipx(3))

    def setProgress(self, value):
        value = max(0, min(self._maximum, value))
        self._value_animation.stop()
        self._value_animation.setStartValue(self._animated_value)
        self._value_animation.setEndValue(value)
        self._value_animation.start()
        if value == 0 or value >= self._maximum:
            self.fadeOut()
            value = 0
        else:
            self.fadeIn()
        self._value = value
        self._updateTooltipText()

    def setMaximum(self, maximum):
        self._maximum = max(0, maximum)
        self.setProgress(self._value)
        self._updateTooltipText()

    def addProgress(self, inc):
        self.setProgress(self._value + inc)

    def addMaximum(self, inc):
        self.setMaximum(self._maximum + inc)

    def maximum(self):
        return self._maximum

    def value(self):
        return self._value

    def _setAnimatedValue(self, val):
        self._animated_value = val
        self.update()

    def _updateGlow(self):
        if self._color_opacity > 0.0 and 0 < self._animated_value < self._maximum:
            self._glow_offset += 0.01
            if self._glow_offset > 1.4:
                self._glow_offset = -0.4
            self.update()

    def _fadeTo(self, target_opacity):
        if self._color_opacity == target_opacity:
            return
        self._opacity_animation.stop()
        self._opacity_animation.setStartValue(self._color_opacity)
        self._opacity_animation.setEndValue(target_opacity)
        self._opacity_animation.start()

    def fadeIn(self):
        self._fadeTo(1.0)

    def fadeOut(self, immediate=False):
        if immediate:
            self.setColorOpacity(0.0)
        else:
            self._fadeTo(0.0)

    def getColorOpacity(self):
        return self._color_opacity

    def setColorOpacity(self, opacity):
        self._color_opacity = opacity
        self.update()

    def getBaseColor(self):
        return self._base_color

    def setBaseColor(self, color):
        self._base_color = color
        self.update()
    colorOpacity = QtCore.Property(float, getColorOpacity, setColorOpacity)
    baseColor = QtCore.Property(QtGui.QColor, getBaseColor, setBaseColor)

    def paintEvent(self, event):
        if self._animated_value <= 0:
            return
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        self._drawBar(painter)
        if self._color_opacity > 0:
            self._drawGlow(painter)

    def _drawBar(self, painter):
        rect = self.rect()
        ratio = self._animated_value / self._maximum if self._maximum else 0
        bar_width = rect.width() * ratio
        base_color = QtGui.QColor(self._base_color)
        base_color.setAlphaF(self._color_opacity)
        painter.setBrush(QtGui.QBrush(base_color))
        painter.setPen(QtCore.Qt.NoPen)
        painter.drawRect(0, 0, int(bar_width), rect.height())

    def _drawGlow(self, painter):
        rect = self.rect()
        ratio = self._animated_value / self._maximum if self._maximum else 0
        bar_width = rect.width() * ratio
        if bar_width <= 0:
            return
        glow_width = max(uipx(10), int(bar_width * 0.4))
        glow_x = int((bar_width + glow_width) * self._glow_offset - glow_width)
        gradient = QtGui.QLinearGradient(glow_x, 0, glow_x + glow_width, 0)
        glow_color = QtGui.QColor(255, 255, 255, int(180 * self._color_opacity))
        transparent = QtGui.QColor(255, 255, 255, 0)
        gradient.setColorAt(0.0, transparent)
        gradient.setColorAt(0.3, glow_color)
        gradient.setColorAt(0.7, glow_color)
        gradient.setColorAt(1.0, transparent)
        painter.setBrush(QtGui.QBrush(gradient))
        painter.setPen(QtCore.Qt.NoPen)
        painter.drawRect(0, 0, int(bar_width), rect.height())

    def mouseMoveEvent(self, event):
        if self._maximum == 0:
            return
        percent = int(self._animated_value / self._maximum * 100)
        text = f'{int(self._animated_value)} / {self._maximum} ({percent}%)'
        offset = QtCore.QPoint(uipx(8), uipx(16))
        if self._tooltip is None:
            self._tooltip = TooltipPopup(text, parent=self)
            self._tooltip.move(QtGui.QCursor.pos() + offset)
            self._tooltip.show()
        else:
            self._tooltip.setText(text)
            self._tooltip.move(QtGui.QCursor.pos() + offset)

    def leaveEvent(self, event):
        if self._tooltip is not None:
            self._tooltip.close()
            self._tooltip = None
        super().leaveEvent(event)

    def _updateTooltipText(self):
        if self._maximum == 0:
            return
        if self._tooltip is not None:
            percent = int(self._animated_value / self._maximum * 100)
            text = f'{int(self._animated_value)} / {self._maximum} ({percent}%)'
            self._tooltip.setText(text)
if __name__ == '__main__':
    import random
    import sys
    app = QtWidgets.QApplication(sys.argv)
    window = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(window)
    layout.setSpacing(0)
    progressBar = ThinProgressBar()
    layout.addWidget(progressBar)
    btn = QtWidgets.QPushButton('Random progress')
    layout.addWidget(btn)

    def update():
        maximum = random.randint(50, 10000)
        progressBar.setMaximum(maximum)
        val = random.randint(0, maximum)
        progressBar.setProgress(val)
    progressBar.setProgress(5000)
    timer = QtCore.QTimer()
    timer.setInterval(500)
    timer.timeout.connect(update)
    timer.start()
    btn.clicked.connect(update)
    window.resize(300, 100)
    window.show()
    sys.exit(app.exec())
