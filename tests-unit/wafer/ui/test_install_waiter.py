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
    from wafer.ui import install_waiter

    app = Mock()

    def lock_factory(name):
        return DummyLock(name, acquire_result=False)

    with patch.object(install_waiter, "get_plugin_dir", return_value="extensions"), \
         patch.object(install_waiter.installer_queue, "has_pending_queue", side_effect=[True, True, False]), \
         patch.object(install_waiter, "SafeProcessLock", side_effect=lock_factory), \
         patch.object(install_waiter.time, "sleep") as sleep, \
         patch.object(install_waiter, "_prepare_tray") as prepare:
        install_waiter.wait_for_install_complete(app=app)

    prepare.assert_not_called()
    sleep.assert_called_once_with(install_waiter._POLL_INTERVAL)
    app.processEvents.assert_called_once()


def test_wait_for_install_complete_releases_waiter_lock_on_skip():
    from wafer.ui import install_waiter

    app = Mock()
    lock = DummyLock("wafer_install_waiter", acquire_result=True)

    with patch.object(install_waiter, "get_plugin_dir", return_value="extensions"), \
            patch.object(install_waiter.installer_queue, "has_pending_queue", side_effect=[True, True, True]), \
         patch.object(install_waiter, "SafeProcessLock", return_value=lock), \
         patch.object(install_waiter, "_prepare_tray", return_value=None):
        install_waiter.wait_for_install_complete(app=app)

    assert lock.released is True


def test_is_install_finished_done_phase_exits_even_if_file_lingers():
    from wafer.ui import install_waiter

    with patch.object(install_waiter.installer_queue, "has_pending_queue", return_value=True):
        assert install_waiter._is_install_finished({"phase": "done"}, False) is True
        assert install_waiter._is_install_finished({"phase": "error"}, False) is True
        assert install_waiter._is_install_finished({"phase": "post_install"}, False) is False


def test_is_install_finished_missing_status_respects_queue():
    from wafer.ui import install_waiter

    with patch.object(install_waiter.installer_queue, "has_pending_queue", return_value=True):
        assert install_waiter._is_install_finished(None, False) is False
        assert install_waiter._is_install_finished(None, True) is True
    with patch.object(install_waiter.installer_queue, "has_pending_queue", return_value=False):
        assert install_waiter._is_install_finished(None, False) is True


def test_status_is_active_only_for_in_progress_phases():
    from wafer.ui import install_waiter

    assert install_waiter._status_is_active({"phase": "pip"}) is True
    assert install_waiter._status_is_active({"phase": "post_install"}) is True
    assert install_waiter._status_is_active({"phase": "done"}) is False
    assert install_waiter._status_is_active({"phase": "error"}) is False
    assert install_waiter._status_is_active(None) is False


def test_prepare_tray_treats_stale_terminal_status_as_not_installing():
    from wafer.ui import install_waiter

    class _Proc:
        pid = 123

    with patch.object(install_waiter.AppProcess, "get_by_args_subset", return_value=[_Proc()]), \
         patch.object(install_waiter, "read_status", return_value={"phase": "done"}), \
         patch.object(install_waiter, "_ask_restart_tray", return_value=999) as ask:
        assert install_waiter._prepare_tray(parent=None) == 999
    ask.assert_called_once()


def test_prepare_tray_attaches_when_install_in_progress():
    from wafer.ui import install_waiter

    class _Proc:
        pid = 123

    with patch.object(install_waiter.AppProcess, "get_by_args_subset", return_value=[_Proc()]), \
         patch.object(install_waiter, "read_status", return_value={"phase": "pip"}), \
         patch.object(install_waiter, "_ask_restart_tray") as ask:
        assert install_waiter._prepare_tray(parent=None) == 123
    ask.assert_not_called()


def test_compile():
    py_compile.compile("wafer/ui/install_waiter.py")