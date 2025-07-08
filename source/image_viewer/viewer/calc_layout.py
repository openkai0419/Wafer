from PySide6 import QtWidgets, QtGui, QtCore
from ...profiling import logger, profiler


class CalculatorSignals(QtCore.QObject):
    layout_ready = QtCore.Signal(list)

class JustifiedLayoutCalculator(QtCore.QRunnable):
    def __init__(self, aspect_ratios, base_height, spacing, container_width, orientation = 1):
        super().__init__()
        self.signals = CalculatorSignals()
        self.aspect_ratios = aspect_ratios
        self.spacing = spacing

        self.base_height = base_height
        self.container_width = container_width

        self.base_width = base_height
        self.container_height = container_width
        self._cancelled = False

        self.orientation = orientation

    def cancel(self):
        self._cancelled = True

    def vertical_L2R(self):
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

    def vertical_R2L(self):
        rects = []
        y = 0
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
                cur_x = container_width
                for a in line:
                    if self._cancelled:
                        return
                    iw = int(a * base_height * scale)
                    ih = int(base_height * scale)
                    cur_x -= iw  # move left
                    append_rects(QtCore.QRect(cur_x, y, iw, ih))
                    cur_x -= spacing  # space to the left
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
            cur_x = container_width
            for a in line:
                iw = int(a * base_height * scale)
                ih = int(base_height * scale)
                cur_x -= iw
                append_rects(QtCore.QRect(cur_x, y, iw, ih))
                cur_x -= spacing

        if not self._cancelled:
            self.signals.layout_ready.emit(rects)

    def horizontal_L2R(self):
        rects = []
        x = 0
        column = []
        column_height = 0
        spacing = self.spacing
        base_width = self.base_width
        container_height = self.container_height

        append_rects = rects.append
        aspect_ratios = self.aspect_ratios

        i = 0
        while i < len(aspect_ratios):
            if self._cancelled:
                return
            aspect = aspect_ratios[i]
            h = base_width / aspect  # 幅基準なので高さを求める

            if column and (column_height + h + spacing * len(column)) > container_height:
                # この列を配置する
                total_spacing = spacing * (len(column) - 1)
                scale = (container_height - total_spacing) / column_height
                cur_y = 0
                for a in column:
                    if self._cancelled:
                        return
                    ih = int((base_width / a) * scale)
                    iw = int(base_width * scale)
                    append_rects(QtCore.QRect(x, cur_y, iw, ih))
                    cur_y += ih + spacing
                x += iw + spacing
                column.clear()
                column_height = 0
            else:
                column.append(aspect)
                column_height += h
                i += 1

        if column and not self._cancelled:
            # 最後の列を配置
            total_spacing = spacing * (len(column) - 1)
            scale = 1
            cur_y = 0
            for a in column:
                ih = int((base_width / a) * scale)
                iw = int(base_width * scale)
                append_rects(QtCore.QRect(x, cur_y, iw, ih))
                cur_y += ih + spacing

        if not self._cancelled:
            self.signals.layout_ready.emit(rects)

    def horizontal_R2L(self):
        rects = []
        x = self.container_width  # ← 右端から始める
        column = []
        column_height = 0
        spacing = self.spacing
        base_width = self.base_width
        container_height = self.container_height

        append_rects = rects.append
        aspect_ratios = self.aspect_ratios

        i = 0
        while i < len(aspect_ratios):
            if self._cancelled:
                return
            aspect = aspect_ratios[i]
            h = base_width / aspect  # 幅基準なので高さを求める

            if column and (column_height + h + spacing * len(column)) > container_height:
                # この列を配置する
                total_spacing = spacing * (len(column) - 1)
                scale = (container_height - total_spacing) / column_height
                cur_y = 0
                cur_x = x - base_width * scale  # 列の左端
                for a in column:
                    if self._cancelled:
                        return
                    ih = int((base_width / a) * scale)
                    iw = int(base_width * scale)
                    append_rects(QtCore.QRect(int(cur_x), int(cur_y), iw, ih))
                    cur_y += ih + spacing
                x -= (iw + spacing)  # ← 左に進む
                column.clear()
                column_height = 0
            else:
                column.append(aspect)
                column_height += h
                i += 1

        if column and not self._cancelled:
            # 最後の列を配置
            total_spacing = spacing * (len(column) - 1)
            scale = (container_height - total_spacing) / column_height
            cur_y = 0
            cur_x = x - base_width * scale
            for a in column:
                ih = int((base_width / a) * scale)
                iw = int(base_width * scale)
                append_rects(QtCore.QRect(int(cur_x), int(cur_y), iw, ih))
                cur_y += ih + spacing

        if not self._cancelled:
            self.signals.layout_ready.emit(rects)

    @profiler.profile
    def run(self):
        if self.orientation == 0:
            self.vertical_L2R()
        elif self.orientation == 1:
            self.vertical_R2L()
        elif self.orientation == 2:
            self.horizontal_L2R()
        else:
            self.horizontal_R2L()
        