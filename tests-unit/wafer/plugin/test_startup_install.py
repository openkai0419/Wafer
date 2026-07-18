import os
from unittest.mock import Mock, patch

import pytest

from wafer.plugin import installer_queue, startup_install
from wafer.plugin.installer import InstallResult

_real_terminate = startup_install._terminate_conflicting_processes


@pytest.fixture
def ext_dir(tmp_path):
    d = tmp_path / "extensions"
    d.mkdir()
    return str(d)


@pytest.fixture(autouse=True)
def _no_real_process_scan():
    with patch.object(startup_install, "_terminate_conflicting_processes"):
        yield


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


def test_terminate_conflicting_kills_app_processes_and_spares_waiter(ext_dir):
    waiter = Mock(pid=100)
    old_viewer = Mock(pid=200)
    other = Mock(pid=300)

    with patch.object(startup_install.SafeProcessLock, "read_owner_pid", return_value=100), \
         patch("wafer.core.platform.process.AppProcess.list_app", return_value=[waiter, old_viewer, other]), \
         patch("wafer.core.platform.process.AppProcess.terminate_and_wait") as terminate:
        _real_terminate()

    terminate.assert_called_once_with([old_viewer, other])


def test_terminate_conflicting_noop_when_only_waiter(ext_dir):
    waiter = Mock(pid=100)

    with patch.object(startup_install.SafeProcessLock, "read_owner_pid", return_value=100), \
         patch("wafer.core.platform.process.AppProcess.list_app", return_value=[waiter]), \
         patch("wafer.core.platform.process.AppProcess.terminate_and_wait") as terminate:
        _real_terminate()

    terminate.assert_not_called()


def test_terminate_conflicting_kills_all_when_no_waiter(ext_dir):
    old_viewer = Mock(pid=200)

    with patch.object(startup_install.SafeProcessLock, "read_owner_pid", return_value=None), \
         patch("wafer.core.platform.process.AppProcess.list_app", return_value=[old_viewer]), \
         patch("wafer.core.platform.process.AppProcess.terminate_and_wait") as terminate:
        _real_terminate()

    terminate.assert_called_once_with([old_viewer])


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
         patch.object(startup_install, "_terminate_conflicting_processes", side_effect=lambda: events.append(("terminate",))), \
         patch.object(startup_install, "install_requirements_only", return_value=cancelled_result), \
         patch.object(startup_install, "run_post_install") as mb, \
         patch("wafer.plugin.startup_install.Notifier"):
        startup_install.run_pending_installs(ext_dir)

    mb.assert_not_called()
    assert events[0] == ("writer", 1)
    assert events[1] == ("terminate",)

