from unittest.mock import MagicMock
from PySide6 import QtWidgets

from wafer.core.commands.binding.editors_common import BindingEditorBase, DraftOverlay
from wafer.core.commands.binding.store_base import resolve_for_widget
from wafer.core.commands.binding.common import WidgetRef
from wafer.core.commands.command.payload import CommandPayload


def _pay(name: str) -> CommandPayload:
    return CommandPayload(name, {})


def _make_store(data=None):
    store = MagicMock()
    store.get_all.return_value = dict(data or {})
    store.save_to_file = MagicMock()
    store._seed_data.return_value = {}
    store.set_all = MagicMock()
    return store


def _make_widget(name: str):
    w = MagicMock(spec=QtWidgets.QWidget)
    w.set_shortcut_bindings = MagicMock()
    w.set_mouse_bindings = MagicMock()
    return WidgetRef(name=name, widget=w)


class TestMergedData:
    def test_returns_store_data_when_no_draft(self, qtbot):
        wref = _make_widget("viewer")
        store = _make_store({"k1": {"*": _pay("cmd1")}})
        editor = BindingEditorBase.__new__(BindingEditorBase)
        editor.widgets = [wref]
        editor._store = store
        editor._draft = DraftOverlay()
        result = editor._merged_data()
        assert "k1" in result
        assert result["k1"]["*"].id == "cmd1"

    def test_draft_overrides_store(self, qtbot):
        wref = _make_widget("viewer")
        store = _make_store({"k1": {"*": _pay("orig")}})
        editor = BindingEditorBase.__new__(BindingEditorBase)
        editor.widgets = [wref]
        editor._store = store
        editor._draft = DraftOverlay()
        editor._draft.update("k1", {"*": _pay("updated")})
        result = editor._merged_data()
        assert result["k1"]["*"].id == "updated"


class TestApplyToWidgets:
    def test_applies_bindings_via_setter(self, qtbot):
        wref = _make_widget("viewer")
        store = _make_store()
        editor = BindingEditorBase.__new__(BindingEditorBase)
        editor.widgets = [wref]
        editor._store = store
        editor._draft = DraftOverlay()
        data = {"k1": {"*": _pay("cmd1"), "viewer": _pay("cmd2")}}
        editor._apply_to_widgets(data, "set_shortcut_bindings")
        wref.widget.set_shortcut_bindings.assert_called_once()
        applied = wref.widget.set_shortcut_bindings.call_args[0][0]
        assert applied["k1"].id == "cmd2"

    def test_skips_widget_without_setter(self, qtbot):
        w = MagicMock(spec=[])
        wref = WidgetRef(name="viewer", widget=w)
        store = _make_store()
        editor = BindingEditorBase.__new__(BindingEditorBase)
        editor.widgets = [wref]
        editor._store = store
        editor._draft = DraftOverlay()
        data = {"k1": {"*": _pay("cmd1")}}
        editor._apply_to_widgets(data, "set_shortcut_bindings")

    def test_resolves_global_for_unscoped_widget(self, qtbot):
        wref = _make_widget("folder")
        store = _make_store()
        editor = BindingEditorBase.__new__(BindingEditorBase)
        editor.widgets = [wref]
        editor._store = store
        editor._draft = DraftOverlay()
        data = {"k1": {"*": _pay("global_cmd")}}
        editor._apply_to_widgets(data, "set_mouse_bindings")
        applied = wref.widget.set_mouse_bindings.call_args[0][0]
        assert applied["k1"].id == "global_cmd"


class TestSaveStore:
    def test_calls_save_to_file(self, qtbot):
        store = _make_store()
        editor = BindingEditorBase.__new__(BindingEditorBase)
        editor._store = store
        editor._draft = DraftOverlay()
        editor.widgets = []
        editor._save_store("/tmp/test.json")
        store.save_to_file.assert_called_once_with("/tmp/test.json")

    def test_handles_save_error(self, qtbot):
        store = _make_store()
        store.save_to_file.side_effect = OSError("disk full")
        editor = BindingEditorBase.__new__(BindingEditorBase)
        editor._store = store
        editor._draft = DraftOverlay()
        editor.widgets = []
        editor._save_store("/tmp/test.json")


class TestResetDraftToSeed:
    def test_replaces_draft_with_seed(self, qtbot):
        seed_data = {"k1": {"*": _pay("default")}}
        store = _make_store()
        store._seed_data.return_value = seed_data
        editor = BindingEditorBase.__new__(BindingEditorBase)
        editor._store = store
        editor._draft = DraftOverlay()
        editor._draft.update("k2", {"*": _pay("custom")})
        editor.widgets = []
        editor._reset_draft_to_seed()
        merged = editor._merged_data()
        assert "k1" in merged
        assert merged["k1"]["*"].id == "default"
