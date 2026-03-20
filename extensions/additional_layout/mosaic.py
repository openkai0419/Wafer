from PySide6 import QtCore
from wafer.plugin.layout import BaseLayoutPlugin, BaseLayoutCalculator, SCROLLBAR_INT_MAX
from wafer.utils.profiling import profiler
from wafer.utils.logs import AppLogger

_FEATURE_INTERVAL = 7
_WIDE_THRESHOLD = 1.5
_TALL_THRESHOLD = 1.0 / _WIDE_THRESHOLD


def _best_adjacent_pair(lane_offsets, num_lanes):
    best = 0
    best_val = max(lane_offsets[0], lane_offsets[1])
    for l in range(1, num_lanes - 1):
        val = max(lane_offsets[l], lane_offsets[l + 1])
        if val < best_val:
            best = l
            best_val = val
    return best


class MosaicLayoutCalculator(BaseLayoutCalculator):

    @profiler.profile
    def _calculate(self):
        hz = self.orientation < 2
        reverse = self.orientation % 2 == 1
        spacing = self.spacing
        base = self.base_size
        aspects = self.aspect_ratios
        n = len(aspects)
        if n == 0:
            self._emit([], 0, hz)
            return

        container = self.container_width if hz else self.container_height
        if container is None:
            raise ValueError('Mosaic layout requires container dimension')

        num_lanes = max(1, round((container + spacing) / (base + spacing)))
        lane_size = (container - spacing * (num_lanes - 1)) / num_lanes
        lane_int = max(1, int(lane_size))
        double_int = lane_int * 2 + spacing
        multi_lane_ok = num_lanes >= 2

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

            multi_lane = False
            multi_primary = False

            if i % _FEATURE_INTERVAL == 0:
                if multi_lane_ok:
                    multi_lane = True
                multi_primary = True
            elif a >= _WIDE_THRESHOLD and multi_lane_ok:
                multi_lane = True
            elif a <= _TALL_THRESHOLD:
                multi_primary = True

            pri_size = double_int if multi_primary else lane_int

            if multi_lane:
                pair = _best_adjacent_pair(lane_offsets, num_lanes)
                offset = max(lane_offsets[pair], lane_offsets[pair + 1])
                sec_pos = min(lane_positions[pair], lane_positions[pair + 1])
                sec_size = double_int
                if hz:
                    rects[i] = QtCore.QRect(sec_pos, offset, sec_size, pri_size)
                else:
                    rects[i] = QtCore.QRect(offset, sec_pos, pri_size, sec_size)
                lane_offsets[pair] = offset + pri_size + spacing
                lane_offsets[pair + 1] = offset + pri_size + spacing
            else:
                lane = min(range(num_lanes), key=lambda c: lane_offsets[c])
                offset = lane_offsets[lane]
                sec_pos = lane_positions[lane]
                if hz:
                    rects[i] = QtCore.QRect(sec_pos, offset, lane_int, pri_size)
                else:
                    rects[i] = QtCore.QRect(offset, sec_pos, pri_size, lane_int)
                lane_offsets[lane] = offset + pri_size + spacing

            if max(lane_offsets) > SCROLLBAR_INT_MAX:
                final_count = i + 1
                AppLogger.debug(f"[MosaicLayout] truncated at item {i}")
                break

        total_extent = max(lane_offsets) if lane_offsets else 0
        if not hz and reverse and total_extent > 0:
            flip = total_extent - spacing
            for i in range(final_count):
                r = rects[i]
                rects[i] = QtCore.QRect(
                    flip - r.x() - r.width(), r.y(), r.width(), r.height(),
                )

        self._emit(rects[:final_count], total_extent, hz)

    @profiler.profile
    def run(self):
        self._calculate()


class MosaicLayout(BaseLayoutPlugin):
    NAME = 'mosaic'
    DISPLAY_NAME = 'Mosaic'
    PRIORITY = 85


    @classmethod
    def create_calculator(cls, aspect_ratios, base_size, spacing,
                          container_width, container_height, orientation):
        return MosaicLayoutCalculator(
            aspect_ratios, base_size, spacing,
            container_width, container_height, orientation,
        )
