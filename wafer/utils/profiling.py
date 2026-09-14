import os
import threading
import time
from collections import defaultdict
from functools import wraps

from .logs import AppLogger


class FunctionProfiler:
    _instance = None

    def __new__(cls, interval=10):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, interval=10):
        if hasattr(self, "_initialized") and self._initialized:
            return
        self.interval = interval
        self.data = defaultdict(lambda: {"total_time": 0.0, "self_time": 0.0, "count": 0})
        self._stop_event = threading.Event()
        self.local = threading.local()
        self.lock = threading.Lock()
        self._thread = None
        self.enabled = False
        self._initialized = True

    def start(self):
        self.enabled = True
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._report_loop, daemon=True)
        self._thread.start()

    def record(self, name: str, duration: float, *, self_time: float | None = None, count: int = 1):
        if not self.enabled:
            return
        own_time = duration if self_time is None else self_time
        duration = max(0.0, float(duration))
        own_time = max(0.0, float(own_time))
        count = max(1, int(count))
        with self.lock:
            info = self.data[str(name)]
            info["total_time"] += duration
            info["self_time"] += own_time
            info["count"] += count

    def record_elapsed(self, name: str, started_at: float, *, ended_at: float | None = None) -> float:
        finished_at = time.perf_counter() if ended_at is None else float(ended_at)
        duration = max(0.0, finished_at - float(started_at))
        self.record(name, duration)
        return duration

    def callable_name(self, fn) -> str:
        return getattr(fn, "__qualname__", getattr(fn, "__name__", type(fn).__qualname__))

    def wrap_queued(self, fn, suffix: str):
        if not self.enabled:
            return fn
        queued_at = time.perf_counter()
        wait_name = f"{self.callable_name(fn)}{suffix}"

        @wraps(fn)
        def wrapper(*args, **kwargs):
            self.record_elapsed(wait_name, queued_at)
            return fn(*args, **kwargs)

        return wrapper

    def profile(self, func):

        @wraps(func)
        def wrapper(*args, **kwargs):
            if not self.enabled:
                return func(*args, **kwargs)
            if not hasattr(self.local, "stack"):
                self.local.stack = []
            start_time = time.perf_counter()
            self.local.stack.append({"name": func.__qualname__, "start": start_time, "children": 0.0})
            try:
                return func(*args, **kwargs)
            finally:
                end_time = time.perf_counter()
                record = self.local.stack.pop()
                duration = end_time - record["start"]
                self_time = duration - record["children"]
                with self.lock:
                    info = self.data[func.__qualname__]
                    info["total_time"] += duration
                    info["self_time"] += self_time
                    info["count"] += 1
                if self.local.stack:
                    self.local.stack[-1]["children"] += duration

        return wrapper

    def _report_loop(self):
        while not self._stop_event.wait(self.interval):
            if self.enabled:
                try:
                    self.report()
                except Exception as e:
                    AppLogger.warning(f"[Profiler] report failed: {e}", exc=e)

    def report(self):
        with self.lock:
            total_self_time = sum(info["self_time"] for info in self.data.values())
            if total_self_time == 0:
                return
            summary_data = list(self.data.items())
            self.data.clear()
        summary = []
        for name, info in summary_data:
            self_time = info["self_time"]
            count = info["count"]
            summary.append((name, self_time, count, self_time / total_self_time))
        summary.sort(key=lambda x: -x[3])
        summary = summary[:5]
        AppLogger.debug("[Profiler] Function self-time breakdown:")
        for name, self_time, count, ratio in summary:
            AppLogger.debug(f"  {name:<30} : {self_time:.3f}s ({ratio:.1%}) - {count} calls")

    def stop(self):
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None

    def set_enabled(self, value):
        self.enabled = value


profiler = FunctionProfiler(interval=5)


class MainThreadWatchdog:
    INTERVAL_MS = 16
    THRESHOLD_MS = 50

    def __init__(self):
        self._timer = None
        self._last_tick = 0.0
        self._enabled = False

    def start(self):
        if self._enabled:
            return
        from PySide6.QtCore import QTimer, Qt

        self._enabled = True
        self._last_tick = time.perf_counter()
        self._timer = QTimer()
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        self._timer.start(self.INTERVAL_MS)
        AppLogger.info("[Watchdog] MainThread watchdog started")

    def _tick(self):
        now = time.perf_counter()
        elapsed_ms = (now - self._last_tick) * 1000
        self._last_tick = now
        if elapsed_ms > self.THRESHOLD_MS:
            AppLogger.warning(f"[Watchdog] MainThread blocked for {elapsed_ms:.1f}ms (threshold={self.THRESHOLD_MS}ms)")

    def stop(self):
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        self._enabled = False
        AppLogger.info("[Watchdog] MainThread watchdog stopped")


watchdog = MainThreadWatchdog()


class MemoryWatchdog:
    def __init__(self, interval=30):
        self.interval = interval
        self.enabled = False
        self.trace = False
        self._stop_event = threading.Event()
        self._thread = None
        self._proc = None
        self._last_rss = 0
        self._peak_rss = 0

    def set_enabled(self, value, *, trace=False):
        self.enabled = value
        self.trace = trace

    def start(self, *, trace=False):
        self.enabled = True
        self.trace = trace
        if self.trace:
            import tracemalloc

            if not tracemalloc.is_tracing():
                tracemalloc.start(25)
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._report_loop, name="mem-watchdog", daemon=True)
        self._thread.start()
        AppLogger.info(f"[MemWatch] started (interval={self.interval}s, trace={self.trace})")

    def _report_loop(self):
        import psutil

        self._proc = psutil.Process()
        self._last_rss = self._peak_rss = self._proc.memory_info().rss
        while not self._stop_event.wait(self.interval):
            if self.enabled:
                try:
                    self.report()
                except Exception as e:
                    AppLogger.warning(f"[MemWatch] report failed: {e}", exc=e)

    def report(self):
        rss = self._proc.memory_info().rss
        delta = rss - self._last_rss
        self._last_rss = rss
        self._peak_rss = max(self._peak_rss, rss)
        mb = 1024 * 1024
        role = AppLogger._role or "root"
        AppLogger.info(f"[MemWatch] {role}(pid={os.getpid()}) RSS={rss / mb:.1f}MB delta={delta / mb:+.1f}MB/{self.interval}s peak={self._peak_rss / mb:.1f}MB")
        if self.trace:
            self.report_tracemalloc()

    def report_tracemalloc(self):
        import tracemalloc

        stats = tracemalloc.take_snapshot().statistics("lineno")[:8]
        AppLogger.info("[MemWatch] top allocations by size:")
        for stat in stats:
            AppLogger.info(f"  {stat}")

    def stop(self):
        self._stop_event.set()
        self.enabled = False
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None
        AppLogger.info("[MemWatch] stopped")


memwatch = MemoryWatchdog()
