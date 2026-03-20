import random

from PySide6 import QtCore
from wafer.plugin.layout import BaseLayoutPlugin, BaseLayoutCalculator, SCROLLBAR_INT_MAX
from wafer.utils.profiling import profiler
from wafer.utils.logs import AppLogger


def _partition(rects, cancelled, rng, sorted_ar, ar_prefix, inv_prefix,
               start, count, x, y, w, h, spacing):
    if count <= 0 or w <= 0 or h <= 0:
        return
    if count == 1:
        rects[start] = QtCore.QRect(x, y, w, h)
        return
    if cancelled():
        return

    cell_ar = w / h
    median_ar = sorted_ar[start + count // 2]
    split_x = median_ar < cell_ar

    if split_x and h > 0 and (w * 0.3) / h < 0.2:
        split_x = False
    elif not split_x and w > 0 and w / (h * 0.3) > 5.0:
        split_x = True

    left_count = round(max(1, min(count - 1, rng.gauss(count / 2, max(1, count / 8)))))
    left_count = max(1, min(count - 1, left_count))

    if split_x:
        left_ar = ar_prefix[start + left_count] - ar_prefix[start]
        total_ar = ar_prefix[start + count] - ar_prefix[start]
        ratio = left_ar / total_ar if total_ar > 0 else left_count / count
    else:
        left_inv = inv_prefix[start + left_count] - inv_prefix[start]
        total_inv = inv_prefix[start + count] - inv_prefix[start]
        ratio = left_inv / total_inv if total_inv > 0 else left_count / count
    ratio = max(0.1, min(0.9, ratio))

    if split_x:
        left_w = max(1, int(w * ratio) - spacing // 2)
        right_w = max(1, w - left_w - spacing)
        _partition(rects, cancelled, rng, sorted_ar, ar_prefix, inv_prefix,
                   start, left_count, x, y, left_w, h, spacing)
        _partition(rects, cancelled, rng, sorted_ar, ar_prefix, inv_prefix,
                   start + left_count, count - left_count,
                   x + left_w + spacing, y, right_w, h, spacing)
    else:
        top_h = max(1, int(h * ratio) - spacing // 2)
        bottom_h = max(1, h - top_h - spacing)
        _partition(rects, cancelled, rng, sorted_ar, ar_prefix, inv_prefix,
                   start, left_count, x, y, w, top_h, spacing)
        _partition(rects, cancelled, rng, sorted_ar, ar_prefix, inv_prefix,
                   start + left_count, count - left_count,
                   x, y + top_h + spacing, w, bottom_h, spacing)


class BspPartitionCalculator(BaseLayoutCalculator):

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
            raise ValueError('BSP partition layout requires container dimension')

        ar = [a if a and a > 0 else 1.0 for a in aspects]

        num_lanes = max(1, round((container + spacing) / (base + spacing)))
        block_size = max(8, num_lanes * num_lanes)

        order = list(range(n))
        for bs in range(0, n, block_size):
            be = min(bs + block_size, n)
            order[bs:be] = sorted(order[bs:be], key=lambda i: ar[i])
        sorted_ar = [ar[order[j]] for j in range(n)]

        ar_prefix = [0.0] * (n + 1)
        inv_prefix = [0.0] * (n + 1)
        for i in range(n):
            ar_prefix[i + 1] = ar_prefix[i] + sorted_ar[i]
            inv_prefix[i + 1] = inv_prefix[i] + 1.0 / sorted_ar[i]

        total_rows = max(1, -(-n // num_lanes))
        total_primary = int(total_rows * base + max(0, total_rows - 1) * spacing)

        if total_primary > SCROLLBAR_INT_MAX:
            total_primary = SCROLLBAR_INT_MAX
            AppLogger.debug(f"[BspPartitionLayout] clamped total_primary to {SCROLLBAR_INT_MAX}")

        sorted_rects = [None] * n
        rng = random.Random(n)
        _partition(sorted_rects, lambda: self._cancelled, rng, sorted_ar, ar_prefix, inv_prefix,
                   0, n, 0, 0, container, total_primary, spacing)

        if self._cancelled:
            return

        for bs in range(0, n, block_size):
            be = min(bs + block_size, n)
            cell_ars = []
            for idx in range(bs, be):
                r = sorted_rects[idx]
                cell_ars.append(r.width() / max(1, r.height()) if r else 0)
            cell_rank = sorted(range(be - bs), key=lambda k: cell_ars[k])
            old_rects = sorted_rects[bs:be]
            for rank, k in enumerate(cell_rank):
                sorted_rects[bs + rank] = old_rects[k]

        rects = [None] * n
        for j in range(n):
            rects[order[j]] = sorted_rects[j]

        if hz and reverse:
            for i in range(n):
                r = rects[i]
                rects[i] = QtCore.QRect(container - r.x() - r.width(), r.y(), r.width(), r.height())
        elif not hz and reverse and total_primary > 0:
            flip = total_primary - spacing
            for i in range(n):
                r = rects[i]
                rects[i] = QtCore.QRect(flip - r.x() - r.width(), r.y(), r.width(), r.height())

        self._emit(rects, total_primary, hz)

    @profiler.profile
    def run(self):
        self._calculate()


class BspPartitionLayout(BaseLayoutPlugin):
    NAME = 'bspPartition'
    DISPLAY_NAME = 'BSP Partition'
    PRIORITY = 85

    @classmethod
    def create_calculator(cls, aspect_ratios, base_size, spacing,
                          container_width, container_height, orientation):
        return BspPartitionCalculator(
            aspect_ratios, base_size, spacing,
            container_width, container_height, orientation,
        )
