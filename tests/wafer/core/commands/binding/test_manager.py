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


def test_register_applies_current_key_bindings(qtbot):
    BindingManager._instance = None
    InstanceRegistry._instance = None
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
