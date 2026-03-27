from __future__ import annotations

import time
from typing import Any

from ...utils.logs import AppLogger
from .db_writer import DatabaseWriter
from .progress_notifier import ProgressAggregator
from .scheduler import TaskScheduler
from .task import Task, TaskPriority

_BATCH_SIZE = 900


class CollectorReceiver:

    def __init__(self, scheduler: TaskScheduler, writer: DatabaseWriter, progress: ProgressAggregator):
        self._scheduler = scheduler
        self._writer = writer
        self._progress = progress

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
            self._submit_results(results)
        return True

    def _submit_results(self, results: list[dict[str, Any]]):
        for i in range(0, len(results), _BATCH_SIZE):
            chunk = results[i:i + _BATCH_SIZE]
            data = _parse_batch(chunk)
            self._scheduler.submit(Task.create(
                'upsert_results',
                priority=TaskPriority.COLLECTION,
                run=lambda d=data: self._writer.upsert_results(
                    d['image_entries'],
                    d['meta_info_entries'], d['tag_entries'], d['collector_status'],
                ),
                on_complete=lambda n=len(chunk): (
                    self._progress.increment(n, 0),
                    self._progress.send_event('update'),
                ),
            ))
        AppLogger.info(f'[Receiver] Queued {len(results)} results')


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
