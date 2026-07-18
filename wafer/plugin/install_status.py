import json
import os
import threading
import time
from collections import deque

from ..constants import APP_DATA_DIR_NAME
from ..utils.logs import AppLogger
from ..utils.paths import resolve_data_path


_STATUS_FILENAME = "install_status.json"
_CANCEL_FILENAME = "install_cancel.flag"
_LOG_TAIL_MAX = 200
_lock = threading.Lock()

INSTALL_WAITER_LOCK_NAME = f"{APP_DATA_DIR_NAME}_install_waiter"


def status_path() -> str:
    return resolve_data_path(_STATUS_FILENAME)


def cancel_flag_path() -> str:
    return resolve_data_path(_CANCEL_FILENAME)


def request_cancel() -> None:
    path = cancel_flag_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(str(time.time()))
        AppLogger.info("[InstallStatus] cancel requested")
    except OSError as e:
        AppLogger.warning(f"[InstallStatus] cancel write failed: {e}", exc=e)


def is_cancel_requested() -> bool:
    return os.path.isfile(cancel_flag_path())


def clear_cancel() -> None:
    path = cancel_flag_path()
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError as e:
        AppLogger.debug(f"[InstallStatus] cancel clear failed: {e}")


def _atomic_write(path: str, data: dict) -> None:
    tmp = f"{path}.tmp"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def read_status() -> dict | None:
    path = status_path()
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        AppLogger.debug(f"[InstallStatus] read failed: {e}")
        return None


def clear_status() -> None:
    path = status_path()
    for attempt in range(10):
        try:
            if os.path.isfile(path):
                os.remove(path)
            return
        except OSError as e:
            if attempt == 9:
                AppLogger.warning(f"[InstallStatus] clear failed after retries: {e}", exc=e)
                return
            time.sleep(0.05)


class InstallStatusWriter:
    def __init__(self, total: int):
        self._total = total
        self._index = 0
        self._name = ""
        self._phase = "pending"
        self._message = ""
        self._log_tail: deque[str] = deque(maxlen=_LOG_TAIL_MAX)
        self._flush()

    def begin_item(self, index: int, name: str, phase: str) -> None:
        with _lock:
            self._index = index
            self._name = name
            self._phase = phase
            self._message = ""
            self._flush()

    def append_log(self, line: str) -> None:
        if not line:
            return
        with _lock:
            self._log_tail.append(line)
            self._flush()

    def finish(self, error: str | None = None) -> None:
        with _lock:
            self._phase = "error" if error else "done"
            if error:
                self._message = error
            self._flush()

    def _flush(self) -> None:
        try:
            _atomic_write(
                status_path(),
                {
                    "phase": self._phase,
                    "current": {"index": self._index, "total": self._total, "name": self._name},
                    "message": self._message,
                    "log_tail": list(self._log_tail),
                    "updated_at": time.time(),
                },
            )
        except OSError as e:
            AppLogger.warning(f"[InstallStatus] write failed: {e}", exc=e)
