import os
import queue
import threading
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from source.utils.profiling import profiler
from source.utils.logs import AppLogger
from .progress_notifier import ProgressAggregator

DISABLE_MODIFY_EVENT = False
_BATCH_TIMEOUT = 0.5


class _FileEventHandler(FileSystemEventHandler):

    def __init__(self, inbox):
        self._inbox = inbox

    def on_created(self, event):
        if event.is_directory:
            self._inbox.put(('folder', event.src_path))
        else:
            self._inbox.put(('changed', event.src_path))

    def on_modified(self, event):
        if DISABLE_MODIFY_EVENT or event.is_directory:
            return
        self._inbox.put(('changed', event.src_path))

    def on_deleted(self, event):
        if event.is_directory:
            self._inbox.put(('folder', event.src_path))
        else:
            self._inbox.put(('deleted', event.src_path))

    def on_moved(self, event):
        if event.is_directory:
            self._inbox.put(('folder', event.src_path))
            return
        self._inbox.put(('moved', (event.src_path, event.dest_path)))


class FolderWatcher:

    def __init__(self, database, progress: ProgressAggregator):
        self._progress = progress
        self._db = database
        self._db.set_progress_callback(self._progress.increment)
        self._db.set_update_callback(lambda: self._progress.send_event('update'))
        self._q = queue.Queue()
        self._emitter = _FileEventHandler(self._q)
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
        AppLogger.info(f'watch start: {len(folders)} folders')
        self.rescan_all()

    def rescan_all(self):
        if self._folders:
            AppLogger.info(f'rescan: {len(self._folders)} folders')
            self._q.put(('rescan', self._folders))

    def set_ignore_paths(self, paths):
        self._q.put(('ignore', paths))

    def request_cleanup(self):
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
                AppLogger.debug(f'observer stop: {e}')
            self._observer = None

    def _loop(self):
        changed = set()
        deleted = set()
        moved = {}
        folder_dirty = False
        while not self._stop.is_set():
            try:
                item = self._q.get(timeout=_BATCH_TIMEOUT)
            except queue.Empty:
                self._flush(changed, deleted, moved)
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
                elif kind == 'moved':
                    src, dst = data
                    moved[src] = dst
                elif kind == 'folder':
                    folder_dirty = True
                elif kind in ('rescan', 'ignore', 'cleanup'):
                    self._flush(changed, deleted, moved)
                    self._exec(kind, data)
                elif kind == '__stop__':
                    return
            if folder_dirty:
                self._progress.send_event('folderchanged')
                folder_dirty = False

    def _flush(self, changed, deleted, moved):
        if moved:
            new_at_dst = {dst for src, dst in moved.items() if src in changed}
            changed -= set(moved.keys())
            self._exec('rename', list(moved.items()))
            changed.update(new_at_dst)
            moved.clear()
        if deleted:
            self._exec('remove', list(deleted))
            deleted.clear()
        if changed:
            self._exec('update', list(changed))
            changed.clear()

    @profiler.profile
    def _exec(self, cmd, data=None):
        try:
            with self._db as indexer:
                if cmd == 'rename':
                    AppLogger.info(f'db rename: {len(data)} files')
                    indexer.rename_by_pairs(data)
                elif cmd == 'update':
                    AppLogger.info(f'db update: {len(data)} files')
                    indexer.update_by_file_list(data)
                elif cmd == 'remove':
                    AppLogger.info(f'db remove: {len(data)} files')
                    indexer.remove_by_file_list(data)
                elif cmd == 'rescan':
                    AppLogger.info(f'db rescan: {len(data)} folders')
                    indexer.update_index(data)
                elif cmd == 'cleanup':
                    AppLogger.info('db cleanup')
                    self._progress.increment(0, 1)
                    indexer.purge_orphan_records()
                    self._progress.increment(1, 0)
                elif cmd == 'ignore':
                    AppLogger.info(f'db ignore: {len(data)} paths')
                    indexer.set_exclude_paths(data, run=True)
        except Exception as e:
            AppLogger.warning(f'db exec {cmd} failed', exc=e)
