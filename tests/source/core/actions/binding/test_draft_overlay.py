import pytest
from source.core.actions.binding.editors_common import DraftOverlay
from source.core.actions.binding.store_base import resolve_for_widget
from source.core.actions.command.payload import CommandPayload


def _pay(name: str) -> CommandPayload:
    return CommandPayload(name, {})


class TestUpdate:
    def test_update_adds_entry(self):
        d = DraftOverlay()
        d.update("a", {"*": _pay("cmd1")})
        merged = d.merge({})
        assert "a" in merged
        assert merged["a"]["*"].id == "cmd1"

    def test_update_empty_scopes_acts_as_delete(self):
        d = DraftOverlay()
        d.update("a", {"*": _pay("cmd1")})
        d.update("a", {})
        merged = d.merge({"a": {"*": _pay("orig")}})
        assert "a" not in merged

    def test_update_overwrites_previous(self):
        d = DraftOverlay()
        d.update("a", {"*": _pay("cmd1")})
        d.update("a", {"*": _pay("cmd2")})
        merged = d.merge({})
        assert merged["a"]["*"].id == "cmd2"


class TestDelete:
    def test_delete_removes_from_store(self):
        d = DraftOverlay()
        d.delete("a")
        merged = d.merge({"a": {"*": _pay("orig")}})
        assert "a" not in merged

    def test_delete_after_update_removes(self):
        d = DraftOverlay()
        d.update("a", {"*": _pay("cmd1")})
        d.delete("a")
        merged = d.merge({})
        assert "a" not in merged

    def test_update_after_delete_restores(self):
        d = DraftOverlay()
        d.delete("a")
        d.update("a", {"*": _pay("cmd2")})
        merged = d.merge({})
        assert "a" in merged
        assert merged["a"]["*"].id == "cmd2"

    def test_delete_nonexistent_key_harmless(self):
        d = DraftOverlay()
        d.delete("x")
        merged = d.merge({"a": {"*": _pay("ok")}})
        assert "a" in merged
        assert "x" not in merged


class TestMerge:
    def test_merge_preserves_untouched_store_data(self):
        d = DraftOverlay()
        d.update("b", {"*": _pay("new")})
        merged = d.merge({"a": {"*": _pay("orig")}})
        assert merged["a"]["*"].id == "orig"
        assert merged["b"]["*"].id == "new"

    def test_merge_does_not_mutate_store_data(self):
        d = DraftOverlay()
        d.delete("a")
        store = {"a": {"*": _pay("orig")}}
        d.merge(store)
        assert "a" in store

    def test_merge_update_overrides_store(self):
        d = DraftOverlay()
        d.update("a", {"*": _pay("updated")})
        merged = d.merge({"a": {"*": _pay("orig")}})
        assert merged["a"]["*"].id == "updated"


class TestReplaceAll:
    def test_replace_all_sets_changes_and_deletes(self):
        d = DraftOverlay()
        d.replace_all({
            "a": {"*": _pay("new_a")},
            "b": {},
        })
        merged = d.merge({"b": {"*": _pay("orig_b")}, "c": {"*": _pay("orig_c")}})
        assert merged["a"]["*"].id == "new_a"
        assert "b" not in merged
        assert merged["c"]["*"].id == "orig_c"


class TestHasAnyPayload:
    def test_with_payload(self):
        assert DraftOverlay.has_any_payload({"*": _pay("x")}) is True

    def test_empty_dict(self):
        assert DraftOverlay.has_any_payload({}) is False

    def test_non_dict(self):
        assert DraftOverlay.has_any_payload(None) is False
        assert DraftOverlay.has_any_payload("str") is False

    def test_dict_with_non_payload_values(self):
        assert DraftOverlay.has_any_payload({"*": "not a payload"}) is False


class TestKeys:
    def test_keys_empty(self):
        d = DraftOverlay()
        assert d.keys() == set()

    def test_keys_after_update(self):
        d = DraftOverlay()
        d.update("a", {"*": _pay("x")})
        d.update("b", {"*": _pay("y")})
        assert d.keys() == {"a", "b"}

    def test_keys_after_delete(self):
        d = DraftOverlay()
        d.delete("c")
        assert d.keys() == {"c"}

    def test_keys_union_of_changes_and_deleted(self):
        d = DraftOverlay()
        d.update("a", {"*": _pay("x")})
        d.delete("b")
        assert d.keys() == {"a", "b"}

    def test_keys_delete_after_update_moves_to_deleted(self):
        d = DraftOverlay()
        d.update("a", {"*": _pay("x")})
        d.delete("a")
        assert d.keys() == {"a"}


class TestResolveForWidget:
    def test_resolve_global_scope(self):
        data = {"k1": {"*": _pay("cmd1")}}
        result = resolve_for_widget(data, "viewer")
        assert result["k1"].id == "cmd1"

    def test_resolve_widget_scope_overrides_global(self):
        data = {"k1": {"*": _pay("global"), "viewer": _pay("specific")}}
        result = resolve_for_widget(data, "viewer")
        assert result["k1"].id == "specific"

    def test_resolve_unrelated_scope_falls_back_to_global(self):
        data = {"k1": {"*": _pay("global"), "viewer": _pay("specific")}}
        result = resolve_for_widget(data, "folder")
        assert result["k1"].id == "global"

    def test_resolve_no_matching_scope_excluded(self):
        data = {"k1": {"viewer": _pay("only_viewer")}}
        result = resolve_for_widget(data, "folder")
        assert "k1" not in result

    def test_resolve_multiple_keys(self):
        data = {
            "k1": {"*": _pay("a")},
            "k2": {"folder": _pay("b")},
            "k3": {"*": _pay("c"), "folder": _pay("d")},
        }
        result = resolve_for_widget(data, "folder")
        assert result["k1"].id == "a"
        assert result["k2"].id == "b"
        assert result["k3"].id == "d"

    def test_resolve_empty_data(self):
        assert resolve_for_widget({}, "viewer") == {}
