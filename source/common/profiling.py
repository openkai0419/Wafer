import glob
import logging
import logging.handlers
import os
import re
import sys
import threading
import time
from collections import defaultdict
from functools import wraps

import psutil
from PySide6 import QtWidgets

from .funcs import data_path

# Global logger and profiler accessed by other modules
logger = None
profiler = None
_initialized = False

LOG_PATH = data_path("log")

def is_pid_active(pid):
    return psutil.pid_exists(pid)

def cleanup_old_logs_safe(log_dir=LOG_PATH, keep_latest=10):
    try:
        log_files = sorted(
            glob.glob(os.path.join(log_dir, "debuglog_*.log*")),
            key=os.path.getmtime,
            reverse=True
        )

        deleted = 0
        primary_files = [f for f in log_files if re.match(r".*\\.log$", f)]

        for f in log_files:
            base = re.sub(r"\\.log(?:\\.\\d+)?$", ".log", f)
            if base not in primary_files[:keep_latest]:
                match = re.search(r"debuglog_(\\d+).log", base)
                if match:
                    pid = int(match.group(1))
                    if is_pid_active(pid):
                        continue  # skip active process logs
                try:
                    os.remove(f)
                    deleted += 1
                except Exception as e:
                    print(f"Failed to delete {f}: {e}")
        return deleted
    except:
        pass
    
class LoggerManager:
    _instance = None

    @classmethod
    def get_logger(cls) -> logging.Logger:
        if cls._instance is not None:
            return cls._instance

        process_id = os.getpid()
        log_id = str(process_id)

        log_dir = LOG_PATH
        os.makedirs(log_dir, exist_ok=True)
        log_filename = os.path.join(log_dir, f'debuglog_{log_id}.log')

        logger = logging.getLogger(f"Profiler-{log_id}")
        logger.setLevel(logging.DEBUG)

        if not logger.hasHandlers():
            file_handler = logging.handlers.RotatingFileHandler(
                log_filename,
                maxBytes=100_000,
                backupCount=5,
                encoding="utf-8",
                delay=True,
            )
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))

            stream_handler = logging.StreamHandler()
            stream_handler.setLevel(logging.DEBUG)
            stream_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))

            logger.addHandler(file_handler)
            logger.addHandler(stream_handler)

        cls._instance = logger
        return logger

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
        self.data = defaultdict(lambda: {"total_time": 0.0, "self_time": 0.0, "count": 0})
        self._stop_event = threading.Event()
        self.local = threading.local()
        # protects access to self.data
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self._report_loop, daemon=True)
        self.thread.start()
        self.enabled = True
        self.logger = LoggerManager.get_logger()
        self._initialized = True

    def profile(self, func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not self.enabled:
                return func(*args, **kwargs)

            if not hasattr(self.local, 'stack'):
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
                self.report()


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

        self.logger.debug("[Profiler] Function self-time breakdown:")
        for name, self_time, count, ratio in summary:
            self.logger.debug(f"  {name:<30} : {self_time:.3f}s ({ratio:.1%}) - {count} calls")

    def stop(self):
        self._stop_event.set()
        self.thread.join()

    def set_enabled(self, value: bool):
        self.enabled = value

def create_exception_hook(logger):
    def exception_hook(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return

        logger.critical("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))

        try:
            if QtWidgets.QApplication.instance():
                QtWidgets.QMessageBox.critical(
                    None,
                    "Unexpected Error",
                    "An unexpected error occurred. Please check the log file."
                )
        except:
            pass

        sys.exit(1)
    return exception_hook

def initialize_profiling(interval: int = 5):
    """Initialize global logger and profiler."""
    global logger, profiler, _initialized

    if _initialized:
        return logger, profiler

    logger = LoggerManager.get_logger()
    sys.excepthook = create_exception_hook(logger)

    profiler = FunctionProfiler(interval=interval)
    if logger.level != logging.DEBUG:
        profiler.set_enabled(False)

    cleanup_old_logs_safe(keep_latest=0)
    _initialized = True
    return logger, profiler

# Backward compatible name
def init_env(interval: int = 5):
    return initialize_profiling(interval)

logger, profiler = initialize_profiling()

if __name__ == "__main__":
    logger, profiler = initialize_profiling()
