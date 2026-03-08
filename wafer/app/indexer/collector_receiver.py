from __future__ import annotations

import time
from typing import Any

from ...utils.logs import AppLogger
from .progress_notifier import ProgressAggregator
from .scheduler import TaskScheduler
from .write_command import WriteCommand, WritePriority

_BATCH_SIZE = 900


class CollectorReceiver:

    def __init__(self, scheduler: TaskScheduler, progress: ProgressAggregator):
        self._scheduler = scheduler
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
            self._scheduler.submit(WriteCommand.create(
                'upsert_results',
                priority=WritePriority.COLLECTION,
                data=data,
                on_complete=lambda n=len(chunk): (
                    self._progress.increment(n, 0),
                    self._progress.send_event('update'),
                ),
            ))
        AppLogger.info(f'[Receiver] Queued {len(results)} results')


def _parse_batch(results: list[dict[str, Any]]) -> dict[str, Any]:
    source_update_map: dict[str, tuple] = {}
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

    return {
        'source_updates': list(source_update_map.values()),
        'image_entries': image_entries,
        'meta_info_entries': meta_info_entries,
        'tag_entries': tag_entries,
        'collector_status': list(collector_status_map.values()),
    }
