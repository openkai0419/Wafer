import os
import sys
from dataclasses import dataclass
from typing import NoReturn

from ...core.common.paths import normalize_path
from ...core.db.path_scope import databases_containing
from ...core.ipc.node import Node
from ...core.logs import AppLogger
from ...core.platform.foreground import activate_window
from ...core.platform.process import AppProcess
from ...core.platform.workspace_lock import WorkspaceLock
from ...core.store.workspace import WindowSlot, WorkspaceStore
from ...qt.common.app_icon import get_icon
from .widgets.workspace_labels import slot_title
from .widgets.workspace_picker import WorkspacePickerDialog

OPEN_PATH_TIMEOUT = 5


@dataclass(frozen=True)
class OpenRequest:
    path: str
    database_name: str


def _lock_dir() -> str | None:
    return None


def slots_to_restore(restore_ids: list[str], chosen_slot_id: str | None) -> list[str]:
    return [slot_id for slot_id in restore_ids if slot_id != chosen_slot_id]


def restore_session(skip_slot_id: str | None) -> None:
    store = WorkspaceStore.instance()
    for slot_id in slots_to_restore(store.get_restore_slot_ids(), skip_slot_id):
        AppProcess.new_main("--viewer", "--slot", slot_id)
    if store.get_restore_webui():
        store.set_restore_webui(False)
        AppProcess.new_main("--webui", "--no-browser")


def is_openable_path(path: str | None) -> bool:
    if path and os.path.isfile(path):
        return True
    AppLogger.warning(f"Open path ignored, not a file: {path}")
    return False


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


def run_viewer(app, lock: WorkspaceLock, open_request: OpenRequest | None = None) -> NoReturn:
    from .mainwindow import MainWindow

    window = MainWindow(get_icon(), workspace_lock=lock, open_request=open_request)
    window.show()
    sys.exit(app.exec())


def run_pick(app, seed_slot_id: str | None) -> NoReturn:
    store = WorkspaceStore.instance()
    slots = store.list_slots()
    open_ids = WorkspaceLock.open_slot_ids([slot.slot_id for slot in slots], lock_dir=_lock_dir())
    picked = WorkspacePickerDialog.ask(slots, open_ids, allow_open=False, databases=[])
    if picked is None:
        sys.exit(0)
    slot_id = picked.slot_id if picked.slot_id is not None else store.create_slot_from(seed_slot_id or store.latest_slot_id())
    lock = claim_workspace(slot_id)
    if lock is None:
        sys.exit(0)
    run_viewer(app, lock)


def send_open_request(slot: WindowSlot, request: OpenRequest) -> None:
    node = Node("launcher")
    node.start()
    try:
        reply = None
        if node.wait_registered(OPEN_PATH_TIMEOUT):
            payload = {"slot_id": slot.slot_id, "path": request.path, "database_name": request.database_name}
            reply = node.request("slot.open_path", payload, dst="viewer", timeout=OPEN_PATH_TIMEOUT)
        if reply is None:
            AppLogger.warning(f"Workspace '{slot_title(slot)}' did not answer; could not open {request.path} there. Try again or pick another workspace.")
            return
        owner = WorkspaceLock.read_owner(slot.slot_id, lock_dir=_lock_dir())
        if owner is not None:
            activate_window(owner.hwnd)
    finally:
        node.stop()


def run_open_path(app, path: str) -> NoReturn:
    store = WorkspaceStore.instance()
    slots = store.list_slots()
    open_ids = WorkspaceLock.open_slot_ids([slot.slot_id for slot in slots], lock_dir=_lock_dir())
    running = bool(open_ids)
    if not running:
        open_ids = set(store.get_restore_slot_ids())
    path = normalize_path(path)
    databases = databases_containing(path)
    picked = WorkspacePickerDialog.ask(slots, open_ids, allow_open=True, databases=databases if len(databases) >= 2 else [])
    if picked is None:
        sys.exit(0)
    fixed_database = databases[0] if len(databases) == 1 else ""
    request = OpenRequest(path, picked.database_name or fixed_database)
    if running and picked.slot_id in open_ids:
        send_open_request(next(slot for slot in slots if slot.slot_id == picked.slot_id), request)
        sys.exit(0)
    slot_id = picked.slot_id or store.create_slot_from(store.latest_slot_id())
    if not running:
        restore_session(slot_id)
    lock = claim_workspace(slot_id)
    if lock is None:
        sys.exit(0)
    run_viewer(app, lock, open_request=request)
