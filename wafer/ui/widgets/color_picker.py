from __future__ import annotations

import math
from PySide6 import QtCore, QtGui, QtWidgets

from ...core.color.theme import ThemeManager
from ...core.lang.manager import t
from ...utils import recent_colors
from ...utils.formatting import dpix
from ...utils.logs import AppLogger


def _qcolor(value) -> QtGui.QColor:
    if isinstance(value, QtGui.QColor):
        return QtGui.QColor(value)
    return QtGui.QColor(value) if value else QtGui.QColor("#888888")


class HueRingSVSquare(QtWidgets.QWidget):
    """Hue ring with central saturation/value square. Emits hsvChanged(h, s, v) in 0..1."""

    hsvChanged = QtCore.Signal(float, float, float)

    RING_THICKNESS_RATIO = 0.18

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(dpix(160), dpix(160))
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self._h = 0.0
        self._s = 1.0
        self._v = 1.0
        self._dragging = None
        self._ring_cache: QtGui.QPixmap | None = None
        self._sv_cache: QtGui.QPixmap | None = None
        self._cached_size = QtCore.QSize()
        self._cached_hue = -1.0

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return w

    def set_hsv(self, h: float, s: float, v: float):
        h = max(0.0, min(1.0, h))
        s = max(0.0, min(1.0, s))
        v = max(0.0, min(1.0, v))
        if (h, s, v) == (self._h, self._s, self._v):
            return
        if h != self._h:
            self._sv_cache = None
        self._h = h
        self._s = s
        self._v = v
        self.update()

    def hsv(self) -> tuple[float, float, float]:
        return self._h, self._s, self._v

    def _geometry(self):
        side = min(self.width(), self.height())
        cx = self.width() / 2.0
        cy = self.height() / 2.0
        outer = side / 2.0 - dpix(2)
        thickness = max(dpix(12), outer * self.RING_THICKNESS_RATIO)
        inner = outer - thickness
        sv_side = inner * math.sqrt(2.0) - dpix(4)
        return cx, cy, outer, inner, sv_side

    def _ensure_caches(self):
        size = self.size()
        if self._cached_size != size:
            self._ring_cache = None
            self._sv_cache = None
            self._cached_size = QtCore.QSize(size)

        cx, cy, outer, inner, sv_side = self._geometry()

        if self._ring_cache is None:
            pm = QtGui.QPixmap(self.size() * self.devicePixelRatioF())
            pm.setDevicePixelRatio(self.devicePixelRatioF())
            pm.fill(QtCore.Qt.transparent)
            painter = QtGui.QPainter(pm)
            painter.setRenderHint(QtGui.QPainter.Antialiasing)
            grad = QtGui.QConicalGradient(QtCore.QPointF(cx, cy), 0)
            for i in range(7):
                pos = i / 6.0
                grad.setColorAt(pos, QtGui.QColor.fromHsvF((1.0 - pos) % 1.0, 1.0, 1.0))
            painter.setBrush(QtGui.QBrush(grad))
            painter.setPen(QtCore.Qt.NoPen)
            painter.drawEllipse(QtCore.QPointF(cx, cy), outer, outer)
            painter.setCompositionMode(QtGui.QPainter.CompositionMode_Clear)
            painter.drawEllipse(QtCore.QPointF(cx, cy), inner, inner)
            painter.end()
            self._ring_cache = pm

        if self._sv_cache is None or self._cached_hue != self._h:
            self._cached_hue = self._h
            sq_size = max(2, int(round(sv_side)))
            img = QtGui.QImage(sq_size, sq_size, QtGui.QImage.Format_ARGB32_Premultiplied)
            painter = QtGui.QPainter(img)
            base = QtGui.QColor.fromHsvF(self._h, 1.0, 1.0)
            sat_grad = QtGui.QLinearGradient(0, 0, sq_size, 0)
            sat_grad.setColorAt(0.0, QtGui.QColor(255, 255, 255))
            sat_grad.setColorAt(1.0, base)
            painter.fillRect(0, 0, sq_size, sq_size, QtGui.QBrush(sat_grad))
            val_grad = QtGui.QLinearGradient(0, 0, 0, sq_size)
            val_grad.setColorAt(0.0, QtGui.QColor(0, 0, 0, 0))
            val_grad.setColorAt(1.0, QtGui.QColor(0, 0, 0, 255))
            painter.fillRect(0, 0, sq_size, sq_size, QtGui.QBrush(val_grad))
            painter.end()
            pm = QtGui.QPixmap.fromImage(img)
            pm.setDevicePixelRatio(self.devicePixelRatioF())
            self._sv_cache = pm

    def paintEvent(self, _event):
        self._ensure_caches()
        cx, cy, outer, inner, sv_side = self._geometry()
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.drawPixmap(0, 0, self._ring_cache)
        sq_rect = QtCore.QRectF(cx - sv_side / 2.0, cy - sv_side / 2.0, sv_side, sv_side)
        painter.drawPixmap(sq_rect, self._sv_cache, QtCore.QRectF(self._sv_cache.rect()))

        ring_radius = (outer + inner) / 2.0
        angle = (1.0 - self._h) * 2.0 * math.pi
        hx = cx + ring_radius * math.cos(angle)
        hy = cy - ring_radius * math.sin(angle)
        marker_pen = QtGui.QPen(QtGui.QColor(0, 0, 0, 200), dpix(2))
        painter.setPen(marker_pen)
        painter.setBrush(QtCore.Qt.NoBrush)
        r = max(dpix(6), (outer - inner) / 2.0 - dpix(2))
        painter.drawEllipse(QtCore.QPointF(hx, hy), r, r)
        painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255), dpix(1)))
        painter.drawEllipse(QtCore.QPointF(hx, hy), r - dpix(1), r - dpix(1))

        sx = sq_rect.left() + self._s * sv_side
        sy = sq_rect.top() + (1.0 - self._v) * sv_side
        painter.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 220), dpix(2)))
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawEllipse(QtCore.QPointF(sx, sy), dpix(5), dpix(5))
        painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255), dpix(1)))
        painter.drawEllipse(QtCore.QPointF(sx, sy), dpix(4), dpix(4))

    def mousePressEvent(self, event):
        if event.button() != QtCore.Qt.LeftButton:
            return
        cx, cy, outer, inner, sv_side = self._geometry()
        dx = event.position().x() - cx
        dy = event.position().y() - cy
        dist = math.hypot(dx, dy)
        if inner <= dist <= outer + dpix(4):
            self._dragging = "ring"
            self._update_from_pos(event.position())
        elif abs(dx) <= sv_side / 2.0 and abs(dy) <= sv_side / 2.0:
            self._dragging = "sv"
            self._update_from_pos(event.position())

    def mouseMoveEvent(self, event):
        if self._dragging:
            self._update_from_pos(event.position())

    def mouseReleaseEvent(self, _event):
        self._dragging = None

    def _update_from_pos(self, pos: QtCore.QPointF):
        cx, cy, outer, inner, sv_side = self._geometry()
        if self._dragging == "ring":
            angle = math.atan2(-(pos.y() - cy), pos.x() - cx)
            h = (1.0 - angle / (2.0 * math.pi)) % 1.0
            self.set_hsv(h, self._s, self._v)
        elif self._dragging == "sv":
            left = cx - sv_side / 2.0
            top = cy - sv_side / 2.0
            s = (pos.x() - left) / sv_side if sv_side else 0.0
            v = 1.0 - (pos.y() - top) / sv_side if sv_side else 1.0
            self.set_hsv(self._h, max(0.0, min(1.0, s)), max(0.0, min(1.0, v)))
        self.hsvChanged.emit(self._h, self._s, self._v)

    def resizeEvent(self, event):
        self._ring_cache = None
        self._sv_cache = None
        super().resizeEvent(event)


class _LabeledSlider(QtWidgets.QWidget):
    valueChanged = QtCore.Signal(int)

    def __init__(self, label: str, maximum: int = 255, parent=None):
        super().__init__(parent)
        self._maximum = maximum
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(dpix(6))
        self._label = QtWidgets.QLabel(label)
        self._label.setFixedWidth(dpix(18))
        self._label.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(self._label)
        self._slider = _GradientSlider(QtCore.Qt.Horizontal)
        self._slider.setRange(0, maximum)
        self._slider.setMinimumWidth(dpix(120))
        layout.addWidget(self._slider, 1)
        self._spin = QtWidgets.QSpinBox()
        self._spin.setRange(0, maximum)
        self._spin.setFixedWidth(dpix(58))
        self._spin.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
        layout.addWidget(self._spin)
        self._slider.valueChanged.connect(self._on_slider)
        self._spin.valueChanged.connect(self._on_spin)

    def value(self) -> int:
        return self._slider.value()

    def set_value(self, v: int):
        v = int(v)
        with QtCore.QSignalBlocker(self._slider), QtCore.QSignalBlocker(self._spin):
            self._slider.setValue(v)
            self._spin.setValue(v)

    def set_gradient(self, stops: list[tuple[float, QtGui.QColor]]):
        self._slider.set_gradient(stops)

    def _on_slider(self, v):
        with QtCore.QSignalBlocker(self._spin):
            self._spin.setValue(v)
        self.valueChanged.emit(v)

    def _on_spin(self, v):
        with QtCore.QSignalBlocker(self._slider):
            self._slider.setValue(v)
        self.valueChanged.emit(v)


class _GradientSlider(QtWidgets.QSlider):
    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self._stops: list[tuple[float, QtGui.QColor]] = []
        self.setMinimumHeight(dpix(20))

    def set_gradient(self, stops: list[tuple[float, QtGui.QColor]]):
        self._stops = stops
        self.update()

    def paintEvent(self, _event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        track_h = dpix(8)
        rect = QtCore.QRectF(0, (self.height() - track_h) / 2.0, self.width(), track_h)
        if self._stops:
            grad = QtGui.QLinearGradient(rect.left(), 0, rect.right(), 0)
            for pos, col in self._stops:
                grad.setColorAt(pos, col)
            painter.setBrush(QtGui.QBrush(grad))
        else:
            painter.setBrush(QtGui.QColor(ThemeManager.instance().palette.bg_tertiary))
        painter.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 60), 1))
        painter.drawRoundedRect(rect, track_h / 2.0, track_h / 2.0)

        if self.maximum() > self.minimum():
            ratio = (self.value() - self.minimum()) / (self.maximum() - self.minimum())
        else:
            ratio = 0.0
        x = rect.left() + ratio * rect.width()
        cy = rect.center().y()
        painter.setBrush(QtGui.QColor(255, 255, 255))
        painter.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 180), dpix(1)))
        painter.drawEllipse(QtCore.QPointF(x, cy), dpix(7), dpix(7))

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self._set_from_pos(event.position().x())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & QtCore.Qt.LeftButton:
            self._set_from_pos(event.position().x())
        super().mouseMoveEvent(event)

    def _set_from_pos(self, x: float):
        if self.width() <= 0:
            return
        ratio = max(0.0, min(1.0, x / self.width()))
        new_val = self.minimum() + round(ratio * (self.maximum() - self.minimum()))
        if new_val != self.value():
            self.setValue(int(new_val))


class _CheckerSwatch(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._color = QtGui.QColor(255, 255, 255)
        self.setMinimumHeight(dpix(28))
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)

    def set_color(self, c: QtGui.QColor):
        self._color = QtGui.QColor(c)
        self.update()

    def paintEvent(self, _event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        rect = self.rect().adjusted(0, 0, -1, -1)
        path = QtGui.QPainterPath()
        path.addRoundedRect(QtCore.QRectF(rect), dpix(4), dpix(4))
        painter.setClipPath(path)
        size = dpix(6)
        light = QtGui.QColor(220, 220, 220)
        dark = QtGui.QColor(170, 170, 170)
        for y in range(0, rect.height() + size, size):
            for x in range(0, rect.width() + size, size):
                painter.fillRect(x, y, size, size, dark if ((x // size + y // size) % 2) else light)
        painter.fillRect(rect, self._color)
        painter.setClipping(False)
        painter.setPen(QtGui.QPen(QtGui.QColor(ThemeManager.instance().palette.border_default), 1))
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawRoundedRect(QtCore.QRectF(rect), dpix(4), dpix(4))


class _RecentColorsBar(QtWidgets.QWidget):
    color_picked = QtCore.Signal(QtGui.QColor)

    def __init__(self, scope: str, parent=None):
        super().__init__(parent)
        self._scope = scope
        self._layout = QtWidgets.QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(dpix(3))
        self.refresh()

    def refresh(self):
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        colors = recent_colors.load(self._scope)
        if not colors:
            label = QtWidgets.QLabel(t("No recent colors"))
            label.setStyleSheet(f"color: {ThemeManager.instance().palette.text_muted};")
            self._layout.addWidget(label)
            self._layout.addStretch(1)
            return
        for c in colors:
            btn = _SwatchButton(QtGui.QColor(c))
            btn.clicked.connect(lambda _=False, col=c: self.color_picked.emit(QtGui.QColor(col)))
            self._layout.addWidget(btn)
        self._layout.addStretch(1)


class _SwatchButton(QtWidgets.QPushButton):
    def __init__(self, color: QtGui.QColor, parent=None):
        super().__init__(parent)
        self._color = color
        self.setFixedSize(dpix(18), dpix(18))
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setToolTip(color.name(QtGui.QColor.HexArgb).upper())
        p = ThemeManager.instance().palette
        self.setStyleSheet(
            f"QPushButton {{ background: {color.name()}; border: 1px solid {p.border_default}; border-radius: {dpix(3)}px; }}"
            f"QPushButton:hover {{ border: {dpix(2)}px solid {p.text_primary}; }}"
        )


class ColorPickerWidget(QtWidgets.QWidget):
    """Embeddable color picker.

    Args:
        initial: initial color (str hex or QColor).
        with_alpha: enable alpha slider and 8-digit hex.
        scope: identifier for persisting recent-color history.
    """

    colorChanged = QtCore.Signal(QtGui.QColor)

    def __init__(self, initial: str | QtGui.QColor = "#888888", with_alpha: bool = False, scope: str = "general", parent=None):
        super().__init__(parent)
        self._with_alpha = bool(with_alpha)
        self._scope = scope or "general"
        self._color = _qcolor(initial)
        if not self._with_alpha:
            self._color.setAlpha(255)
        self._updating = False
        self._build_ui()
        self._sync_all_from_color()

    def _build_ui(self):
        outer = QtWidgets.QHBoxLayout(self)
        outer.setContentsMargins(dpix(8), dpix(8), dpix(8), dpix(8))
        outer.setSpacing(0)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(dpix(6))
        outer.addWidget(splitter)

        self._wheel = HueRingSVSquare()
        splitter.addWidget(self._wheel)

        right_container = QtWidgets.QWidget()
        right_container.setMinimumWidth(dpix(220))
        right = QtWidgets.QVBoxLayout(right_container)
        right.setContentsMargins(dpix(8), 0, 0, 0)
        right.setSpacing(dpix(6))
        splitter.addWidget(right_container)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)

        self._swatch = _CheckerSwatch()
        self._swatch.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        right.addWidget(self._swatch)

        hex_row = QtWidgets.QHBoxLayout()
        hex_row.setSpacing(dpix(4))
        hex_label = QtWidgets.QLabel(t("Hex"))
        hex_label.setFixedWidth(dpix(28))
        hex_row.addWidget(hex_label)
        self._hex_edit = QtWidgets.QLineEdit()
        self._hex_edit.setMaxLength(9)
        self._hex_edit.setPlaceholderText("#RRGGBB" + ("AA" if self._with_alpha else ""))
        hex_row.addWidget(self._hex_edit, 1)
        right.addLayout(hex_row)

        self._slider_h = _LabeledSlider("H", 359)
        self._slider_s = _LabeledSlider("S", 255)
        self._slider_v = _LabeledSlider("V", 255)
        self._slider_r = _LabeledSlider("R", 255)
        self._slider_g = _LabeledSlider("G", 255)
        self._slider_b = _LabeledSlider("B", 255)

        self._tabs = QtWidgets.QTabWidget()
        self._tabs.setDocumentMode(True)

        hsv_page = QtWidgets.QWidget()
        hsv_layout = QtWidgets.QVBoxLayout(hsv_page)
        hsv_layout.setContentsMargins(dpix(1), dpix(1), dpix(1), dpix(1))
        hsv_layout.setSpacing(dpix(2))
        for w in (self._slider_h, self._slider_s, self._slider_v):
            hsv_layout.addWidget(w)
        self._tabs.addTab(hsv_page, "HSV")

        rgb_page = QtWidgets.QWidget()
        rgb_layout = QtWidgets.QVBoxLayout(rgb_page)
        rgb_layout.setContentsMargins(dpix(1), dpix(1), dpix(1), dpix(1))
        rgb_layout.setSpacing(dpix(2))
        for w in (self._slider_r, self._slider_g, self._slider_b):
            rgb_layout.addWidget(w)
        self._tabs.addTab(rgb_page, "RGB")
        self._tabs.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Preferred)

        right.addWidget(self._tabs)

        if self._with_alpha:
            self._slider_a = _LabeledSlider("A", 255)
            right.addWidget(self._slider_a)
            self._slider_a.valueChanged.connect(self._on_rgb_changed)
        else:
            self._slider_a = None

        right.addSpacing(dpix(4))
        recent_label = QtWidgets.QLabel(t("Recent colors"))
        recent_label.setStyleSheet(f"color: {ThemeManager.instance().palette.text_secondary}; font-size: {dpix(11)}px;")
        right.addWidget(recent_label)
        self._recent_bar = _RecentColorsBar(self._scope)
        right.addWidget(self._recent_bar)

        self._wheel.hsvChanged.connect(self._on_wheel_changed)
        for w in (self._slider_h, self._slider_s, self._slider_v):
            w.valueChanged.connect(self._on_hsv_changed)
        for w in (self._slider_r, self._slider_g, self._slider_b):
            w.valueChanged.connect(self._on_rgb_changed)
        self._hex_edit.editingFinished.connect(self._on_hex_changed)
        self._recent_bar.color_picked.connect(self.set_color)

    def color(self) -> QtGui.QColor:
        c = QtGui.QColor(self._color)
        if not self._with_alpha:
            c.setAlpha(255)
        return c

    def set_color(self, value):
        c = _qcolor(value)
        if not self._with_alpha:
            c.setAlpha(255)
        if c == self._color:
            return
        self._color = c
        self._sync_all_from_color()
        self.colorChanged.emit(self.color())

    def commit_to_recent(self):
        recent_colors.add(self.color().name(QtGui.QColor.HexArgb if self._with_alpha else QtGui.QColor.HexRgb), self._scope)
        self._recent_bar.refresh()

    def _sync_all_from_color(self):
        self._updating = True
        try:
            h, s, v, _ = self._color.getHsvF()
            if h < 0:
                h = 0.0
            self._wheel.set_hsv(h, s, v)
            self._slider_h.set_value(int(round(h * 359)))
            self._slider_s.set_value(int(round(s * 255)))
            self._slider_v.set_value(int(round(v * 255)))
            self._slider_r.set_value(self._color.red())
            self._slider_g.set_value(self._color.green())
            self._slider_b.set_value(self._color.blue())
            if self._slider_a is not None:
                self._slider_a.set_value(self._color.alpha())
            self._update_gradients()
            self._swatch.set_color(self._color)
            fmt = QtGui.QColor.HexArgb if self._with_alpha else QtGui.QColor.HexRgb
            self._hex_edit.setText(self._color.name(fmt).upper())
        finally:
            self._updating = False

    def _update_gradients(self):
        r, g, b = self._color.red(), self._color.green(), self._color.blue()

        def stops_replace(idx, low, high):
            base = [r, g, b]
            base[idx] = low
            c1 = QtGui.QColor(*base)
            base[idx] = high
            c2 = QtGui.QColor(*base)
            return [(0.0, c1), (1.0, c2)]

        self._slider_r.set_gradient(stops_replace(0, 0, 255))
        self._slider_g.set_gradient(stops_replace(1, 0, 255))
        self._slider_b.set_gradient(stops_replace(2, 0, 255))

        h, s, v, _ = self._color.getHsvF()
        if h < 0:
            h = 0.0
        hue_stops = []
        for i in range(7):
            pos = i / 6.0
            hue_stops.append((pos, QtGui.QColor.fromHsvF(pos, 1.0, 1.0)))
        self._slider_h.set_gradient(hue_stops)
        self._slider_s.set_gradient([(0.0, QtGui.QColor.fromHsvF(h, 0.0, v)), (1.0, QtGui.QColor.fromHsvF(h, 1.0, v))])
        self._slider_v.set_gradient([(0.0, QtGui.QColor.fromHsvF(h, s, 0.0)), (1.0, QtGui.QColor.fromHsvF(h, s, 1.0))])
        if self._slider_a is not None:
            opaque = QtGui.QColor(self._color)
            opaque.setAlpha(255)
            transparent = QtGui.QColor(opaque)
            transparent.setAlpha(0)
            self._slider_a.set_gradient([(0.0, transparent), (1.0, opaque)])

    def _on_wheel_changed(self, h, s, v):
        if self._updating:
            return
        a = self._color.alpha()
        c = QtGui.QColor.fromHsvF(h, s, v)
        c.setAlpha(a)
        self._set_internal(c)

    def _on_hsv_changed(self, _):
        if self._updating:
            return
        h = self._slider_h.value() / 359.0
        s = self._slider_s.value() / 255.0
        v = self._slider_v.value() / 255.0
        c = QtGui.QColor.fromHsvF(max(0.0, min(1.0, h)), max(0.0, min(1.0, s)), max(0.0, min(1.0, v)))
        c.setAlpha(self._color.alpha())
        self._set_internal(c)

    def _on_rgb_changed(self, _):
        if self._updating:
            return
        c = QtGui.QColor(self._slider_r.value(), self._slider_g.value(), self._slider_b.value())
        c.setAlpha(self._slider_a.value() if self._slider_a is not None else self._color.alpha())
        self._set_internal(c)

    def _on_hex_changed(self):
        if self._updating:
            return
        text = self._hex_edit.text().strip()
        if not text:
            return
        if not text.startswith("#"):
            text = "#" + text
        c = QtGui.QColor(text)
        if not c.isValid():
            AppLogger.warning(f"Invalid hex color: {text}")
            self._sync_all_from_color()
            return
        if not self._with_alpha:
            c.setAlpha(255)
        self._set_internal(c)

    def _set_internal(self, c: QtGui.QColor):
        self._color = c
        self._sync_all_from_color()
        self.colorChanged.emit(self.color())


class ColorPickerDialog(QtWidgets.QDialog):
    def __init__(self, initial: str | QtGui.QColor = "#888888", parent=None, title: str = "", with_alpha: bool = False, scope: str = "general"):
        super().__init__(parent)
        self.setWindowTitle(title or t("Color picker"))
        self.setModal(True)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, dpix(8))
        layout.setSpacing(dpix(6))
        self._picker = ColorPickerWidget(initial=initial, with_alpha=with_alpha, scope=scope)
        layout.addWidget(self._picker, 1)

        btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.setContentsMargins(dpix(8), 0, dpix(8), 0)
        btn_row.addWidget(btns)
        layout.addLayout(btn_row)

    def color(self) -> QtGui.QColor:
        return self._picker.color()

    def accept(self):
        self._picker.commit_to_recent()
        super().accept()

    @classmethod
    def get_color(
        cls,
        initial: str | QtGui.QColor = "#888888",
        parent=None,
        title: str = "",
        with_alpha: bool = False,
        scope: str = "general",
    ) -> QtGui.QColor | None:
        dlg = cls(initial=initial, parent=parent, title=title, with_alpha=with_alpha, scope=scope)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return None
        return dlg.color()
