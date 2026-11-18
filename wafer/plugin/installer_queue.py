import json
import os
import time
from dataclasses import dataclass, asdict

from ..core.common.json_io import write_json_file
from ..core.logs import AppLogger
from ..core.platform.process_lock import file_lock


_QUEUE_DIR = ".installer_queue"
_QUEUE_FILE = "queue.json"


@dataclass
class QueueEntry:
    name: str
    plugin_dir: str
    requested_at: float


def _queue_dir(extensions_dir: str) -> str:
    return os.path.join(extensions_dir, _QUEUE_DIR)


def _queue_path(extensions_dir: str) -> str:
    return os.path.join(_queue_dir(extensions_dir), _QUEUE_FILE)


def _lock(extensions_dir: str):
    return file_lock(f"{_queue_path(extensions_dir)}.lock")


def _read(extensions_dir: str) -> list[QueueEntry]:
    path = _queue_path(extensions_dir)
    if not os.path.isfile(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return [QueueEntry(**item) for item in data]
    except (OSError, ValueError, TypeError) as e:
        AppLogger.warning(f"[InstallerQueue] Failed to read queue: {path}", exc=e)
        return []


def _write(extensions_dir: str, entries: list[QueueEntry]) -> bool:
    return write_json_file(_queue_path(extensions_dir), [asdict(e) for e in entries])


def enqueue(extensions_dir: str, name: str, plugin_dir: str) -> None:
    with _lock(extensions_dir):
        entries = _read(extensions_dir)
        entries = [e for e in entries if e.name != name]
        entries.append(QueueEntry(name=name, plugin_dir=plugin_dir, requested_at=time.time()))
        if _write(extensions_dir, entries):
            AppLogger.info(f"[InstallerQueue] Enqueued: {name}")


def dequeue(extensions_dir: str, name: str) -> bool:
    with _lock(extensions_dir):
        entries = _read(extensions_dir)
        new_entries = [e for e in entries if e.name != name]
        if len(new_entries) == len(entries):
            return False
        if new_entries:
            _write(extensions_dir, new_entries)
        else:
            _clear_unlocked(extensions_dir)
        AppLogger.info(f"[InstallerQueue] Dequeued: {name}")
        return True


def read_queue(extensions_dir: str) -> list[QueueEntry]:
    return _read(extensions_dir)


def remove_entries(extensions_dir: str, names: list[str]) -> None:
    if not names:
        return
    with _lock(extensions_dir):
        names_set = set(names)
        entries = _read(extensions_dir)
        new_entries = [e for e in entries if e.name not in names_set]
        if not new_entries:
            _clear_unlocked(extensions_dir)
        else:
            _write(extensions_dir, new_entries)


def has_pending_queue(extensions_dir: str) -> bool:
    return bool(_read(extensions_dir))


def queued_names(extensions_dir: str) -> set[str]:
    return {e.name for e in read_queue(extensions_dir)}


def clear_queue(extensions_dir: str) -> None:
    with _lock(extensions_dir):
        _clear_unlocked(extensions_dir)


def _clear_unlocked(extensions_dir: str):
    path = _queue_path(extensions_dir)
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError as e:
        AppLogger.warning(f"[InstallerQueue] Failed to clear queue: {path}", exc=e)
