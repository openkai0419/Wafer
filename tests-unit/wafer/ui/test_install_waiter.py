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


def test_compile():
    py_compile.compile("wafer/ui/install_waiter.py")