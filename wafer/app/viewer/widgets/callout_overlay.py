from PySide6 import QtCore, QtGui, QtWidgets

from ....utils.formatting import dpix
from ....core.color.theme import ThemeManager

_TRACK_INTERVAL_MS = 100
_FADE_DURATION_MS = 500

class CalloutOverlay(QtWidgets.QWidget):
    dismissed = QtCore.Signal()

    def __init__(self, target: QtWidgets.QWidget, text: str, parent=None):
        super().__init__(parent)
        self._target = target
        self._text = text
        self._opacity = 1.0
        self._fade_anim: QtCore.QPropertyAnimation | None = None
        self._last_anchor = QtCore.QPoint()
        self.setWindowFlags(
            QtCore.Qt.Tool
            | QtCore.Qt.FramelessWindowHint
            | QtCore.Qt.WindowTransparentForInput
            | QtCore.Qt.WindowStaysOnTopHint
        )
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)

        self._font = self.font()
        self._font.setPointSizeF(self._font.pointSizeF() * 1.05)
        self._font.setBold(True)

        self._arrow_margin = dpix(16)
        self._outline_w = max(2.0, dpix(2.5))
        self._update_size()

        self._track_timer = QtCore.QTimer(self)
        self._track_timer.setInterval(_TRACK_INTERVAL_MS)
        self._track_timer.timeout.connect(self._reposition)

    def _update_size(self):
        fm = QtGui.QFontMetrics(self._font)
        text_rect = fm.boundingRect(
            0, 0, 9999, 9999, QtCore.Qt.AlignLeft, self._text
        )
        tw = text_rect.width() + dpix(8)
        th = text_rect.height() + dpix(4)
        total_w = self._arrow_margin + tw
        total_h = self._arrow_margin + th
        self.setFixedSize(total_w, total_h)

    def show(self):
        self._reposition()
        self.setWindowOpacity(0.0)
        super().show()
        self._track_timer.start()
        self._fade_anim = QtCore.QPropertyAnimation(self, b"opacity_prop", self)
        self._fade_anim.setDuration(_FADE_DURATION_MS)
        self._fade_anim.setStartValue(0.0)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.setEasingCurve(QtCore.QEasingCurve.OutCubic)
        self._fade_anim.start()

    def hide(self):
        self._track_timer.stop()
        super().hide()

    def _reposition(self):
        try:
            if not self._target.isVisible():
                self.hide()
                return
            anchor = self._target.mapToGlobal(
                QtCore.QPoint(self._target.width(), self._target.height())
            )
        except RuntimeError:
            self.close()
            return
        if anchor == self._last_anchor:
            return
        self._last_anchor = anchor
        self.move(anchor.x() - dpix(6), anchor.y() + dpix(2))

    def _get_opacity(self):
        return self._opacity

    def _set_opacity(self, val):
        self._opacity = val
        self.setWindowOpacity(val)

    opacity_prop = QtCore.Property(float, _get_opacity, _set_opacity)

    def dismiss(self):
        self._track_timer.stop()
        if self._fade_anim and self._fade_anim.state() == QtCore.QAbstractAnimation.Running:
            return
        self._fade_anim = QtCore.QPropertyAnimation(self, b"opacity_prop", self)
        self._fade_anim.setDuration(_FADE_DURATION_MS)
        self._fade_anim.setStartValue(self._opacity)
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.setEasingCurve(QtCore.QEasingCurve.OutCubic)
        self._fade_anim.finished.connect(self._on_fade_done)
        self._fade_anim.start()

    def _on_fade_done(self):
        self.dismissed.emit()
        self.close()

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)

        palette = ThemeManager.instance().palette
        fg = QtGui.QColor(palette.text_primary)
        outline = QtGui.QColor(palette.bg_primary)
        outline.setAlpha(200)

        self._draw_curved_arrow(p, fg, outline)
        self._draw_outlined_text(p, fg, outline)
        p.end()

    def _draw_curved_arrow(self, p: QtGui.QPainter, fg: QtGui.QColor, outline: QtGui.QColor):
        w = self.width()
        h = self.height()
        am = self._arrow_margin

        start = QtCore.QPointF(am * 0.4, h * 0.55)
        ctrl1 = QtCore.QPointF(am * 0.15, h * 0.25)
        ctrl2 = QtCore.QPointF(am * 0.05, am * 0.15)
        end = QtCore.QPointF(dpix(3), dpix(3))

        shaft = QtGui.QPainterPath()
        shaft.moveTo(start)
        shaft.cubicTo(ctrl1, ctrl2, end)

        arrow_len = dpix(7)
        head = QtGui.QPainterPath()
        head.moveTo(end)
        head.lineTo(end + QtCore.QPointF(arrow_len, arrow_len * 0.3))
        head.moveTo(end)
        head.lineTo(end + QtCore.QPointF(arrow_len * 0.3, arrow_len))

        stroke_w = max(1.5, dpix(1.8))
        outline_pen = QtGui.QPen(outline, stroke_w + self._outline_w * 2)
        outline_pen.setCapStyle(QtCore.Qt.RoundCap)
        outline_pen.setJoinStyle(QtCore.Qt.RoundJoin)
        p.setPen(outline_pen)
        p.drawPath(shaft)
        p.drawPath(head)

        fg_pen = QtGui.QPen(fg, stroke_w)
        fg_pen.setCapStyle(QtCore.Qt.RoundCap)
        fg_pen.setJoinStyle(QtCore.Qt.RoundJoin)
        p.setPen(fg_pen)
        p.drawPath(shaft)
        p.drawPath(head)

    def _draw_outlined_text(self, p: QtGui.QPainter, fg: QtGui.QColor, outline: QtGui.QColor):
        am = self._arrow_margin
        text_x = am
        text_y = am + dpix(2)

        p.setFont(self._font)
        text_path = QtGui.QPainterPath()
        text_path.addText(QtCore.QPointF(text_x, text_y + QtGui.QFontMetrics(self._font).ascent()), self._font, self._text)

        outline_pen = QtGui.QPen(outline, self._outline_w * 2)
        outline_pen.setJoinStyle(QtCore.Qt.RoundJoin)
        outline_pen.setCapStyle(QtCore.Qt.RoundCap)
        p.setPen(outline_pen)
        p.setBrush(QtCore.Qt.NoBrush)
        p.drawPath(text_path)

        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(fg)
        p.drawPath(text_path)
