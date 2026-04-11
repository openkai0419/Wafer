from PySide6 import QtWidgets
from wafer.plugin.meta_panel.base import BaseMetaPanelPlugin
from wafer.plugin.meta_panel.handler import meta_panel_registry


class _StubMetaPanel(BaseMetaPanelPlugin):
    NAME = "test_meta_panel"
    PREFIX = "test_prefix"
    DISPLAY_NAME = "Test"
    DEFAULT_ENABLED = True
    PRIORITY = 10

    def __init__(self):
        self._widget = None
        self._last_data = None

    def create_widget(self, parent=None):
        self._widget = QtWidgets.QLabel("stub", parent)
        return self._widget

    def update_data(self, data):
        self._last_data = data


def test_meta_panel_plugin_interface():
    plugin = _StubMetaPanel()
    assert plugin.PREFIX == "test_prefix"
    w = plugin.create_widget()
    assert isinstance(w, QtWidgets.QLabel)
    plugin.update_data({"key": "value"})
    assert plugin._last_data == {"key": "value"}


def test_meta_panel_registry_register_and_lookup():
    from wafer.plugin.registry import PluginRegistry
    reg = PluginRegistry()
    reg.register(_StubMetaPanel)
    assert reg.get("test_meta_panel") is _StubMetaPanel
    inst = reg.instance("test_meta_panel")
    assert isinstance(inst, _StubMetaPanel)
    assert inst.PREFIX == "test_prefix"
