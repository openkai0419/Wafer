from __future__ import annotations

import sqlite3
import threading
from abc import abstractmethod
from dataclasses import dataclass, asdict
from collections.abc import Callable, Sequence
from typing import Any, TypeVar

from ..registry import BasePlugin

_READER_INIT_LOCK = threading.Lock()
T = TypeVar("T")


def _fetch_all(conn: sqlite3.Connection, sql: str, params: Sequence[Any]) -> list[tuple]:
    cur = conn.cursor()
    try:
        return cur.execute(sql, tuple(params)).fetchall()
    finally:
        cur.close()


@dataclass
class ParserResult:
    source: str
    status: bool
    meta_info: dict | None = None
    tags: dict | None = None
    delete_meta_keys: list[str] | None = None
    delete_tag_keys: list[str] | None = None
    update_hash: str | None = None

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


def required_collectors(trigger_keys: tuple[str, ...]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for key in trigger_keys:
        collector, sep, meta_key = key.partition(".")
        if sep and collector and meta_key:
            result.setdefault(collector, []).append(meta_key)
    return result


class BaseParser(BasePlugin):
    SCOPE: str = "tray"
    TRIGGER_KEYS: tuple[str, ...] = ()

    db_name: str = ""
    _reader: sqlite3.Connection | None = None
    _reader_lock: threading.Lock | None = None

    @classmethod
    def trigger_keys(cls, db_name: str) -> tuple[str, ...]:
        return cls.TRIGGER_KEYS

    @abstractmethod
    def process(self, path: str, file_info: tuple, metadata: dict) -> ParserResult: ...

    def query_db(self, sql: str, params: Sequence[Any] = ()) -> list[tuple]:
        return self.read_db(lambda conn: _fetch_all(conn, sql, params), [])

    def read_db(self, read: Callable[[sqlite3.Connection], T], default: T | None = None) -> T | None:
        reader, lock = self._reader, self._reader_lock
        if reader is None or lock is None:
            reader, lock = self._open_reader()
        with lock:
            if self._reader is None:
                return default
            return read(reader)

    def _open_reader(self) -> tuple[sqlite3.Connection, threading.Lock]:
        from ...core.db.db_utils import open_readonly
        from ...core.common.paths import data_db_path

        if not self.db_name:
            raise RuntimeError(f"{self.NAME}: query_db() needs a per-indexer parser (BaseParserPlugin)")
        with _READER_INIT_LOCK:
            if self._reader is None or self._reader_lock is None:
                self._reader_lock = threading.Lock()
                self._reader = open_readonly(data_db_path(self.db_name))
            return self._reader, self._reader_lock

    def shutdown(self):
        reader, lock = self._reader, self._reader_lock
        if reader is None:
            return
        if lock is None:
            self._reader = None
            reader.close()
            return
        with lock:
            self._reader = None
            reader.close()

    def on_notify(self, payload: dict | None = None) -> None:
        pass

    @staticmethod
    def notify_to(name: str, payload: Any = None) -> None:
        from ...qt.commands.binding.instance_registry import InstanceRegistry

        node = InstanceRegistry.instance().resolve_node()
        if node:
            node.send("plugin.notify", payload, dst=f"parser-{name}")


class BaseParserPlugin(BaseParser):
    BATCH_SIZE: int = 1200
    MAX_WORKERS: int = 1
    MAX_TIMEOUT: float = 300.0


class BaseSingletonParser(BaseParser):
    BATCH_SIZE: int = 300
    MAX_WORKERS: int = 1
    MAX_TIMEOUT: float = 300.0
