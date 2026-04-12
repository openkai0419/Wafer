from PySide6 import QtWidgets
from wafer.plugin.meta_panel.base import BaseMetaPanelPlugin
from wafer.plugin.meta_panel.handler import meta_panel_registry


class _StubMetaPanel(BaseMetaPanelPlugin):
    NAME = "test_meta_panel"
    PREFIX = "test_prefix"
    DEFAULT_ENABLED = True
    PRIORITY = 10

    def __init__(self):
        self._card = None
        self._last_data = None

    def create_card(self, parent=None):
        self._card = QtWidgets.QFrame(parent)
        return self._card

    def update_data(self, data):
        self._last_data = data


def test_meta_panel_plugin_interface():
    plugin = _StubMetaPanel()
    assert plugin.PREFIX == "test_prefix"
    card = plugin.create_card()
    assert isinstance(card, QtWidgets.QWidget)
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
