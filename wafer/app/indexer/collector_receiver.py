from __future__ import annotations

import threading
import time
from typing import Any

from ...utils.logs import AppLogger
from ...utils.profiling import profiler
from .db_writer import DatabaseWriter
from .progress_notifier import ProgressAggregator
from .scheduler import TaskScheduler
from .task import Task, TaskPriority

_BATCH_SIZE = 900
_FLUSH_DELAY = 4.0


class _ResultBuffer:

    def __init__(self):
        self._lock = threading.Lock()
        self._entries: list[dict[str, Any]] = []
        self._count = 0
        self._flush_scheduled = False
        self._first_append: float = 0.0

    def append(self, parsed: dict, count: int) -> bool:
        with self._lock:
            self._entries.append(parsed)
            self._count += count
            if not self._flush_scheduled:
                self._flush_scheduled = True
                self._first_append = time.monotonic()
                return True
            return False

    def drain(self) -> tuple[dict | None, int]:
        with self._lock:
            if not self._count:
                self._flush_scheduled = False
                return None, 0
            merged = _merge_parsed(self._entries)
            count = self._count
            self._entries.clear()
            self._count = 0
            self._flush_scheduled = False
            return merged, count

    def time_since_first(self) -> float:
        with self._lock:
            if not self._first_append:
                return 0.0
            return time.monotonic() - self._first_append

    def has_pending(self) -> bool:
        with self._lock:
            if self._count > 0 and not self._flush_scheduled:
                self._flush_scheduled = True
                return True
            return False


def _write_batched(writer: DatabaseWriter, data: dict[str, Any]):
    cs = data['collector_status']
    img = data['image_entries']
    meta = data['meta_info_entries']
    tags = data['tag_entries']
    total = max(len(cs), len(img), len(meta), len(tags))
    if total <= _BATCH_SIZE:
        writer.upsert_results(img, meta, tags, cs)
        return
    for i in range(0, total, _BATCH_SIZE):
        writer.upsert_results(
            img[i:i + _BATCH_SIZE],
            meta[i:i + _BATCH_SIZE],
            tags[i:i + _BATCH_SIZE],
            cs[i:i + _BATCH_SIZE],
        )


def _merge_parsed(entries: list[dict[str, Any]]) -> dict[str, Any]:
    image_entries: list[tuple] = []
    meta_info_entries: list[tuple] = []
    tag_entries: list[tuple] = []
    collector_status_map: dict[tuple[str, str], tuple] = {}
    for e in entries:
        image_entries.extend(e['image_entries'])
        meta_info_entries.extend(e['meta_info_entries'])
        tag_entries.extend(e['tag_entries'])
        for cs in e['collector_status']:
            cs_key = (cs[0], cs[1])
            prev = collector_status_map.get(cs_key)
            if prev is None or cs[2] == 'ok':
                collector_status_map[cs_key] = cs
    return {
        'image_entries': image_entries,
        'meta_info_entries': meta_info_entries,
        'tag_entries': tag_entries,
        'collector_status': list(collector_status_map.values()),
    }


class CollectorReceiver:

    def __init__(self, scheduler: TaskScheduler, writer: DatabaseWriter, progress: ProgressAggregator):
        self._scheduler = scheduler
        self._writer = writer
        self._progress = progress
        self._buffer = _ResultBuffer()

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
            parsed = _parse_batch(results)
            need_submit = self._buffer.append(parsed, len(results))
            if need_submit:
                self._schedule_flush()
        return True

    def _schedule_flush(self):
        self._scheduler.submit(Task.create(
            'flush_collection_results',
            priority=TaskPriority.COLLECTION,
            run=self._flush,
        ))

    @profiler.profile
    def _flush(self):
        remaining = _FLUSH_DELAY - self._buffer.time_since_first()
        if remaining > 0:
            time.sleep(remaining)
        data, count = self._buffer.drain()
        if not data:
            return
        _write_batched(self._writer, data)
        self._progress.increment(count, 0)
        self._progress.send_event('update')
        AppLogger.info(f'[Receiver] Flushed {count} results')
        if self._buffer.has_pending():
            self._schedule_flush()


_DATETIME_FORMATS = (
    '%Y:%m:%d %H:%M:%S',
    '%Y-%m-%d %H:%M:%S',
    '%Y:%m:%d',
    '%Y-%m-%d',
)


def _try_parse_datetime(s: str):
    from datetime import datetime, timezone
    for fmt in _DATETIME_FORMATS:
        try:
            dt = datetime.strptime(s.strip(), fmt)
            return dt.replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
    return None


def _try_float(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(v)
    except (ValueError, TypeError):
        pass
    if isinstance(v, str):
        ts = _try_parse_datetime(v)
        if ts is not None:
            return ts
    return None


def _parse_batch(results: list[dict[str, Any]]) -> dict[str, Any]:
    image_entries: list[tuple] = []
    meta_info_entries: list[tuple] = []
    tag_entries: list[tuple] = []
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
        cs_key = (source, collector)
        prev_cs = collector_status_map.get(cs_key)
        if prev_cs is None or s_status == 'ok':
            collector_status_map[cs_key] = (source, collector, s_status, now)

        if ok:
            if aspect or (path != source):
                image_entries.append((path, source, aspect))
            for k, v in meta_info.items():
                if v is not None:
                    meta_info_entries.append((path, k, str(v), _try_float(v)))
            if file_hash:
                tag_entries.extend(
                    (file_hash, k, str(v), _try_float(v)) for k, v in tags.items() if v is not None
                )

    return {
        'image_entries': image_entries,
        'meta_info_entries': meta_info_entries,
        'tag_entries': tag_entries,
        'collector_status': list(collector_status_map.values()),
    }
