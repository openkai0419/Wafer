import sys
from typing import NoReturn

from ...core.logs import AppLogger
from ...core.platform.foreground import activate_window
from ...core.platform.workspace_lock import WorkspaceLock
from ...core.store.workspace import WorkspaceStore
from ...qt.common.app_icon import get_icon


def _lock_dir() -> str | None:
    return None


def claim_workspace(slot_id: str | None) -> WorkspaceLock | None:
    store = WorkspaceStore.instance()
    if slot_id is None or store.get_slot(slot_id) is None:
        slot_id = store.create_slot_from(None)
    lock = WorkspaceLock.acquire(slot_id, lock_dir=_lock_dir())
    if lock is not None:
        return lock
    owner = WorkspaceLock.read_owner(slot_id, lock_dir=_lock_dir())
    if owner is not None:
        activate_window(owner.hwnd)
    AppLogger.info(f"workspace {slot_id} is already open in another window (owner={owner}); not opening a duplicate")
    return None


def run_viewer(app, lock: WorkspaceLock) -> NoReturn:
    from .mainwindow import MainWindow

    window = MainWindow(get_icon(), workspace_lock=lock)
    window.show()
    sys.exit(app.exec())
