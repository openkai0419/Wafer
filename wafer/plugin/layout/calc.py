import bisect
from typing import TYPE_CHECKING
from PySide6 import QtCore
from ...utils.profiling import profiler

if TYPE_CHECKING:
    pass
SCROLLBAR_INT_MAX = 2147483647


class LayoutData:
    __slots__ = (
        "_count",
        "_is_horizontal",
        "_max_primary_size",
        "_rects",
        "_sorted_indices",
        "_sorted_primary_starts",
        "_total_extent",
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
    def calculate_visible_indices(self, p_start, p_end, s_start=None, s_end=None):
        if not self._count:
            return []
        lo = bisect.bisect_left(self._sorted_primary_starts, p_start - self._max_primary_size)
        hi = bisect.bisect_right(self._sorted_primary_starts, p_end)
        indices = self._sorted_indices[lo:hi]
        if s_start is None:
            return indices
        rects = self._rects
        hz = self._is_horizontal
        if hz:
            return [i for i in indices if rects[i].x() < s_end and rects[i].x() + rects[i].width() > s_start]
        return [i for i in indices if rects[i].y() < s_end and rects[i].y() + rects[i].height() > s_start]

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
    def nearest_index_to_point(self, point, indices=None):
        if not self._count:
            return None
        candidates = range(self._count) if indices is None else indices
        px, py = point.x(), point.y()
        best = None
        best_key = None
        hz = self._is_horizontal
        for raw_index in candidates:
            i = int(raw_index)
            if i < 0 or i >= self._count:
                continue
            r = self._rects[i]
            left = r.x()
            top = r.y()
            right = left + r.width()
            bottom = top + r.height()
            dx = left - px if px < left else px - right if px > right else 0
            dy = top - py if py < top else py - bottom if py > bottom else 0
            center = r.center()
            center_dx = center.x() - px
            center_dy = center.y() - py
            key = (
                dx * dx + dy * dy,
                center_dx * center_dx + center_dy * center_dy,
                r.y() if hz else r.x(),
                r.x() if hz else r.y(),
                i,
            )
            if best_key is None or key < best_key:
                best = i
                best_key = key
        return best

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


class _BaseLayoutCalculator:
    def __init__(self, aspect_ratios, base_size, spacing, container_width, container_height, orientation=0):
        self.aspect_ratios = aspect_ratios
        self.spacing = spacing
        self.base_size = base_size
        self.container_width = container_width
        self.container_height = container_height
        self._cancelled_flag = False
        self._cancel_token = None
        self._result = None
        self.orientation = orientation

    @property
    def _cancelled(self):
        if self._cancelled_flag:
            return True
        token = self._cancel_token
        return token is not None and token.is_cancelled()

    def bind_cancel_token(self, token):
        self._cancel_token = token

    def cancel(self):
        self._cancelled_flag = True

    def _emit(self, rects, total_extent, hz):
        self._result = LayoutData(rects, total_extent, hz)

    def _build_justified_rects(self, groups, hz, reverse):
        base = self.base_size
        aspects = self.aspect_ratios
        spacing = self.spacing

        if not hz and reverse:
            last_g = groups[-1]
            total = last_g[2] + int(base * last_g[3])
            groups = [(si, cnt, total - ofs - int(base * sc), sc) for si, cnt, ofs, sc in groups]

        rn = groups[-1][0] + groups[-1][1]
        rects = [None] * rn
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

        total_extent = max(ofs + int(base * sc) for _, _, ofs, sc in groups) + spacing
        self._emit(rects, total_extent, hz)
