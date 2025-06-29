from PySide6 import QtCore
from .progress_notifier import _progress_aggregator
from ..profiling import init_env
extensions = (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp")

logger, profiler = init_env()

@profiler.profile
def progress_callback(current_inc, total_inc):
    _progress_aggregator.add(current_inc, total_inc)

@profiler.profile
def update_callback(message="update_done"):
    logger.debug(f"Update: {message}")
    _progress_aggregator.notify_extra("update", message)

@profiler.profile
def filechange_callback(folder):
    logger.debug(f"folder changed: {folder}")
    _progress_aggregator.notify_extra("folderchanged", folder)

class EventBatcher(QtCore.QObject):
    batched_deleted = QtCore.Signal(list)
    batched_changed = QtCore.Signal(list)
    folder_changed = QtCore.Signal(str)

    def __init__(self, interval_ms=1000):
        super().__init__()
        self._deleted = set()
        self._changed = set()
        self._pathchanged = False
        self._processing = False
        self._timer = QtCore.QTimer()
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self.flush)
        self._timer.start()

    def add_deleted(self, path):
        if path not in self._deleted:
            self._deleted.add(path)
            progress_callback(0, 1)

    def add_changed(self, path):
        if path not in self._changed:
            self._changed.add(path)
            progress_callback(0, 1)

    def path_changed(self, path):
        self._pathchanged = path

    @profiler.profile
    def flush(self):
        if self._processing:
            return
        if self._pathchanged:
            self.folder_changed.emit(self._pathchanged)
            self._pathchanged = None
            return
        if self._deleted:
            self._processing = True
            self.batched_deleted.emit(list(self._deleted))
            self._deleted.clear()
            return
        if self._changed:
            self._processing = True
            self.batched_changed.emit(list(self._changed))
            self._changed.clear()
            return

    @QtCore.Slot()
    def on_db_finished(self):
        self._processing = False
        self.flush()

