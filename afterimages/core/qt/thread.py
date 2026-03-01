import multiprocessing
import threading
import time
from collections import deque, defaultdict
from typing import Callable, Optional

import psutil
from PySide6 import QtCore
from afterimages.utils.profiling import profiler
from afterimages.utils.logs import AppLogger

class _CancellableSignals(QtCore.QObject):
    finished = QtCore.Signal(object)


class CancellableRunnable(QtCore.QRunnable):
    def __init__(self):
        super().__init__()
        self.signals = _CancellableSignals()
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def execute(self):
        raise NotImplementedError

    def run(self):
        if self._cancelled:
            return
        try:
            result = self.execute()
        except Exception as e:
            AppLogger.warning(f'[{type(self).__name__}] failed: {e}', exc=e)
            return
        if self._cancelled:
            return
        self.signals.finished.emit(result)


class _AdjustProxy(QtCore.QObject):
    requestDelta = QtCore.Signal(int)


class AdaptiveThreadPool:
    _instance = None
    _lock = threading.Lock()

    _latency_config      = {}
    _latency_buffer      = defaultdict(lambda: deque(maxlen=20))
    _latency_ok_streak   = defaultdict(int)
    _lat_lock            = threading.Lock()
    _last_decrease_time  = 0.0
    _decrease_cooldown_ms = 300.0
    _severe_latency_multiplier = 2.0
    _HALVE_SENTINEL      = -10_000_000

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls, *args, **kwargs)
        return cls._instance

    def __init__(self, base_limit=3, max_limit=-2, cpu_threshold=65):
        super().__init__()
        self.pool = QtCore.QThreadPool.globalInstance()

        cpu_count = multiprocessing.cpu_count()

        eff_max = max(1, cpu_count + int(max_limit))

        bl = int(base_limit)
        if bl <= 0:
            eff_base = max(1, eff_max + bl)   # bl は負 or 0
        else:
            eff_base = bl

        if eff_base > eff_max:
            eff_max = eff_base

        self.base_limit = eff_base
        self.max_limit = eff_max
        self.cpu_threshold = cpu_threshold

        self.pool.setMaxThreadCount(self.base_limit)

        self.cpu_threshold = cpu_threshold

        self._proxy = _AdjustProxy()
        self._proxy.requestDelta.connect(self._on_delta_requested, QtCore.Qt.QueuedConnection)
        self.monitor = None
        self._initialized = True

    # ========== デコレータ：関数単位でレイテンシ監視 ==========
    @classmethod
    def register(cls, low_ms: int, high_ms: int, *, window: int = 20, cool_needed: int = 3):
        inst = cls()  # singleton を取得

        def _decorator(func: Callable):
            name = f"{func.__module__}.{func.__qualname__}"
            with cls._lat_lock:
                cls._latency_config[name] = (low_ms, high_ms, window, cool_needed)
                buf = cls._latency_buffer[name]
                if buf.maxlen != window:
                    cls._latency_buffer[name] = deque(buf, maxlen=window)

            def _wrapped(*args, **kwargs):
                t0 = time.perf_counter()
                try:
                    return func(*args, **kwargs)
                finally:
                    dt_ms = (time.perf_counter() - t0) * 1000.0
                    cls._record_latency(name, dt_ms, inst)
            return _wrapped
        return _decorator

    @classmethod
    def _record_latency(cls, name: str, dt_ms: float, inst: "AdaptiveThreadPool"):
        with cls._lat_lock:
            cfg = cls._latency_config.get(name)
            if not cfg:
                return
            low_ms, high_ms, window, cool_needed = cfg
            cls._latency_buffer[name].append(dt_ms)

            now = time.perf_counter() * 1000.0
            if dt_ms >= high_ms and (now - cls._last_decrease_time) >= cls._decrease_cooldown_ms:
                if dt_ms >= (high_ms * cls._severe_latency_multiplier):
                    inst._proxy.requestDelta.emit(cls._HALVE_SENTINEL)
                else:
                    inst._proxy.requestDelta.emit(-1)
                cls._last_decrease_time = now

            if dt_ms <= low_ms:
                cls._latency_ok_streak[name] += 1
            else:
                cls._latency_ok_streak[name] = 0

    # ========================================================

    @profiler.profile
    def start_monitoring(self):
        if self.monitor:
            return
        self.monitor = QtCore.QTimer()
        self.monitor.timeout.connect(self.adjust_thread_count)
        self.monitor.setInterval(1000)
        self.monitor.start()

    @profiler.profile
    def submit(self, obj, *args, **kwargs):
        self.pool.start(obj, *args, **kwargs)

    def adjust_thread_count(self):
        cpu_usage = psutil.cpu_percent()
        # 回復条件：CPU余裕 & 全関数で「low未満がしばらく継続」
        with self._lat_lock:
            can_recover = all(
                (cfg and self._latency_ok_streak[name] >= cfg[3])
                for name, cfg in self._latency_config.items()
            )
            if can_recover:
                for name, cfg in self._latency_config.items():
                    buf = list(self._latency_buffer[name])
                    if len(buf) >= 5:
                        buf_sorted = sorted(buf)
                        p95 = buf_sorted[max(0, int(len(buf_sorted) * 0.95) - 1)]
                        if p95 > cfg[0]:  # low_ms
                            can_recover = False
                            break

        if can_recover and cpu_usage < self.cpu_threshold:
            self._proxy.requestDelta.emit(+1)
            # 回復カウンタをリセットして暴れを防止
            with self._lat_lock:
                for k in list(self._latency_ok_streak.keys()):
                    self._latency_ok_streak[k] = 0

    # ---- メインスレッドで実行される実処理 ----
    @QtCore.Slot(int)
    def _on_delta_requested(self, delta: int):
        current = self.pool.maxThreadCount()
        if delta == 0:
            return

        # ★半減要求の処理
        if delta == self._HALVE_SENTINEL:
            # ceil(current/2) だが base_limit 未満にはしない
            new_count = max(self.base_limit, (current + 1) // 2)
            if new_count != current:
                self.pool.setMaxThreadCount(new_count)
                AppLogger.debug(f'[ThreadPool] Halved maxThreadCount: {current} -> {new_count}')
            return

        # 従来の ±1 調整
        if delta > 0 and current >= self.max_limit:
            return
        if delta < 0 and current <= self.base_limit:
            return

        new_count = max(1, min(self.max_limit, max(self.base_limit, current + delta)))
        if new_count != current:
            self.pool.setMaxThreadCount(new_count)
            AppLogger.debug(f'[ThreadPool] Adjusted maxThreadCount: {current} -> {new_count} (delta {delta:+d})')



# 既存のシングルトン
thread_pool = AdaptiveThreadPool()
