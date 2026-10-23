from unittest.mock import Mock, patch

from wafer.plugin import install_wait


class DummyLock:
    def __init__(self, _name="", *, acquire_result):
        self._acquire_result = acquire_result
        self.released = False

    def acquire(self):
        return self._acquire_result

    def release(self):
        self.released = True


class _Proc:
    def __init__(self, pid):
        self.pid = pid


def test_wait_for_install_returns_when_other_waiter_finishes():
    on_idle = Mock()
    wait_for_tray = Mock()

    with (
        patch.object(install_wait, "has_pending_install", side_effect=[True, True, False]),
        patch.object(install_wait, "SafeProcessLock", side_effect=lambda name: DummyLock(name, acquire_result=False)),
        patch.object(install_wait.time, "sleep") as sleep,
        patch.object(install_wait, "prepare_tray") as prepare,
    ):
        install_wait.wait_for_install(restart_idle_tray=Mock(), wait_for_tray=wait_for_tray, on_idle=on_idle)

    prepare.assert_not_called()
    wait_for_tray.assert_not_called()
    sleep.assert_called_once_with(install_wait.POLL_INTERVAL)
    on_idle.assert_called_once()


def test_wait_for_install_releases_waiter_lock_on_skip():
    lock = DummyLock(acquire_result=True)
    wait_for_tray = Mock()

    with (
        patch.object(install_wait, "has_pending_install", return_value=True),
        patch.object(install_wait, "SafeProcessLock", return_value=lock),
        patch.object(install_wait, "prepare_tray", return_value=None),
    ):
        install_wait.wait_for_install(restart_idle_tray=Mock(), wait_for_tray=wait_for_tray)

    wait_for_tray.assert_not_called()
    assert lock.released is True


def test_wait_for_install_waits_for_the_tray_then_releases_the_lock():
    lock = DummyLock(acquire_result=True)
    wait_for_tray = Mock()

    with (
        patch.object(install_wait, "has_pending_install", return_value=True),
        patch.object(install_wait, "SafeProcessLock", return_value=lock),
        patch.object(install_wait, "prepare_tray", return_value=42),
    ):
        install_wait.wait_for_install(restart_idle_tray=Mock(), wait_for_tray=wait_for_tray)

    wait_for_tray.assert_called_once_with(42)
    assert lock.released is True


def test_wait_for_install_does_nothing_without_pending_install():
    with (
        patch.object(install_wait, "has_pending_install", return_value=False),
        patch.object(install_wait, "SafeProcessLock") as lock_cls,
    ):
        install_wait.wait_for_install(restart_idle_tray=Mock(), wait_for_tray=Mock())

    lock_cls.assert_not_called()


def test_is_install_finished_done_phase_exits_even_if_file_lingers():
    with patch.object(install_wait, "has_pending_install", return_value=True):
        assert install_wait.is_install_finished({"phase": "done"}, False) is True
        assert install_wait.is_install_finished({"phase": "error"}, False) is True
        assert install_wait.is_install_finished({"phase": "post_install"}, False) is False


def test_is_install_finished_missing_status_respects_queue():
    with patch.object(install_wait, "has_pending_install", return_value=True):
        assert install_wait.is_install_finished(None, False) is False
        assert install_wait.is_install_finished(None, True) is True
    with patch.object(install_wait, "has_pending_install", return_value=False):
        assert install_wait.is_install_finished(None, False) is True


def test_status_is_active_only_for_in_progress_phases():
    assert install_wait.status_is_active({"phase": "pip"}) is True
    assert install_wait.status_is_active({"phase": "post_install"}) is True
    assert install_wait.status_is_active({"phase": "done"}) is False
    assert install_wait.status_is_active({"phase": "error"}) is False
    assert install_wait.status_is_active(None) is False


def test_prepare_tray_spawns_tray_when_none_runs():
    with (
        patch.object(install_wait.AppProcess, "get_by_args_subset", return_value=[]),
        patch.object(install_wait.AppProcess, "new_main", return_value=_Proc(77)) as new_main,
    ):
        assert install_wait.prepare_tray(Mock()) == 77
    new_main.assert_called_once_with("--tray")


def test_prepare_tray_treats_stale_terminal_status_as_not_installing():
    restart = Mock(return_value=True)
    with (
        patch.object(install_wait.AppProcess, "get_by_args_subset", return_value=[_Proc(123)]),
        patch.object(install_wait, "read_status", return_value={"phase": "done"}),
        patch.object(install_wait.AppProcess, "terminate_and_wait") as terminate,
        patch.object(install_wait.AppProcess, "new_main", return_value=_Proc(999)),
    ):
        assert install_wait.prepare_tray(restart) == 999
    restart.assert_called_once()
    terminate.assert_called_once()


def test_prepare_tray_attaches_when_install_in_progress():
    restart = Mock()
    with (
        patch.object(install_wait.AppProcess, "get_by_args_subset", return_value=[_Proc(123)]),
        patch.object(install_wait, "read_status", return_value={"phase": "pip"}),
    ):
        assert install_wait.prepare_tray(restart) == 123
    restart.assert_not_called()


def test_prepare_tray_keeps_idle_tray_when_restart_is_declined():
    with (
        patch.object(install_wait.AppProcess, "get_by_args_subset", return_value=[_Proc(123)]),
        patch.object(install_wait, "read_status", return_value=None),
        patch.object(install_wait.AppProcess, "terminate_and_wait") as terminate,
        patch.object(install_wait.AppProcess, "new_main") as new_main,
    ):
        assert install_wait.prepare_tray(Mock(return_value=False)) is None
    terminate.assert_not_called()
    new_main.assert_not_called()


def test_poll_until_done_stops_when_tray_exits():
    on_status = Mock()
    with patch.object(install_wait.psutil, "pid_exists", return_value=False):
        install_wait.poll_until_done(5, on_status=on_status)
    on_status.assert_not_called()


def test_poll_until_done_reports_each_status_until_done():
    statuses = [{"phase": "pip"}, {"phase": "done"}]
    seen = []
    with (
        patch.object(install_wait.psutil, "pid_exists", return_value=True),
        patch.object(install_wait, "read_status", side_effect=statuses),
        patch.object(install_wait.time, "sleep"),
    ):
        install_wait.poll_until_done(5, on_status=seen.append)
    assert seen == statuses


def test_headless_wait_never_restarts_an_idle_tray():
    lock = DummyLock(acquire_result=True)
    with (
        patch.object(install_wait, "has_pending_install", return_value=True),
        patch.object(install_wait, "SafeProcessLock", return_value=lock),
        patch.object(install_wait.AppProcess, "get_by_args_subset", return_value=[_Proc(123)]),
        patch.object(install_wait, "read_status", return_value=None),
        patch.object(install_wait.AppProcess, "terminate_and_wait") as terminate,
        patch.object(install_wait.AppProcess, "new_main") as new_main,
    ):
        install_wait.wait_for_install_headless()
    terminate.assert_not_called()
    new_main.assert_not_called()
    assert lock.released is True


def test_headless_wait_logs_each_phase_once():
    with (
        patch.object(install_wait.psutil, "pid_exists", return_value=True),
        patch.object(install_wait, "read_status", side_effect=[{"phase": "pip"}, {"phase": "pip"}, {"phase": "done"}]),
        patch.object(install_wait.time, "sleep"),
        patch.object(install_wait.AppLogger, "info") as info,
    ):
        install_wait._log_until_done(5)
    assert [c.args[0] for c in info.call_args_list] == ["[InstallWaiter] Installing", "[InstallWaiter] Finalizing"]


def test_describe_status_names_the_current_item():
    status = {"phase": "pip", "current": {"name": "wd14", "index": 1, "total": 2}}
    assert install_wait.describe_status(status) == "Installing wd14 (1/2)"
    assert install_wait.describe_status(None) == "Waiting"
