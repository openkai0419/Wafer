import py_compile
from unittest.mock import Mock, patch


class DummyLock:
    def __init__(self, _name, *, acquire_result):
        self._acquire_result = acquire_result
        self.released = False

    def acquire(self):
        return self._acquire_result

    def release(self):
        self.released = True


def test_wait_for_install_complete_returns_when_other_waiter_finishes():
    from wafer.qt.install import waiter

    app = Mock()

    def lock_factory(name):
        return DummyLock(name, acquire_result=False)

    with (
        patch.object(waiter, "get_plugin_dir", return_value="extensions"),
        patch.object(waiter.installer_queue, "has_pending_queue", side_effect=[True, True, False]),
        patch.object(waiter, "SafeProcessLock", side_effect=lock_factory),
        patch.object(waiter.time, "sleep") as sleep,
        patch.object(waiter, "_prepare_tray") as prepare,
    ):
        waiter.wait_for_install_complete(app=app)

    prepare.assert_not_called()
    sleep.assert_called_once_with(waiter._POLL_INTERVAL)
    app.processEvents.assert_called_once()


def test_wait_for_install_complete_releases_waiter_lock_on_skip():
    from wafer.qt.install import waiter

    app = Mock()
    lock = DummyLock("wafer_install_waiter", acquire_result=True)

    with (
        patch.object(waiter, "get_plugin_dir", return_value="extensions"),
        patch.object(waiter.installer_queue, "has_pending_queue", side_effect=[True, True, True]),
        patch.object(waiter, "SafeProcessLock", return_value=lock),
        patch.object(waiter, "_prepare_tray", return_value=None),
    ):
        waiter.wait_for_install_complete(app=app)

    assert lock.released is True


def test_is_install_finished_done_phase_exits_even_if_file_lingers():
    from wafer.qt.install import waiter

    with patch.object(waiter.installer_queue, "has_pending_queue", return_value=True):
        assert waiter._is_install_finished({"phase": "done"}, False) is True
        assert waiter._is_install_finished({"phase": "error"}, False) is True
        assert waiter._is_install_finished({"phase": "post_install"}, False) is False


def test_is_install_finished_missing_status_respects_queue():
    from wafer.qt.install import waiter

    with patch.object(waiter.installer_queue, "has_pending_queue", return_value=True):
        assert waiter._is_install_finished(None, False) is False
        assert waiter._is_install_finished(None, True) is True
    with patch.object(waiter.installer_queue, "has_pending_queue", return_value=False):
        assert waiter._is_install_finished(None, False) is True


def test_status_is_active_only_for_in_progress_phases():
    from wafer.qt.install import waiter

    assert waiter._status_is_active({"phase": "pip"}) is True
    assert waiter._status_is_active({"phase": "post_install"}) is True
    assert waiter._status_is_active({"phase": "done"}) is False
    assert waiter._status_is_active({"phase": "error"}) is False
    assert waiter._status_is_active(None) is False


def test_prepare_tray_treats_stale_terminal_status_as_not_installing():
    from wafer.qt.install import waiter

    class _Proc:
        pid = 123

    with (
        patch.object(waiter.AppProcess, "get_by_args_subset", return_value=[_Proc()]),
        patch.object(waiter, "read_status", return_value={"phase": "done"}),
        patch.object(waiter, "_ask_restart_tray", return_value=999) as ask,
    ):
        assert waiter._prepare_tray(parent=None) == 999
    ask.assert_called_once()


def test_prepare_tray_attaches_when_install_in_progress():
    from wafer.qt.install import waiter

    class _Proc:
        pid = 123

    with (
        patch.object(waiter.AppProcess, "get_by_args_subset", return_value=[_Proc()]),
        patch.object(waiter, "read_status", return_value={"phase": "pip"}),
        patch.object(waiter, "_ask_restart_tray") as ask,
    ):
        assert waiter._prepare_tray(parent=None) == 123
    ask.assert_not_called()


def test_compile():
    py_compile.compile("wafer/qt/install/waiter.py")
