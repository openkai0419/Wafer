import pytest

from wafer.core.commands.binding.store_base import BindingStoreBase, resolve_for_widget
from wafer.core.commands.binding.key.sequence import KeySequence
from wafer.core.commands.command.payload import CommandPayload


class _TestStore(BindingStoreBase[KeySequence]):
    key_type = KeySequence


@pytest.fixture(autouse=True)
def _reset_store():
    prev = _TestStore._instance
    _TestStore._instance = None
    yield
    _TestStore._instance = prev


class TestResolveForWidget:
    def test_global_scope(self):
        data = {
            KeySequence(["A"]): {"*": CommandPayload("cmd.a")},
        }
        result = resolve_for_widget(data, "Viewer")
        assert KeySequence(["A"]) in result
        assert result[KeySequence(["A"])].id == "cmd.a"

    def test_widget_scope_overrides_global(self):
        data = {
            KeySequence(["A"]): {
                "*": CommandPayload("cmd.global"),
                "Viewer": CommandPayload("cmd.viewer"),
            },
        }
        result = resolve_for_widget(data, "Viewer")
        assert result[KeySequence(["A"])].id == "cmd.viewer"

    def test_unknown_widget_falls_back_to_global(self):
        data = {
            KeySequence(["A"]): {
                "*": CommandPayload("cmd.global"),
                "Viewer": CommandPayload("cmd.viewer"),
            },
        }
        result = resolve_for_widget(data, "Unknown")
        assert result[KeySequence(["A"])].id == "cmd.global"

    def test_no_matching_scope(self):
        data = {
            KeySequence(["A"]): {"Viewer": CommandPayload("cmd.viewer")},
        }
        result = resolve_for_widget(data, "Unknown")
        assert KeySequence(["A"]) not in result

    def test_empty_data(self):
        assert resolve_for_widget({}, "Viewer") == {}

    def test_multiple_keys(self):
        data = {
            KeySequence(["A"]): {"*": CommandPayload("cmd.a")},
            KeySequence(["B"]): {"Grid": CommandPayload("cmd.b")},
        }
        result = resolve_for_widget(data, "Grid")
        assert result[KeySequence(["A"])].id == "cmd.a"
        assert result[KeySequence(["B"])].id == "cmd.b"


class TestBindingStoreBaseSetAll:
    def test_set_all_basic(self):
        store = _TestStore.instance()
        store.set_all({
            KeySequence(["A"]): {"*": CommandPayload("cmd.a")},
        })
        assert store.get_all()[KeySequence(["A"])]["*"].id == "cmd.a"

    def test_set_all_invalid_key_type_raises(self):
        store = _TestStore.instance()
        with pytest.raises(TypeError, match="KeySequence"):
            store.set_all({("Control", "A"): {"*": CommandPayload("cmd.a")}})

    def test_set_all_replaces(self):
        store = _TestStore.instance()
        store.set_all({KeySequence(["A"]): {"*": CommandPayload("cmd.a")}})
        store.set_all({KeySequence(["B"]): {"*": CommandPayload("cmd.b")}})
        data = store.get_all()
        assert KeySequence(["A"]) not in data
        assert KeySequence(["B"]) in data


class TestBindingStoreBaseSetBinding:
    def test_add_binding(self):
        store = _TestStore.instance()
        store.set_binding(KeySequence(["A"]), "*", CommandPayload("cmd.a"))
        assert store.resolve("*", KeySequence(["A"])).id == "cmd.a"

    def test_overwrite_binding(self):
        store = _TestStore.instance()
        store.set_binding(KeySequence(["A"]), "*", CommandPayload("cmd.a"))
        store.set_binding(KeySequence(["A"]), "*", CommandPayload("cmd.b"))
        assert store.resolve("*", KeySequence(["A"])).id == "cmd.b"

    def test_delete_binding_with_none(self):
        store = _TestStore.instance()
        store.set_binding(KeySequence(["A"]), "*", CommandPayload("cmd.a"))
        store.set_binding(KeySequence(["A"]), "*", None)
        assert store.resolve("*", KeySequence(["A"])) is None

    def test_delete_binding_cleans_empty_key(self):
        store = _TestStore.instance()
        store.set_binding(KeySequence(["A"]), "*", CommandPayload("cmd.a"))
        store.set_binding(KeySequence(["A"]), "*", None)
        assert KeySequence(["A"]) not in store.get_all()

    def test_delete_nonexistent_key_is_noop(self):
        store = _TestStore.instance()
        store.set_binding(KeySequence(["Z"]), "*", None)

    def test_invalid_key_type_raises(self):
        store = _TestStore.instance()
        with pytest.raises(TypeError, match="KeySequence"):
            store.set_binding("not_a_keyseq", "*", CommandPayload("cmd.a"))

    def test_invalid_command_raises(self):
        store = _TestStore.instance()
        with pytest.raises(TypeError, match="CommandPayload"):
            store.set_binding(KeySequence(["A"]), "*", "not a payload")

    def test_empty_scope_becomes_star(self):
        store = _TestStore.instance()
        store.set_binding(KeySequence(["A"]), "", CommandPayload("cmd.a"))
        assert store.resolve("*", KeySequence(["A"])).id == "cmd.a"

    def test_scope_stripped(self):
        store = _TestStore.instance()
        store.set_binding(KeySequence(["A"]), "  grid  ", CommandPayload("cmd.a"))
        data = store.get_all()
        assert "grid" in data[KeySequence(["A"])]

    def test_multiple_scopes(self):
        store = _TestStore.instance()
        store.set_binding(KeySequence(["A"]), "*", CommandPayload("cmd.global"))
        store.set_binding(KeySequence(["A"]), "viewer", CommandPayload("cmd.viewer"))
        assert store.resolve("viewer", KeySequence(["A"])).id == "cmd.viewer"
        assert store.resolve("grid", KeySequence(["A"])).id == "cmd.global"


class TestBindingStoreBaseResolve:
    def test_widget_scope_hit(self):
        store = _TestStore.instance()
        store.set_all({
            KeySequence(["A"]): {
                "*": CommandPayload("cmd.global"),
                "viewer": CommandPayload("cmd.viewer"),
            },
        })
        assert store.resolve("viewer", KeySequence(["A"])).id == "cmd.viewer"

    def test_global_fallback(self):
        store = _TestStore.instance()
        store.set_all({
            KeySequence(["A"]): {"*": CommandPayload("cmd.global")},
        })
        assert store.resolve("viewer", KeySequence(["A"])).id == "cmd.global"

    def test_no_match(self):
        store = _TestStore.instance()
        store.set_all({
            KeySequence(["A"]): {"viewer": CommandPayload("cmd.viewer")},
        })
        assert store.resolve("grid", KeySequence(["A"])) is None

    def test_missing_key(self):
        store = _TestStore.instance()
        assert store.resolve("*", KeySequence(["Z"])) is None

    def test_empty_widget_uses_star(self):
        store = _TestStore.instance()
        store.set_all({
            KeySequence(["A"]): {"*": CommandPayload("cmd.global")},
        })
        assert store.resolve("", KeySequence(["A"])).id == "cmd.global"


class TestBindingStoreBaseDiff:
    def test_empty_diff_on_identical(self):
        store = _TestStore.instance()
        data = {KeySequence(["A"]): {"*": CommandPayload("cmd.a")}}
        diff = store._diff_data(data, data)
        assert diff == {}

    def test_added_key(self):
        store = _TestStore.instance()
        seed = {}
        cur = {KeySequence(["A"]): {"*": CommandPayload("cmd.a")}}
        diff = store._diff_data(cur, seed)
        assert KeySequence(["A"]) in diff
        assert diff[KeySequence(["A"])]["*"].id == "cmd.a"

    def test_deleted_scope(self):
        store = _TestStore.instance()
        seed = {KeySequence(["A"]): {"*": CommandPayload("cmd.a")}}
        cur = {}
        diff = store._diff_data(cur, seed)
        assert diff[KeySequence(["A"])]["*"] is None

    def test_changed_payload(self):
        store = _TestStore.instance()
        seed = {KeySequence(["A"]): {"*": CommandPayload("cmd.a")}}
        cur = {KeySequence(["A"]): {"*": CommandPayload("cmd.b")}}
        diff = store._diff_data(cur, seed)
        assert diff[KeySequence(["A"])]["*"].id == "cmd.b"


class TestBindingStoreBaseApplyDiff:
    def test_apply_addition(self):
        store = _TestStore.instance()
        base = {}
        diff = {KeySequence(["A"]): {"*": CommandPayload("cmd.a")}}
        result = store._apply_diff(base, diff)
        assert result[KeySequence(["A"])]["*"].id == "cmd.a"

    def test_apply_deletion(self):
        store = _TestStore.instance()
        base = {KeySequence(["A"]): {"*": CommandPayload("cmd.a")}}
        diff = {KeySequence(["A"]): {"*": None}}
        result = store._apply_diff(base, diff)
        assert KeySequence(["A"]) not in result

    def test_apply_modification(self):
        store = _TestStore.instance()
        base = {KeySequence(["A"]): {"*": CommandPayload("cmd.a")}}
        diff = {KeySequence(["A"]): {"*": CommandPayload("cmd.b")}}
        result = store._apply_diff(base, diff)
        assert result[KeySequence(["A"])]["*"].id == "cmd.b"


class TestBindingStoreBasePayloadEqual:
    def test_equal(self):
        store = _TestStore.instance()
        a = CommandPayload("cmd.a", {"x": 1})
        b = CommandPayload("cmd.a", {"x": 1})
        assert store._payload_equal(a, b)

    def test_different_id(self):
        store = _TestStore.instance()
        a = CommandPayload("cmd.a")
        b = CommandPayload("cmd.b")
        assert not store._payload_equal(a, b)

    def test_different_args(self):
        store = _TestStore.instance()
        a = CommandPayload("cmd.a", {"x": 1})
        b = CommandPayload("cmd.a", {"x": 2})
        assert not store._payload_equal(a, b)

    def test_none_args_equal_empty(self):
        store = _TestStore.instance()
        a = CommandPayload("cmd.a")
        b = CommandPayload("cmd.a", {})
        assert store._payload_equal(a, b)


class TestBindingStoreBaseSerialization:
    def test_to_items_and_from_items_roundtrip(self):
        store = _TestStore.instance()
        data = {
            KeySequence(["A"]): {"*": CommandPayload("cmd.a", {"x": 1})},
            KeySequence(["Control", "B"]): {
                "*": CommandPayload("cmd.b"),
                "viewer": CommandPayload("cmd.b_view"),
            },
        }
        items = store._to_items(data)
        restored = store._from_items(items)
        for key in data:
            assert key in restored
            for scope in data[key]:
                assert scope in restored[key]
                assert restored[key][scope].id == data[key][scope].id
                assert restored[key][scope].args == data[key][scope].args

    def test_from_items_skips_invalid_entries(self):
        store = _TestStore.instance()
        items = [
            "not a dict",
            {"key": {"bad": "format"}, "scopes": {"*": {"id": "cmd.x"}}},
            {"scopes": {"*": {"id": "cmd.y"}}},
        ]
        result = store._from_items(items)
        assert len(result) == 0

    def test_from_items_handles_none_payload(self):
        store = _TestStore.instance()
        items = [{"key": {"key": "A"}, "scopes": {"*": None}}]
        result = store._from_items(items)
        assert KeySequence(["A"]) in result
        assert result[KeySequence(["A"])]["*"] is None


class TestBindingStoreBaseSaveLoad:
    def test_save_and_load_roundtrip(self, tmp_path):
        store = _TestStore.instance()
        store.set_all({
            KeySequence(["A"]): {"*": CommandPayload("cmd.a", {"x": 1})},
        })
        path = str(tmp_path / "bindings.json")
        store.save_to_file(path)

        store2 = _TestStore.__new__(_TestStore)
        store2._data = {}
        loaded = store2.load_from_file(path)
        assert loaded is True
        assert KeySequence(["A"]) in store2._data

    def test_load_nonexistent_file(self, tmp_path):
        store = _TestStore.instance()
        loaded = store.load_from_file(str(tmp_path / "no_such_file.json"))
        assert loaded is False

    def test_load_invalid_json(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("not json", encoding="utf-8")
        store = _TestStore.instance()
        loaded = store.load_from_file(str(p))
        assert loaded is False

    def test_load_no_items_key(self, tmp_path):
        p = tmp_path / "no_items.json"
        p.write_text('{"data": []}', encoding="utf-8")
        store = _TestStore.instance()
        loaded = store.load_from_file(str(p))
        assert loaded is False
