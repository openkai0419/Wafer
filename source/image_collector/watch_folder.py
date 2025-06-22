from PySide6 import QtWidgets, QtGui, QtCore
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import os
import threading
from pathlib import Path

from ..core.collector import ImageIndexer
from ..core.zmq import ZMQPublisher
from ..profiling import init_env
from ..constants import data_db

logger, profiler = init_env()
extensions = (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp")

_publisher = None
_publisher_lock = threading.Lock()

def _get_publisher() -> ZMQPublisher:
    global _publisher
    with _publisher_lock:
        if _publisher is None:
            _publisher = ZMQPublisher()
        return _publisher

class EventBatcher(QtCore.QObject):
    batched_deleted = QtCore.Signal(list)
    batched_changed = QtCore.Signal(list)
    folder_changed = QtCore.Signal()

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
        self._deleted.add(path)

    def add_changed(self, path):
        self._changed.add(path)

    def path_changed(self, path):
        self._pathchanged = True

    def flush(self):
        if self._processing:
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
        if self._pathchanged:
            self.folder_changed.emit()
            self._pathchanged = False

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

    def on_moved(self, event):
        if event.is_directory:
            self.on_folder_changed(event.src_path)
            return
        if self.on_deleted_func:
            self.on_deleted_func(event.src_path)
        if self.on_changed_func:
            self.on_changed_func(event.dest_path)

    def on_modified(self, event):
        if event.is_directory:
            self.on_folder_changed(event.src_path)
            return
        if self.on_changed_func:
            self.on_changed_func(event.src_path)

    def on_created(self, event):
        if event.is_directory:
            self.on_folder_changed(event.src_path)
            return
        if self.on_changed_func:
            self.on_changed_func(event.src_path)

    def on_deleted(self, event):
        if event.is_directory:
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

    def _on_file_deleted(self, path):
        self.file_deleted.emit(path)

    def _on_changed_func(self, path):
        self.file_changed.emit(path)

    def _on_folder_changed(self, path):
        self.folder_changed.emit(path)

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

def progress_callback(current, total):
    logger.info(f"Progress: {current}/{total} ({100 * current // total}%)")
    try:
        publisher = _get_publisher()
        if current == 0:
            publisher.send("maximum", str(total))
        publisher.send("progress", str(current))
    except Exception as e:
        logger.warning(f"通知失敗: {e}")

def notify_gui_process(message: str = "update_done"):
    logger.info(f"Update: {message}")
    try:
        publisher = _get_publisher()
        publisher.send("update", message)
    except Exception as e:
        logger.warning(f"通知失敗: {e}")

class WatchFolder:
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
        self.db_worker.finished.connect(self.event_batcher.on_db_finished)

    def rescan_all(self, paths):
        self.db_worker.rescan_all(paths)

    def start(self, folders):
        if self.watcher_thread:
            self.watcher_thread.stop()
            self.watcher_thread.wait()

        self.watcher_thread = FolderWatcherThread(folders)
        self.watcher_thread.file_deleted.connect(self.event_batcher.add_deleted)
        self.watcher_thread.file_changed.connect(self.event_batcher.add_changed)
        self.watcher_thread.folder_changed.connect(self.event_batcher.path_changed)
        self.watcher_thread.start()

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

