from __future__ import annotations

from ...core.common.paths import resolve_temp_path
from ...core.platform.foreground import activate_window
from ...core.platform.process import AppProcess
from ...core.platform.window_lock import WindowLock, claim_window
from ...core.store.workspace import WorkspaceStore

SESSION_ID = "webui"
LOCK_FILENAME = "webui_window.lock"


def lock_path() -> str:
    return resolve_temp_path(LOCK_FILENAME)


class WebUILock(WindowLock):
    @classmethod
    def acquire(cls) -> WebUILock | None:
        return cls.acquire_path(lock_path())

    @classmethod
    def is_open(cls) -> bool:
        probe = cls.acquire()
        if probe is None:
            return True
        probe.release()
        return False


def activate_webui_window() -> bool:
    owner = WindowLock.read_owner_at(lock_path())
    if owner is None:
        return False
    activate_window(owner.hwnd)
    return True


def claim_webui() -> WebUILock | None:
    return claim_window(WebUILock.acquire, activate_webui_window)


def restore_webui() -> None:
    if WorkspaceStore.instance().get_restore_webui() and not WebUILock.is_open():
        AppProcess.new_main("--webui", "--no-browser")


def replace_webui() -> None:
    AppProcess.new_main("--webui", "--no-browser", extra_env={"WAFER_REPLACE_WEBUI": "1"})
