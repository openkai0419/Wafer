from wafer.qt.commands.binding.instance_registry import InstanceRegistry


class _Win:
    def __init__(self, name):
        self.name = name


class TestGetHostWindow:
    def _fresh(self):
        reg = InstanceRegistry()
        return reg

    def test_prefers_main_window(self):
        reg = self._fresh()
        main = _Win("MainWindow")
        webui = _Win("WebUIWindow")
        reg.register("MainWindow", main)
        reg.register("WebUIWindow", webui)
        assert reg.get_host_window() is main

    def test_falls_back_to_webui_window(self):
        reg = self._fresh()
        webui = _Win("WebUIWindow")
        reg.register("WebUIWindow", webui)
        assert reg.get_host_window() is webui

    def test_none_when_no_host(self):
        reg = self._fresh()
        assert reg.get_host_window() is None
