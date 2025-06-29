from PySide6 import QtWidgets, QtCore
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import os
from ..profiling import init_env
from .event_batcher import extensions

logger, profiler = init_env()

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
                        extensions=extensions,
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

