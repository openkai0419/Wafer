import os
from unittest.mock import patch, MagicMock

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


def test_lock_held_by_alive_process_skips(ext_dir):
    plugin_dir = _make_plugin(ext_dir, "ext_a")
    installer_queue.enqueue(ext_dir, "ext_a", plugin_dir)

    fake_lock = MagicMock()
    fake_lock.acquire.return_value = False

    pa, pb = _patch_phases(True, True)
    with patch("wafer.plugin.startup_install.SafeProcessLock", return_value=fake_lock), \
         patch.object(startup_install, "_acquire_with_wait", return_value=False), \
         pa as ma, pb as mb:
        result = startup_install.run_pending_installs(ext_dir)

    assert result is False
    ma.assert_not_called()
    mb.assert_not_called()
    assert len(installer_queue.read_queue(ext_dir)) == 1


def test_lock_holder_drains_other_processes_skip(ext_dir):
    plugin_dir = _make_plugin(ext_dir, "ext_a")
    installer_queue.enqueue(ext_dir, "ext_a", plugin_dir)

    pa, pb = _patch_phases(True, True)
    with pa, pb:
        startup_install.run_pending_installs(ext_dir)

    pa, pb = _patch_phases(True, True)
    with pa as ma, pb as mb:
        result = startup_install.run_pending_installs(ext_dir)

    assert result is False
    ma.assert_not_called()
    mb.assert_not_called()


def test_acquire_with_wait_succeeds_immediately(ext_dir):
    lock = MagicMock()
    lock.acquire.side_effect = [True]
    assert startup_install._acquire_with_wait(lock, 1.0) is True


def test_acquire_with_wait_times_out(ext_dir):
    lock = MagicMock()
    lock.acquire.return_value = False
    assert startup_install._acquire_with_wait(lock, 0.05) is False


def test_blocking_path_used_without_qapp(ext_dir):
    plugin_dir = _make_plugin(ext_dir, "ext_a")
    installer_queue.enqueue(ext_dir, "ext_a", plugin_dir)

    pa, pb = _patch_phases(True, True)
    with pa, pb, patch("PySide6.QtWidgets.QApplication") as qapp_cls:
        qapp_cls.instance.return_value = None
        startup_install.run_pending_installs(ext_dir)

    assert installer_queue.read_queue(ext_dir) == []
