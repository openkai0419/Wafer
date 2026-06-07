from __future__ import annotations

import time
from typing import Any

from ....utils.logs import AppLogger
from ....utils.profiling import profiler
from ....plugin.parser.handler import parser_resolver
from ._batch_utils import BATCH_SIZE, FLUSH_DELAY, ResultBuffer, try_float
from ..db_writer import DatabaseWriter
from ..runtime.progress_aggregator import ProgressAggregator
from ..runtime.scheduler import TaskScheduler
from ..runtime.task import Task, TaskPriority


def trigger_parser_pending(
    source_keys: dict[str, set[str]],
    writer: DatabaseWriter,
    request_dispatch=None,
):
    if not source_keys:
        return
    all_keys = set().union(*source_keys.values())
    matched = parser_resolver.parsers_for_keys(all_keys)
    if not matched:
        return
    dispatched = False
    for name in matched:
        trigger = set(parser_resolver.trigger_keys(name))
        filtered = [s for s, keys in source_keys.items() if keys & trigger]
        if not filtered:
            continue
        status_name = parser_resolver.status_name(name)
        writer.insert_pending(filtered, [status_name])
        dispatched = True
    if dispatched and request_dispatch:
        request_dispatch()


def _write_batched(writer: DatabaseWriter, data: dict[str, Any]):
    cs = data["collector_status"]
    meta = data["meta_info_entries"]
    tags = data["tag_entries"]
    delete = data["delete_entries"]
    total = max(len(cs), len(meta), len(tags))
    if total <= BATCH_SIZE:
        writer.upsert_parser_results(meta, tags, cs, delete)
        return
    for i in range(0, total, BATCH_SIZE):
        writer.upsert_parser_results(
            meta[i : i + BATCH_SIZE],
            tags[i : i + BATCH_SIZE],
            cs[i : i + BATCH_SIZE],
            delete[i : i + BATCH_SIZE] if i < len(delete) else [],
        )


def _merge_parsed(entries: list[dict[str, Any]]) -> dict[str, Any]:
    meta_info_entries: list[tuple] = []
    tag_entries: list[tuple] = []
    delete_entries: list[tuple] = []
    collector_status_map: dict[tuple[str, str], tuple] = {}
    for e in entries:
        meta_info_entries.extend(e["meta_info_entries"])
        tag_entries.extend(e["tag_entries"])
        delete_entries.extend(e["delete_entries"])
        for cs in e["collector_status"]:
            cs_key = (cs[0], cs[1])
            prev = collector_status_map.get(cs_key)
            if prev is None or cs[2] == "ok":
                collector_status_map[cs_key] = cs
    return {
        "meta_info_entries": meta_info_entries,
        "tag_entries": tag_entries,
        "delete_entries": delete_entries,
        "collector_status": list(collector_status_map.values()),
    }


class ParserReceiver:
    def __init__(self, scheduler: TaskScheduler, writer: DatabaseWriter, progress: ProgressAggregator):
        self._scheduler = scheduler
        self._writer = writer
        self._progress = progress
        self._buffer = ResultBuffer(_merge_parsed)
        self._request_dispatch = None

    def set_request_dispatch(self, fn):
        self._request_dispatch = fn

    def handle_result(self, msg) -> bool:
        payload = msg.payload
        if not isinstance(payload, dict):
            AppLogger.warning(f"parse.result: invalid payload type: {type(payload)}")
            return True
        parser = payload.get("parser", "")
        results = payload.get("results", [])
        if results:
            for r in results:
                r.setdefault("parser", parser)
            parsed = _parse_batch(results)
            need_submit = self._buffer.append(parsed, len(results))
            if need_submit:
                self._schedule_flush()
        return True

    def _schedule_flush(self):
        self._scheduler.submit(
            Task.create(
                "flush_parser_results",
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
        AppLogger.info(f"[ParserReceiver] Flushed {count} results")

        source_keys = _build_source_keys(data)
        trigger_parser_pending(source_keys, self._writer, self._request_dispatch)

        if self._buffer.has_pending():
            self._schedule_flush()


def _build_source_keys(data: dict[str, Any]) -> dict[str, set[str]]:
    source_keys: dict[str, set[str]] = {}
    for entry in data["meta_info_entries"]:
        source_keys.setdefault(entry[0], set()).add(entry[1])
    for entry in data.get("tag_entries", ()):
        source_keys.setdefault(entry[0], set()).add(entry[1])
    return source_keys


def _parse_batch(results: list[dict[str, Any]]) -> dict[str, Any]:
    meta_info_entries: list[tuple] = []
    tag_entries: list[tuple] = []
    delete_entries: list[tuple] = []
    collector_status_map: dict[tuple[str, str], tuple] = {}
    now = time.time()

    for r in results:
        source = r.get("source")
        path = r.get("path", source)
        file_hash = r.get("file_hash")
        meta_info = r.get("meta_info", {})
        tags = r.get("tags", {})
        delete_keys = r.get("delete_keys")
        status = r.get("status")
        parser = r.get("parser", "")

        ok = bool(status)
        s_status = "ok" if ok else "fail"
        cs_key = (source, parser)
        prev_cs = collector_status_map.get(cs_key)
        if prev_cs is None or s_status == "ok":
            collector_status_map[cs_key] = (source, parser, s_status, now)

        if ok:
            prefix = f"{parser}." if parser else ""
            for k, v in meta_info.items():
                if v is not None:
                    meta_info_entries.append((path, f"{prefix}{k}", str(v), try_float(v)))
            if file_hash:
                tag_entries.extend((file_hash, f"{prefix}{k}", str(v), try_float(v)) for k, v in tags.items() if v is not None)
            if delete_keys:
                delete_entries.append((path, file_hash, delete_keys))

    return {
        "meta_info_entries": meta_info_entries,
        "tag_entries": tag_entries,
        "delete_entries": delete_entries,
        "collector_status": list(collector_status_map.values()),
    }
