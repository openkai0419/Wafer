import pytest
import json

from wafer.core.commands.command.payload import (
    CommandPayload,
    ScopedPayloads,
    normalize_scoped_payloads,
    format_payload_display,
)


class TestCommandPayloadInit:
    def test_valid_creation(self):
        p = CommandPayload("cmd.test", {"step": 5})
        assert p.id == "cmd.test"
        assert p.args == {"step": 5}

    def test_none_args_become_empty_dict(self):
        p = CommandPayload("cmd.test")
        assert p.args == {}

    def test_empty_id_raises(self):
        with pytest.raises(ValueError, match="non-empty string"):
            CommandPayload("", {})

    def test_non_string_id_raises(self):
        with pytest.raises(ValueError, match="non-empty string"):
            CommandPayload(123, {})

    def test_none_id_raises(self):
        with pytest.raises(ValueError):
            CommandPayload(None, {})


class TestCommandPayloadSerialization:
    def test_to_dict(self):
        p = CommandPayload("cmd.x", {"a": 1})
        d = p.to_dict()
        assert d == {"id": "cmd.x", "args": {"a": 1}}

    def test_to_json(self):
        p = CommandPayload("cmd.x", {"a": 1})
        j = p.to_json()
        parsed = json.loads(j)
        assert parsed["id"] == "cmd.x"
        assert parsed["args"] == {"a": 1}

    def test_from_dict(self):
        p = CommandPayload.from_dict({"id": "cmd.x", "args": {"a": 1}})
        assert p.id == "cmd.x"
        assert p.args == {"a": 1}

    def test_from_dict_without_args(self):
        p = CommandPayload.from_dict({"id": "cmd.x"})
        assert p.id == "cmd.x"
        assert p.args == {}

    def test_from_dict_missing_id_raises(self):
        with pytest.raises(TypeError, match="must contain id"):
            CommandPayload.from_dict({"args": {}})

    def test_from_dict_non_dict_raises(self):
        with pytest.raises(TypeError, match="must contain id"):
            CommandPayload.from_dict("not a dict")

    def test_from_json(self):
        j = json.dumps({"id": "cmd.y", "args": {"b": 2}})
        p = CommandPayload.from_json(j)
        assert p.id == "cmd.y"
        assert p.args == {"b": 2}

    def test_from_json_invalid_raises(self):
        with pytest.raises(TypeError, match="invalid json"):
            CommandPayload.from_json("not json")

    def test_roundtrip(self):
        original = CommandPayload("cmd.rt", {"x": 42, "y": "hello"})
        restored = CommandPayload.from_json(original.to_json())
        assert restored.id == original.id
        assert restored.args == original.args


class TestCommandPayloadFromAny:
    def test_from_payload_instance(self):
        p = CommandPayload("cmd.x")
        assert CommandPayload.from_any(p) is p

    def test_from_dict(self):
        p = CommandPayload.from_any({"id": "cmd.x", "args": {"a": 1}})
        assert p.id == "cmd.x"

    def test_from_invalid_type_raises(self):
        with pytest.raises(TypeError, match="CommandPayload required"):
            CommandPayload.from_any(42)

    def test_from_string_raises(self):
        with pytest.raises(TypeError, match="CommandPayload required"):
            CommandPayload.from_any("cmd.x")


class TestScopedPayloads:
    def test_init_requires_dict(self):
        with pytest.raises(TypeError, match="scopes must be dict"):
            ScopedPayloads("not a dict")

    def test_to_dict(self):
        sp = ScopedPayloads({"*": {"id": "cmd.x"}})
        assert sp.to_dict() == {"*": {"id": "cmd.x"}}

    def test_from_any_dict_with_id_wraps_to_global(self):
        sp = ScopedPayloads.from_any({"id": "cmd.x"})
        assert "*" in sp.to_dict()
        assert sp.to_dict()["*"]["id"] == "cmd.x"

    def test_from_any_dict_without_id(self):
        sp = ScopedPayloads.from_any({"viewer": {"id": "cmd.x"}})
        assert "viewer" in sp.to_dict()

    def test_from_any_scoped_payloads_instance(self):
        original = ScopedPayloads({"*": {"id": "cmd.x"}})
        assert ScopedPayloads.from_any(original) is original

    def test_from_any_invalid_type_raises(self):
        with pytest.raises(TypeError, match="scopes must be dict"):
            ScopedPayloads.from_any(42)


class TestNormalizeScopedPayloads:
    def test_basic(self):
        result = normalize_scoped_payloads({"*": {"id": "cmd.x", "args": {"a": 1}}})
        assert "*" in result
        assert isinstance(result["*"], CommandPayload)
        assert result["*"].id == "cmd.x"

    def test_none_values_skipped(self):
        result = normalize_scoped_payloads({"*": {"id": "cmd.x"}, "viewer": None})
        assert "viewer" not in result
        assert "*" in result

    def test_dict_with_id_wraps_to_global(self):
        result = normalize_scoped_payloads({"id": "cmd.x"})
        assert "*" in result
        assert result["*"].id == "cmd.x"


class TestFormatPayloadDisplay:
    def test_simple_command(self):
        p = CommandPayload("cmd.test")
        result = format_payload_display(p)
        assert "cmd.test" in result

    def test_invalid_payload_fallback(self):
        result = format_payload_display("just a string")
        assert result == "just a string"

    def test_dict_payload(self):
        result = format_payload_display({"id": "cmd.x"})
        assert "cmd.x" in result
