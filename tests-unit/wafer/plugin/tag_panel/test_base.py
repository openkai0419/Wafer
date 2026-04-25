from PySide6 import QtWidgets
from wafer.plugin.tag_panel.base import BaseTagPanelPlugin
from wafer.plugin.tag_panel.handler import tag_panel_registry


class _StubTagPanel(BaseTagPanelPlugin):
    NAME = "test_tag_panel"
    PREFIX = "test_prefix"
    DEFAULT_ENABLED = True
    PRIORITY = 10

    def __init__(self):
        self._card = None
        self._last = None

    def create_card(self, parent=None):
        self._card = QtWidgets.QFrame(parent)
        return self._card

    def update_data(self, tags, locks, path, file_hash, db):
        self._last = (tags, locks, path, file_hash, db)


def test_tag_panel_plugin_interface(qtbot):
    plugin = _StubTagPanel()
    assert plugin.PREFIX == "test_prefix"
    card = plugin.create_card()
    qtbot.addWidget(card)
    assert isinstance(card, QtWidgets.QWidget)
    plugin.update_data({"k": "v"}, {"k": True}, "/p", "h", "db")
    assert plugin._last == ({"k": "v"}, {"k": True}, "/p", "h", "db")


def test_tag_panel_registry_register_and_lookup():
    from wafer.plugin.registry import PluginRegistry
    reg = PluginRegistry()
    reg.register(_StubTagPanel)
    assert reg.get("test_tag_panel") is _StubTagPanel
    inst = reg.instance("test_tag_panel")
    assert isinstance(inst, _StubTagPanel)
    assert inst.PREFIX == "test_prefix"


def test_tag_panel_default_save_state_returns_empty_dict():
    plugin = _StubTagPanel()
    assert plugin.save_state() == {}


def test_tag_panel_default_restore_state_is_noop():
    plugin = _StubTagPanel()
    plugin.restore_state({"k": "v"})


def test_tag_panel_overridden_save_restore_roundtrip():
    class Stateful(BaseTagPanelPlugin):
        NAME = "stateful_tag"
        PREFIX = "stateful"
        def __init__(self):
            self._expanded = True
        def create_card(self, parent=None):
            return QtWidgets.QWidget(parent)
        def update_data(self, tags, locks, path, file_hash, db):
            pass
        def save_state(self):
            return {"expanded": self._expanded}
        def restore_state(self, state):
            self._expanded = state.get("expanded", True)

    plugin = Stateful()
    plugin._expanded = False
    saved = plugin.save_state()
    plugin2 = Stateful()
    plugin2.restore_state(saved)
    assert plugin2._expanded is False
