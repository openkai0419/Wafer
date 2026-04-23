import os
from unittest.mock import patch

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
