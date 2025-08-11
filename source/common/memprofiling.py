import threading
import time
import re
import tracemalloc
from pathlib import Path

from .profiling import LoggerManager  # 既存 LoggerManager/LOG_PATH を再利用

class MemoryUsageReporter:
    """
    現在確保済みメモリの内訳を定期レポート（増分ではなく“現状”）。
    - Top by lineno（ファイル:行）
    - Top by filename（ファイル合計）
    - Top by traceback（確保スタック）
    - include/exclude 正規表現フィルタ
    """

    _instance = None

    def __new__(cls, *a, **kw):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self,
                 interval: int = 30,
                 topn: int = 15,
                 frames: int = 25):
        if getattr(self, "_initialized", False):
            return

        self.interval = max(5, int(interval))
        self.topn = int(topn)
        self.frames = int(frames)
        self.enabled = True

        self.logger = LoggerManager.get_logger()
        if not tracemalloc.is_tracing():
            tracemalloc.start(self.frames)

        self._include = None
        self._exclude = None

        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

        self._initialized = True
        self.logger.debug("[MemUsage] initialized: interval=%ss, topn=%d, frames=%d",
                          self.interval, self.topn, self.frames)

    # ---------- Public API ----------

    def set_enabled(self, v: bool):
        self.enabled = bool(v)

    def stop(self):
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=2)

    def set_filters(self, include: str | None = None, exclude: str | None = None):
        """ファイルパス/関数名などの文字列に対してフィルタ適用。"""
        self._include = re.compile(include) if include else None
        self._exclude = re.compile(exclude) if exclude else None

    def report_now(self, title: str = "Current allocations"):
        """即時レポート（interval待ちなし）"""
        if not self.enabled:
            return
        try:
            snap = tracemalloc.take_snapshot()
            self._log_stats(snap, "lineno",   f"[MemUsage] Top by lineno — {title}")
            self._log_stats(snap, "filename", f"[MemUsage] Top by file — {title}")
            self._log_stats(snap, "traceback",f"[MemUsage] Top by traceback — {title}")
        except Exception as e:
            self.logger.warning("[MemUsage] report failed: %s", e, exc_info=True)

    # ---------- Internals ----------

    def _loop(self):
        while not self._stop.wait(self.interval):
            if self.enabled:
                self.report_now(f"last {self.interval}s")

    def _filter_stats(self, stats):
        """statistics() で得たリストを include/exclude（正規表現）で間引く"""
        if self._include is None and self._exclude is None:
            return stats
        out = []
        for s in stats:
            txt = " | ".join(f"{fr.filename}:{fr.lineno}" for fr in s.traceback)
            if self._include and not self._include.search(txt):
                continue
            if self._exclude and self._exclude.search(txt):
                continue
            out.append(s)
        return out

    def _log_stats(self, snap: tracemalloc.Snapshot, key: str, header: str):
        """
        key: 'lineno' | 'filename' | 'traceback'
        """
        stats = snap.statistics(key)
        stats = self._filter_stats(stats)
        if not stats:
            self.logger.debug("%s: (no allocations)", header)
            return

        total = sum(s.size for s in stats)
        total_mb = total / (1024 * 1024)
        top = stats[: self.topn]

        self.logger.debug("%s (total=%.2f MB):", header, total_mb)

        for s in top:
            kb = s.size / 1024.0
            cnt = s.count
            where = self._fmt_stat_where(s, key)
            self.logger.debug("  %8.1f KB  x%-6d  %s", kb, cnt, where)

    def _fmt_stat_where(self, stat, key: str) -> str:
        try:
            if key in ("lineno", "traceback"):
                if stat.traceback:
                    fr = stat.traceback[0]
                    return f"{Path(fr.filename).name}:{fr.lineno}"
            elif key == "filename":
                if stat.traceback:
                    return Path(stat.traceback[0].filename).name
        except Exception:
            pass
        return str(stat)

"""
mem_usage = MemoryUsageReporter(interval=20, topn=12, frames=25)
mem_usage.set_filters(
    include=r"(?i)F:\\codes\\NAI_image_viewer\\source",  # プロジェクト配下のみ
    exclude=r"(?i)pydevd\.py|importlib|_bootstrap|memprofiling\.py"
)
"""