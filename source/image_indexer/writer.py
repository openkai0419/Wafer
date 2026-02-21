import queue
import threading
import time

from ..common.logs import AppLogger
from ..common.profiling import profiler
from ..db.file_db import FileDB
from .progress_notifier import ProgressAggregator

_WRITE_INTERVAL = 2.0
_BATCH_SIZE = 900


class CollectionWriter:

    def __init__(self, db_path: str, progress: ProgressAggregator):
        self._db_path = db_path
        self._progress = progress
        self._queue: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._db: FileDB | None = None

    def start(self):
        self._db = FileDB(self._db_path)
        self._db.start()
        self._thread = threading.Thread(target=self._write_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None
        self._flush_all()
        if self._db:
            self._db.exit()
            self._db = None

    def handle_result(self, msg) -> bool:
        payload = msg.payload
        if not isinstance(payload, dict):
            AppLogger.warning(f'collect.result: invalid payload type: {type(payload)}')
            return True
        collector = payload.get('collector', '')
        results = payload.get('results', [])
        if results:
            for r in results:
                r.setdefault('collector', collector)
                self._queue.put(r)
        return True

    def _write_loop(self):
        while not self._stop.is_set():
            self._stop.wait(timeout=_WRITE_INTERVAL)
            self._flush_all()

    @profiler.profile
    def _flush_all(self):
        batch = []
        while True:
            try:
                batch.append(self._queue.get_nowait())
            except queue.Empty:
                break
        if not batch:
            return
        for i in range(0, len(batch), _BATCH_SIZE):
            chunk = batch[i:i + _BATCH_SIZE]
            self._write_batch(chunk)

    @profiler.profile
    def _write_batch(self, results):
        if not self._db or not self._db.conn:
            AppLogger.warning('[Writer] DB not available')
            return

        source_updates = []
        image_entries = []
        meta_info_entries = []
        tag_entries = []
        collector_status = []
        now = time.time()

        for r in results:
            source = r.get('source')
            info = r.get('info', {})
            meta_info = r.get('meta_info', {})
            tags = r.get('tags', {})
            status = r.get('status', 'fail')
            collector = r.get('collector', '')

            path = info.get('path', source)
            name = info.get('name', '')
            aspect = info.get('aspect', 1.0)
            file_hash = info.get('file_hash')

            ok = status != 'fail'
            source_updates.append((now, 'ok' if ok else 'fail', source))
            collector_status.append((source, collector, 'ok' if ok else 'fail', now))

            if ok:
                image_entries.append((path, source, name, aspect))
                meta_info_entries.extend((path, k, v) for k, v in meta_info.items())
                if file_hash:
                    tag_entries.extend((file_hash, k, v) for k, v in tags.items())

        try:
            self._db.upsert_collection_results(
                source_updates, image_entries,
                meta_info_entries, tag_entries, collector_status,
            )
            self._db.try_checkpoint('PASSIVE')
            self._progress.add(len(results), 0)
            self._progress.notify('update')
        except Exception as e:
            AppLogger.warning(f'[Writer] DB write failed: {e}', exc=e)
        AppLogger.info(f'[Writer] Wrote {len(results)} results')
