from PySide6 import QtCore
from wafer.plugin.layout import BaseLayoutPlugin, BaseLayoutCalculator, SCROLLBAR_INT_MAX
from wafer.utils.profiling import profiler
from wafer.utils.logs import AppLogger

MAX_SPAN_C = 3
MAX_SPAN_R = 3
GAP_MAX_SPAN = 2
AREA_WEIGHT = 0.08
POSITION_WEIGHT = 0.2


def _build_span_table(num_cols, cell_w, cell_h, spacing, hz):
    spans = []
    max_c = min(MAX_SPAN_C, num_cols)
    for sc in range(1, max_c + 1):
        for sr in range(1, MAX_SPAN_R + 1):
            if hz:
                w = sc * cell_w + (sc - 1) * spacing
                h = sr * cell_h + (sr - 1) * spacing
            else:
                w = sr * cell_h + (sr - 1) * spacing
                h = sc * cell_w + (sc - 1) * spacing
            spans.append((sc, sr, w / h if h > 0 else 1.0, sc * sr))
    return spans


def _make_rect(c, r, sc, sr, cell_w, cell_h, spacing, hz):
    if hz:
        return QtCore.QRect(
            int(c * (cell_w + spacing)),
            int(r * (cell_h + spacing)),
            int(sc * cell_w + (sc - 1) * spacing),
            int(sr * cell_h + (sr - 1) * spacing))
    return QtCore.QRect(
        int(r * (cell_h + spacing)),
        int(c * (cell_w + spacing)),
        int(sr * cell_h + (sr - 1) * spacing),
        int(sc * cell_w + (sc - 1) * spacing))


class MultiSpanCalculator(BaseLayoutCalculator):

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
            raise ValueError('MultiSpan layout requires container dimension')

        ar = [a if a and a > 0 else 1.0 for a in aspects]
        num_cols = max(1, round((container + spacing) / (base + spacing)))
        cell_w = (container - spacing * (num_cols - 1)) / num_cols
        cell_h = cell_w
        span_table = _build_span_table(num_cols, cell_w, cell_h, spacing, hz)
        area_norm = max(1, MAX_SPAN_C * MAX_SPAN_R - 1)
        gap_spans_multi = [(sc, sr, sa, area) for sc, sr, sa, area in span_table
                          if sc <= GAP_MAX_SPAN and sr <= GAP_MAX_SPAN and area > 1]
        gap_span_1x1_ar = next(sa for sc, sr, sa, area in span_table if area == 1)
        gap_threshold = num_cols

        heights = [0] * num_cols
        h_min = 0
        h_max = 0
        occupied = set()
        rects = [None] * n
        item_idx = 0
        base_row = 0

        while item_idx < n:
            if self._cancelled:
                return

            frontier = h_min
            ceiling = h_max

            if ceiling - frontier >= gap_threshold:
                filled_any = False
                for r in range(base_row, ceiling):
                    if item_idx >= n or self._cancelled:
                        break
                    for c in range(num_cols):
                        if item_idx >= n:
                            break
                        if (r, c) in occupied:
                            continue

                        img_ar = ar[item_idx]
                        best_sc, best_sr = 1, 1
                        multi_score = -1.0
                        for sc, sr, span_ar, area in gap_spans_multi:
                            if c + sc > num_cols:
                                continue
                            ok = True
                            for dr in range(sr):
                                for dc in range(sc):
                                    if (r + dr, c + dc) in occupied:
                                        ok = False
                                        break
                                if not ok:
                                    break
                            if not ok:
                                continue
                            ar_match = min(img_ar, span_ar) / max(img_ar, span_ar)
                            if ar_match > multi_score:
                                multi_score = ar_match
                                best_sc, best_sr = sc, sr

                        sc, sr = best_sc, best_sr
                        for dr in range(sr):
                            for dc in range(sc):
                                occupied.add((r + dr, c + dc))
                        for dc in range(sc):
                            top = r + sr
                            if heights[c + dc] < top:
                                heights[c + dc] = top
                                if top > h_max:
                                    h_max = top

                        rects[item_idx] = _make_rect(c, r, sc, sr,
                                                     cell_w, cell_h, spacing, hz)
                        item_idx += 1
                        filled_any = True

                h_min = min(heights)
                if h_min > base_row:
                    occupied = {(gr, gc) for gr, gc in occupied if gr >= h_min}
                    base_row = h_min
                if filled_any:
                    continue

            img_ar = ar[item_idx]
            best_score = -1e9
            best_slot = None

            for sc, sr, span_ar, area in span_table:
                ar_match = min(img_ar, span_ar) / max(img_ar, span_ar)
                base_score = ar_match + AREA_WEIGHT * (area - 1) / area_norm
                for c in range(num_cols - sc + 1):
                    row = max(heights[c:c + sc])
                    gap = row - frontier
                    score = base_score - POSITION_WEIGHT * gap / (gap + num_cols)
                    if score > best_score:
                        best_score = score
                        best_slot = (row, c, sc, sr)

            r, c, sc, sr = best_slot
            for dr in range(sr):
                for dc in range(sc):
                    occupied.add((r + dr, c + dc))
            top = r + sr
            for dc in range(sc):
                heights[c + dc] = top
            if top > h_max:
                h_max = top
            h_min = min(heights)

            rects[item_idx] = _make_rect(c, r, sc, sr,
                                         cell_w, cell_h, spacing, hz)
            item_idx += 1

        total_primary = int(h_max * (cell_h + spacing) - spacing) if n > 0 else 0
        if total_primary > SCROLLBAR_INT_MAX:
            total_primary = SCROLLBAR_INT_MAX
            AppLogger.debug(f"[MultiSpanLayout] clamped total_primary to {SCROLLBAR_INT_MAX}")

        if reverse:
            for i in range(n):
                r = rects[i]
                if r is None:
                    continue
                if hz:
                    rects[i] = QtCore.QRect(
                        container - r.x() - r.width(), r.y(), r.width(), r.height())
                else:
                    rects[i] = QtCore.QRect(
                        total_primary - r.x() - r.width(), r.y(), r.width(), r.height())

        self._emit(rects, total_primary, hz)

    @profiler.profile
    def run(self):
        self._calculate()


class MultiSpanLayout(BaseLayoutPlugin):
    NAME = 'multiSpan'
    DISPLAY_NAME = 'MultiSpan Grid'
    PRIORITY = 83

    @classmethod
    def create_calculator(cls, aspect_ratios, base_size, spacing,
                          container_width, container_height, orientation):
        return MultiSpanCalculator(
            aspect_ratios, base_size, spacing,
            container_width, container_height, orientation,
        )
