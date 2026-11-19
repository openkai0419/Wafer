from __future__ import annotations

import subprocess
import time

import psutil

from ....core.platform.process import AppProcess

WORKER_SHUTDOWN_TIMEOUT = 5.0
WORKER_SHUTDOWN_POLL_INTERVAL = 0.1


def wait_workers_stopped(kind: str, db_name: str, procs: dict[str, subprocess.Popen], timeout: float) -> list[str]:
    deadline = time.monotonic() + timeout
    running: dict[psutil.Process, str] = {}
    exited_early = []
    for plugin, proc in procs.items():
        if proc.poll() is not None:
            exited_early.append(plugin)
            continue
        try:
            running[psutil.Process(proc.pid)] = plugin
        except psutil.NoSuchProcess:
            continue
    _, alive = psutil.wait_procs(list(running), timeout=timeout)
    still_running = [running[p] for p in alive]
    for plugin in exited_early:
        if not wait_worker_stopped(kind, db_name, plugin, max(0.0, deadline - time.monotonic())):
            still_running.append(plugin)
    return still_running


def wait_worker_stopped(kind: str, db_name: str, plugin: str, timeout: float) -> bool:
    args = (f"--{kind}", db_name, "--plugin", plugin)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not AppProcess.get_by_args_subset(*args):
            return True
        time.sleep(WORKER_SHUTDOWN_POLL_INTERVAL)
    return not AppProcess.get_by_args_subset(*args)
