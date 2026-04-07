from wafer.utils.logs import AppLogger


class TestAppLoggerSignalEmission:
    def test_error_emits_on_error(self):
        received = []
        AppLogger.on_error.connect(lambda text: received.append(text))
        AppLogger.error("test error")
        assert any("test error" in r for r in received)

    def test_warning_emits_on_warning(self):
        received = []
        AppLogger.on_warning.connect(lambda text: received.append(text))
        AppLogger.warning("test warning")
        assert any("test warning" in r for r in received)

    def test_info_emits_on_info(self):
        received = []
        AppLogger.on_info.connect(lambda text: received.append(text))
        AppLogger.info("test info")
        assert any("test info" in r for r in received)

    def test_debug_emits_on_debug(self):
        received = []
        AppLogger.on_debug.connect(lambda text: received.append(text))
        AppLogger.debug("test debug")
        assert any("test debug" in r for r in received)


class TestAppLoggerExcFormat:
    def test_error_with_exception(self):
        received = []
        AppLogger.on_error.connect(lambda text: received.append(text))
        try:
            raise ValueError("boom")
        except ValueError as e:
            AppLogger.error("caught error", exc=e)
        assert len(received) > 0
        full = received[-1]
        assert "caught error" in full
        assert "ValueError" in full
        assert "boom" in full

    def test_warning_with_exception(self):
        received = []
        AppLogger.on_warning.connect(lambda text: received.append(text))
        try:
            raise RuntimeError("warn")
        except RuntimeError as e:
            AppLogger.warning("caught warning", exc=e)
        assert len(received) > 0
        full = received[-1]
        assert "caught warning" in full
        assert "RuntimeError" in full

    def test_error_without_exception(self):
        received = []
        AppLogger.on_error.connect(lambda text: received.append(text))
        AppLogger.error("plain error")
        assert any("plain error" in r for r in received)
        last = received[-1]
        assert "Traceback" not in last
