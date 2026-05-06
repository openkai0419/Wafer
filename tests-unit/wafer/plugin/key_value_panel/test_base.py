from PySide6 import QtWidgets

from wafer.plugin.key_value_panel.base import BaseKeyValuePanelPlugin


class _StubKeyValuePanel(BaseKeyValuePanelPlugin):
    NAME = "test_key_value_panel"
    PREFIX = "test_prefix"
    DATA_SCOPE = "*"
    DEFAULT_ENABLED = True
    PRIORITY = 10

    def __init__(self):
        self._card = None
        self._last = None

    def create_card(self, parent=None, *, scope="meta_info"):
        self._card = QtWidgets.QFrame(parent)
        return self._card

    def update_data(self, data, locks=None, path="", file_hash="", db="", *, scope="meta_info"):
        self._last = (data, locks, path, file_hash, db, scope)


def test_key_value_panel_plugin_interface(qtbot):
    plugin = _StubKeyValuePanel()
    assert plugin.PREFIX == "test_prefix"
    assert plugin.DATA_SCOPE == "*"
    card = plugin.create_card(scope="tag")
    qtbot.addWidget(card)
    assert isinstance(card, QtWidgets.QWidget)
    plugin.update_data({"k": "v"}, {"k": True}, "/p", "h", "db", scope="tag")
    assert plugin._last == ({"k": "v"}, {"k": True}, "/p", "h", "db", "tag")


def test_key_value_panel_registry_register_and_lookup():
    from wafer.plugin.registry import PluginRegistry

    reg = PluginRegistry()
    reg.register(_StubKeyValuePanel)
    assert reg.get("test_key_value_panel") is _StubKeyValuePanel
    inst = reg.instance("test_key_value_panel")
    assert isinstance(inst, _StubKeyValuePanel)
    assert inst.PREFIX == "test_prefix"


def test_key_value_panel_default_save_state_returns_empty_dict():
    plugin = _StubKeyValuePanel()
    assert plugin.save_ui_state() == {}


def test_key_value_panel_default_restore_state_is_noop():
    plugin = _StubKeyValuePanel()
    plugin.restore_ui_state({"k": "v"})


def test_key_value_panel_default_shutdown_is_noop():
    plugin = _StubKeyValuePanel()
    plugin.shutdown()


def test_key_value_panel_overridden_save_restore_roundtrip():
    class Stateful(BaseKeyValuePanelPlugin):
        NAME = "stateful_key_value"
        PREFIX = "stateful"

        def __init__(self):
            self._expanded = True

        def create_card(self, parent=None, *, scope="meta_info"):
            return QtWidgets.QWidget(parent)

        def update_data(self, data, locks=None, path="", file_hash="", db="", *, scope="meta_info"):
            pass

        def save_ui_state(self):
            return {"expanded": self._expanded}

        def restore_ui_state(self, state):
            self._expanded = state.get("expanded", True)

    plugin = Stateful()
    plugin._expanded = False
    saved = plugin.save_ui_state()
    plugin2 = Stateful()
    plugin2.restore_ui_state(saved)
    assert plugin2._expanded is False