import os
import queue
import threading
import time
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from ..common.funcs import IMAGE_EXTENSIONS
from ..common.profiling import logger, profiler
from ..common.signal import Signal
from .progress_notifier import ProgressAggregator
extensions = set(IMAGE_EXTENSIONS)

def throttle(throttle_ms=100, idle_ms=200):

    def decorator(func):
        last_call = [0.0]
        timer = [None]
        lock = threading.Lock()

        def wrapper(*args, **kwargs):
            now = time.time() * 1000
            with lock:
                if now - last_call[0] >= throttle_ms:
                    last_call[0] = now
                    func(*args, **kwargs)
                if timer[0]:
                    timer[0].cancel()

                def call_later():
                    func(*args, **kwargs)
                timer[0] = threading.Timer(idle_ms / 1000.0, call_later)
                timer[0].daemon = True
                timer[0].start()
        return wrapper
    return decorator

class DBWorker:

    def __init__(self, database, progress_callback):
        self.db = database
        self.progress_callback = progress_callback
        self.finished = Signal()
        self._queue = queue.Queue()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        while not self._stop.is_set():
            try:
                task, data = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                if task == 'update':
                    self._update(data)
                elif task == 'remove':
                    self._remove(data)
                elif task == 'rescan':
                    self._rescan(data)
                elif task == 'ignore':
                    self._ignore(data)
                elif task == 'cleanup':
                    self._cleanup()
            finally:
                self.finished.emit()
                self._queue.task_done()

    def trigger_update(self, paths):
        self._queue.put(('update', paths))

    def trigger_remove(self, paths):
        self._queue.put(('remove', paths))

    def trigger_rescan(self, roots):
        self._queue.put(('rescan', roots))

    def trigger_ignore(self, paths):
        self._queue.put(('ignore', paths))

    def trigger_cleanup(self):
        self._queue.put(('cleanup', None))

    def _update(self, paths):
        self.progress_callback(0, len(paths))
        with self.db as indexer:
            indexer.update_by_file_list(paths)
        self.progress_callback(len(paths), 0)

    def _remove(self, paths):
        self.progress_callback(0, len(paths))
        with self.db as indexer:
            indexer.remove_by_file_list(paths)
        self.progress_callback(len(paths), 0)

    def _rescan(self, roots):
        with self.db as indexer:
            indexer.update_index(roots)

    def _cleanup(self):
        with self.db as indexer:
            indexer.clean_unused()

    def _ignore(self, paths):
        with self.db as indexer:
            indexer.set_exclude_paths(paths, run=True)

    def stop(self):
        self._stop.set()
        self._queue.put((None, None))
        self._thread.join()

class FileChangeEmitter(FileSystemEventHandler):

    def __init__(self, extensions):
        self.extensions = extensions
        self.file_deleted = Signal()
        self.file_changed = Signal()
        self.folder_changed = Signal()

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

class WatchFolder:

    def __init__(self, name, database):
        self.folder_changed = Signal()
        self._progress_aggregator = ProgressAggregator(name)
        self.name = name
        self.db = database
        self.db.set_progress_callback(self.progress_callback)
        self.db.set_update_callback(self.update_callback)
        self.observer = None
        self.old_observers = []
        self.db_worker = DBWorker(database, self.progress_callback)
        self.db_worker.finished.connect(self._on_db_finished)
        self._processing = False
        self.deleted_set = set()
        self.changed_set = set()
        self._timer_stop = threading.Event()
        self._timer_thread = threading.Thread(target=self._timer_loop, daemon=True)
        self._timer_thread.start()
        self.emitter = FileChangeEmitter(extensions)
        self.emitter.file_deleted.connect(self._on_deleted)
        self.emitter.file_changed.connect(self._on_changed)
        self.emitter.folder_changed.connect(self._on_folder_change)

    @profiler.profile
    def progress_callback(self, current, total):
        self._progress_aggregator.add(current, total)

    @profiler.profile
    def update_callback(self, message='update_done'):
        logger.debug(f'Update: {message}')
        self._progress_aggregator.notify_extra('update', message)

    @profiler.profile
    @throttle(1000, 2000)
    def folderchange_callback(self, folder):
        logger.debug(f'folder changed: {folder}')
        self._progress_aggregator.notify_extra('folderchanged', '')

    @profiler.profile
    def start(self, folders):
        if self.observer:
            try:
                if self.observer.is_alive():
                    self.observer.stop()
                    self.observer.join()
                self.old_observers.append(self.observer)
            except Exception as e:
                logger.warning(f'Failed to stop old observer: {e}')
        self.observer = Observer()
        for path in folders:
            if os.path.exists(path):
                self.observer.schedule(self.emitter, path, recursive=True)
        self.observer.start()
        self.folders = folders
        self.rescan_all()
        self._cleanup_old_observers()

    def _cleanup_old_observers(self):
        alive = [ob for ob in self.old_observers if ob.is_alive()]
        self.old_observers = alive

    def _on_deleted(self, path):
        self.deleted_set.add(path)
        self.progress_callback(0, 1)

    def _on_changed(self, path):
        self.changed_set.add(path)
        self.progress_callback(0, 1)

    def _on_folder_change(self, path):
        self.folderchange_callback(path)
        self.folder_changed.emit(path)

    def _on_db_finished(self):
        self._processing = False
        self.progress_callback(1, 0)
        self._flush()

    @profiler.profile
    def _flush(self):
        if self._processing:
            return
        if self.deleted_set:
            self._processing = True
            self.progress_callback(1, 2)
            self.db_worker.trigger_remove(list(self.deleted_set))
            self.deleted_set.clear()
            return
        if self.changed_set:
            self._processing = True
            self.progress_callback(1, 2)
            self.db_worker.trigger_update(list(self.changed_set))
            self.changed_set.clear()
            return

    def _timer_loop(self):
        while not self._timer_stop.is_set():
            time.sleep(1)
            self._flush()

    def rescan_all(self):
        if hasattr(self, 'folders'):
            self.db_worker.trigger_rescan(self.folders)

    def set_ignore(self, paths):
        self.db_worker.trigger_ignore(paths)

    def clean(self):
        pass

    def cancel(self):
        pass

    def stop(self):
        logger.debug('Stopping WatchFolder')
        if self.observer:
            self.observer.stop()
            self.observer.join()
        self._timer_stop.set()
        self._timer_thread.join()
        self.db_worker.stop()
