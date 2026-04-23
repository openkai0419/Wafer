import json
import os
import threading
import time
from dataclasses import dataclass, asdict

from ..utils.logs import AppLogger


_QUEUE_DIR = ".installer_queue"
_QUEUE_FILE = "queue.json"
_lock = threading.Lock()


@dataclass
class QueueEntry:
    name: str
    plugin_dir: str
    requested_at: float


def _queue_dir(extensions_dir: str) -> str:
    return os.path.join(extensions_dir, _QUEUE_DIR)


def _queue_path(extensions_dir: str) -> str:
    return os.path.join(_queue_dir(extensions_dir), _QUEUE_FILE)


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


def _write(extensions_dir: str, entries: list[QueueEntry]):
    path = _queue_path(extensions_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump([asdict(e) for e in entries], f, ensure_ascii=False, indent=2)


def enqueue(extensions_dir: str, name: str, plugin_dir: str) -> None:
    with _lock:
        entries = _read(extensions_dir)
        entries = [e for e in entries if e.name != name]
        entries.append(QueueEntry(name=name, plugin_dir=plugin_dir, requested_at=time.time()))
        _write(extensions_dir, entries)
        AppLogger.info(f"[InstallerQueue] Enqueued: {name}")


def dequeue(extensions_dir: str, name: str) -> bool:
    with _lock:
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
    with _lock:
        return _read(extensions_dir)


def remove_entries(extensions_dir: str, names: list[str]) -> None:
    if not names:
        return
    with _lock:
        names_set = set(names)
        entries = _read(extensions_dir)
        new_entries = [e for e in entries if e.name not in names_set]
        if not new_entries:
            _clear_unlocked(extensions_dir)
        else:
            _write(extensions_dir, new_entries)


def has_pending_queue(extensions_dir: str) -> bool:
    with _lock:
        return bool(_read(extensions_dir))


def queued_names(extensions_dir: str) -> set[str]:
    return {e.name for e in read_queue(extensions_dir)}


def clear_queue(extensions_dir: str) -> None:
    with _lock:
        _clear_unlocked(extensions_dir)


def _clear_unlocked(extensions_dir: str):
    path = _queue_path(extensions_dir)
    try:
        if os.path.isfile(path):
            os.remove(path)
        qdir = _queue_dir(extensions_dir)
        if os.path.isdir(qdir) and not os.listdir(qdir):
            os.rmdir(qdir)
    except OSError as e:
        AppLogger.warning(f"[InstallerQueue] Failed to clear queue: {path}", exc=e)
