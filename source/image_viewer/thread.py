import psutil
import multiprocessing
from enum import Enum
from PySide6 import QtWidgets, QtGui, QtCore

from ..profiling import init_env
logger, profiler = init_env("viewer")

class AdaptiveThreadPool:
    def __init__(self, base_limit= -2, max_limit= -2, cpu_threshold=65):
        super().__init__()
        self.pool = QtCore.QThreadPool.globalInstance()
        cpu_count = (multiprocessing.cpu_count())
        max_limit = max(1, cpu_count + max_limit)
        base_limit = max(1, max_limit + base_limit)
        self.base_limit =  base_limit
        self.max_limit = max_limit
        self.cpu_threshold = cpu_threshold
        self.pool.setMaxThreadCount(base_limit)

    def watch_start(self):
        self.monitor = QtCore.QTimer()
        self.monitor.timeout.connect(self.adjust_thread_count)
        self.monitor.setInterval(1000)
        self.monitor.start()

    def start(self, obj, *args, **kwargs):
        self.pool.start(obj, *args, **kwargs)

    @profiler.profile
    def adjust_thread_count(self):
        cpu_usage = psutil.cpu_percent()
        current = self.pool.maxThreadCount()
        if cpu_usage < self.cpu_threshold and current < self.max_limit:
            new_count = max(1, current + 1)
            self.pool.setMaxThreadCount(new_count)
            logger.debug(f"[ThreadPool] Increased maxThreadCount: {current} -> {new_count}")
        elif cpu_usage > self.cpu_threshold and current > self.base_limit:
            new_count = max(1, current - 1)
            self.pool.setMaxThreadCount(new_count)
            logger.debug(f"[ThreadPool] Decreased maxThreadCount: {current} -> {new_count}")
        

main_thread = AdaptiveThreadPool()