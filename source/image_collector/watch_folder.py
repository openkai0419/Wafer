from PySide6 import QtWidgets, QtGui, QtCore
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import os

from .progress_notifier import _progress_aggregator
from ..debounce import qt_debounce

from ..profiling import logger, profiler
extensions = (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp")

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
            progress_callback(0,1)

    def add_changed(self, path):
        if path not in self._changed:
            self._changed.add(path)
            progress_callback(0,1)

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

    def run(self):
        logger.debug("[DEBUG] FolderWatcherThread.run() started")
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
                    logger.warning(f"[WARNING] Path does not exist: {path}")
                    QtWidgets.QMessageBox.warning(None, "監視対象エラー", f"存在しないパス: {path}")

            self.observer.start()
            while self.running:
                self.msleep(1000)

        except Exception as e:
            logger.error(f"[ERROR] Exception in FolderWatcherThread.run: {e}")
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
            logger.debug("[DEBUG] Stopping observer")
            self.observer.stop()
            self.observer.join()

class DBWorker(QtCore.QObject):
    finished = QtCore.Signal()
    trigger_ignore = QtCore.Signal(object)
    trigger_rescan = QtCore.Signal(object)

    def __init__(self, database,*args, **kwargs):
        super().__init__(*args, **kwargs)
        self.trigger_ignore.connect(self.set_ignore)
        self.trigger_rescan.connect(self.rescan_all)
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
        logger.debug(f"スキャン開始: {root_paths}")
        with self.database as indexer:
            indexer.update_index(root_paths)
    
    @QtCore.Slot(list)
    def set_ignore(self, paths):
        logger.debug(f"無視対象を追加: {paths}")
        with self.database as indexer:
            indexer.set_exclude_paths(paths, run=True)


class WatchFolder:
    @profiler.profile
    def __init__(self, database):
        super().__init__()

        self.watcher_thread = None
        self.old_threads = []
        self.folders = None
        self.ignore_folders = None

        self.database = database
        self.database.set_progress_callback(progress_callback)
        self.database.set_update_callback(update_callback)

        self.db_thread = QtCore.QThread()
        self.db_worker = DBWorker(self.database)
        self.db_worker.moveToThread(self.db_thread)
        self.db_thread.start()
        self.event_batcher = EventBatcher(100)

        self.event_batcher.batched_deleted.connect(self.db_worker.remove_files)
        self.event_batcher.batched_changed.connect(self.db_worker.update_files)
        self.event_batcher.folder_changed.connect(filechange_callback)
        self.db_worker.finished.connect(self.event_batcher.on_db_finished)

        logger.debug("WatchFolder init end")

    @profiler.profile
    @qt_debounce(200)
    def rescan_all(self):
        if not self.folders:
            return
        self.db_worker.trigger_rescan.emit(self.folders)

    def set_ignore_folders(self, folders):
        self.ignore_folders = folders
        self.run_ignore_folders()

    @qt_debounce(200)
    def run_ignore_folders(self):
        if not self.ignore_folders:
            return
        self.db_worker.trigger_ignore.emit(self.ignore_folders)

    @profiler.profile
    def start(self, folders):
        if not folders:
            return
        if self.watcher_thread:
            self.watcher_thread.stop()
            self.old_threads.append(self.watcher_thread)

        self.watcher_thread = FolderWatcherThread(folders)
        self.watcher_thread.file_deleted.connect(self.event_batcher.add_deleted)
        self.watcher_thread.file_changed.connect(self.event_batcher.add_changed)
        self.watcher_thread.folder_changed.connect(self.event_batcher.path_changed)
        self.watcher_thread.start()

        self.folders = folders
        self.rescan_all()
        logger.debug("[FatchFOlder] ディレクトリ監視開始")
        self.delete_if_ended()

    def delete_if_ended(self):
        deleatings = []
        for thread in self.old_threads:
            if thread.isFinished():
                deleatings.append(thread)
        self.old_threads = [d for d in self.old_threads if not d in deleatings]


    def quit(self):
        logger.debug("Quitting TrayApp")
        if self.watcher_thread:
            self.watcher_thread.stop()
            #self.watcher_thread.wait()
        if self.db_thread:
            self.db_thread.quit()
            #self.db_thread.wait()
        with self.database as indexer:
            indexer.clean_unused()

