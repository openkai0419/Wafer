from unittest.mock import patch, MagicMock

import pytest

from wayfer.utils.logs import AppLogger


@pytest.fixture(autouse=True)
def _clear_signals():
    signals = [
        AppLogger.on_critical,
        AppLogger.on_error,
        AppLogger.on_warning,
        AppLogger.on_info,
        AppLogger.on_debug,
    ]
    saved = [list(s._callbacks) for s in signals]
    saved_node = AppLogger._node
    saved_role = AppLogger._role
    for s in signals:
        s._callbacks.clear()
    AppLogger._node = None
    AppLogger._role = ''
    yield
    for s, cb in zip(signals, saved):
        s._callbacks = cb
    AppLogger._node = saved_node
    AppLogger._role = saved_role


class TestAppLogger:
    def test_error_emits_signal(self):
        received = []
        AppLogger.on_error.connect(lambda t: received.append(t))
        AppLogger.error("test error")
        assert received == ["test error"]

    def test_warning_emits_signal(self):
        received = []
        AppLogger.on_warning.connect(lambda t: received.append(t))
        AppLogger.warning("test warning")
        assert received == ["test warning"]

    def test_info_emits_signal(self):
        received = []
        AppLogger.on_info.connect(lambda t: received.append(t))
        AppLogger.info("test info")
        assert received == ["test info"]

    def test_debug_emits_signal(self):
        received = []
        AppLogger.on_debug.connect(lambda t: received.append(t))
        AppLogger.debug("test debug")
        assert received == ["test debug"]

    def test_critical_signal_exists(self):
        assert hasattr(AppLogger, 'on_critical')

    def test_error_with_exc(self):
        exc = ValueError("original")
        with patch("wayfer.utils.logs._logger") as mock_logger:
            AppLogger.error("wrapped", exc=exc)
            mock_logger.error.assert_called_once_with("wrapped", exc_info=exc)

    def test_warning_with_exc(self):
        exc = RuntimeError("oops")
        with patch("wayfer.utils.logs._logger") as mock_logger:
            AppLogger.warning("warn", exc=exc)
            mock_logger.warning.assert_called_once_with("warn", exc_info=exc)

    def test_error_does_not_raise(self):
        AppLogger.error("should not raise")

    def test_multiple_callbacks(self):
        a, b = [], []
        AppLogger.on_warning.connect(lambda t: a.append(t))
        AppLogger.on_warning.connect(lambda t: b.append(t))
        AppLogger.warning("multi")
        assert a == ["multi"]
        assert b == ["multi"]

    def test_logger_called_for_each_level(self):
        with patch("wayfer.utils.logs._logger") as mock_logger:
            AppLogger.error("e")
            mock_logger.error.assert_called_once()
            AppLogger.warning("w")
            mock_logger.warning.assert_called_once()
            AppLogger.info("i")
            mock_logger.info.assert_called_once()
            AppLogger.debug("d")
            mock_logger.debug.assert_called_once()

    def test_set_node_forwards_log(self):
        node = MagicMock()
        AppLogger.set_node(node, role='test')
        AppLogger.info("hello")
        node.send.assert_called_once()
        args = node.send.call_args
        assert args[0][0] == 'dev.log'
        payload = args[0][1]
        assert payload['level'] == 'info'
        assert payload['text'] == 'hello'

    def test_set_node_none_no_forward(self):
        AppLogger.set_node(None)
        AppLogger.info("no forward")

    def test_forward_all_levels(self):
        node = MagicMock()
        AppLogger.set_node(node, role='r')
        AppLogger.debug("d")
        AppLogger.info("i")
        AppLogger.warning("w")
        AppLogger.error("e")
        assert node.send.call_count == 4
        levels = [c[0][1]['level'] for c in node.send.call_args_list]
        assert levels == ['debug', 'info', 'warning', 'error']

    def test_forward_exception_suppressed(self):
        node = MagicMock()
        node.send.side_effect = RuntimeError("zmq fail")
        AppLogger.set_node(node, role='r')
        AppLogger.info("should not raise")

    def test_set_role_updates_role(self):
        AppLogger.set_role('viewer')
        assert AppLogger._role == 'viewer'

    def test_set_node_with_role_sets_both(self):
        node = MagicMock()
        AppLogger.set_node(node, role='indexer')
        assert AppLogger._node is node
        assert AppLogger._role == 'indexer'

    def test_set_node_without_role_keeps_role(self):
        AppLogger._role = 'original'
        node = MagicMock()
        AppLogger.set_node(node)
        assert AppLogger._node is node
        assert AppLogger._role == 'original'


class TestLoggerFactory:
    @pytest.fixture(autouse=True)
    def _reset_factory(self):
        from wayfer.utils.logs import _LoggerFactory
        saved = (_LoggerFactory._instance, _LoggerFactory._file_handler, _LoggerFactory._log_id)
        yield
        if _LoggerFactory._instance is not None and _LoggerFactory._instance is not saved[0]:
            for h in list(_LoggerFactory._instance.handlers):
                _LoggerFactory._instance.removeHandler(h)
                h.close()
        _LoggerFactory._instance = saved[0]
        _LoggerFactory._file_handler = saved[1]
        _LoggerFactory._log_id = saved[2]

    def test_make_log_id_with_role(self):
        from wayfer.utils.logs import _make_log_id
        import os
        pid = os.getpid()
        assert _make_log_id('viewer') == f'viewer_{pid}'

    def test_make_log_id_without_role(self):
        from wayfer.utils.logs import _make_log_id
        import os
        assert _make_log_id('') == str(os.getpid())

    def test_set_role_renames_file_handler(self, tmp_path):
        import os
        import logging
        from wayfer.utils.logs import _LoggerFactory, _make_log_id

        _LoggerFactory._instance = None
        _LoggerFactory._file_handler = None
        _LoggerFactory._log_id = None

        pid = os.getpid()
        cached_logger = logging.getLogger(f'AppLog-{pid}')
        for h in list(cached_logger.handlers):
            cached_logger.removeHandler(h)

        with patch('wayfer.utils.logs._LOG_PATH', str(tmp_path)):
            with patch('sys.stderr', None):
                logger = _LoggerFactory.get('')
            assert _LoggerFactory._file_handler is not None
            assert _LoggerFactory._log_id == str(pid)

            logger = _LoggerFactory.get('viewer')
            expected_id = f'viewer_{pid}'
            assert _LoggerFactory._log_id == expected_id
            assert _LoggerFactory._file_handler.baseFilename.endswith(f'{expected_id}.log')

    def test_set_role_does_not_recreate_on_same_role(self, tmp_path):
        import os
        import logging
        from wayfer.utils.logs import _LoggerFactory

        _LoggerFactory._instance = None
        _LoggerFactory._file_handler = None
        _LoggerFactory._log_id = None

        pid = os.getpid()
        cached_logger = logging.getLogger(f'AppLog-{pid}')
        for h in list(cached_logger.handlers):
            cached_logger.removeHandler(h)

        with patch('wayfer.utils.logs._LOG_PATH', str(tmp_path)):
            with patch('sys.stderr', None):
                _LoggerFactory.get('')
            _LoggerFactory.get('viewer')
            handler_before = _LoggerFactory._file_handler
            _LoggerFactory.get('viewer')
            assert _LoggerFactory._file_handler is handler_before

    def test_file_handler_always_created(self, tmp_path):
        import os
        import logging
        from wayfer.utils.logs import _LoggerFactory

        _LoggerFactory._instance = None
        _LoggerFactory._file_handler = None
        _LoggerFactory._log_id = None

        pid = os.getpid()
        cached_logger = logging.getLogger(f'AppLog-{pid}')
        for h in list(cached_logger.handlers):
            cached_logger.removeHandler(h)

        with patch('wayfer.utils.logs._LOG_PATH', str(tmp_path)):
            _LoggerFactory.get('')
            assert _LoggerFactory._file_handler is not None
            assert _LoggerFactory._log_id == str(pid)
            _LoggerFactory.get('indexer')
            assert _LoggerFactory._file_handler.baseFilename.endswith(f'indexer_{pid}.log')
