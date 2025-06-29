from PySide6 import QtCore, QtGui
from ...profiling import init_env

logger, profiler = init_env()

class CalculatorSignals(QtCore.QObject):
    layout_ready = QtCore.Signal(list)

class JustifiedLayoutCalculator(QtCore.QRunnable):
    def __init__(self, aspect_ratios, base_height, spacing, container_width):
        super().__init__()
        self.signals = CalculatorSignals()
        self.aspect_ratios = aspect_ratios
        self.base_height = base_height
        self.spacing = spacing
        self.container_width = container_width
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    @profiler.profile
    def run(self):
        rects = []
        x, y = 0, 0
        line = []
        line_width = 0
        spacing = self.spacing
        base_height = self.base_height
        container_width = self.container_width
        append_rects = rects.append
        aspect_ratios = self.aspect_ratios
        i = 0
        while i < len(aspect_ratios):
            if self._cancelled:
                return
            aspect = aspect_ratios[i]
            w = aspect * base_height
            if line and (line_width + w + spacing * len(line)) > container_width:
                total_spacing = spacing * (len(line) - 1)
                scale = (container_width - total_spacing) / line_width
                cur_x = 0
                for a in line:
                    if self._cancelled:
                        return
                    iw = int(a * base_height * scale)
                    ih = int(base_height * scale)
                    append_rects(QtCore.QRect(cur_x, y, iw, ih))
                    cur_x += iw + spacing
                y += ih + spacing
                line.clear()
                line_width = 0
            else:
                line.append(aspect)
                line_width += w
                i += 1
        if line and not self._cancelled:
            total_spacing = spacing * (len(line) - 1)
            scale = (container_width - total_spacing) / line_width
            cur_x = 0
            for a in line:
                iw = int(a * base_height * scale)
                ih = int(base_height * scale)
                append_rects(QtCore.QRect(cur_x, y, iw, ih))
                cur_x += iw + spacing
        if not self._cancelled:
            self.signals.layout_ready.emit(rects)

