import bisect
from PySide6 import QtCore
from afterimages.utils.profiling import profiler
from afterimages.utils.logs import AppLogger
SCROLLBAR_INT_MAX = 2147483647


class LayoutData:
    __slots__ = (
        '_aspects', '_base_height', '_spacing', '_container_width', '_is_horizontal', '_is_reversed',
        '_groups', '_group_start_indices', '_sorted_starts', '_sorted_ends',
        '_visible_group_order_map', '_total_extent', '_count',
        'group_starts', 'group_ends', 'group_mids', '_cache',
    )

    def __init__(self, aspects, base_height, spacing, container_width,
                 hz, reversed_secondary, groups):
        self._aspects = aspects
        self._base_height = base_height
        self._spacing = spacing
        self._container_width = container_width
        self._is_horizontal = hz
        self._is_reversed = reversed_secondary
        self._groups = groups
        self._group_start_indices = [g[0] for g in groups]
        self._cache = {}
        offsets = [g[2] for g in groups]
        extents = [int(base_height * g[3]) for g in groups]
        need_sort = any(offsets[i] > offsets[i + 1] for i in range(len(offsets) - 1))
        if need_sort:
            order = sorted(range(len(groups)), key=lambda i: offsets[i])
            self._sorted_starts = [offsets[i] for i in order]
            self._sorted_ends = [offsets[i] + extents[i] - 1 for i in order]
            self._visible_group_order_map = order
        else:
            self._sorted_starts = offsets
            self._sorted_ends = [o + e - 1 for o, e in zip(offsets, extents)]
            self._visible_group_order_map = None
        self._total_extent = (self._sorted_ends[-1] + spacing) if self._sorted_ends else 0
        self._count = sum(g[1] for g in groups)

        self.group_starts = self._sorted_starts
        self.group_ends = [e + 1 for e in self._sorted_ends]
        self.group_mids = [(s + e) // 2 for s, e in zip(self._sorted_starts, self._sorted_ends)]

    @staticmethod
    def empty():
        d = LayoutData.__new__(LayoutData)
        d._aspects = []
        d._base_height = 0
        d._spacing = 0
        d._container_width = 0
        d._is_horizontal = True
        d._is_reversed = False
        d._groups = []
        d._group_start_indices = []
        d._sorted_starts = []
        d._sorted_ends = []
        d._visible_group_order_map = None
        d._total_extent = 0
        d._count = 0
        d.group_starts = []
        d.group_ends = []
        d.group_mids = []
        d._cache = {}
        return d

    @property
    def total_extent(self):
        return self._total_extent

    def __len__(self):
        return self._count

    def __bool__(self):
        return self._count > 0

    def __getitem__(self, i):
        cached = self._cache.get(i)
        if cached is not None:
            return cached
        r = self._compute(i)
        self._cache[i] = r
        return r

    def _find_group(self, i):
        return bisect.bisect_right(self._group_start_indices, i) - 1

    def _compute(self, i):
        gi = self._find_group(i)
        si, cnt, offset, scale = self._groups[gi]
        bs = self._base_height * scale
        sp = self._spacing
        fixed = int(bs)
        if self._is_horizontal:
            if self._is_reversed:
                cur = self._container_width
                for j in range(si, si + cnt):
                    w = int(self._aspects[j] * bs)
                    cur -= w
                    if j == i:
                        return QtCore.QRect(cur, offset, w, fixed)
                    cur -= sp
            else:
                cur = 0
                for j in range(si, i):
                    cur += int(self._aspects[j] * bs) + sp
                return QtCore.QRect(cur, offset, int(self._aspects[i] * bs), fixed)
        else:
            cur = 0
            for j in range(si, i):
                cur += int(bs / self._aspects[j]) + sp
            return QtCore.QRect(offset, cur, fixed, int(bs / self._aspects[i]))

    def _visible_group_range(self, p_start, p_end):

        n = len(self._sorted_starts)
        if n == 0:
            return 0, -1
        first = max(0, min(bisect.bisect_left(self._sorted_ends, p_start), n - 1))
        last = max(first, min(bisect.bisect_right(self._sorted_starts, p_end) - 1, n - 1))
        return first, last

    def _iter_visible_groups(self, p_start, p_end):
        first, last = self._visible_group_range(p_start, p_end)
        for sgi in range(first, last + 1):
            gi = self._visible_group_order_map[sgi] if self._visible_group_order_map else sgi
            yield self._groups[gi][0], self._groups[gi][1]

    def calculate_visible_indices(self, p_start, p_end):
        first, last = self._visible_group_range(p_start, p_end)
        if first > last:
            return range(0, 0)
        if self._visible_group_order_map is not None:
            indices = []
            for sgi in range(first, last + 1):
                gi = self._visible_group_order_map[sgi]
                indices.extend(range(self._groups[gi][0], self._groups[gi][0] + self._groups[gi][1]))
            return indices
        si_first = self._groups[first][0]
        g_last = self._groups[last]
        return range(si_first, g_last[0] + g_last[1])

    def index_at_point(self, point):
        p = point.y() if self._is_horizontal else point.x()
        for si, cnt in self._iter_visible_groups(p, p):
            for idx in range(si, si + cnt):
                if self[idx].contains(point):
                    return idx
        return None

    def intersecting_indices(self, rect):
        p_start = rect.top() if self._is_horizontal else rect.left()
        p_end = rect.bottom() if self._is_horizontal else rect.right()
        result = []
        for si, cnt in self._iter_visible_groups(p_start, p_end):
            for idx in range(si, si + cnt):
                if self[idx].intersects(rect):
                    result.append(idx)
        return result


class CalculatorSignals(QtCore.QObject):
    layout_ready = QtCore.Signal(object)

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
    def _calculate(self, hz, reverse):
        if not hz and self.container_height is None:
            raise ValueError('Vertical layout requires container_height')
        groups = []
        offset = 0
        start_idx = 0
        line_count = 0
        line_extent = 0.0
        spacing = self.spacing
        base = self.base_height
        aspects = self.aspect_ratios
        container = self.container_width if hz else self.container_height
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
        reversed_secondary = False
        if reverse:
            if hz:
                reversed_secondary = True
            elif groups:
                last_g = groups[-1]
                total = last_g[2] + int(base * last_g[3])
                groups = [(si, cnt, total - ofs - int(base * sc), sc)
                          for si, cnt, ofs, sc in groups]
        layout = LayoutData(aspects, base, spacing, self.container_width,
                           hz=hz, reversed_secondary=reversed_secondary, groups=groups)
        self.signals.layout_ready.emit(layout)

    @profiler.profile
    def run(self):
        self._calculate(hz=self.orientation < 2, reverse=self.orientation % 2 == 1)
