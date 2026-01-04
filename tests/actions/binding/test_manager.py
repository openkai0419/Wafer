from PySide6 import QtWidgets

from source.actions.binding.manager import BindingManager
from source.actions.binding.widget_registry import WidgetRegistry
from source.actions.binding.mixins import CommandBindingMixin
from source.actions.command.context import CommandContext
from source.actions.binding.key.store import KeyBindingStore
from source.actions.binding.key.sequence import Key
from source.actions.command.payload import CommandPayload


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
    WidgetRegistry._instance = None
    w1 = _W()
    w2 = _W()
    qtbot.addWidget(w1)
    qtbot.addWidget(w2)

    w1.init_command_binding("folder")
    w2.init_command_binding("viewer")

    ctx = CommandContext.create(w2, w2.binding_scope(), source="test")
    assert ctx.get_widget("folder") is w1
    assert ctx.get_widget("viewer") is w2
    assert ctx.get_widgets("folder") == [w1]
    assert ctx.get_widget("missing") is None


def test_ctx_can_get_multiple_widgets_by_same_name(qtbot):
    BindingManager._instance = None
    WidgetRegistry._instance = None
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
    xs = ctx.get_widgets("same")
    assert set(xs) == {w1, w2}


def test_ctx_can_get_context_only_widget(qtbot):
    BindingManager._instance = None
    WidgetRegistry._instance = None
    anchor = _W()
    w = QtWidgets.QWidget()
    qtbot.addWidget(anchor)
    qtbot.addWidget(w)

    anchor.init_command_binding("anchor")
    WidgetRegistry.instance().register("plain", w)
    ctx = CommandContext.create(anchor, anchor.binding_scope(), source="test")
    assert ctx.get_widget("plain") is w


def test_ctx_filters_deleted_widget(qtbot):
    BindingManager._instance = None
    WidgetRegistry._instance = None
    anchor = _W()
    w = QtWidgets.QWidget()
    qtbot.addWidget(anchor)

    anchor.init_command_binding("anchor")
    WidgetRegistry.instance().register("gone", w)
    import shiboken6

    shiboken6.delete(w)
    QtWidgets.QApplication.processEvents()

    ctx = CommandContext.create(anchor, anchor.binding_scope(), source="test")
    assert ctx.get_widget("gone") is None
    assert ctx.get_widgets("gone") == []


def test_register_applies_current_key_bindings(qtbot):
    BindingManager._instance = None
    WidgetRegistry._instance = None
    store = KeyBindingStore()
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
