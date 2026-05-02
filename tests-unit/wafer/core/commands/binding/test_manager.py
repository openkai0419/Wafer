from PySide6 import QtWidgets

from wafer.core.commands.binding.manager import BindingManager
from wafer.core.commands.binding.instance_registry import InstanceRegistry
from wafer.core.commands.binding.mixins import CommandBindingMixin
from wafer.core.commands.command.context import CommandContext
from wafer.core.commands.binding.key.store import KeyBindingStore
from wafer.core.commands.binding.key.sequence import Key
from wafer.core.commands.command.payload import CommandPayload


class _W(QtWidgets.QWidget, CommandBindingMixin):
    pass


class _WCapture(QtWidgets.QWidget, CommandBindingMixin):
    def __init__(self):
        super().__init__()
        self.captured_shortcuts = None

    def set_shortcut_bindings(self, bindings):
        self.captured_shortcuts = dict(bindings or {})


class _WKeyRoute(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.logical_bindings = None
        self.physical_bindings = None

    def binding_scope(self):
        return "viewer"

    def set_shortcut_bindings(self, bindings):
        self.logical_bindings = dict(bindings or {})

    def set_physical_shortcut_bindings(self, bindings):
        self.physical_bindings = dict(bindings or {})


def test_ctx_can_resolve_widget_by_name(qtbot):
    BindingManager._instance = None
    InstanceRegistry._instance = None
    w1 = _W()
    w2 = _W()
    qtbot.addWidget(w1)
    qtbot.addWidget(w2)

    w1.init_command_binding("folder")
    w2.init_command_binding("viewer")

    ctx = CommandContext.create(w2, w2.binding_scope(), source="test")
    assert ctx.get_instance("folder") is w1
    assert ctx.get_instance("viewer") is w2
    assert ctx.get_instances("folder") == [w1]
    assert ctx.get_instance("missing") is None


def test_ctx_can_get_multiple_widgets_by_same_name(qtbot):
    BindingManager._instance = None
    InstanceRegistry._instance = None
    w1 = _W()
    w2 = _W()
    w3 = _W()
    qtbot.addWidget(w1)
    qtbot.addWidget(w2)
    qtbot.addWidget(w3)

    w1.init_command_binding("same")
    w2.init_command_binding("same")
    w3.init_command_binding("other")

    ctx = CommandContext.create(w3, w3.binding_scope(), source="test")
    xs = ctx.get_instances("same")
    assert set(xs) == {w1, w2}


def test_ctx_can_get_context_only_widget(qtbot):
    BindingManager._instance = None
    InstanceRegistry._instance = None
    anchor = _W()
    w = QtWidgets.QWidget()
    qtbot.addWidget(anchor)
    qtbot.addWidget(w)

    anchor.init_command_binding("anchor")
    InstanceRegistry.instance().register("plain", w)
    ctx = CommandContext.create(anchor, anchor.binding_scope(), source="test")
    assert ctx.get_instance("plain") is w


def test_ctx_filters_deleted_widget(qtbot):
    BindingManager._instance = None
    InstanceRegistry._instance = None
    anchor = _W()
    w = QtWidgets.QWidget()
    qtbot.addWidget(anchor)

    anchor.init_command_binding("anchor")
    InstanceRegistry.instance().register("gone", w)
    import shiboken6

    shiboken6.delete(w)
    QtWidgets.QApplication.processEvents()

    ctx = CommandContext.create(anchor, anchor.binding_scope(), source="test")
    assert ctx.get_instance("gone") is None
    assert ctx.get_instances("gone") == []


def test_resolve_node_from_mainwindow(qtbot):
    InstanceRegistry._instance = None
    reg = InstanceRegistry.instance()
    mock_w = _W()
    mock_w._node = object()
    qtbot.addWidget(mock_w)
    reg.register("MainWindow", mock_w)
    assert reg.resolve_node() is mock_w._node


def test_resolve_node_from_tray(qtbot):
    InstanceRegistry._instance = None
    reg = InstanceRegistry.instance()
    mock_tray = _W()
    mock_tray._node = object()
    qtbot.addWidget(mock_tray)
    reg.register("Tray", mock_tray)
    assert reg.resolve_node() is mock_tray._node


def test_resolve_node_none():
    InstanceRegistry._instance = None
    reg = InstanceRegistry.instance()
    assert reg.resolve_node() is None


def test_resolve_node_prefers_mainwindow(qtbot):
    InstanceRegistry._instance = None
    reg = InstanceRegistry.instance()
    mock_w = _W()
    mock_w._node = object()
    mock_tray = _W()
    mock_tray._node = object()
    qtbot.addWidget(mock_w)
    qtbot.addWidget(mock_tray)
    reg.register("MainWindow", mock_w)
    reg.register("Tray", mock_tray)
    assert reg.resolve_node() is mock_w._node


def test_register_applies_current_key_bindings(qtbot):
    store = KeyBindingStore.instance()
    try:
        seq = Key("Control", "A")
        store.set_all({seq: {"*": CommandPayload("dummy")}})
        w = _WCapture()
        qtbot.addWidget(w)
        w.init_command_binding("viewer")
        assert isinstance(w.captured_shortcuts, dict)
        assert seq in w.captured_shortcuts
    finally:
        store.set_all({})


def test_digit_key_bindings_are_logical_keys(qtbot):
    store = KeyBindingStore.instance()
    old = store.get_all()
    one = Key("1")
    two = Key("2")
    payload_one = CommandPayload("mark.toggle", {"name": "temp"})
    payload_two = CommandPayload("mark.toggle", {"name": "temp 2"})
    try:
        store.set_all({one: {"*": payload_one}, two: {"*": payload_two}})
        w = _WKeyRoute()
        qtbot.addWidget(w)

        BindingManager().apply_key_bindings([w])

        assert set(w.logical_bindings or {}) == {one, two}
        assert w.logical_bindings[one].to_dict() == payload_one.to_dict()
        assert w.logical_bindings[two].to_dict() == payload_two.to_dict()
        assert w.physical_bindings is None
    finally:
        store.set_all(old)


def test_sc_key_bindings_are_physical_keys(qtbot):
    store = KeyBindingStore.instance()
    old = store.get_all()
    sc2 = Key("SC2")
    payload = CommandPayload("mark.toggle", {"name": "temp 2"})
    try:
        store.set_all({sc2: {"*": payload}})
        w = _WKeyRoute()
        qtbot.addWidget(w)

        BindingManager().apply_key_bindings([w])

        assert w.logical_bindings is None
        assert set(w.physical_bindings or {}) == {("SC2",)}
        assert w.physical_bindings[("SC2",)].to_dict() == payload.to_dict()
    finally:
        store.set_all(old)
