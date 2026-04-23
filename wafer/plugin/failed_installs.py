import json
import os
import threading
import time

from ..utils.logs import AppLogger


_FAILED_DIR = ".installer_queue"
_FAILED_FILE = "failed.json"
_lock = threading.Lock()


def _failed_path(extensions_dir: str) -> str:
    return os.path.join(extensions_dir, _FAILED_DIR, _FAILED_FILE)


def _read(extensions_dir: str) -> dict:
    path = _failed_path(extensions_dir)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError) as e:
        AppLogger.warning(f"[FailedInstalls] read failed: {path}", exc=e)
        return {}


def _write(extensions_dir: str, data: dict) -> None:
    path = _failed_path(extensions_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def mark_failed(extensions_dir: str, name: str, reason: str = "") -> None:
    with _lock:
        data = _read(extensions_dir)
        data[name] = {"reason": reason, "failed_at": time.time()}
        _write(extensions_dir, data)
        AppLogger.info(f"[FailedInstalls] marked failed: {name}")


def clear(extensions_dir: str, names) -> None:
    names_set = set(names) if not isinstance(names, str) else {names}
    if not names_set:
        return
    with _lock:
        data = _read(extensions_dir)
        removed = [n for n in names_set if n in data]
        if not removed:
            return
        for n in removed:
            data.pop(n, None)
        if data:
            _write(extensions_dir, data)
        else:
            try:
                os.remove(_failed_path(extensions_dir))
            except OSError:
                pass
        AppLogger.info(f"[FailedInstalls] cleared: {removed}")


def failed_names(extensions_dir: str) -> set[str]:
    with _lock:
        return set(_read(extensions_dir).keys())


def failure_info(extensions_dir: str, name: str) -> dict | None:
    with _lock:
        return _read(extensions_dir).get(name)
