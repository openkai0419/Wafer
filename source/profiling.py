import logging.handlers
import time
import threading
import logging
import os
from collections import defaultdict
from functools import wraps

import sys
from PySide6 import QtWidgets

def setup_logger(identifier: str = None) -> logging.Logger:
    import os

    process_id = os.getpid()
    log_id = identifier or str(process_id)

    log_dir = "log"
    os.makedirs(log_dir, exist_ok=True)  # フォルダがなければ作成
    log_filename = os.path.join(log_dir, f'debuglog_{log_id}.log')

    logger = logging.getLogger(f"Profiler-{log_id}")
    logger.setLevel(logging.DEBUG)

    if not logger.hasHandlers():
        # 1MBでローテーション、最大5ファイル保持
        file_handler = logging.handlers.RotatingFileHandler(log_filename,
                                                            maxBytes=100_000,
                                                            backupCount=2, 
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

    return logger

class FunctionProfiler:
    def __init__(self, interval=10, logger_instance=None):
        self.interval = interval
        self.lock = threading.Lock()
        self.data = defaultdict(lambda: {"total_time": 0.0, "self_time": 0.0, "count": 0})
        self._stop_event = threading.Event()
        self.thread = threading.Thread(target=self._report_loop, daemon=True)
        self.thread.start()
        self.local = threading.local()
        self.enabled = True  # プロファイリングの有効/無効フラグ
        self.logger = logger_instance or setup_logger()

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
                self.logger.debug("[Profiler] No activity recorded.")
            summary = []
            for name, info in self.data.items():
                self_time = info["self_time"]
                count = info["count"]
                summary.append((name, self_time, count, self_time / total_self_time))
            summary.sort(key=lambda x: -x[3])
            summary = summary[:5]  # 上位5件のみ表示

            self.logger.info("[Profiler] Function self-time breakdown:")
            for name, self_time, count, ratio in summary:
                self.logger.info(f"  {name:<30} : {self_time:.3f}s ({ratio:.1%}) - {count} calls")

            self.data.clear()

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


def init_env(env_name: str = None, interval: int = 5):
    """
    環境識別子を指定して、ロガーとプロファイラーを初期化する
    """
    logger = setup_logger(env_name)
    sys.excepthook = create_exception_hook(logger)

    profiler = FunctionProfiler(interval=interval, logger_instance=logger)
    if logger.level != logging.DEBUG:
        profiler.set_enabled(False)

    return logger, profiler

# 利用例（__main__チェック）
if __name__ == "__main__":
    logger, profiler = init_env("main")
    # 以降ここで profile 使用可
