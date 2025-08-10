from PySide6 import QtCore
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import os

from ..common.profiling import logger, profiler
from ..common.funcs import IMAGE_EXTENSIONS
from ..qt.debounce import qt_debounce
from ..qt.progress_notifier import ProgressAggregator

extensions = set(IMAGE_EXTENSIONS)

# プログレス管理
_progress_aggregator = ProgressAggregator("*")

@profiler.profile
def progress_callback(current, total):
    _progress_aggregator.add(current, total)

@profiler.profile
def update_callback(message="update_done"):
    logger.debug(f"Update: {message}")
    _progress_aggregator.notify_extra("update", message)

@profiler.profile
def folderchange_callback(folder):
    logger.debug(f"folder changed: {folder}")
    _progress_aggregator.notify_extra("folderchanged", "")


class DBWorker(QtCore.QObject):
    finished = QtCore.Signal()
    trigger_update = QtCore.Signal(list)
    trigger_remove = QtCore.Signal(list)
    trigger_rescan = QtCore.Signal(list)
    trigger_ignore = QtCore.Signal(list)

    def __init__(self, database):
        super().__init__()
        self.db = database

        self.trigger_update.connect(self.update)
        self.trigger_remove.connect(self.remove)
        self.trigger_rescan.connect(self.rescan)
        self.trigger_ignore.connect(self.ignore)

    @QtCore.Slot(list)
    @profiler.profile
    def update(self, paths):
        progress_callback(0, len(paths))
        with self.db as indexer:
            indexer.update_by_file_list(paths)
        progress_callback(len(paths), 0)
        self.finished.emit()

    @QtCore.Slot(list)
    @profiler.profile
    def remove(self, paths):
        progress_callback(0, len(paths))
        with self.db as indexer:
            indexer.remove_by_file_list(paths)
        progress_callback(len(paths), 0)
        self.finished.emit()

    @QtCore.Slot(list)
    @profiler.profile
    def rescan(self, roots):
        update_callback("full_rescan")
        with self.db as indexer:
            indexer.update_index(roots)

    @QtCore.Slot(list)
    @profiler.profile
    def ignore(self, paths):
        with self.db as indexer:
            indexer.set_exclude_paths(paths, run=True)


class FileChangeEmitter(QtCore.QObject, FileSystemEventHandler):
    file_deleted = QtCore.Signal(str)
    file_changed = QtCore.Signal(str)
    folder_changed = QtCore.Signal(str)

    def __init__(self, extensions):
        super().__init__()
        self.extensions = extensions

    def _should_handle(self, path):
        return os.path.splitext(path)[1].lower() in self.extensions

    def on_created(self, event):
        if event.is_directory:
            self.folder_changed.emit(event.src_path)
        elif self._should_handle(event.src_path):
            self.file_changed.emit(event.src_path)

    def on_modified(self, event):
        if event.is_directory:
            self.folder_changed.emit(event.src_path)
        elif self._should_handle(event.src_path):
            self.file_changed.emit(event.src_path)

    def on_deleted(self, event):
        if event.is_directory:
            self.folder_changed.emit(event.src_path)
        elif self._should_handle(event.src_path):
            self.file_deleted.emit(event.src_path)

    def on_moved(self, event):
        if event.is_directory:
            self.folder_changed.emit(event.dest_path)
        else:
            if self._should_handle(event.src_path):
                self.file_deleted.emit(event.src_path)
            if self._should_handle(event.dest_path):
                self.file_changed.emit(event.dest_path)


class WatchFolder(QtCore.QObject):
    folder_changed = QtCore.Signal(str)

    @profiler.profile
    def __init__(self, name, database):
        super().__init__()

        global _progress_aggregator
        _progress_aggregator = ProgressAggregator(name)

        self.name = name
        self.db = database
        self.db.set_progress_callback(progress_callback)
        self.db.set_update_callback(update_callback)

        self.observer = None
        self.old_observers = []
        self.db_thread = QtCore.QThread()
        self.db_worker = DBWorker(database)
        self.db_worker.moveToThread(self.db_thread)
        self.db_thread.start()

        self._processing = False
        self.deleted_set = set()
        self.changed_set = set()
        self.db_worker.finished.connect(self._on_db_finished)

        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._flush)
        self.timer.start()

        self.emitter = FileChangeEmitter(extensions)
        self.emitter.file_deleted.connect(self._on_deleted)
        self.emitter.file_changed.connect(self._on_changed)
        self.emitter.folder_changed.connect(self._on_folder_change)

    @profiler.profile
    def start(self, folders):
        # 古い observer がまだ止まってなければ保持
        if self.observer:
            try:
                if self.observer.is_alive():
                    self.observer.stop()
                    self.observer.join()
                self.old_observers.append(self.observer)
            except Exception as e:
                logger.warning(f"Failed to stop old observer: {e}")
        self.observer = Observer()
        for path in folders:
            if os.path.exists(path):
                self.observer.schedule(self.emitter, path, recursive=True)
        self.observer.start()
        self.folders = folders
        self.rescan_all()
        self._cleanup_old_observers()

    def _cleanup_old_observers(self):
        # 終了した observer を削除
        alive = []
        for ob in self.old_observers:
            if ob.is_alive():
                alive.append(ob)
        self.old_observers = alive

    @QtCore.Slot(str)
    def _on_deleted(self, path):
        self.deleted_set.add(path)
        progress_callback(0, 1)

    @QtCore.Slot(str)
    def _on_changed(self, path):
        self.changed_set.add(path)
        progress_callback(0, 1)

    @QtCore.Slot(str)
    def _on_folder_change(self, path):
        folderchange_callback(path)
        self.folder_changed.emit(path)
    
    @QtCore.Slot()
    def _on_db_finished(self):
        self._processing = False
        progress_callback(1, 0)  # ← ステップ2完了
        self._flush() 
        
    @profiler.profile
    def _flush(self):
        if hasattr(self, "_processing") and self._processing:
            return

        if self.deleted_set:
            self._processing = True
            progress_callback(1, 2)  # ← ステップ1開始
            self.db_worker.trigger_remove.emit(list(self.deleted_set))
            self.deleted_set.clear()
            return

        if self.changed_set:
            self._processing = True
            progress_callback(1, 2)  # ← ステップ1開始
            self.db_worker.trigger_update.emit(list(self.changed_set))
            self.changed_set.clear()
            return

    @qt_debounce(200)
    def rescan_all(self):
        if hasattr(self, "folders"):
            self.db_worker.trigger_rescan.emit(self.folders)

    def set_ignore(self, paths):
        self.db_worker.trigger_ignore.emit(paths)

    def stop(self, clean=True):
        logger.debug("Stopping WatchFolder")
        self.observer.stop()
        self.observer.join()
        self.timer.stop()
        self.db_thread.quit()
        self.db_thread.wait()
        if clean:
            try:
                with self.db as indexer:
                    indexer.clean_unused()
            except Exception as e:
                logger.warning(f"[quit] cleanup failed: {e}")
