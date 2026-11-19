import sys
from pathlib import Path

import psutil
import pytest

from debug import profile_setup
from test_support.debug_instances import (
    CHECKOUT,
    agent_call,
    checkout_processes,
    core_pids,
    explorer_menu_snapshot,
    isolate_debug_dirs,
    quit_all_normal,
    spawn_normal,
    still_running,
    terminate_checkout_processes,
    visible_window_titles,
    wait_until,
)
from wafer.core.common.paths import get_plugin_dir, profile_data_root
from wafer.core.ipc.node import Node
from wafer.core.platform.process import AppProcess
from wafer.plugin import installer_queue

pytestmark = [
    pytest.mark.slow,
    pytest.mark.timeout(600),
    pytest.mark.skipif(sys.platform != "win32", reason="runs the real Windows app"),
]

DEBUG_PROFILE = "debug-smoke"
START_TIMEOUT = 120.0
EXIT_TIMEOUT = 60.0


class Instances:
    def __init__(self, cwd: Path):
        self.cwd = cwd
        self.debug_node: Node | None = None

    def start_debug(self) -> dict[str, list[int]]:
        profile_setup.launch_process(CHECKOUT, DEBUG_PROFILE)
        pids = wait_until(lambda: core_pids(AppProcess.list_profile_processes(DEBUG_PROFILE)), START_TIMEOUT, f"{DEBUG_PROFILE} tray, viewer and indexer")
        self.debug_node = Node("debug", profile=DEBUG_PROFILE)
        self.debug_node.start()
        assert self.debug_node.wait_registered(START_TIMEOUT), f"the broker of {DEBUG_PROFILE} did not register the test node"
        viewer = pids["viewer"][0]
        wait_until(lambda: self.debug_state(viewer), START_TIMEOUT, f"the MainWindow of {DEBUG_PROFILE}")
        return pids

    def debug_state(self, viewer: int):
        reply = agent_call(self.debug_node, viewer, "get_state")
        return reply is not None and reply["result"]

    def start_normal(self) -> dict[str, list[int]]:
        spawn_normal(self.cwd)
        pids = wait_until(lambda: core_pids(checkout_processes(self.cwd)), START_TIMEOUT, "the normal instance's tray, viewer and indexer")
        wait_until(lambda: visible_window_titles(pids["viewer"][0]), START_TIMEOUT, "the normal instance's Viewer window")
        return pids

    def quit_all_debug(self) -> None:
        self.debug_node.send("app.quit_all", dst="tray")
        wait_until(lambda: not AppProcess.list_profile_processes(DEBUG_PROFILE), EXIT_TIMEOUT, f"every process of {DEBUG_PROFILE} to exit")

    def stop_all(self) -> None:
        if self.debug_node is not None:
            self.debug_node.stop()
            self.debug_node = None
        try:
            profile_setup.stop_profile(DEBUG_PROFILE)
        finally:
            terminate_checkout_processes(self.cwd)


@pytest.fixture
def instances(tmp_path, monkeypatch):
    dirs = isolate_debug_dirs(tmp_path, monkeypatch)
    if AppProcess.list_profile_processes(DEBUG_PROFILE):
        pytest.skip(f"{DEBUG_PROFILE} is already running; this test does not stop processes it did not start")
    if installer_queue.has_pending_queue(get_plugin_dir()):
        pytest.skip("an extension install is queued; a normal tray would run it")
    menu_before = explorer_menu_snapshot()
    launched = Instances(dirs.cwd)
    try:
        yield launched
    finally:
        launched.stop_all()
        assert not AppProcess.list_profile_processes(DEBUG_PROFILE)
        assert not checkout_processes(dirs.cwd)
        assert explorer_menu_snapshot() == menu_before


def test_quit_all_of_normal_keeps_debug(instances):
    debug = instances.start_debug()
    normal = instances.start_normal()

    quit_all_normal(instances.cwd)

    wait_until(lambda: not checkout_processes(instances.cwd), EXIT_TIMEOUT, "every process of the normal instance to exit")
    assert still_running(debug), f"Quit All of the normal Wafer stopped {DEBUG_PROFILE}: {debug}"
    assert instances.debug_state(debug["viewer"][0]), f"the Viewer of {DEBUG_PROFILE} stopped answering"
    assert not any(psutil.pid_exists(pid) for pids in normal.values() for pid in pids)


def test_quit_all_of_debug_keeps_normal(instances):
    debug = instances.start_debug()
    normal = instances.start_normal()

    instances.quit_all_debug()

    assert still_running(normal), f"Quit All of {DEBUG_PROFILE} stopped the normal Wafer: {normal}"
    assert core_pids(checkout_processes(instances.cwd))
    assert not any(psutil.pid_exists(pid) for pids in debug.values() for pid in pids)


def test_debug_launch_leaves_explorer_menu_alone(instances):
    before = explorer_menu_snapshot()

    debug = instances.start_debug()

    assert explorer_menu_snapshot() == before
    titles = visible_window_titles(debug["viewer"][0])
    assert any(title.startswith(f"[{DEBUG_PROFILE}] ") for title in titles), titles
    logs = "".join(path.read_text(encoding="utf-8", errors="replace") for path in (profile_data_root(DEBUG_PROFILE) / ".log").rglob("*.log"))
    assert "Explorer menu sync skipped" in logs
    instances.quit_all_debug()
    assert explorer_menu_snapshot() == before
