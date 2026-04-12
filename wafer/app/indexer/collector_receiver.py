from __future__ import annotations

import time
from typing import Any

from ...utils.logs import AppLogger
from ...utils.profiling import profiler
from ._parse_utils import BATCH_SIZE, FLUSH_DELAY, ResultBuffer, try_float
from .db_writer import DatabaseWriter
from .progress_notifier import ProgressAggregator
from .scheduler import TaskScheduler
from .task import Task, TaskPriority


def _write_batched(writer: DatabaseWriter, data: dict[str, Any]):
    cs = data["collector_status"]
    img = data["image_entries"]
    meta = data["meta_info_entries"]
    tags = data["tag_entries"]
    total = max(len(cs), len(img), len(meta), len(tags))
    if total <= BATCH_SIZE:
        writer.upsert_results(img, meta, tags, cs)
        return
    for i in range(0, total, BATCH_SIZE):
        writer.upsert_results(
            img[i : i + BATCH_SIZE],
            meta[i : i + BATCH_SIZE],
            tags[i : i + BATCH_SIZE],
            cs[i : i + BATCH_SIZE],
        )


def _merge_parsed(entries: list[dict[str, Any]]) -> dict[str, Any]:
    image_entries: list[tuple] = []
    meta_info_entries: list[tuple] = []
    tag_entries: list[tuple] = []
    collector_status_map: dict[tuple[str, str], tuple] = {}
    for e in entries:
        image_entries.extend(e["image_entries"])
        meta_info_entries.extend(e["meta_info_entries"])
        tag_entries.extend(e["tag_entries"])
        for cs in e["collector_status"]:
            cs_key = (cs[0], cs[1])
            prev = collector_status_map.get(cs_key)
            if prev is None or cs[2] == "ok":
                collector_status_map[cs_key] = cs
    return {
        "image_entries": image_entries,
        "meta_info_entries": meta_info_entries,
        "tag_entries": tag_entries,
        "collector_status": list(collector_status_map.values()),
    }


class CollectorReceiver:
    def __init__(self, scheduler: TaskScheduler, writer: DatabaseWriter, progress: ProgressAggregator):
        self._scheduler = scheduler
        self._writer = writer
        self._progress = progress
        self._buffer = ResultBuffer(_merge_parsed)
        self._parser_request_dispatch = None
        self._parser_writer = None

    def set_parser_dispatch(self, request_dispatch, writer):
        self._parser_request_dispatch = request_dispatch
        self._parser_writer = writer

    def handle_result(self, msg) -> bool:
        payload = msg.payload
        if not isinstance(payload, dict):
            AppLogger.warning(f"collect.result: invalid payload type: {type(payload)}")
            return True
        collector = payload.get("collector", "")
        results = payload.get("results", [])
        if results:
            for r in results:
                r.setdefault("collector", collector)
            parsed = _parse_batch(results)
            need_submit = self._buffer.append(parsed, len(results))
            if need_submit:
                self._schedule_flush()
        return True

    def _schedule_flush(self):
        self._scheduler.submit(
            Task.create(
                "flush_collection_results",
                priority=TaskPriority.COLLECTION,
                run=self._flush,
            )
        )

    @profiler.profile
    def _flush(self):
        remaining = FLUSH_DELAY - self._buffer.time_since_first()
        if remaining > 0:
            time.sleep(remaining)
        data, count = self._buffer.drain()
        if not data:
            return
        _write_batched(self._writer, data)
        self._progress.increment(count, 0)
        self._progress.send_event("update")
        AppLogger.info(f"[Receiver] Flushed {count} results")
        if self._parser_writer:
            from .parser_receiver import trigger_parser_pending, _build_source_keys

            source_keys = _build_source_keys(data)
            trigger_parser_pending(source_keys, self._parser_writer, self._parser_request_dispatch)
        if self._buffer.has_pending():
            self._schedule_flush()


def _parse_batch(results: list[dict[str, Any]]) -> dict[str, Any]:
    image_entries: list[tuple] = []
    meta_info_entries: list[tuple] = []
    tag_entries: list[tuple] = []
    collector_status_map: dict[tuple[str, str], tuple] = {}
    now = time.time()

    for r in results:
        source = r.get("source")
        path = r.get("path", source)
        r.get("name") or None
        aspect = r.get("aspect")
        file_hash = r.get("file_hash")
        meta_info = r.get("meta_info", {})
        tags = r.get("tags", {})
        status = r.get("status")
        collector = r.get("collector", "")

        ok = bool(status)
        s_status = "ok" if ok else "fail"
        cs_key = (source, collector)
        prev_cs = collector_status_map.get(cs_key)
        if prev_cs is None or s_status == "ok":
            collector_status_map[cs_key] = (source, collector, s_status, now)

        if ok:
            prefix = f"{collector}." if collector else ""
            if aspect or (path != source):
                image_entries.append((path, source, aspect))
            for k, v in meta_info.items():
                if v is not None:
                    meta_info_entries.append((path, f"{prefix}{k}", str(v), try_float(v)))
            if file_hash:
                tag_entries.extend((file_hash, f"{prefix}{k}", str(v), try_float(v)) for k, v in tags.items() if v is not None)

    return {
        "image_entries": image_entries,
        "meta_info_entries": meta_info_entries,
        "tag_entries": tag_entries,
        "collector_status": list(collector_status_map.values()),
    }
