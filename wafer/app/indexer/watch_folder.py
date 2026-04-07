import os
import queue
import threading
import time
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from ...utils.logs import AppLogger
from ...utils.paths import normalize_path
from ...utils.profiling import profiler
from .db_writer import DatabaseWriter
from .progress_notifier import ProgressAggregator
from .scanner import DirectoryScanner
from .scheduler import TaskScheduler
from .task import Task, TaskPriority

DISABLE_MODIFY_EVENT = False
_BATCH_TIMEOUT = 0.5
_STABLE_THRESHOLD = 2.0


def _stat_signature(path):
    try:
        st = os.stat(path)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def _extract_stable(pending):
    now = time.monotonic()
    stable = set()
    for p, (ts, prev_sig) in list(pending.items()):
        age = now - ts
        if age < _STABLE_THRESHOLD:
            continue
        cur_sig = _stat_signature(p)
        if cur_sig is None:
            stable.add(p)
        elif cur_sig != prev_sig:
            pending[p] = (now, cur_sig)
        else:
            stable.add(p)
    for p in stable:
        del pending[p]
    if stable:
        AppLogger.debug(f"[stabilize] {len(stable)} files stabilized, {len(pending)} still pending")
    return stable


def _drain_queue(q, first_item):
    batch = [first_item]
    while True:
        try:
            batch.append(q.get_nowait())
        except queue.Empty:
            return batch


class _FileEventHandler(FileSystemEventHandler):
    def __init__(self, inbox):
        self._inbox = inbox

    def on_created(self, event):
        if event.is_directory:
            self._inbox.put(("folder", event.src_path))
        else:
            self._inbox.put(("created", event.src_path))

    def on_modified(self, event):
        if DISABLE_MODIFY_EVENT or event.is_directory:
            return
        self._inbox.put(("changed", event.src_path))

    def on_deleted(self, event):
        if event.is_directory:
            self._inbox.put(("folder", event.src_path))
        else:
            self._inbox.put(("deleted", event.src_path))

    def on_moved(self, event):
        if event.is_directory:
            self._inbox.put(("folder", event.src_path))
            return
        self._inbox.put(("moved", (event.src_path, event.dest_path)))


class _EventAccumulator:
    def __init__(self):
        self._pending = {}
        self._notified = set()
        self._ready = set()
        self._new = set()
        self._deleted = set()
        self._moved = {}
        self._folder_dirty = False

    def on_created(self, path):
        self._pending.pop(path, None)
        self._notified.discard(path)
        self._ready.add(path)
        self._new.add(path)

    def on_changed(self, path, now):
        if path in self._ready:
            return
        if path not in self._notified and path not in self._pending:
            self._ready.add(path)
            self._notified.add(path)
        else:
            self._pending[path] = (now, _stat_signature(path))

    def on_deleted(self, path):
        self._pending.pop(path, None)
        self._notified.discard(path)
        self._ready.discard(path)
        self._deleted.add(path)

    def on_moved(self, src, dst):
        self._pending.pop(src, None)
        self._notified.discard(src)
        was_new = src in self._new
        self._ready.discard(src)
        self._new.discard(src)
        if was_new:
            self._ready.add(dst)
            self._new.add(dst)
        else:
            self._moved[src] = dst

    def on_folder(self):
        self._folder_dirty = True

    def consume_folder_dirty(self):
        if self._folder_dirty:
            self._folder_dirty = False
            return True
        return False

    def drain(self):
        stable = _extract_stable(self._pending)
        stable.update(self._ready)
        self._ready.clear()
        self._new.clear()
        deleted = set(self._deleted)
        moved = dict(self._moved)
        self._deleted.clear()
        self._moved.clear()
        if stable or deleted or moved:
            AppLogger.debug(f"[acc] drain: stable={len(stable)}, deleted={len(deleted)}, moved={len(moved)}, still_pending={len(self._pending)}")
        return stable, deleted, moved

    def drain_all(self):
        AppLogger.debug(f"[acc] drain_all: ready={len(self._ready)}, pending={len(self._pending)}")
        self._ready.update(self._pending)
        self._pending.clear()
        self._notified.clear()
        return self.drain()


class FolderWatcher:
    def __init__(
        self,
        scheduler: TaskScheduler,
        writer: DatabaseWriter,
        scanner: DirectoryScanner,
        progress: ProgressAggregator,
    ):
        self._scheduler = scheduler
        self._writer = writer
        self._scanner = scanner
        self._progress = progress
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
        AppLogger.info(f"watch start: {len(folders)} folders")
        self.rescan_all()

    def rescan_all(self):
        if self._folders:
            AppLogger.info(f"rescan: {len(self._folders)} folders")
            self._q.put(("rescan", self._folders))

    def set_ignore_paths(self, paths):
        self._scanner.set_exclude_paths(paths)

    def request_cleanup(self):
        self._q.put(("cleanup", None))

    def stop(self):
        self._stop.set()
        self._q.put(("__stop__", None))
        self._stop_observer()
        self._worker.join(timeout=5.0)

    def _stop_observer(self):
        if self._observer:
            try:
                self._observer.stop()
                self._observer.join()
            except Exception as e:
                AppLogger.debug(f"observer stop: {e}")
            self._observer = None

    def _loop(self):
        acc = _EventAccumulator()
        while not self._stop.is_set():
            try:
                item = self._q.get(timeout=_BATCH_TIMEOUT)
            except queue.Empty:
                self._flush(*acc.drain())
                continue
            now = time.monotonic()
            for kind, data in _drain_queue(self._q, item):
                if kind == "created":
                    acc.on_created(data)
                elif kind == "changed":
                    acc.on_changed(data, now)
                elif kind == "deleted":
                    acc.on_deleted(data)
                elif kind == "moved":
                    acc.on_moved(*data)
                elif kind == "folder":
                    acc.on_folder()
                elif kind in ("rescan", "cleanup"):
                    self._flush(*acc.drain_all())
                    self._exec(kind, data)
                elif kind == "__stop__":
                    return
            if acc.consume_folder_dirty():
                self._progress.send_event("folderchanged")

    def _flush(self, changed, deleted, moved):
        if not changed and not deleted and not moved:
            return
        AppLogger.debug(f"[flush] changed={len(changed)}, deleted={len(deleted)}, moved={len(moved)}")
        if moved:
            new_at_dst = {dst for src, dst in moved.items() if src in changed}
            changed -= set(moved.keys())
            self._exec("rename", list(moved.items()))
            changed.update(new_at_dst)
        if deleted:
            self._exec("remove", list(deleted))
        if changed:
            self._exec("update", list(changed))

    @profiler.profile
    def _exec(self, cmd, data=None):
        if cmd == "rename":
            AppLogger.info(f"watcher rename: {len(data)} files")
            pairs = [(normalize_path(old), normalize_path(new)) for old, new in data if normalize_path(old) != normalize_path(new)]
            if pairs:
                self._progress.increment(0, len(pairs))
                self._scheduler.submit(
                    Task.create(
                        "rename_paths",
                        priority=TaskPriority.REALTIME,
                        run=lambda p=pairs: self._writer.rename_paths(p),
                        on_complete=lambda n=len(pairs): (
                            self._progress.increment(n, 0),
                            self._progress.send_event("update"),
                        ),
                    )
                )
        elif cmd == "update":
            AppLogger.info(f"watcher update: {len(data)} files")
            self._scanner.request_update(data)
        elif cmd == "remove":
            AppLogger.info(f"watcher remove: {len(data)} files")
            paths = [normalize_path(p) for p in data if not os.path.exists(p)]
            if paths:
                self._progress.increment(0, len(paths))
                self._scheduler.submit(
                    Task.create(
                        "delete_sources",
                        priority=TaskPriority.REALTIME,
                        run=lambda p=paths: self._writer.delete_sources(p),
                        on_complete=lambda n=len(paths): (
                            self._progress.increment(n, 0),
                            self._progress.send_event("update"),
                        ),
                    )
                )
        elif cmd == "rescan":
            AppLogger.info(f"watcher rescan: {len(data)} folders")
            self._scanner.request_scan(data)
        elif cmd == "cleanup":
            AppLogger.info("watcher cleanup")
            self._progress.increment(0, 1)
            self._scheduler.submit(
                Task.create(
                    "purge_orphans",
                    priority=TaskPriority.MAINTENANCE,
                    run=lambda: self._writer.purge_orphans(),
                    on_complete=lambda: (
                        self._progress.increment(1, 0),
                        self._progress.send_event("update"),
                    ),
                )
            )
