import os
from collections.abc import Iterable

from ..common.paths import resolve_temp_path
from ..logs import AppLogger
from .window_lock import WindowLock, WindowOwner


def lock_path(slot_id: str) -> str:
    return os.path.join(resolve_temp_path("workspaces"), f"{slot_id}.lock")


class WorkspaceLock(WindowLock):
    slot_id: str

    @classmethod
    def acquire(cls, slot_id: str) -> "WorkspaceLock | None":
        lock = cls.acquire_path(lock_path(slot_id))
        if lock is not None:
            lock.slot_id = slot_id
        return lock

    @staticmethod
    def read_owner(slot_id: str) -> WindowOwner | None:
        return WindowLock.read_owner_at(lock_path(slot_id))

    @staticmethod
    def delete_file_if_unused(slot_id: str) -> bool:
        path = lock_path(slot_id)
        if not os.path.exists(path):
            return False
        probe = WorkspaceLock.acquire(slot_id)
        if probe is None:
            AppLogger.info(f"WorkspaceLock: kept the lock file of open workspace {slot_id}")
            return False
        probe.release()
        try:
            os.remove(path)
        except OSError as exc:
            AppLogger.warning(f"WorkspaceLock: could not delete the lock file of workspace {slot_id}", exc=exc)
            return False
        return True

    @staticmethod
    def open_slot_ids(slot_ids: Iterable[str]) -> set[str]:
        held = set()
        for slot_id in slot_ids:
            probe = WorkspaceLock.acquire(slot_id)
            if probe is None:
                held.add(slot_id)
            else:
                probe.release()
        return held
