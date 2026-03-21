from PySide6 import QtCore
from wafer.plugin.layout import BaseLayoutPlugin, BaseLayoutCalculator, SCROLLBAR_INT_MAX
from wafer.utils.profiling import profiler
from wafer.utils.logs import AppLogger

_DP_CHUNK_SIZE = 3000


class OptimizedJustifiedLayoutCalculator(BaseLayoutCalculator):

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
        n = len(aspects)
        if n == 0:
            self._emit([], 0, hz)
            return

        prefix = [0.0] * (n + 1)
        for i in range(n):
            a = aspects[i] or 1.0
            prefix[i + 1] = prefix[i] + (a * base if hz else base / a)

        min_ext = min((a or 1.0) * base if hz else base / (a or 1.0) for a in aspects)
        max_per_row = max(1, int((container + spacing) / (min_ext + spacing))) + 1

        all_breaks = []
        cs = 0
        while cs < n:
            if self._cancelled:
                return
            ce = min(cs + _DP_CHUNK_SIZE, n)
            cn = ce - cs
            is_last = ce == n

            INF = float('inf')
            dp = [INF] * (cn + 1)
            dp[0] = 0.0
            par = [0] * (cn + 1)

            for j in range(1, cn + 1):
                if self._cancelled:
                    return
                i_lo = max(j - max_per_row, 0)
                best = dp[j]
                pj = prefix[cs + j]
                last_item = is_last and j == cn
                for i in range(j - 1, i_lo - 1, -1):
                    dpi = dp[i]
                    if dpi >= best:
                        break
                    le = pj - prefix[cs + i]
                    if le <= 0:
                        continue
                    total_sp = spacing * (j - i - 1)
                    if le > container - total_sp + container * 0.5:
                        break
                    sc = (container - total_sp) / le
                    if sc < 0.1:
                        break
                    r = sc - 1.0
                    if last_item and r > 0:
                        cand = dpi
                    else:
                        ar = r if r >= 0 else -r
                        cand = dpi + ar * ar * ar
                    if cand < best:
                        best = cand
                        dp[j] = cand
                        par[j] = i

            if self._cancelled:
                return

            j = cn
            chunk_breaks = []
            while j > 0:
                chunk_breaks.append(cs + par[j])
                j = par[j]
            chunk_breaks.reverse()
            all_breaks.extend(chunk_breaks)
            cs = ce

        groups = []
        offset = 0
        num_rows = len(all_breaks)
        for k in range(num_rows):
            si = all_breaks[k]
            ei = all_breaks[k + 1] if k + 1 < num_rows else n
            cnt = ei - si
            line_ext = prefix[ei] - prefix[si]
            total_sp = spacing * (cnt - 1)
            scale = max((container - total_sp) / line_ext, 0.1) if line_ext > 0 else 1.0
            if k == num_rows - 1 and scale > 1.0:
                scale = 1.0
            groups.append((si, cnt, offset, scale))
            offset += int(base * scale) + spacing
            if offset > SCROLLBAR_INT_MAX:
                AppLogger.debug(f"[OptimizedJustifiedLayout] truncated offset={offset} max={SCROLLBAR_INT_MAX} items={n}")
                break

        if not groups or self._cancelled:
            return

        self._build_justified_rects(groups, hz, reverse)

    @profiler.profile
    def run(self):
        self._calculate(hz=self.orientation < 2, reverse=self.orientation % 2 == 1)


class OptimizedJustifiedLayout(BaseLayoutPlugin):
    NAME = 'optimizedJustified'
    DISPLAY_NAME = 'Justified (Optimized)'
    PRIORITY = 95

    @classmethod
    def create_calculator(cls, aspect_ratios, base_size, spacing,
                          container_width, container_height, orientation):
        return OptimizedJustifiedLayoutCalculator(
            aspect_ratios, base_size, spacing,
            container_width, container_height, orientation,
        )
