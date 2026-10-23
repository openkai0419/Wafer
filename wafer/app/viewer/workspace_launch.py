import os
import sys
from dataclasses import dataclass
from time import monotonic, sleep
from typing import NoReturn

from PySide6 import QtWidgets

from ...core.common.paths import normalize_path
from ...core.lang.manager import t
from ...core.db.path_scope import databases_containing
from ...core.ipc.node import Node
from ...core.ipc.transport import NODE_TIMEOUT, RECONNECT_FORCE_INTERVAL
from ...core.logs import AppLogger
from ...core.platform.foreground import activate_window, allow_foreground
from ...core.platform.process import AppProcess
from ...core.platform.workspace_lock import WorkspaceLock
from ...core.store.workspace import WindowSlot, WorkspaceStore
from ...qt.common.app_icon import get_icon
from .widgets.workspace_labels import slot_title
from .widgets.workspace_picker import PickResult, WorkspacePickerDialog

OPEN_PATH_TIMEOUT = 5
OPEN_PATH_ATTEMPT_TIMEOUT = 1.0
VIEWER_REJOIN_SECONDS = NODE_TIMEOUT + RECONNECT_FORCE_INTERVAL
CLAIM_RETRIES = 5
CLAIM_RETRY_INTERVAL = 0.05


@dataclass(frozen=True)
class OpenRequest:
    path: str
    database_name: str


def slots_to_restore(restore_ids: list[str], chosen_slot_id: str | None) -> list[str]:
    return [slot_id for slot_id in restore_ids if slot_id != chosen_slot_id]


def first_restore_slot_id() -> str | None:
    restore_ids = WorkspaceStore.instance().get_restore_slot_ids()
    return restore_ids[0] if restore_ids else None


def spawn_viewer(slot_id: str, open_request: OpenRequest | None = None):
    args = ["--viewer", "--slot", slot_id]
    if open_request is not None:
        args += ["--open-path", open_request.path]
        if open_request.database_name:
            args += ["--open-database", open_request.database_name]
    return AppProcess.new_main(*args)


def restore_session(skip_slot_id: str | None) -> None:
    store = WorkspaceStore.instance()
    for slot_id in slots_to_restore(store.get_restore_slot_ids(), skip_slot_id):
        spawn_viewer(slot_id)
    if store.get_restore_webui():
        store.set_restore_webui(False)
        AppProcess.new_main("--webui", "--no-browser")


def wait_for_pending_install(app) -> None:
    from ...qt.install.waiter import wait_for_install_complete

    wait_for_install_complete(icon=get_icon(), app=app)


def is_openable_path(path: str | None) -> bool:
    if path and os.path.isfile(path):
        return True
    AppLogger.warning(f"Open path ignored, not a file: {path}")
    return False


def activate_workspace_window(slot_id: str) -> bool:
    owner = WorkspaceLock.read_owner(slot_id)
    if owner is None:
        return False
    activate_window(owner.hwnd)
    return True


def claim_workspace(slot_id: str | None) -> WorkspaceLock | None:
    store = WorkspaceStore.instance()
    if slot_id is None or store.get_slot(slot_id) is None:
        slot_id = store.create_slot_from(None)
    for attempt in range(CLAIM_RETRIES + 1):
        lock = WorkspaceLock.acquire(slot_id)
        if lock is not None:
            return lock
        if activate_workspace_window(slot_id) or attempt == CLAIM_RETRIES:
            break
        sleep(CLAIM_RETRY_INTERVAL)
    AppLogger.info(f"workspace {slot_id} is already open in another window; not opening a duplicate")
    return None


def run_viewer(app, lock: WorkspaceLock, open_request: OpenRequest | None = None) -> NoReturn:
    from .mainwindow import MainWindow

    window = MainWindow(get_icon(), workspace_lock=lock, open_request=open_request)
    window.show()
    sys.exit(app.exec())


def run_pick(app, seed_slot_id: str | None) -> NoReturn:
    store = WorkspaceStore.instance()
    slots = store.list_slots()
    open_ids = WorkspaceLock.open_slot_ids([slot.slot_id for slot in slots])
    if all(slot.slot_id in open_ids for slot in slots):
        picked = PickResult(None, "")
    else:
        picked = WorkspacePickerDialog.ask(slots, open_ids, allow_open=False, databases=[])
    if picked is None:
        sys.exit(0)
    slot_id = picked.slot_id if picked.slot_id is not None else store.create_slot_from(seed_slot_id or store.latest_slot_id())
    lock = claim_workspace(slot_id)
    if lock is None:
        sys.exit(0)
    run_viewer(app, lock)


def deliver_open_request(slot: WindowSlot, request: OpenRequest) -> bool:
    node = Node("launcher")
    node.start()
    try:
        if not node.wait_registered(OPEN_PATH_TIMEOUT):
            return False
        payload = {"slot_id": slot.slot_id, "path": request.path, "database_name": request.database_name}
        deadline = monotonic() + VIEWER_REJOIN_SECONDS
        while node.request("slot.open_path", payload, dst="viewer", timeout=OPEN_PATH_ATTEMPT_TIMEOUT) is None:
            if monotonic() >= deadline:
                return False
            AppLogger.info(f"slot.open_path: workspace {slot.slot_id} has not answered yet; it may still be reconnecting to a restarted tray, retrying")
        return True
    finally:
        node.stop()


def send_open_request(slot: WindowSlot, request: OpenRequest) -> None:
    if deliver_open_request(slot, request):
        activate_workspace_window(slot.slot_id)
        return
    AppLogger.warning(f"Workspace '{slot_title(slot)}' did not answer; could not open {request.path} there. Try again or pick another workspace.")
    QtWidgets.QMessageBox.warning(None, t("Open Path"), t("{name} did not respond. Try again.", name=slot_title(slot)))


def claim_or_hand_over(slot_id: str | None, request: OpenRequest | None) -> WorkspaceLock | None:
    lock = claim_workspace(slot_id)
    if lock is None and request is not None and slot_id is not None:
        taken_slot = WorkspaceStore.instance().get_slot(slot_id)
        if taken_slot is not None:
            send_open_request(taken_slot, request)
    return lock


def run_open_path(app, path: str) -> NoReturn:
    store = WorkspaceStore.instance()
    slots = store.list_slots()
    open_ids = WorkspaceLock.open_slot_ids([slot.slot_id for slot in slots])
    running = bool(open_ids)
    first_slot_id = None
    if not running:
        wait_for_pending_install(app)
        open_ids = set(store.get_restore_slot_ids())
        first_slot_id = first_restore_slot_id()
    path = normalize_path(path)
    databases = databases_containing(path)
    picked = WorkspacePickerDialog.ask(slots, open_ids, allow_open=True, databases=databases if len(databases) >= 2 else [])
    if picked is None:
        if not running:
            restore_session(None)
        sys.exit(0)
    fixed_database = databases[0] if len(databases) == 1 else ""
    request = OpenRequest(path, picked.database_name or fixed_database)
    if running and picked.slot_id in open_ids:
        send_open_request(next(slot for slot in slots if slot.slot_id == picked.slot_id), request)
        sys.exit(0)
    slot_id = picked.slot_id or store.create_slot_from(first_slot_id or store.latest_slot_id())
    if not running:
        restore_session(slot_id)
    allow_foreground(spawn_viewer(slot_id, request).pid)
    sys.exit(0)
