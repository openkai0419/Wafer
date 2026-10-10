import os
from unittest.mock import patch, MagicMock

import pytest

import wafer.constants
from wafer.core.logs import AppLogger


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
    def test_each_level_emits_its_signal(self):
        levels = ["error", "warning", "info", "debug"]
        received = {level: [] for level in levels}
        for level in levels:
            getattr(AppLogger, f"on_{level}").connect(received[level].append)
        for level in levels:
            getattr(AppLogger, level)(f"test {level}")
        assert received == {level: [f"test {level}"] for level in levels}

    def test_error_with_exc(self):
        exc = ValueError("original")
        with patch("wafer.core.logs._logger") as mock_logger:
            AppLogger.error("wrapped", exc=exc)
            mock_logger.error.assert_called_once_with("wrapped", exc_info=exc)

    def test_set_node_forwards_log(self):
        node = MagicMock()
        AppLogger.set_node(node, role="test")
        AppLogger.warning("hello")
        assert node.send.call_count == 2
        args = node.send.call_args_list[0]
        assert args[0][0] == "dev.log"
        payload = args[0][1]
        assert payload["level"] == "warning"
        assert payload["text"] == "hello"
        dsts = {c.kwargs["dst"] for c in node.send.call_args_list}
        assert dsts == {"viewer", "webui"}

    def test_forward_all_levels_always(self):
        node = MagicMock()
        AppLogger.set_node(node, role="r")
        AppLogger.debug("d")
        AppLogger.info("i")
        AppLogger.warning("w")
        AppLogger.error("e")
        assert node.send.call_count == 8
        levels = [c[0][1]["level"] for c in node.send.call_args_list[::2]]
        assert levels == ["debug", "info", "warning", "error"]

    def test_forward_skips_own_sink_role(self):
        node = MagicMock()
        AppLogger.set_node(node, role="viewer")
        AppLogger.info("from viewer")
        assert node.send.call_count == 1
        assert node.send.call_args.kwargs["dst"] == "webui"

    def test_forward_exception_suppressed(self):
        node = MagicMock()
        node.send.side_effect = RuntimeError("zmq fail")
        AppLogger.set_node(node, role="r")
        AppLogger.warning("should not raise")

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

    def test_debug_non_recursive_suppresses_logger_failure(self):
        from wafer.core.logs import debug_non_recursive

        with patch("wafer.core.logs._logger") as logger:
            logger.debug.side_effect = RuntimeError("logging failed")
            debug_non_recursive("still safe")


class TestLoggerFactory:
    @pytest.fixture(autouse=True)
    def _reset_factory(self):
        from wafer.core.logs import _LoggerFactory

        saved = (_LoggerFactory._instance, _LoggerFactory._file_handler, _LoggerFactory._log_id)
        yield
        if _LoggerFactory._instance is not None and _LoggerFactory._instance is not saved[0]:
            for h in list(_LoggerFactory._instance.handlers):
                _LoggerFactory._instance.removeHandler(h)
                h.close()
        _LoggerFactory._instance = saved[0]
        _LoggerFactory._file_handler = saved[1]
        _LoggerFactory._log_id = saved[2]

    def test_set_role_renames_file_handler(self, tmp_path):
        import os
        import logging
        from wafer.core.logs import _LoggerFactory, _make_log_id

        _LoggerFactory._instance = None
        _LoggerFactory._file_handler = None
        _LoggerFactory._log_id = None

        pid = os.getpid()
        cached_logger = logging.getLogger(f"AppLog-{pid}")
        for h in list(cached_logger.handlers):
            cached_logger.removeHandler(h)

        with patch("wafer.core.logs._LOG_PATH", str(tmp_path)):
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
        from wafer.core.logs import _LoggerFactory

        _LoggerFactory._instance = None
        _LoggerFactory._file_handler = None
        _LoggerFactory._log_id = None

        pid = os.getpid()
        cached_logger = logging.getLogger(f"AppLog-{pid}")
        for h in list(cached_logger.handlers):
            cached_logger.removeHandler(h)

        with patch("wafer.core.logs._LOG_PATH", str(tmp_path)):
            with patch("sys.stderr", None):
                _LoggerFactory.get("")
            _LoggerFactory.get("viewer")
            handler_before = _LoggerFactory._file_handler
            _LoggerFactory.get("viewer")
            assert _LoggerFactory._file_handler is handler_before


def _write_crash_logs(crash_dir, entries):
    for i, (pid, text) in enumerate(entries):
        p = crash_dir / f"crash_{pid}.log"
        p.write_text(text)
        os.utime(p, (1000 + i, 1000 + i))


class TestCleanupCrashLogs:
    def test_empty_crash_files_deleted(self, tmp_path):
        from wafer.core.logs import _cleanup_crash_logs

        _write_crash_logs(tmp_path, [(99990 + i, "") for i in range(3)])
        with patch("wafer.core.logs._is_pid_active", return_value=False):
            deleted = _cleanup_crash_logs(crash_dir=str(tmp_path), keep_latest=20)
        assert deleted == 3
        assert list(tmp_path.glob("crash_*.log")) == []

    def test_non_empty_crash_files_kept_within_limit(self, tmp_path):
        from wafer.core.logs import _cleanup_crash_logs

        _write_crash_logs(tmp_path, [(99990 + i, f"segfault trace {i}") for i in range(3)])
        with patch("wafer.core.logs._is_pid_active", return_value=False):
            deleted = _cleanup_crash_logs(crash_dir=str(tmp_path), keep_latest=20)
        assert deleted == 0
        assert len(list(tmp_path.glob("crash_*.log"))) == 3

    def test_non_empty_crash_files_trimmed_by_limit(self, tmp_path):
        from wafer.core.logs import _cleanup_crash_logs

        _write_crash_logs(tmp_path, [(99990 + i, f"segfault trace {i}") for i in range(5)])
        with patch("wafer.core.logs._is_pid_active", return_value=False):
            deleted = _cleanup_crash_logs(crash_dir=str(tmp_path), keep_latest=2)
        assert deleted == 3
        remaining = sorted(tmp_path.glob("crash_*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
        assert len(remaining) == 2
        assert "99994" in remaining[0].name
        assert "99993" in remaining[1].name

    def test_mixed_empty_and_non_empty(self, tmp_path):
        from wafer.core.logs import _cleanup_crash_logs

        _write_crash_logs(tmp_path, [(10001, ""), (10002, "real crash"), (10003, "")])
        with patch("wafer.core.logs._is_pid_active", return_value=False):
            deleted = _cleanup_crash_logs(crash_dir=str(tmp_path), keep_latest=20)
        assert deleted == 2
        remaining = list(tmp_path.glob("crash_*.log"))
        assert len(remaining) == 1
        assert "10002" in remaining[0].name

    def test_active_pid_empty_crash_not_deleted(self, tmp_path):
        from wafer.core.logs import _cleanup_crash_logs

        (tmp_path / "crash_12345.log").write_text("")

        def mock_active(pid):
            return pid == 12345

        with patch("wafer.core.logs._is_pid_active", side_effect=mock_active):
            deleted = _cleanup_crash_logs(crash_dir=str(tmp_path), keep_latest=20)
        assert deleted == 0
        assert (tmp_path / "crash_12345.log").exists()

    def test_active_pid_non_empty_over_limit_not_deleted(self, tmp_path):
        from wafer.core.logs import _cleanup_crash_logs

        _write_crash_logs(tmp_path, [(99990 + i, f"crash data {i}") for i in range(3)])

        def mock_active(pid):
            return pid == 99990

        with patch("wafer.core.logs._is_pid_active", side_effect=mock_active):
            deleted = _cleanup_crash_logs(crash_dir=str(tmp_path), keep_latest=1)
        assert deleted == 1
        remaining_names = {p.name for p in tmp_path.glob("crash_*.log")}
        assert "crash_99990.log" in remaining_names
        assert "crash_99992.log" in remaining_names

    def test_empty_directory(self, tmp_path):
        from wafer.core.logs import _cleanup_crash_logs

        deleted = _cleanup_crash_logs(crash_dir=str(tmp_path), keep_latest=20)
        assert deleted == 0
