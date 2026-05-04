from __future__ import annotations

import time

from ...core.platform.process import AppProcess

WORKER_SHUTDOWN_TIMEOUT = 5.0
WORKER_SHUTDOWN_POLL_INTERVAL = 0.1


def wait_worker_stopped(kind: str, db_name: str, plugin: str, timeout: float) -> bool:
    args = (f"--{kind}", db_name, "--plugin", plugin)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not AppProcess.get_by_args_subset(*args):
            return True
        time.sleep(WORKER_SHUTDOWN_POLL_INTERVAL)
    return not AppProcess.get_by_args_subset(*args)
