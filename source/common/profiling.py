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
        if hasattr(self, '_initialized') and self._initialized:
            return
        self.interval = interval
        self.data = defaultdict(lambda: {'total_time': 0.0, 'self_time': 0.0, 'count': 0})
        self._stop_event = threading.Event()
        self.local = threading.local()
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self._report_loop, daemon=True)
        self.thread.start()
        self.enabled = True
        self._initialized = True

    def profile(self, func):

        @wraps(func)
        def wrapper(*args, **kwargs):
            if not self.enabled:
                return func(*args, **kwargs)
            if not hasattr(self.local, 'stack'):
                self.local.stack = []
            start_time = time.perf_counter()
            self.local.stack.append({'name': func.__qualname__, 'start': start_time, 'children': 0.0})
            try:
                return func(*args, **kwargs)
            finally:
                end_time = time.perf_counter()
                record = self.local.stack.pop()
                duration = end_time - record['start']
                self_time = duration - record['children']
                with self.lock:
                    info = self.data[func.__qualname__]
                    info['total_time'] += duration
                    info['self_time'] += self_time
                    info['count'] += 1
                if self.local.stack:
                    self.local.stack[-1]['children'] += duration
        return wrapper

    def _report_loop(self):
        while not self._stop_event.wait(self.interval):
            if self.enabled:
                self.report()

    def report(self):
        with self.lock:
            total_self_time = sum(info['self_time'] for info in self.data.values())
            if total_self_time == 0:
                return
            summary_data = list(self.data.items())
            self.data.clear()
        summary = []
        for name, info in summary_data:
            self_time = info['self_time']
            count = info['count']
            summary.append((name, self_time, count, self_time / total_self_time))
        summary.sort(key=lambda x: -x[3])
        summary = summary[:5]
        AppLogger.debug('[Profiler] Function self-time breakdown:')
        for name, self_time, count, ratio in summary:
            AppLogger.debug(f'  {name:<30} : {self_time:.3f}s ({ratio:.1%}) - {count} calls')

    def stop(self):
        self._stop_event.set()
        self.thread.join()

    def set_enabled(self, value):
        self.enabled = value


profiler = FunctionProfiler(interval=5)
