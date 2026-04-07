from PySide6 import QtCore
from ..plugin.layout import BaseLayoutPlugin, BaseLayoutCalculator, SCROLLBAR_INT_MAX
from ..utils.profiling import profiler
from ..utils.logs import AppLogger


class JustifiedLayoutCalculator(BaseLayoutCalculator):
    def __init__(self, aspect_ratios, base_height, spacing, container_width, container_height, orientation=0):
        super().__init__(aspect_ratios, base_height, spacing, container_width, container_height, orientation)

    @property
    def base_height(self):
        return self.base_size

    @profiler.profile
    def _calculate(self, hz, reverse):
        if not hz and self.container_height is None:
            raise ValueError("Vertical layout requires container_height")
        spacing = self.spacing
        base = self.base_size
        aspects = self.aspect_ratios
        container = self.container_width if hz else self.container_height

        groups = []
        offset = 0
        start_idx = 0
        line_count = 0
        line_extent = 0.0
        i = 0
        while i < len(aspects):
            if self._cancelled:
                return
            a = aspects[i] or 1.0
            ext = a * base if hz else base / a
            if line_count > 0 and line_extent + ext + spacing * line_count > container:
                total_sp = spacing * (line_count - 1)
                scale = max((container - total_sp) / line_extent, 0.1)
                groups.append((start_idx, line_count, offset, scale))
                offset += int(base * scale) + spacing
                start_idx = i
                line_count = 0
                line_extent = 0.0
                if offset > SCROLLBAR_INT_MAX:
                    AppLogger.debug(f"[JustifiedLayout] truncated offset={offset} max={SCROLLBAR_INT_MAX} items={len(aspects)} processed={i}")
                    break
            else:
                line_count += 1
                line_extent += ext
                i += 1
        if line_count > 0 and not self._cancelled:
            total_sp = spacing * (line_count - 1)
            scale = max((container - total_sp) / line_extent, 0.1)
            groups.append((start_idx, line_count, offset, scale))
        if self._cancelled or not groups:
            return

        self._build_justified_rects(groups, hz, reverse)

    @profiler.profile
    def run(self):
        self._calculate(hz=self.orientation < 2, reverse=self.orientation % 2 == 1)


class MasonryLayoutCalculator(BaseLayoutCalculator):
    @profiler.profile
    def _calculate(self):
        hz = self.orientation < 2
        reverse = self.orientation % 2 == 1
        spacing = self.spacing
        aspects = self.aspect_ratios
        base = self.base_size
        n = len(aspects)

        container = self.container_width if hz else self.container_height
        if container is None:
            raise ValueError("Vertical masonry requires container_height")
        num_lanes = max(1, round((container + spacing) / (base + spacing)))
        lane_size = (container - spacing * (num_lanes - 1)) / num_lanes
        lane_int = max(1, int(lane_size))
        lane_offsets = [0] * num_lanes
        lane_positions = [l * (lane_int + spacing) for l in range(num_lanes)]
        if hz and reverse:
            lane_positions = [container - lp - lane_int for lp in lane_positions]

        rects = [None] * n
        final_count = n
        for i in range(n):
            if self._cancelled:
                return
            a = aspects[i] or 1.0
            lane = min(range(num_lanes), key=lambda c: lane_offsets[c])
            primary_offset = lane_offsets[lane]
            if hz:
                item_var = max(1, int(lane_int / a))
                rects[i] = QtCore.QRect(lane_positions[lane], primary_offset, lane_int, item_var)
            else:
                item_var = max(1, int(lane_int * a))
                rects[i] = QtCore.QRect(primary_offset, lane_positions[lane], item_var, lane_int)
            lane_offsets[lane] = primary_offset + item_var + spacing
            if lane_offsets[lane] > SCROLLBAR_INT_MAX:
                final_count = i + 1
                AppLogger.debug(f"[MasonryLayout] truncated at item {i}")
                break

        total_extent = max(lane_offsets) if lane_offsets else 0
        if not hz and reverse and total_extent > 0:
            flip = total_extent - spacing
            for i in range(final_count):
                r = rects[i]
                rects[i] = QtCore.QRect(flip - r.x() - r.width(), r.y(), r.width(), r.height())

        self._emit(rects[:final_count], total_extent, hz)

    @profiler.profile
    def run(self):
        self._calculate()


class JustifiedLayout(BaseLayoutPlugin):
    NAME = "justified"
    DISPLAY_NAME = "Justified"
    PRIORITY = 100

    @classmethod
    def create_calculator(cls, aspect_ratios, base_size, spacing, container_width, container_height, orientation):
        return JustifiedLayoutCalculator(
            aspect_ratios,
            base_size,
            spacing,
            container_width,
            container_height,
            orientation,
        )


class MasonryLayout(BaseLayoutPlugin):
    NAME = "masonry"
    DISPLAY_NAME = "Masonry"
    PRIORITY = 90

    @classmethod
    def create_calculator(cls, aspect_ratios, base_size, spacing, container_width, container_height, orientation):
        return MasonryLayoutCalculator(
            aspect_ratios,
            base_size,
            spacing,
            container_width,
            container_height,
            orientation,
        )
