"""File system watcher without Qt dependencies."""

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from ..common.funcs import IMAGE_EXTENSIONS
from ..common.profiling import logger, profiler
from .progress_notifier import ProgressAggregator

extensions = set(IMAGE_EXTENSIONS)


class DBWorker:
    """Run database operations in a background thread."""

    def __init__(self, database, progress_cb):
        self.db = database
        self.progress_cb = progress_cb

    @profiler.profile
    def update(self, paths):
        self.progress_cb(0, len(paths))
        with self.db as indexer:
            indexer.update_by_file_list(paths)
        self.progress_cb(len(paths), 0)

    @profiler.profile
    def remove(self, paths):
        self.progress_cb(0, len(paths))
        with self.db as indexer:
            indexer.remove_by_file_list(paths)
        self.progress_cb(len(paths), 0)

    @profiler.profile
    def rescan(self, roots):
        with self.db as indexer:
            indexer.update_index(roots)

    @profiler.profile
    def cleanup(self):
        with self.db as indexer:
            indexer.clean_unused()

    @profiler.profile
    def ignore(self, paths):
        with self.db as indexer:
            indexer.set_exclude_paths(paths, run=True)


class FileChangeHandler(FileSystemEventHandler):
    """Translate watchdog events into WatchFolder callbacks."""

    def __init__(self, watcher):
        self.watcher = watcher

    def _should_handle(self, path):
        return os.path.splitext(path)[1].lower() in extensions

    def on_created(self, event):
        if event.is_directory:
            self.watcher._on_folder_change(event.src_path)
        elif self._should_handle(event.src_path):
            self.watcher._on_changed(event.src_path)

    def on_modified(self, event):
        if event.is_directory:
            self.watcher._on_folder_change(event.src_path)
        elif self._should_handle(event.src_path):
            self.watcher._on_changed(event.src_path)

    def on_deleted(self, event):
        if event.is_directory:
            self.watcher._on_folder_change(event.src_path)
        elif self._should_handle(event.src_path):
            self.watcher._on_deleted(event.src_path)

    def on_moved(self, event):
        if event.is_directory:
            self.watcher._on_folder_change(event.dest_path)
        else:
            if self._should_handle(event.src_path):
                self.watcher._on_deleted(event.src_path)
            if self._should_handle(event.dest_path):
                self.watcher._on_changed(event.dest_path)


class WatchFolder:
    """Watch folders and update database without Qt."""

    @profiler.profile
    def __init__(self, name, database):
        self.name = name
        self.progress_aggregator = ProgressAggregator(name)
        self.db = database
        self.db.set_progress_callback(self._progress_callback)
        self.db.set_update_callback(self._update_callback)

        self.observer = None
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.db_worker = DBWorker(database, self._progress_callback)

        self._processing = False
        self.deleted_set = set()
        self.changed_set = set()

        self._stop_event = threading.Event()
        self._flush_thread = threading.Thread(
            target=self._periodic_flush, daemon=True
        )
        self._flush_thread.start()

        self.handler = FileChangeHandler(self)

    # ----------- progress callbacks -----------
    def _progress_callback(self, current, total):
        self.progress_aggregator.add(current, total)

    def _update_callback(self, message="update_done"):
        logger.debug(f"Update: {message}")
        self.progress_aggregator.notify_extra("update", message)

    def _folderchange_callback(self, folder):
        logger.debug(f"folder changed: {folder}")
        self.progress_aggregator.notify_extra("folderchanged", "")

    # ----------- event handlers -----------
    def _on_deleted(self, path):
        self.deleted_set.add(path)
        self._progress_callback(0, 1)

    def _on_changed(self, path):
        self.changed_set.add(path)
        self._progress_callback(0, 1)

    def _on_folder_change(self, path):
        self._folderchange_callback(path)

    def _on_db_finished(self, _future=None):
        self._processing = False
        self._progress_callback(1, 0)
        self._flush()

    # ----------- main logic -----------
    @profiler.profile
    def start(self, folders):
        if self.observer:
            self.observer.stop()
            self.observer.join()
        self.observer = Observer()
        for path in folders:
            if os.path.exists(path):
                self.observer.schedule(self.handler, path, recursive=True)
        self.observer.start()
        self.folders = folders
        self.rescan_all()

    def _periodic_flush(self):
        while not self._stop_event.is_set():
            self._flush()
            time.sleep(1)

    @profiler.profile
    def _flush(self):
        if self._processing:
            return
        if self.deleted_set:
            self._processing = True
            paths = list(self.deleted_set)
            self.deleted_set.clear()
            self._progress_callback(1, 2)
            fut = self.executor.submit(self.db_worker.remove, paths)
            fut.add_done_callback(self._on_db_finished)
            return
        if self.changed_set:
            self._processing = True
            paths = list(self.changed_set)
            self.changed_set.clear()
            self._progress_callback(1, 2)
            fut = self.executor.submit(self.db_worker.update, paths)
            fut.add_done_callback(self._on_db_finished)

    def rescan_all(self):
        if hasattr(self, "folders"):
            self.executor.submit(self.db_worker.rescan, self.folders)

    def set_ignore_folders(self, paths):
        self.executor.submit(self.db_worker.ignore, paths)

    def clean(self):
        self.executor.submit(self.db_worker.cleanup)

    def cancel(self):
        pass

    def stop(self):
        logger.debug("Stopping WatchFolder")
        self._stop_event.set()
        if self.observer:
            self.observer.stop()
            self.observer.join()
        self.executor.shutdown(wait=True)
        if self._flush_thread.is_alive():
            self._flush_thread.join()

