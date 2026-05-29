import os
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from wafer.plugin import installer_queue, startup_install
from wafer.plugin.installer import InstallResult


@pytest.fixture
def ext_dir(tmp_path):
    d = tmp_path / "extensions"
    d.mkdir()
    return str(d)


def _make_plugin(ext_dir: str, name: str) -> str:
    p = os.path.join(ext_dir, name)
    os.makedirs(p, exist_ok=True)
    return p


def _patch_phases(ok_a: bool = True, ok_b: bool = True):
    return (
        patch.object(startup_install, "install_requirements_only", return_value=InstallResult(success=ok_a)),
        patch.object(startup_install, "run_post_install", return_value=InstallResult(success=ok_b, post_install_ok=ok_b)),
    )


def test_no_pending_returns_false(ext_dir):
    assert startup_install.run_pending_installs(ext_dir) is False


def test_processes_queue_and_clears_on_success(ext_dir):
    plugin_dir = _make_plugin(ext_dir, "ext_a")
    installer_queue.enqueue(ext_dir, "ext_a", plugin_dir)

    pa, pb = _patch_phases(True, True)
    with pa as ma, pb as mb:
        result = startup_install.run_pending_installs(ext_dir)

    assert result is True
    ma.assert_called_once()
    mb.assert_called_once()
    assert installer_queue.read_queue(ext_dir) == []


def test_failed_phase_a_skips_phase_b(ext_dir):
    plugin_dir = _make_plugin(ext_dir, "ext_bad")
    installer_queue.enqueue(ext_dir, "ext_bad", plugin_dir)

    pa, pb = _patch_phases(False, True)
    with pa, pb as mb, patch("wafer.plugin.startup_install.Notifier") as notifier:
        startup_install.run_pending_installs(ext_dir)

    mb.assert_not_called()
    assert installer_queue.read_queue(ext_dir) == []
    notifier.warning.assert_called_once()


def test_failed_phase_b_marked_failed(ext_dir):
    plugin_dir = _make_plugin(ext_dir, "ext_bad")
    installer_queue.enqueue(ext_dir, "ext_bad", plugin_dir)

    pa, pb = _patch_phases(True, False)
    with pa, pb, patch("wafer.plugin.startup_install.Notifier") as notifier:
        startup_install.run_pending_installs(ext_dir)

    assert installer_queue.read_queue(ext_dir) == []
    notifier.warning.assert_called_once()


def test_phase_a_exception_treated_as_failure(ext_dir):
    plugin_dir = _make_plugin(ext_dir, "ext_x")
    installer_queue.enqueue(ext_dir, "ext_x", plugin_dir)

    with patch.object(startup_install, "install_requirements_only", side_effect=RuntimeError("boom")), \
         patch.object(startup_install, "run_post_install", return_value=InstallResult(success=True, post_install_ok=True)) as mb, \
         patch("wafer.plugin.startup_install.Notifier") as notifier:
        startup_install.run_pending_installs(ext_dir)

    mb.assert_not_called()
    assert installer_queue.read_queue(ext_dir) == []
    notifier.warning.assert_called_once()


def test_missing_plugin_dir_marked_failed(ext_dir):
    installer_queue.enqueue(ext_dir, "ghost", os.path.join(ext_dir, "ghost"))

    pa, pb = _patch_phases(True, True)
    with pa as ma, pb as mb, patch("wafer.plugin.startup_install.Notifier"):
        startup_install.run_pending_installs(ext_dir)

    ma.assert_not_called()
    mb.assert_not_called()
    assert installer_queue.read_queue(ext_dir) == []


def test_status_writer_receives_progress(ext_dir):
    plugin_dir = _make_plugin(ext_dir, "ext_a")
    installer_queue.enqueue(ext_dir, "ext_a", plugin_dir)

    pa, pb = _patch_phases(True, True)
    with pa, pb, patch("wafer.plugin.startup_install.InstallStatusWriter") as cls:
        writer = cls.return_value
        startup_install.run_pending_installs(ext_dir)

    cls.assert_called_once_with(total=1)
    assert writer.begin_item.call_count == 2
    writer.finish.assert_called_once()


def test_cancel_during_phase_a_keeps_remaining_in_queue(ext_dir):
    plugin_dir = _make_plugin(ext_dir, "ext_a")
    installer_queue.enqueue(ext_dir, "ext_a", plugin_dir)

    cancelled_result = InstallResult(success=False, cancelled=True)
    with patch.object(startup_install, "install_requirements_only", return_value=cancelled_result), \
         patch.object(startup_install, "run_post_install") as mb, \
         patch("wafer.plugin.startup_install.Notifier"):
        result = startup_install.run_pending_installs(ext_dir)

    assert result is True
    mb.assert_not_called()
    remaining = installer_queue.read_queue(ext_dir)
    assert len(remaining) == 1
    assert remaining[0].name == "ext_a"


def test_cancel_request_before_loop_skips_all(ext_dir):
    plugin_dir = _make_plugin(ext_dir, "ext_a")
    installer_queue.enqueue(ext_dir, "ext_a", plugin_dir)

    pa, pb = _patch_phases(True, True)
    with pa as ma, pb as mb, \
         patch.object(startup_install, "is_cancel_requested", return_value=True), \
         patch("wafer.plugin.startup_install.Notifier"):
        result = startup_install.run_pending_installs(ext_dir)

    assert result is True
    ma.assert_not_called()
    mb.assert_not_called()
    assert len(installer_queue.read_queue(ext_dir)) == 1


def test_open_files_oserror_does_not_abort_lock_scan(ext_dir):
    packages_dir = os.path.join(ext_dir, ".packages")
    os.makedirs(packages_dir)

    broken_proc = Mock(pid=123)
    broken_proc.open_files.side_effect = OSError(433, "device missing")

    locked_proc = Mock(pid=456)
    locked_proc.open_files.return_value = [SimpleNamespace(path=os.path.join(packages_dir, "pkg", "locked.pyd"))]

    with patch.object(startup_install.os, "getpid", return_value=999), \
         patch.object(startup_install.psutil, "process_iter", return_value=[broken_proc, locked_proc]), \
         patch.object(startup_install.AppLogger, "warning") as warning, \
         patch("wafer.core.platform.process.AppProcess.terminate_and_wait") as terminate:
        startup_install._terminate_processes_holding_packages(ext_dir)

    warning.assert_called_once()
    terminate.assert_called_once_with([locked_proc])


def test_status_writer_created_before_lock_scan(ext_dir):
    plugin_dir = _make_plugin(ext_dir, "ext_a")
    installer_queue.enqueue(ext_dir, "ext_a", plugin_dir)
    events = []

    class Writer:
        def __init__(self, total):
            events.append(("writer", total))

        def begin_item(self, *_args):
            return None

        def append_log(self, _line):
            return None

        def finish(self, error=None):
            events.append(("finish", error))

    cancelled_result = InstallResult(success=False, cancelled=True)
    with patch.object(startup_install, "InstallStatusWriter", Writer), \
         patch.object(startup_install, "_terminate_processes_holding_packages", side_effect=lambda d: events.append(("terminate", d))), \
         patch.object(startup_install, "install_requirements_only", return_value=cancelled_result), \
         patch.object(startup_install, "run_post_install") as mb, \
         patch("wafer.plugin.startup_install.Notifier"):
        startup_install.run_pending_installs(ext_dir)

    mb.assert_not_called()
    assert events[0] == ("writer", 1)
    assert events[1] == ("terminate", ext_dir)

