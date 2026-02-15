import multiprocessing
import threading
import time
from collections import deque, defaultdict
from typing import Callable, Optional

import psutil
from PySide6 import QtCore
from ..common.profiling import profiler
from ..common.logs import AppLogger


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

    _lat_cfg      = {}                 # name -> (low_ms, high_ms, window, cool_needed)
    _lat_buf      = defaultdict(lambda: deque(maxlen=20))   # name -> deque[ms]
    _lat_ok_streak= defaultdict(int)   # name -> 低遅延継続回数
    _lat_lock     = threading.Lock()
    _last_dec_t   = 0.0               # 直近で減速した時刻（連打防止）
    _dec_cool_ms  = 300.0             # 減速のクールダウン(ms)
    _big_over_mul = 2.0       
    _HALVE_CODE   = -10_000_000         # high_ms の何倍超で -2 にするか

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
                cls._lat_cfg[name] = (low_ms, high_ms, window, cool_needed)
                buf = cls._lat_buf[name]
                if buf.maxlen != window:
                    cls._lat_buf[name] = deque(buf, maxlen=window)

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
            cfg = cls._lat_cfg.get(name)
            if not cfg:
                return
            low_ms, high_ms, window, cool_needed = cfg
            cls._lat_buf[name].append(dt_ms)

            now = time.perf_counter() * 1000.0
            # high 超過で即時縮小（クールダウンあり）
            if dt_ms >= high_ms and (now - cls._last_dec_t) >= cls._dec_cool_ms:
                # 重大超過なら「半減」、軽微超過なら -1
                if dt_ms >= (high_ms * cls._big_over_mul):
                    inst._proxy.requestDelta.emit(cls._HALVE_CODE)   # ★半減
                else:
                    inst._proxy.requestDelta.emit(-1)                # 従来通り -1
                cls._last_dec_t = now

            # 回復カウンタ
            if dt_ms <= low_ms:
                cls._lat_ok_streak[name] += 1
            else:
                cls._lat_ok_streak[name] = 0

    # ========================================================

    @profiler.profile
    def watch_start(self):
        if self.monitor:
            return
        self.monitor = QtCore.QTimer()
        self.monitor.timeout.connect(self.adjust_thread_count)
        self.monitor.setInterval(1000)
        self.monitor.start()

    @profiler.profile
    def start(self, obj, *args, **kwargs):
        self.pool.start(obj, *args, **kwargs)

    def adjust_thread_count(self):
        cpu_usage = psutil.cpu_percent()
        # 回復条件：CPU余裕 & 全関数で「low未満がしばらく継続」
        with self._lat_lock:
            can_recover = all(
                (cfg and self._lat_ok_streak[name] >= cfg[3])  # cool_needed
                for name, cfg in self._lat_cfg.items()
            )
            # p95 が low 未満であることも追加チェック（安定性向上）
            if can_recover:
                for name, cfg in self._lat_cfg.items():
                    buf = list(self._lat_buf[name])
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
                for k in list(self._lat_ok_streak.keys()):
                    self._lat_ok_streak[k] = 0

    # ---- メインスレッドで実行される実処理 ----
    @QtCore.Slot(int)
    def _on_delta_requested(self, delta: int):
        current = self.pool.maxThreadCount()
        if delta == 0:
            return

        # ★半減要求の処理
        if delta == self._HALVE_CODE:
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
main_thread = AdaptiveThreadPool()
