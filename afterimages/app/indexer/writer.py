import queue
import threading
import time

from afterimages.utils.logs import AppLogger
from afterimages.utils.profiling import profiler
from afterimages.core.db.file_db import FileDB
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
            self._db.close()
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

        source_update_map: dict[str, tuple] = {}
        image_entries = []
        meta_info_entries = []
        tag_entries = []
        collector_status_map: dict[tuple[str, str], tuple] = {}
        now = time.time()

        for r in results:
            source = r.get('source')
            path = r.get('path', source)
            name = r.get('name') or None
            aspect = r.get('aspect')
            file_hash = r.get('file_hash')
            meta_info = r.get('meta_info', {})
            tags = r.get('tags', {})
            status = r.get('status')
            collector = r.get('collector', '')

            ok = bool(status)
            s_status = 'ok' if ok else 'fail'
            prev = source_update_map.get(source)
            if prev is None or s_status == 'ok':
                source_update_map[source] = (now, s_status, source)
            cs_key = (source, collector)
            prev_cs = collector_status_map.get(cs_key)
            if prev_cs is None or s_status == 'ok':
                collector_status_map[cs_key] = (source, collector, s_status, now)

            if ok:
                if name or aspect or (path != source):
                    image_entries.append((path, source, name, aspect))
                meta_info_entries.extend(
                    (path, k, v) for k, v in meta_info.items() if v is not None
                )
                if file_hash:
                    tag_entries.extend(
                        (file_hash, k, v) for k, v in tags.items() if v is not None
                    )

        source_updates = list(source_update_map.values())
        collector_status = list(collector_status_map.values())

        try:
            self._db.upsert_collection_results(
                source_updates, image_entries,
                meta_info_entries, tag_entries, collector_status,
            )
            self._db.try_checkpoint('PASSIVE')
            self._progress.increment(len(results), 0)
            self._progress.send_event('update')
        except Exception as e:
            AppLogger.warning(f'[Writer] DB write failed: {e}', exc=e)
        AppLogger.info(f'[Writer] Wrote {len(results)} results')
