import multiprocessing
import threading
import time
from collections import deque, defaultdict
from collections.abc import Callable

import psutil
from PySide6 import QtCore
from ...utils.profiling import profiler
from ...utils.logs import AppLogger


class SimpleThreadPool:
    def __init__(self, name: str = "simple"):
        self.name = name
        self.pool = QtCore.QThreadPool()

    @profiler.profile
    def submit(self, obj, *args, **kwargs):
        self.pool.start(obj, *args, **kwargs)


class _AdjustProxy(QtCore.QObject):
    requestDelta = QtCore.Signal(int)


_HALVE_SENTINEL = -10_000_000


class AdaptiveThreadPool:
    def __init__(self, name: str = "adaptive", base_limit=3, max_limit=-2, cpu_threshold=65):
        self.name = name
        self.pool = QtCore.QThreadPool()

        cpu_count = multiprocessing.cpu_count()

        eff_max = max(1, cpu_count + int(max_limit))

        bl = int(base_limit)
        if bl <= 0:
            eff_base = max(1, eff_max + bl)
        else:
            eff_base = bl

        if eff_base > eff_max:
            eff_max = eff_base

        self.base_limit = eff_base
        self.max_limit = eff_max
        self.cpu_threshold = cpu_threshold

        self.pool.setMaxThreadCount(self.base_limit)

        self._latency_config: dict[str, tuple] = {}
        self._latency_buffer: dict[str, deque] = defaultdict(lambda: deque(maxlen=20))
        self._latency_ok_streak: dict[str, int] = defaultdict(int)
        self._lat_lock = threading.Lock()
        self._last_decrease_time = 0.0
        self._decrease_cooldown_ms = 300.0
        self._severe_latency_multiplier = 2.0

        self._proxy = _AdjustProxy()
        self._proxy.requestDelta.connect(self._on_delta_requested, QtCore.Qt.QueuedConnection)
        self._monitor = None

    def register(self, low_ms: int, high_ms: int, *, window: int = 20, cool_needed: int = 3):
        def _decorator(func: Callable):
            name = f"{func.__module__}.{func.__qualname__}"
            with self._lat_lock:
                self._latency_config[name] = (low_ms, high_ms, window, cool_needed)
                buf = self._latency_buffer[name]
                if buf.maxlen != window:
                    self._latency_buffer[name] = deque(buf, maxlen=window)

            def _wrapped(*args, **kwargs):
                t0 = time.perf_counter()
                try:
                    return func(*args, **kwargs)
                finally:
                    dt_ms = (time.perf_counter() - t0) * 1000.0
                    self._record_latency(name, dt_ms)

            return _wrapped

        return _decorator

    def _record_latency(self, name: str, dt_ms: float):
        with self._lat_lock:
            cfg = self._latency_config.get(name)
            if not cfg:
                return
            low_ms, high_ms, _window, _cool_needed = cfg
            self._latency_buffer[name].append(dt_ms)

            now = time.perf_counter() * 1000.0
            if dt_ms >= high_ms and (now - self._last_decrease_time) >= self._decrease_cooldown_ms:
                if dt_ms >= (high_ms * self._severe_latency_multiplier):
                    self._proxy.requestDelta.emit(_HALVE_SENTINEL)
                else:
                    self._proxy.requestDelta.emit(-1)
                self._last_decrease_time = now

            if dt_ms <= low_ms:
                self._latency_ok_streak[name] += 1
            else:
                self._latency_ok_streak[name] = 0

    @profiler.profile
    def start_monitoring(self):
        if self._monitor:
            return
        self._monitor = QtCore.QTimer()
        self._monitor.timeout.connect(self._adjust_thread_count)
        self._monitor.setInterval(1000)
        self._monitor.start()

    @profiler.profile
    def submit(self, obj, *args, **kwargs):
        self.pool.start(obj, *args, **kwargs)

    def _adjust_thread_count(self):
        cpu_usage = psutil.cpu_percent()
        with self._lat_lock:
            can_recover = all((cfg and self._latency_ok_streak[name] >= cfg[3]) for name, cfg in self._latency_config.items())
            if can_recover:
                for name, cfg in self._latency_config.items():
                    buf = list(self._latency_buffer[name])
                    if len(buf) >= 5:
                        buf_sorted = sorted(buf)
                        p95 = buf_sorted[max(0, int(len(buf_sorted) * 0.95) - 1)]
                        if p95 > cfg[0]:
                            can_recover = False
                            break

        if can_recover and cpu_usage < self.cpu_threshold:
            self._proxy.requestDelta.emit(+1)
            with self._lat_lock:
                for k in list(self._latency_ok_streak.keys()):
                    self._latency_ok_streak[k] = 0

    @QtCore.Slot(int)
    def _on_delta_requested(self, delta: int):
        current = self.pool.maxThreadCount()
        if delta == 0:
            return

        if delta == _HALVE_SENTINEL:
            new_count = max(self.base_limit, (current + 1) // 2)
            if new_count != current:
                self.pool.setMaxThreadCount(new_count)
                AppLogger.debug(f"[{self.name}] Halved maxThreadCount: {current} -> {new_count}")
            return

        if delta > 0 and current >= self.max_limit:
            return
        if delta < 0 and current <= self.base_limit:
            return

        new_count = max(1, min(self.max_limit, max(self.base_limit, current + delta)))
        if new_count != current:
            self.pool.setMaxThreadCount(new_count)
            AppLogger.debug(f"[{self.name}] Adjusted maxThreadCount: {current} -> {new_count} (delta {delta:+d})")


grid_thumb_pool = AdaptiveThreadPool("grid_thumb", max_limit=-2)
grid_render_pool = AdaptiveThreadPool("grid_render", max_limit=-2)
utility_pool = SimpleThreadPool("utility")
