from unittest.mock import patch, MagicMock

import pytest

import wafer.constants
from wafer.utils.logs import AppLogger


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
    AppLogger._role = ""
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
        assert hasattr(AppLogger, "on_critical")

    def test_error_with_exc(self):
        exc = ValueError("original")
        with patch("wafer.utils.logs._logger") as mock_logger:
            AppLogger.error("wrapped", exc=exc)
            mock_logger.error.assert_called_once_with("wrapped", exc_info=exc)

    def test_warning_with_exc(self):
        exc = RuntimeError("oops")
        with patch("wafer.utils.logs._logger") as mock_logger:
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
        with patch("wafer.utils.logs._logger") as mock_logger:
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
        AppLogger.set_node(node, role="test")
        AppLogger.warning("hello")
        node.send.assert_called_once()
        args = node.send.call_args
        assert args[0][0] == "dev.log"
        payload = args[0][1]
        assert payload["level"] == "warning"
        assert payload["text"] == "hello"

    def test_set_node_none_no_forward(self):
        AppLogger.set_node(None)
        AppLogger.info("no forward")

    def test_forward_all_levels_always(self):
        node = MagicMock()
        AppLogger.set_node(node, role="r")
        AppLogger.debug("d")
        AppLogger.info("i")
        AppLogger.warning("w")
        AppLogger.error("e")
        assert node.send.call_count == 4
        levels = [c[0][1]["level"] for c in node.send.call_args_list]
        assert levels == ["debug", "info", "warning", "error"]

    def test_forward_exception_suppressed(self):
        node = MagicMock()
        node.send.side_effect = RuntimeError("zmq fail")
        AppLogger.set_node(node, role="r")
        AppLogger.warning("should not raise")

    def test_set_role_updates_role(self):
        AppLogger.set_role("viewer")
        assert AppLogger._role == "viewer"

    def test_set_node_with_role_sets_both(self):
        node = MagicMock()
        AppLogger.set_node(node, role="indexer")
        assert AppLogger._node is node
        assert AppLogger._role == "indexer"

    def test_set_node_without_role_keeps_role(self):
        AppLogger._role = "original"
        node = MagicMock()
        AppLogger.set_node(node)
        assert AppLogger._node is node
        assert AppLogger._role == "original"

    def test_forward_skips_when_node_not_registered(self):
        node = MagicMock()
        node.is_registered = False
        AppLogger.set_node(node, role="test")
        AppLogger.info("should not forward")
        node.send.assert_not_called()

    def test_forward_sends_when_node_registered(self):
        node = MagicMock()
        node.is_registered = True
        AppLogger.set_node(node, role="test")
        AppLogger.info("should forward")
        node.send.assert_called_once()
        assert node.send.call_args[0][0] == "dev.log"


class TestLoggerFactory:
    @pytest.fixture(autouse=True)
    def _reset_factory(self):
        from wafer.utils.logs import _LoggerFactory

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
        from wafer.utils.logs import _make_log_id
        import os

        pid = os.getpid()
        assert _make_log_id("viewer") == f"viewer_{pid}"

    def test_make_log_id_without_role(self):
        from wafer.utils.logs import _make_log_id
        import os

        assert _make_log_id("") == str(os.getpid())

    def test_set_role_renames_file_handler(self, tmp_path):
        import os
        import logging
        from wafer.utils.logs import _LoggerFactory, _make_log_id

        _LoggerFactory._instance = None
        _LoggerFactory._file_handler = None
        _LoggerFactory._log_id = None

        pid = os.getpid()
        cached_logger = logging.getLogger(f"AppLog-{pid}")
        for h in list(cached_logger.handlers):
            cached_logger.removeHandler(h)

        with patch("wafer.utils.logs._LOG_PATH", str(tmp_path)):
            with patch("sys.stderr", None):
                logger = _LoggerFactory.get("")
            assert _LoggerFactory._file_handler is not None
            assert _LoggerFactory._log_id == str(pid)

            logger = _LoggerFactory.get("viewer")
            expected_id = f"viewer_{pid}"
            assert _LoggerFactory._log_id == expected_id
            assert _LoggerFactory._file_handler.baseFilename.endswith(f"{expected_id}.log")

    def test_set_role_does_not_recreate_on_same_role(self, tmp_path):
        import os
        import logging
        from wafer.utils.logs import _LoggerFactory

        _LoggerFactory._instance = None
        _LoggerFactory._file_handler = None
        _LoggerFactory._log_id = None

        pid = os.getpid()
        cached_logger = logging.getLogger(f"AppLog-{pid}")
        for h in list(cached_logger.handlers):
            cached_logger.removeHandler(h)

        with patch("wafer.utils.logs._LOG_PATH", str(tmp_path)):
            with patch("sys.stderr", None):
                _LoggerFactory.get("")
            _LoggerFactory.get("viewer")
            handler_before = _LoggerFactory._file_handler
            _LoggerFactory.get("viewer")
            assert _LoggerFactory._file_handler is handler_before

    def test_file_handler_always_created(self, tmp_path):
        import os
        import logging
        from wafer.utils.logs import _LoggerFactory

        _LoggerFactory._instance = None
        _LoggerFactory._file_handler = None
        _LoggerFactory._log_id = None

        pid = os.getpid()
        cached_logger = logging.getLogger(f"AppLog-{pid}")
        for h in list(cached_logger.handlers):
            cached_logger.removeHandler(h)

        with patch("wafer.utils.logs._LOG_PATH", str(tmp_path)):
            _LoggerFactory.get("")
            assert _LoggerFactory._file_handler is not None
            assert _LoggerFactory._log_id == str(pid)
            _LoggerFactory.get("indexer")
            assert _LoggerFactory._file_handler.baseFilename.endswith(f"indexer_{pid}.log")


class TestCleanupCrashLogs:
    def test_empty_crash_files_deleted(self, tmp_path):
        import time
        from wafer.utils.logs import _cleanup_crash_logs

        for i in range(3):
            p = tmp_path / f"crash_{99990 + i}.log"
            p.write_text("")
            time.sleep(0.01)
        with patch("wafer.utils.logs._is_pid_active", return_value=False):
            deleted = _cleanup_crash_logs(crash_dir=str(tmp_path), keep_latest=20)
        assert deleted == 3
        assert list(tmp_path.glob("crash_*.log")) == []

    def test_non_empty_crash_files_kept_within_limit(self, tmp_path):
        import time
        from wafer.utils.logs import _cleanup_crash_logs

        for i in range(3):
            p = tmp_path / f"crash_{99990 + i}.log"
            p.write_text(f"segfault trace {i}")
            time.sleep(0.01)
        with patch("wafer.utils.logs._is_pid_active", return_value=False):
            deleted = _cleanup_crash_logs(crash_dir=str(tmp_path), keep_latest=20)
        assert deleted == 0
        assert len(list(tmp_path.glob("crash_*.log"))) == 3

    def test_non_empty_crash_files_trimmed_by_limit(self, tmp_path):
        import time
        from wafer.utils.logs import _cleanup_crash_logs

        for i in range(5):
            p = tmp_path / f"crash_{99990 + i}.log"
            p.write_text(f"segfault trace {i}")
            time.sleep(0.01)
        with patch("wafer.utils.logs._is_pid_active", return_value=False):
            deleted = _cleanup_crash_logs(crash_dir=str(tmp_path), keep_latest=2)
        assert deleted == 3
        remaining = sorted(tmp_path.glob("crash_*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
        assert len(remaining) == 2
        assert "99994" in remaining[0].name
        assert "99993" in remaining[1].name

    def test_mixed_empty_and_non_empty(self, tmp_path):
        import time
        from wafer.utils.logs import _cleanup_crash_logs

        (tmp_path / "crash_10001.log").write_text("")
        time.sleep(0.01)
        (tmp_path / "crash_10002.log").write_text("real crash")
        time.sleep(0.01)
        (tmp_path / "crash_10003.log").write_text("")
        with patch("wafer.utils.logs._is_pid_active", return_value=False):
            deleted = _cleanup_crash_logs(crash_dir=str(tmp_path), keep_latest=20)
        assert deleted == 2
        remaining = list(tmp_path.glob("crash_*.log"))
        assert len(remaining) == 1
        assert "10002" in remaining[0].name

    def test_active_pid_empty_crash_not_deleted(self, tmp_path):
        from wafer.utils.logs import _cleanup_crash_logs

        (tmp_path / "crash_12345.log").write_text("")

        def mock_active(pid):
            return pid == 12345

        with patch("wafer.utils.logs._is_pid_active", side_effect=mock_active):
            deleted = _cleanup_crash_logs(crash_dir=str(tmp_path), keep_latest=20)
        assert deleted == 0
        assert (tmp_path / "crash_12345.log").exists()

    def test_active_pid_non_empty_over_limit_not_deleted(self, tmp_path):
        import time
        from wafer.utils.logs import _cleanup_crash_logs

        for i in range(3):
            p = tmp_path / f"crash_{99990 + i}.log"
            p.write_text(f"crash data {i}")
            time.sleep(0.01)

        def mock_active(pid):
            return pid == 99990

        with patch("wafer.utils.logs._is_pid_active", side_effect=mock_active):
            deleted = _cleanup_crash_logs(crash_dir=str(tmp_path), keep_latest=1)
        assert deleted == 1
        remaining_names = {p.name for p in tmp_path.glob("crash_*.log")}
        assert "crash_99990.log" in remaining_names
        assert "crash_99992.log" in remaining_names

    def test_empty_directory(self, tmp_path):
        from wafer.utils.logs import _cleanup_crash_logs

        deleted = _cleanup_crash_logs(crash_dir=str(tmp_path), keep_latest=20)
        assert deleted == 0
