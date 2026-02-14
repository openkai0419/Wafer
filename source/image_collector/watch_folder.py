import os
import queue
import threading
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from ..common.funcs import IMAGE_EXTENSIONS
from ..common.profiling import logger, profiler
from .progress_notifier import ProgressAggregator

_EXTENSIONS = set(IMAGE_EXTENSIONS)
DISABLE_MODIFY_EVENT = False
_BATCH_TIMEOUT = 0.5


class _FileEmitter(FileSystemEventHandler):

    def __init__(self, inbox):
        self._inbox = inbox

    def _ext_ok(self, path):
        return os.path.splitext(path)[1].lower() in _EXTENSIONS

    def on_created(self, event):
        if event.is_directory:
            self._inbox.put(('folder', event.src_path))
        elif self._ext_ok(event.src_path):
            self._inbox.put(('changed', event.src_path))

    def on_modified(self, event):
        if DISABLE_MODIFY_EVENT or event.is_directory:
            return
        if self._ext_ok(event.src_path):
            self._inbox.put(('changed', event.src_path))

    def on_deleted(self, event):
        if event.is_directory:
            self._inbox.put(('folder', event.src_path))
        elif self._ext_ok(event.src_path):
            self._inbox.put(('deleted', event.src_path))

    def on_moved(self, event):
        if event.is_directory:
            self._inbox.put(('folder', event.dest_path))
        else:
            if self._ext_ok(event.src_path):
                self._inbox.put(('deleted', event.src_path))
            if self._ext_ok(event.dest_path):
                self._inbox.put(('changed', event.dest_path))


class WatchFolder:

    def __init__(self, name, database, node=None):
        self._progress = ProgressAggregator(name, node)
        self._db = database
        self._db.set_progress_callback(self._progress.add)
        self._db.set_update_callback(lambda: self._progress.notify('update'))
        self._q = queue.Queue()
        self._emitter = _FileEmitter(self._q)
        self._observer = None
        self._folders = []
        self._stop = threading.Event()
        self._worker = threading.Thread(target=self._loop, daemon=True)
        self._worker.start()

    def start(self, folders):
        self._stop_observer()
        self._observer = Observer()
        for path in folders:
            if os.path.exists(path):
                self._observer.schedule(self._emitter, path, recursive=True)
        self._observer.start()
        self._folders = folders
        self.rescan_all()

    def rescan_all(self):
        if self._folders:
            self._q.put(('rescan', self._folders))

    def set_ignore(self, paths):
        self._q.put(('ignore', paths))

    def clean(self):
        self._q.put(('cleanup', None))

    def stop(self):
        self._stop.set()
        self._q.put(('__stop__', None))
        self._stop_observer()
        self._worker.join(timeout=5.0)

    def _stop_observer(self):
        if self._observer:
            try:
                self._observer.stop()
                self._observer.join()
            except Exception as e:
                logger.debug(f'observer stop: {e}')
            self._observer = None

    def _loop(self):
        changed = set()
        deleted = set()
        folder_dirty = False
        while not self._stop.is_set():
            try:
                item = self._q.get(timeout=_BATCH_TIMEOUT)
            except queue.Empty:
                folder_dirty = self._flush(changed, deleted, folder_dirty)
                continue
            batch = [item]
            while True:
                try:
                    batch.append(self._q.get_nowait())
                except queue.Empty:
                    break
            for kind, data in batch:
                if kind == 'changed':
                    changed.add(data)
                elif kind == 'deleted':
                    deleted.add(data)
                elif kind == 'folder':
                    folder_dirty = True
                elif kind in ('rescan', 'ignore', 'cleanup'):
                    folder_dirty = self._flush(changed, deleted, folder_dirty)
                    self._exec(kind, data)
                elif kind == '__stop__':
                    return

    def _flush(self, changed, deleted, folder_dirty):
        if deleted:
            self._exec('remove', list(deleted))
            deleted.clear()
        if changed:
            self._exec('update', list(changed))
            changed.clear()
        if folder_dirty:
            self._progress.notify('folderchanged')
        return False

    @profiler.profile
    def _exec(self, cmd, data=None):
        try:
            with self._db as indexer:
                if cmd == 'update':
                    self._progress.add(0, len(data))
                    indexer.update_by_file_list(data)
                elif cmd == 'remove':
                    self._progress.add(0, len(data))
                    indexer.remove_by_file_list(data)
                elif cmd == 'rescan':
                    indexer.update_index(data)
                elif cmd == 'cleanup':
                    self._progress.add(0, 1)
                    indexer.clean_unused()
                    self._progress.add(1, 0)
                elif cmd == 'ignore':
                    indexer.set_exclude_paths(data, run=True)
        except Exception:
            logger.exception(f'db exec {cmd} failed')
