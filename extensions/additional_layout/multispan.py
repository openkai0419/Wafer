from PySide6 import QtCore
from wafer.plugin.layout import BaseLayoutPlugin, BaseLayoutCalculator, SCROLLBAR_INT_MAX
from wafer.utils.profiling import profiler
from wafer.utils.logs import AppLogger

MAX_SPAN_C = 3
MAX_SPAN_R = 3
GAP_MAX_SPAN = 2
AREA_WEIGHT = 0.35
AREA_WEIGHT_GAP = 0.4
POSITION_WEIGHT = 0.2


def _build_span_table(num_cols, cell_w, cell_h, spacing, hz, max_span_c, max_span_r):
    spans = []
    max_c = min(max_span_c, num_cols)
    for sc in range(1, max_c + 1):
        for sr in range(1, max_span_r + 1):
            if hz:
                w = sc * cell_w + (sc - 1) * spacing
                h = sr * cell_h + (sr - 1) * spacing
            else:
                w = sr * cell_h + (sr - 1) * spacing
                h = sc * cell_w + (sc - 1) * spacing
            spans.append((sc, sr, w / h if h > 0 else 1.0, sc * sr))
    return spans


class MultiSpanCalculator(BaseLayoutCalculator):
    def __init__(self, aspect_ratios, base_size, spacing, container_width, container_height, orientation, max_span_c=MAX_SPAN_C, max_span_r=MAX_SPAN_R, max_area=None):
        super().__init__(aspect_ratios, base_size, spacing, container_width, container_height, orientation)
        self._max_span_c = max_span_c
        self._max_span_r = max_span_r
        self._max_area = max_area or max_span_c * max_span_r

    @profiler.profile
    def _calculate(self):
        hz = self.orientation < 2
        reverse = self.orientation % 2 == 1
        spacing = self.spacing
        base = self.base_size / 2
        aspects = self.aspect_ratios
        n = len(aspects)
        if n == 0:
            self._emit([], 0, hz)
            return

        container = self.container_width if hz else self.container_height
        if container is None:
            raise ValueError("MultiSpan layout requires container dimension")

        ar = [a if a and a > 0 else 1.0 for a in aspects]
        num_cols = max(1, round((container + spacing) / (base + spacing)))
        cell_w = (container - spacing * (num_cols - 1)) / num_cols
        cell_h = cell_w
        max_sc = self._max_span_c
        max_sr = self._max_span_r
        max_area = self._max_area
        gap_max = min(GAP_MAX_SPAN, max_sc, max_sr)
        span_table = _build_span_table(num_cols, cell_w, cell_h, spacing, hz, max_sc, max_sr)
        if max_area < max_sc * max_sr:
            span_table = [(sc, sr, sa, a) for sc, sr, sa, a in span_table if a <= max_area]
        area_norm = max(1, max_area - 1)
        gap_spans_multi = [(sc, sr, sa, area) for sc, sr, sa, area in span_table if sc <= gap_max and sr <= gap_max and area > 1]
        gap_threshold = max(max_sc, max_sr) * 2 - 1

        spans_by_sc: dict[int, list[tuple]] = {}
        for sc, sr, span_ar, area in span_table:
            if sc not in spans_by_sc:
                spans_by_sc[sc] = []
            spans_by_sc[sc].append((sr, span_ar, area))

        _QRect = QtCore.QRect
        step = cell_w + spacing
        col_pos = [int(c * step) for c in range(num_cols)]
        span_dims: dict[tuple[int, int], tuple[int, int]] = {}
        for sc, sr, _, _ in span_table:
            if (sc, sr) not in span_dims:
                if hz:
                    span_dims[(sc, sr)] = (int(sc * cell_w + (sc - 1) * spacing), int(sr * cell_h + (sr - 1) * spacing))
                else:
                    span_dims[(sc, sr)] = (int(sr * cell_h + (sr - 1) * spacing), int(sc * cell_w + (sc - 1) * spacing))

        heights = [0] * num_cols
        h_min = 0
        h_max = 0
        occ_rows: dict[int, bytearray] = {}
        rects = [None] * n
        item_idx = 0
        base_row = 0

        _pw = POSITION_WEIGHT
        _aw = AREA_WEIGHT
        _awg = AREA_WEIGHT_GAP
        _sc_keys = sorted(spans_by_sc.keys())

        while item_idx < n:
            if self._cancelled:
                return

            frontier = h_min
            ceiling = h_max

            if ceiling - frontier >= gap_threshold:
                filled_any = False
                for row in range(base_row, ceiling):
                    if item_idx >= n or self._cancelled:
                        break
                    row_data = occ_rows.get(row)
                    if row_data is None:
                        row_data = bytearray(num_cols)
                        occ_rows[row] = row_data
                    for c in range(num_cols):
                        if item_idx >= n:
                            break
                        if row_data[c]:
                            continue

                        img_ar = ar[item_idx]
                        best_sc, best_sr = 1, 1
                        multi_score = -1.0
                        for sc, sr, span_ar, area in gap_spans_multi:
                            if c + sc > num_cols:
                                continue
                            ok = True
                            for dr in range(sr):
                                rd = occ_rows.get(row + dr)
                                if rd is None:
                                    continue
                                for dc in range(sc):
                                    if rd[c + dc]:
                                        ok = False
                                        break
                                if not ok:
                                    break
                            if not ok:
                                continue
                            ar_match = img_ar / span_ar if img_ar <= span_ar else span_ar / img_ar
                            gap_score = ar_match + _awg * (area - 1) / area_norm
                            if gap_score > multi_score:
                                multi_score = gap_score
                                best_sc, best_sr = sc, sr

                        sc, sr = best_sc, best_sr
                        for dr in range(sr):
                            rd = occ_rows.get(row + dr)
                            if rd is None:
                                rd = bytearray(num_cols)
                                occ_rows[row + dr] = rd
                            for dc in range(sc):
                                rd[c + dc] = 1
                        for dc in range(sc):
                            top = row + sr
                            if heights[c + dc] < top:
                                heights[c + dc] = top
                                if top > h_max:
                                    h_max = top

                        sw, sh = span_dims[(sc, sr)]
                        if hz:
                            rects[item_idx] = _QRect(col_pos[c], int(row * step), sw, sh)
                        else:
                            rects[item_idx] = _QRect(int(row * step), col_pos[c], sw, sh)
                        item_idx += 1
                        filled_any = True

                h_min = min(heights)
                if h_min > base_row:
                    for r_del in range(base_row, h_min):
                        occ_rows.pop(r_del, None)
                    base_row = h_min
                if filled_any:
                    continue

            img_ar = ar[item_idx]
            best_score = -1e9
            best_slot_r = 0
            best_slot_c = 0
            best_slot_sc = 1
            best_slot_sr = 1

            for sc in _sc_keys:
                c_end = num_cols - sc + 1
                best_c = 0
                best_row = heights[0]
                for dc in range(1, sc):
                    if heights[dc] > best_row:
                        best_row = heights[dc]
                for c in range(1, c_end):
                    row = heights[c]
                    for dc in range(1, sc):
                        h = heights[c + dc]
                        if h > row:
                            row = h
                    if row < best_row:
                        best_row = row
                        best_c = c

                gap = best_row - frontier
                penalty = _pw * gap / (gap + num_cols)
                for sr, span_ar, area in spans_by_sc[sc]:
                    ar_match = img_ar / span_ar if img_ar <= span_ar else span_ar / img_ar
                    score = ar_match + _aw * (area - 1) / area_norm - penalty
                    if score > best_score:
                        best_score = score
                        best_slot_r = best_row
                        best_slot_c = best_c
                        best_slot_sc = sc
                        best_slot_sr = sr

            r, c, sc, sr = best_slot_r, best_slot_c, best_slot_sc, best_slot_sr
            for dr in range(sr):
                rd = occ_rows.get(r + dr)
                if rd is None:
                    rd = bytearray(num_cols)
                    occ_rows[r + dr] = rd
                for dc in range(sc):
                    rd[c + dc] = 1
            top = r + sr
            for dc in range(sc):
                heights[c + dc] = top
            if top > h_max:
                h_max = top
            h_min = min(heights)

            sw, sh = span_dims[(sc, sr)]
            if hz:
                rects[item_idx] = _QRect(col_pos[c], int(r * step), sw, sh)
            else:
                rects[item_idx] = _QRect(int(r * step), col_pos[c], sw, sh)
            item_idx += 1

        total_primary = int(h_max * step - spacing) if n > 0 else 0
        if total_primary > SCROLLBAR_INT_MAX:
            total_primary = SCROLLBAR_INT_MAX
            AppLogger.debug(f"[MultiSpanLayout] clamped total_primary to {SCROLLBAR_INT_MAX}")

        if reverse:
            for i in range(n):
                r = rects[i]
                if r is None:
                    continue
                if hz:
                    rects[i] = _QRect(container - r.x() - r.width(), r.y(), r.width(), r.height())
                else:
                    rects[i] = _QRect(total_primary - r.x() - r.width(), r.y(), r.width(), r.height())

        self._emit(rects, total_primary, hz)

    @profiler.profile
    def run(self):
        self._calculate()


class MultiSpanLayout(BaseLayoutPlugin):
    NAME = "multiSpan"
    DISPLAY_NAME = "MultiSpan Grid"
    PRIORITY = 86
    DEFAULT_ENABLED = True

    @classmethod
    def create_calculator(cls, aspect_ratios, base_size, spacing, container_width, container_height, orientation):
        return MultiSpanCalculator(
            aspect_ratios,
            base_size,
            spacing,
            container_width,
            container_height,
            orientation,
        )


class MultiSpanTilingLayout(BaseLayoutPlugin):
    NAME = "multiSpanTiling"
    DISPLAY_NAME = "MultiSpan Tiling"
    PRIORITY = 84
    DEFAULT_ENABLED = True

    @classmethod
    def create_calculator(cls, aspect_ratios, base_size, spacing, container_width, container_height, orientation):
        return MultiSpanCalculator(
            aspect_ratios,
            base_size,
            spacing,
            container_width,
            container_height,
            orientation,
            max_span_c=2,
            max_span_r=2,
            max_area=2,
        )
