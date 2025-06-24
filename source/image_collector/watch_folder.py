from PySide6 import QtWidgets, QtGui, QtCore
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import os
import threading
import atexit
from pathlib import Path

from ..core.collector import ImageIndexer
from ..core.zmq import ZMQPublisher
from ..profiling import init_env
from ..constants import data_db

logger, profiler = init_env()
extensions = (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp")

_publisher = None
_publisher_lock = threading.Lock()

@profiler.profile
def _get_publisher() -> ZMQPublisher:
    global _publisher
    with _publisher_lock:
        if _publisher is None:
            _publisher = ZMQPublisher()
        return _publisher

@profiler.profile
def _notify_maximum_inc(count=1):
    try:
        _progress_aggregator.add(0, count)
    except Exception as e:
        logger.warning(f"通知失敗: {e}")

class ProgressAggregator:
    def __init__(self):
        self.current = 0
        self.maximum = 0

    def reset(self):
        self.current = 0
        self.maximum = 0
        self._notify()

    @profiler.profile
    def add(self, current_inc=0, total_inc=0):
        if total_inc:
            self.maximum += total_inc
        if current_inc:
            self.current += current_inc
        self._notify()
        if self.maximum and self.current >= self.maximum:
            pass
            #self.reset()

    @profiler.profile
    def _notify(self):
        try:
            publisher = _get_publisher()
            publisher.send("maximum", str(self.maximum))
            publisher.send("progress", str(self.current))
        except Exception as e:
            logger.warning(f"通知失敗: {e}")

_progress_aggregator = ProgressAggregator()

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
            _notify_maximum_inc(1)

    def add_changed(self, path):
        if path not in self._changed:
            self._changed.add(path)
            _notify_maximum_inc(1)

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


class FileChangeHandler(FileSystemEventHandler):
    def __init__(self, folder_path, on_deleted_func=None, on_changed_func=None, on_folder_changed=None, extensions=None):
        super().__init__()
        self.folder_path = folder_path
        self.on_deleted_func = on_deleted_func
        self.on_changed_func = on_changed_func
        self.on_folder_changed = on_folder_changed
        self.extensions = set(e.lower() for e in (extensions or []))

    @profiler.profile
    def on_moved(self, event):
        if event.is_directory and self.on_folder_changed:
            self.on_folder_changed(event.src_path)
            return
        if self.on_deleted_func:
            self.on_deleted_func(event.src_path)
        if self.on_changed_func:
            self.on_changed_func(event.dest_path)

    @profiler.profile
    def on_modified(self, event):
        if event.is_directory and self.on_folder_changed:
            self.on_folder_changed(event.src_path)
            return
        if self.on_changed_func:
            self.on_changed_func(event.src_path)

    @profiler.profile
    def on_created(self, event):
        if event.is_directory and self.on_folder_changed:
            self.on_folder_changed(event.src_path)
            return
        if self.on_changed_func:
            self.on_changed_func(event.src_path)

    @profiler.profile
    def on_deleted(self, event):
        if event.is_directory and self.on_folder_changed:
            self.on_folder_changed(event.src_path)
            return
        if self.on_deleted_func:
            self.on_deleted_func(event.src_path)


class FolderWatcherThread(QtCore.QThread):
    file_deleted = QtCore.Signal(str)
    file_changed = QtCore.Signal(str)
    folder_changed = QtCore.Signal(str)

    def __init__(self, paths_to_watch):
        super().__init__()
        self.paths_to_watch = paths_to_watch
        self.observer = None
        self.running = True

    @profiler.profile
    def run(self):
        print("[DEBUG] FolderWatcherThread.run() started")
        try:
            self.observer = Observer()
            for path in self.paths_to_watch:
                if os.path.exists(path):
                    handler = FileChangeHandler(
                        path,
                        on_deleted_func=self._on_file_deleted,
                        on_changed_func=self._on_changed_func,
                        on_folder_changed=self._on_folder_changed,
                        extensions=extensions
                    )
                    self.observer.schedule(handler, path, recursive=True)
                else:
                    print(f"[WARNING] Path does not exist: {path}")
                    QtWidgets.QMessageBox.warning(None, "監視対象エラー", f"存在しないパス: {path}")

            self.observer.start()
            while self.running:
                self.msleep(1000)

        except Exception as e:
            print(f"[ERROR] Exception in FolderWatcherThread.run: {e}")
        finally:
            if self.observer:
                self.observer.stop()
                self.observer.join()

    @profiler.profile
    def _on_file_deleted(self, path):
        self.file_deleted.emit(path)

    @profiler.profile
    def _on_changed_func(self, path):
        self.file_changed.emit(path)

    @profiler.profile
    def _on_folder_changed(self, path):
        self.folder_changed.emit(path)

    @profiler.profile
    def stop(self):
        self.running = False
        if self.observer and self.observer.is_alive():
            print("[DEBUG] Stopping observer")
            self.observer.stop()
            self.observer.join()

class DBWorker(QtCore.QObject):
    finished = QtCore.Signal()
    def __init__(self, database,*args, **kwargs):
        super().__init__(*args, **kwargs)
        self.database = database

    @QtCore.Slot(list)
    def update_files(self, paths):
        with self.database as indexer:
            indexer.update_by_file_list(paths)
        self.finished.emit()

    @QtCore.Slot(list)
    def remove_files(self, paths):
        with self.database as indexer:
            indexer.remove_by_file_list(paths)
        self.finished.emit()

    @QtCore.Slot(list)
    def rescan_all(self, root_paths):
        with self.database as indexer:
            indexer.update_index(root_paths)

@profiler.profile
def filechange_callback(folder):
    logger.info(f"folder changed: {folder}")
    try:
        publisher = _get_publisher()
        publisher.send("folderchanged", str(folder))
    except Exception as e:
        logger.warning(f"通知失敗: {e}")
    
@profiler.profile
def progress_callback(current_inc, total_inc):
    try:
        _progress_aggregator.add(current_inc, total_inc)
    except Exception as e:
        logger.warning(f"通知失敗: {e}")

@profiler.profile
def notify_gui_process(message: str = "update_done"):
    logger.info(f"Update: {message}")
    try:
        publisher = _get_publisher()
        publisher.send("update", message)
    except Exception as e:
        logger.warning(f"通知失敗: {e}")

class WatchFolder:
    @profiler.profile
    def __init__(self):
        super().__init__()

        self.watcher_thread = None

        self.database = ImageIndexer(data_db)
        self.database.set_progress_callback(progress_callback)
        self.database.set_update_callback(notify_gui_process)

        self.event_batcher = EventBatcher(100)
        self.db_thread = QtCore.QThread()
        self.db_worker = DBWorker(self.database)
        self.db_worker.moveToThread(self.db_thread)
        self.db_thread.start()

        self.event_batcher.batched_deleted.connect(self.db_worker.remove_files)
        self.event_batcher.batched_changed.connect(self.db_worker.update_files)
        self.event_batcher.folder_changed.connect(filechange_callback)
        self.db_worker.finished.connect(self.event_batcher.on_db_finished)

    @profiler.profile
    def rescan_all(self, paths):
        self.db_worker.rescan_all(paths)

    @profiler.profile
    def start(self, folders):
        if self.watcher_thread:
            self.watcher_thread.stop()
            self.watcher_thread.wait()

        self.watcher_thread = FolderWatcherThread(folders)
        self.watcher_thread.file_deleted.connect(self.event_batcher.add_deleted)
        self.watcher_thread.file_changed.connect(self.event_batcher.add_changed)
        self.watcher_thread.folder_changed.connect(self.event_batcher.path_changed)
        self.watcher_thread.start()
        atexit.register(self.quit)

        self.rescan_all(folders)

    @profiler.profile
    def quit(self):
        logger.info("Quitting TrayApp")
        if self.watcher_thread:
            self.watcher_thread.stop()
            self.watcher_thread.wait()
        if self.db_thread:
            self.db_thread.quit()
            self.db_thread.wait()
        with self.database as indexer:
            indexer.clean_unused()

