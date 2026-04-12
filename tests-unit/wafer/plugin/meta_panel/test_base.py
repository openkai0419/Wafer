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


def test_meta_panel_default_save_state_returns_empty_dict():
    plugin = _StubMetaPanel()
    assert plugin.save_state() == {}


def test_meta_panel_default_restore_state_is_noop():
    plugin = _StubMetaPanel()
    plugin.restore_state({"key": "value"})


def test_meta_panel_overridden_save_restore_roundtrip():
    class StatefulMetaPanel(BaseMetaPanelPlugin):
        NAME = "stateful_meta"
        PREFIX = "stateful"
        def __init__(self):
            self._expanded = True
        def create_card(self, parent=None):
            return QtWidgets.QWidget(parent)
        def update_data(self, data):
            pass
        def save_state(self):
            return {"expanded": self._expanded}
        def restore_state(self, state):
            self._expanded = state.get("expanded", True)

    plugin = StatefulMetaPanel()
    plugin._expanded = False
    saved = plugin.save_state()
    assert saved == {"expanded": False}

    plugin2 = StatefulMetaPanel()
    plugin2.restore_state(saved)
    assert plugin2._expanded is False
