from afterimages.utils.notifier import Notifier


class TestNotifier:
    def setup_method(self):
        self._saved_i = list(Notifier.on_info._callbacks)
        self._saved_w = list(Notifier.on_warning._callbacks)
        self._saved_e = list(Notifier.on_error._callbacks)
        Notifier.on_info._callbacks.clear()
        Notifier.on_warning._callbacks.clear()
        Notifier.on_error._callbacks.clear()

    def teardown_method(self):
        Notifier.on_info._callbacks = self._saved_i
        Notifier.on_warning._callbacks = self._saved_w
        Notifier.on_error._callbacks = self._saved_e

    def test_info_emits_signal(self):
        received = []
        Notifier.on_info.connect(lambda t: received.append(t))
        Notifier.info("test info")
        assert received == ["test info"]

    def test_warning_emits_signal(self):
        received = []
        Notifier.on_warning.connect(lambda t: received.append(t))
        Notifier.warning("test warning")
        assert received == ["test warning"]

    def test_error_emits_signal(self):
        received = []
        Notifier.on_error.connect(lambda t: received.append(t))
        Notifier.error("test error")
        assert received == ["test error"]

    def test_warning_does_not_raise(self):
        Notifier.warning("should not raise")

    def test_error_does_not_raise(self):
        Notifier.error("should not raise")

    def test_multiple_callbacks(self):
        a, b = [], []
        Notifier.on_warning.connect(lambda t: a.append(t))
        Notifier.on_warning.connect(lambda t: b.append(t))
        Notifier.warning("multi")
        assert a == ["multi"]
        assert b == ["multi"]

    def test_signals_are_independent(self):
        infos = []
        warnings = []
        errors = []
        Notifier.on_info.connect(lambda t: infos.append(t))
        Notifier.on_warning.connect(lambda t: warnings.append(t))
        Notifier.on_error.connect(lambda t: errors.append(t))
        Notifier.info("i")
        Notifier.warning("w")
        Notifier.error("e")
        assert infos == ["i"]
        assert warnings == ["w"]
        assert errors == ["e"]
