import bisect
from PySide6 import QtCore
from ....utils.profiling import profiler
from ....utils.logs import AppLogger
SCROLLBAR_INT_MAX = 2147483647


class LayoutData:
    __slots__ = (
        '_rects', '_count', '_total_extent', '_is_horizontal',
        '_sorted_indices', '_sorted_primary_starts', '_max_primary_size',
    )

    def __init__(self, rects, total_extent, is_horizontal):
        self._rects = rects
        self._count = len(rects)
        self._total_extent = total_extent
        self._is_horizontal = is_horizontal
        if rects:
            if is_horizontal:
                ps = [(r.y(), r.height()) for r in rects]
            else:
                ps = [(r.x(), r.width()) for r in rects]
            order = sorted(range(len(rects)), key=lambda i: ps[i][0])
            self._sorted_indices = order
            self._sorted_primary_starts = [ps[i][0] for i in order]
            self._max_primary_size = max(s for _, s in ps)
        else:
            self._sorted_indices = []
            self._sorted_primary_starts = []
            self._max_primary_size = 0

    @staticmethod
    def empty():
        d = LayoutData.__new__(LayoutData)
        d._rects = []
        d._count = 0
        d._total_extent = 0
        d._is_horizontal = True
        d._sorted_indices = []
        d._sorted_primary_starts = []
        d._max_primary_size = 0
        return d

    @property
    def total_extent(self):
        return self._total_extent

    def __len__(self):
        return self._count

    def __bool__(self):
        return self._count > 0

    def __getitem__(self, i):
        return self._rects[i]

    @profiler.profile
    def calculate_visible_indices(self, p_start, p_end):
        if not self._count:
            return []
        lo = bisect.bisect_left(self._sorted_primary_starts, p_start - self._max_primary_size)
        hi = bisect.bisect_right(self._sorted_primary_starts, p_end)
        return self._sorted_indices[lo:hi]

    @profiler.profile
    def index_at_point(self, point):
        px, py = point.x(), point.y()
        p = py if self._is_horizontal else px
        lo = bisect.bisect_left(self._sorted_primary_starts, p - self._max_primary_size)
        hi = bisect.bisect_right(self._sorted_primary_starts, p)
        rects = self._rects
        indices = self._sorted_indices
        for si in range(lo, hi):
            i = indices[si]
            if rects[i].contains(point):
                return i
        return None

    @profiler.profile
    def intersecting_indices(self, rect):
        p_start = rect.top() if self._is_horizontal else rect.left()
        p_end = rect.bottom() if self._is_horizontal else rect.right()
        lo = bisect.bisect_left(self._sorted_primary_starts, p_start - self._max_primary_size)
        hi = bisect.bisect_right(self._sorted_primary_starts, p_end)
        rects = self._rects
        indices = self._sorted_indices
        result = []
        for si in range(lo, hi):
            i = indices[si]
            if rects[i].intersects(rect):
                result.append(i)
        return result

    @profiler.profile
    def nearest_in_direction(self, idx, forward):
        if idx is None or idx >= self._count:
            return None
        rect = self._rects[idx]
        hz = self._is_horizontal
        p_edge = (rect.y() + rect.height() if hz else rect.x() + rect.width()) if forward else (rect.y() if hz else rect.x())
        s_hint = rect.center().x() if hz else rect.center().y()
        search = self._max_primary_size
        candidates = self.calculate_visible_indices(
            p_edge if forward else p_edge - search,
            p_edge + search if forward else p_edge,
        )
        best = None
        best_key = None
        for i in candidates:
            if i == idx:
                continue
            r = self._rects[i]
            rp = r.y() if hz else r.x()
            rp_end = rp + (r.height() if hz else r.width())
            if forward and rp < p_edge:
                continue
            if not forward and rp_end > p_edge:
                continue
            rs = r.center().x() if hz else r.center().y()
            key = (rp if forward else -rp_end, abs(rs - s_hint))
            if best_key is None or key < best_key:
                best = i
                best_key = key
        return best


class CalculatorSignals(QtCore.QObject):
    layout_ready = QtCore.Signal(object)


class _BaseLayoutCalculator(QtCore.QRunnable):

    def __init__(self, aspect_ratios, base_size, spacing, container_width, container_height, orientation=0):
        super().__init__()
        self.signals = CalculatorSignals()
        self.aspect_ratios = aspect_ratios
        self.spacing = spacing
        self.base_size = base_size
        self.container_width = container_width
        self.container_height = container_height
        self._cancelled = False
        self.orientation = orientation

    def cancel(self):
        self._cancelled = True

    def _emit(self, rects, total_extent, hz):
        layout = LayoutData(rects, total_extent, hz)
        self.signals.layout_ready.emit(layout)


class JustifiedLayoutCalculator(_BaseLayoutCalculator):

    def __init__(self, aspect_ratios, base_height, spacing, container_width, container_height, orientation=0):
        super().__init__(aspect_ratios, base_height, spacing, container_width, container_height, orientation)

    @property
    def base_height(self):
        return self.base_size

    @profiler.profile
    def _calculate(self, hz, reverse):
        if not hz and self.container_height is None:
            raise ValueError('Vertical layout requires container_height')
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
        if self._cancelled:
            return

        if not hz and reverse and groups:
            last_g = groups[-1]
            total = last_g[2] + int(base * last_g[3])
            groups = [(si, cnt, total - ofs - int(base * sc), sc)
                      for si, cnt, ofs, sc in groups]

        n = groups[-1][0] + groups[-1][1] if groups else 0
        rects = [None] * n
        cw = self.container_width
        for si, cnt, grp_offset, scale in groups:
            bs = base * scale
            fixed = int(bs)
            if hz:
                if reverse:
                    cur = cw
                    for j in range(si, si + cnt):
                        w = int((aspects[j] or 1.0) * bs)
                        cur -= w
                        rects[j] = QtCore.QRect(cur, grp_offset, w, fixed)
                        cur -= spacing
                else:
                    cur = 0
                    for j in range(si, si + cnt):
                        w = int((aspects[j] or 1.0) * bs)
                        rects[j] = QtCore.QRect(cur, grp_offset, w, fixed)
                        cur += w + spacing
            else:
                cur = 0
                for j in range(si, si + cnt):
                    h = int(bs / (aspects[j] or 1.0))
                    rects[j] = QtCore.QRect(grp_offset, cur, fixed, h)
                    cur += h + spacing

        if groups:
            last_g = groups[-1]
            total_extent = last_g[2] + int(base * last_g[3]) + spacing
        else:
            total_extent = 0
        self._emit(rects, total_extent, hz)

    @profiler.profile
    def run(self):
        self._calculate(hz=self.orientation < 2, reverse=self.orientation % 2 == 1)


class MasonryLayoutCalculator(_BaseLayoutCalculator):

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
            raise ValueError('Vertical masonry requires container_height')
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
