from wafer.utils.notifier import Notifier


class TestNotifierSignalEmission:
    def test_info_emits_signal(self):
        received = []
        Notifier.on_info.connect(lambda text: received.append(("info", text)))
        Notifier.info("hello")
        assert ("info", "hello") in received

    def test_warning_emits_signal(self):
        received = []
        Notifier.on_warning.connect(lambda text: received.append(("warning", text)))
        Notifier.warning("caution")
        assert ("warning", "caution") in received

    def test_error_emits_signal(self):
        received = []
        Notifier.on_error.connect(lambda text: received.append(("error", text)))
        Notifier.error("failure")
        assert ("error", "failure") in received

    def test_multiple_listeners(self):
        a, b = [], []
        Notifier.on_info.connect(lambda t: a.append(t))
        Notifier.on_info.connect(lambda t: b.append(t))
        Notifier.info("broadcast")
        assert "broadcast" in a
        assert "broadcast" in b
