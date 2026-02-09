from PySide6 import QtCore
from ...common.profiling import profiler, logger
QWIDGETSIZE_MAX = 16777215

class CalculatorSignals(QtCore.QObject):
    layout_ready = QtCore.Signal(list)

class JustifiedLayoutCalculator(QtCore.QRunnable):

    def __init__(self, aspect_ratios, base_height, spacing, container_width, container_height, orientation=0):
        super().__init__()
        self.signals = CalculatorSignals()
        self.aspect_ratios = aspect_ratios
        self.spacing = spacing
        self.base_height = base_height
        self.container_width = container_width
        self.container_height = container_height
        self._cancelled = False
        self.orientation = orientation

    def cancel(self):
        self._cancelled = True

    @profiler.profile
    def _calculate_horizontal(self, reverse):
        rects = []
        y = 0
        line = []
        line_width = 0
        spacing = self.spacing
        base_height = self.base_height
        container_width = self.container_width
        aspect_ratios = self.aspect_ratios
        append_rects = rects.append
        i = 0
        while i < len(aspect_ratios):
            if self._cancelled:
                return
            aspect = aspect_ratios[i]
            w = aspect * base_height
            if line and line_width + w + spacing * len(line) > container_width:
                self._emit_horizontal_line(rects, line, line_width, y, reverse)
                y += self._line_height(line, line_width) + spacing
                line.clear()
                line_width = 0
                if y > QWIDGETSIZE_MAX:
                    logger.debug(f"[JustifiedLayout] truncated y={y} max={QWIDGETSIZE_MAX} items={len(aspect_ratios)} processed={i} rects={len(rects)}")
                    break
            else:
                line.append(aspect)
                line_width += w
                i += 1
        if line and (not self._cancelled):
            self._emit_horizontal_line(rects, line, line_width, y, reverse)
        if not self._cancelled:
            self.signals.layout_ready.emit(rects)

    @profiler.profile
    def _emit_horizontal_line(self, rects, line, line_width, y, reverse):
        spacing = self.spacing
        base_height = self.base_height
        container_width = self.container_width
        total_spacing = spacing * (len(line) - 1)
        scale = max((container_width - total_spacing) / line_width, 0.1)
        ih = int(base_height * scale)
        if reverse:
            cur_x = container_width
            for a in line:
                if self._cancelled:
                    return
                iw = int(a * base_height * scale)
                cur_x -= iw
                rects.append(QtCore.QRect(cur_x, y, iw, ih))
                cur_x -= spacing
        else:
            cur_x = 0
            for a in line:
                if self._cancelled:
                    return
                iw = int(a * base_height * scale)
                rects.append(QtCore.QRect(cur_x, y, iw, ih))
                cur_x += iw + spacing

    @profiler.profile
    def _line_height(self, line, line_width):
        total_spacing = self.spacing * (len(line) - 1)
        scale = max((self.container_width - total_spacing) / line_width, 0.1)
        return int(self.base_height * scale)

    @profiler.profile
    def _calculate_vertical(self, reverse):
        if self.container_height is None:
            raise ValueError('Vertical layout requires container_height')
        rects = []
        line = []
        line_height = 0
        spacing = self.spacing
        base_width = self.base_height
        container_height = self.container_height
        container_width = self.container_width
        aspect_ratios = self.aspect_ratios
        append_rects = rects.append
        i = 0
        if reverse:
            cur_x = container_width
        else:
            cur_x = 0
        while i < len(aspect_ratios):
            if self._cancelled:
                return
            aspect = aspect_ratios[i]
            h = base_width / aspect
            if line and line_height + h + spacing * len(line) > container_height:
                cur_x = self._emit_vertical_line(rects, line, line_height, cur_x, reverse)
                line.clear()
                line_height = 0
                if abs(cur_x) > QWIDGETSIZE_MAX:
                    break
            else:
                line.append(aspect)
                line_height += h
                i += 1
        if line and (not self._cancelled):
            self._emit_vertical_line(rects, line, line_height, cur_x, reverse)
        if not self._cancelled:
            self.signals.layout_ready.emit(rects)

    @profiler.profile
    def _emit_vertical_line(self, rects, line, line_height, cur_x, reverse):
        spacing = self.spacing
        base_width = self.base_height
        container_height = self.container_height
        container_width = self.container_width
        total_spacing = spacing * (len(line) - 1)
        scale = max((container_height - total_spacing) / line_height, 0.1)
        iw = int(base_width * scale)
        if reverse:
            cur_x -= iw
        cur_y = 0
        for a in line:
            if self._cancelled:
                return cur_x
            ih = int(base_width / a * scale)
            rects.append(QtCore.QRect(cur_x, cur_y, iw, ih))
            cur_y += ih + spacing
        if reverse:
            cur_x -= spacing
            cur_x = max(cur_x, 0)
        else:
            cur_x += iw + spacing
        return cur_x

    @profiler.profile
    def _line_width(self, line, line_height):
        total_spacing = self.spacing * (len(line) - 1)
        scale = max((self.container_height - total_spacing) / line_height, 0.1)
        return int(self.base_height * scale)

    @profiler.profile
    def run(self):
        if self.orientation == 0:
            self._calculate_horizontal(reverse=False)
        elif self.orientation == 1:
            self._calculate_horizontal(reverse=True)
        elif self.orientation == 2:
            self._calculate_vertical(reverse=False)
        elif self.orientation == 3:
            self._calculate_vertical(reverse=True)
