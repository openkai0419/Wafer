import pytest

from wafer.qt.commands.binding.mouse.types import (
    ClickType,
    MouseButton,
    ModifierKey,
    MouseActionKey,
)


class TestClickType:
    def test_from_any_enum(self):
        assert ClickType.from_any(ClickType.SINGLE) is ClickType.SINGLE

    def test_from_any_string(self):
        assert ClickType.from_any("SINGLE") is ClickType.SINGLE

    def test_from_any_lowercase(self):
        assert ClickType.from_any("single") is ClickType.SINGLE

    def test_from_any_alias_wheelup(self):
        assert ClickType.from_any("WHEELUP") is ClickType.WHEEL_UP

    def test_from_any_with_spaces(self):
        assert ClickType.from_any("WHEEL UP") is ClickType.WHEEL_UP

    def test_from_any_with_hyphens(self):
        assert ClickType.from_any("drag-start") is ClickType.DRAG_START

    def test_from_any_invalid_raises(self):
        with pytest.raises(ValueError, match="invalid ClickType"):
            ClickType.from_any("INVALID")

    def test_from_any_non_string_raises(self):
        with pytest.raises(TypeError, match="ClickType must be"):
            ClickType.from_any(42)


class TestMouseButton:
    def test_from_any_enum(self):
        assert MouseButton.from_any(MouseButton.LEFT) is MouseButton.LEFT

    def test_from_any_string(self):
        assert MouseButton.from_any("LEFT") is MouseButton.LEFT

    def test_from_any_alias_lmb(self):
        assert MouseButton.from_any("LMB") is MouseButton.LEFT

    def test_from_any_invalid_raises(self):
        with pytest.raises(ValueError, match="invalid MouseButton"):
            MouseButton.from_any("UNKNOWN")

    def test_from_any_non_string_raises(self):
        with pytest.raises(TypeError):
            MouseButton.from_any(42)


class TestModifierKey:
    def test_from_any_enum(self):
        assert ModifierKey.from_any(ModifierKey.CTRL) is ModifierKey.CTRL

    def test_from_any_string(self):
        assert ModifierKey.from_any("CTRL") is ModifierKey.CTRL

    def test_from_any_alias_control(self):
        assert ModifierKey.from_any("CONTROL") is ModifierKey.CTRL

    def test_from_any_invalid_raises(self):
        with pytest.raises(ValueError, match="invalid ModifierKey"):
            ModifierKey.from_any("UNKNOWN")

    def test_from_any_non_string_raises(self):
        with pytest.raises(TypeError):
            ModifierKey.from_any(42)


class TestMouseActionKey:
    def test_basic_creation(self):
        k = MouseActionKey("LEFT", "SINGLE")
        assert k.button is MouseButton.LEFT
        assert k.click_type is ClickType.SINGLE
        assert k.held_buttons == frozenset()
        assert k.modifiers == frozenset()

    def test_with_held_buttons(self):
        k = MouseActionKey("LEFT", "SINGLE", held_buttons=["RIGHT"])
        assert MouseButton.RIGHT in k.held_buttons

    def test_with_modifiers(self):
        k = MouseActionKey("LEFT", "SINGLE", modifiers=["CTRL", "SHIFT"])
        assert ModifierKey.CTRL in k.modifiers
        assert ModifierKey.SHIFT in k.modifiers

    def test_missing_click_type_raises(self):
        with pytest.raises(TypeError, match="requires click_type"):
            MouseActionKey("LEFT")

    def test_none_held_buttons_becomes_empty(self):
        k = MouseActionKey("LEFT", "SINGLE", held_buttons=None)
        assert k.held_buttons == frozenset()

    def test_empty_dict_held_buttons_becomes_empty(self):
        k = MouseActionKey("LEFT", "SINGLE", held_buttons={})
        assert k.held_buttons == frozenset()

    def test_none_modifiers_becomes_empty(self):
        k = MouseActionKey("LEFT", "SINGLE", modifiers=None)
        assert k.modifiers == frozenset()

    def test_empty_dict_modifiers_becomes_empty(self):
        k = MouseActionKey("LEFT", "SINGLE", modifiers={})
        assert k.modifiers == frozenset()

    def test_equality(self):
        a = MouseActionKey("LEFT", "SINGLE", modifiers=["CTRL"])
        b = MouseActionKey("LEFT", "SINGLE", modifiers=["CTRL"])
        assert a == b

    def test_inequality(self):
        a = MouseActionKey("LEFT", "SINGLE", modifiers=["CTRL"])
        assert a != MouseActionKey("RIGHT", "SINGLE", modifiers=["CTRL"])
        assert a != MouseActionKey("LEFT", "DOUBLE", modifiers=["CTRL"])
        assert a != MouseActionKey("LEFT", "SINGLE", modifiers=["SHIFT"])
        assert a != MouseActionKey("LEFT", "SINGLE", modifiers=["CTRL"], held_buttons=["RIGHT"])

    def test_inequality_with_non_mouseactionkey(self):
        a = MouseActionKey("LEFT", "SINGLE")
        assert a != "LEFT SINGLE"

    def test_hash_equal(self):
        a = MouseActionKey("LEFT", "DOUBLE", modifiers=["CTRL"])
        b = MouseActionKey("LEFT", "DOUBLE", modifiers=["CTRL"])
        assert hash(a) == hash(b)

    def test_repr(self):
        r = repr(MouseActionKey("LEFT", "SINGLE", modifiers=["CTRL"], held_buttons=["RIGHT"]))
        for part in ("LEFT", "SINGLE", "CTRL", "RIGHT"):
            assert part in r


class TestMouseActionKeySerialization:
    def test_to_dict(self):
        k = MouseActionKey("LEFT", "SINGLE", held_buttons=["RIGHT"], modifiers=["CTRL"])
        d = k.to_dict()
        assert d["button"] == "LEFT"
        assert d["click"] == "SINGLE"
        assert "RIGHT" in d["held"]
        assert "CTRL" in d["modifiers"]

    def test_to_dict_empty_held_and_modifiers(self):
        k = MouseActionKey("LEFT", "SINGLE")
        d = k.to_dict()
        assert d["held"] == []
        assert d["modifiers"] == []

    def test_from_dict(self):
        d = {"button": "LEFT", "click": "SINGLE", "held": ["RIGHT"], "modifiers": ["CTRL"]}
        k = MouseActionKey.from_dict(d)
        assert k.button is MouseButton.LEFT
        assert k.click_type is ClickType.SINGLE
        assert MouseButton.RIGHT in k.held_buttons
        assert ModifierKey.CTRL in k.modifiers

    def test_from_dict_non_dict_raises(self):
        with pytest.raises(TypeError, match="dict required"):
            MouseActionKey.from_dict("not a dict")

    def test_from_dict_missing_held(self):
        d = {"button": "LEFT", "click": "SINGLE"}
        k = MouseActionKey.from_dict(d)
        assert k.held_buttons == frozenset()

    def test_roundtrip(self):
        original = MouseActionKey("MIDDLE", "DOUBLE", held_buttons=["LEFT"], modifiers=["ALT", "SHIFT"])
        restored = MouseActionKey.from_dict(original.to_dict())
        assert original == restored

    def test_string_aliases_in_from_dict(self):
        d = {"button": "LMB", "click": "WHEELUP", "held": [], "modifiers": ["CONTROL"]}
        k = MouseActionKey.from_dict(d)
        assert k.button is MouseButton.LEFT
        assert k.click_type is ClickType.WHEEL_UP
        assert ModifierKey.CTRL in k.modifiers
