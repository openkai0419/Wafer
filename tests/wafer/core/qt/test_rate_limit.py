import time
import pytest
from unittest.mock import MagicMock
from PySide6 import QtWidgets
from wafer.core.qt.rate_limit import QtDebounceManager


def _flush_events(ms=100, step=10):
    app = QtWidgets.QApplication.instance()
    elapsed = 0
    while elapsed < ms:
        app.processEvents()
        time.sleep(step / 1000)
        elapsed += step
    app.processEvents()


class TestQtDebounceManager:
    @pytest.fixture
    def manager(self, qtbot):
        return QtDebounceManager()

    def test_debounce_fires_after_delay(self, manager, qtbot):
        cb = MagicMock()
        manager.debounce('k', 30, cb, 1, x=2)
        cb.assert_not_called()
        _flush_events(80)
        cb.assert_called_once_with(1, x=2)

    def test_debounce_resets_timer(self, manager, qtbot):
        cb = MagicMock()
        manager.debounce('k', 50, cb, 'a')
        manager.debounce('k', 50, cb, 'b')
        _flush_events(100)
        cb.assert_called_once_with('b')

    def test_cancel_prevents_fire(self, manager, qtbot):
        cb = MagicMock()
        manager.debounce('k', 30, cb)
        manager.cancel('k')
        _flush_events(80)
        cb.assert_not_called()

    def test_cancel_nonexistent_key_noop(self, manager, qtbot):
        manager.cancel('no_such_key')

    def test_independent_keys(self, manager, qtbot):
        cb1 = MagicMock()
        cb2 = MagicMock()
        manager.debounce('a', 30, cb1)
        manager.debounce('b', 30, cb2)
        _flush_events(80)
        cb1.assert_called_once()
        cb2.assert_called_once()

    def test_cancel_one_key_keeps_other(self, manager, qtbot):
        cb1 = MagicMock()
        cb2 = MagicMock()
        manager.debounce('a', 30, cb1)
        manager.debounce('b', 30, cb2)
        manager.cancel('a')
        _flush_events(80)
        cb1.assert_not_called()
        cb2.assert_called_once()

    def test_timer_cleaned_after_fire(self, manager, qtbot):
        cb = MagicMock()
        manager.debounce('k', 30, cb)
        _flush_events(80)
        assert 'k' not in manager._timers


class TestQtThrottleManager:
    @pytest.fixture
    def manager(self, qtbot):
        from wafer.core.qt.rate_limit import QtThrottleManager
        return QtThrottleManager()

    def test_throttle_fires_immediately(self, manager, qtbot):
        cb = MagicMock()
        manager.throttle('k', 200, 100, cb, 'first')
        cb.assert_called_once_with('first')

    def test_throttle_idle_fires_with_latest_args(self, manager, qtbot):
        received = []

        def cb(val):
            received.append(val)

        manager.throttle('k', 5000, 50, cb, 'first')
        assert received == ['first']

        manager.throttle('k', 5000, 50, cb, 'second')
        manager.throttle('k', 5000, 50, cb, 'third')

        _flush_events(150)
        assert received[-1] == 'third'
