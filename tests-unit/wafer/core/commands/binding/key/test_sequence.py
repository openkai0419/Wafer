import pytest

from wafer.core.commands.binding.key.sequence import KeySequence, Key, KeySpecCatalog


class TestKeySequenceInit:
    def test_single_key(self):
        ks = KeySequence(["A"])
        assert ks.key == "A"
        assert ks.modifier is None

    def test_two_keys(self):
        ks = KeySequence(["Control", "A"])
        assert ks.modifier == "Control"
        assert ks.key == "A"

    def test_more_than_two_truncated(self):
        ks = KeySequence(["Control", "Shift", "A"])
        assert len(ks.to_tuple()) == 2

    def test_from_key_sequence(self):
        original = KeySequence(["Shift", "B"])
        copy = KeySequence(original)
        assert copy == original
        assert copy.to_tuple() == original.to_tuple()

    def test_empty_list_raises(self):
        with pytest.raises(ValueError, match="at least one key"):
            KeySequence([])

    def test_invalid_type_raises(self):
        with pytest.raises(TypeError, match="list|tuple|KeySequence"):
            KeySequence("A")

    def test_whitespace_stripped(self):
        ks = KeySequence(["  A  "])
        assert ks.key == "A"

    def test_empty_strings_filtered(self):
        with pytest.raises(ValueError, match="at least one key"):
            KeySequence(["", "  "])

    def test_tuple_input(self):
        ks = KeySequence(("Control", "A"))
        assert ks.modifier == "Control"


class TestKeySequenceSerialization:
    def test_to_dict_single_key(self):
        ks = KeySequence(["A"])
        assert ks.to_dict() == {"key": "A"}

    def test_to_dict_two_keys(self):
        ks = KeySequence(["Control", "A"])
        assert ks.to_dict() == {"modifier": "Control", "key": "A"}

    def test_from_dict_single_key(self):
        ks = KeySequence.from_dict({"key": "A"})
        assert ks.key == "A"
        assert ks.modifier is None

    def test_from_dict_two_keys(self):
        ks = KeySequence.from_dict({"modifier": "Control", "key": "A"})
        assert ks.modifier == "Control"
        assert ks.key == "A"

    def test_from_dict_missing_key_raises(self):
        with pytest.raises(ValueError, match="Key is required"):
            KeySequence.from_dict({"modifier": "Control"})

    def test_from_dict_empty_key_raises(self):
        with pytest.raises(ValueError, match="Key is required"):
            KeySequence.from_dict({"key": ""})

    def test_roundtrip(self):
        original = KeySequence(["Shift", "F5"])
        restored = KeySequence.from_dict(original.to_dict())
        assert original == restored


class TestKeySequenceEquality:
    def test_equal(self):
        a = KeySequence(["Control", "A"])
        b = KeySequence(["Control", "A"])
        assert a == b

    def test_not_equal_different_keys(self):
        a = KeySequence(["Control", "A"])
        b = KeySequence(["Control", "B"])
        assert a != b

    def test_not_equal_different_type(self):
        a = KeySequence(["A"])
        assert a != "A"
        assert a != 42

    def test_hash_equal(self):
        a = KeySequence(["Control", "A"])
        b = KeySequence(["Control", "A"])
        assert hash(a) == hash(b)

    def test_hash_can_be_dict_key(self):
        ks = KeySequence(["A"])
        d = {ks: "value"}
        assert d[KeySequence(["A"])] == "value"


class TestKeySequenceOrdering:
    def test_lt(self):
        a = KeySequence(["A"])
        b = KeySequence(["B"])
        assert a < b

    def test_lt_not_implemented_for_other_types(self):
        a = KeySequence(["A"])
        assert a.__lt__("B") == NotImplemented


class TestKeySequenceStr:
    def test_single_key(self):
        assert str(KeySequence(["A"])) == "A"

    def test_two_keys(self):
        assert str(KeySequence(["Control", "A"])) == "Control+A"

    def test_repr(self):
        ks = KeySequence(["Control", "A"])
        r = repr(ks)
        assert "KeySequence" in r
        assert "Control" in r


class TestKeySubclass:
    def test_single_string(self):
        ks = Key("H")
        assert ks.key == "H"
        assert ks.modifier is None

    def test_two_strings(self):
        ks = Key("Control", "A")
        assert ks.modifier == "Control"
        assert ks.key == "A"

    def test_from_list(self):
        ks = Key(["Shift", "B"])
        assert ks.modifier == "Shift"
        assert ks.key == "B"

    def test_from_tuple(self):
        ks = Key(("Alt", "F4"))
        assert ks.modifier == "Alt"
        assert ks.key == "F4"

    def test_equality_with_key_sequence(self):
        a = Key("Control", "A")
        b = KeySequence(["Control", "A"])
        assert a == b


class TestKeySpecCatalog:
    def setup_method(self):
        self.catalog = KeySpecCatalog()

    def test_modifier_priority_known(self):
        assert self.catalog.modifier_priority("Control") == 0
        assert self.catalog.modifier_priority("Shift") == 1
        assert self.catalog.modifier_priority("Alt") == 2
        assert self.catalog.modifier_priority("Meta") == 3

    def test_modifier_priority_unknown(self):
        assert self.catalog.modifier_priority("Custom") == 9

    def test_sort_modifiers(self):
        result = self.catalog.sort_modifiers(["Meta", "Control", "Shift"])
        assert result == ["Control", "Shift", "Meta"]

    def test_sort_modifiers_excludes(self):
        result = self.catalog.sort_modifiers(["Meta", "Control", "Shift"], exclude=("Control",))
        assert "Control" not in result

    def test_key_sort_tuple_modifier(self):
        t = self.catalog.key_sort_tuple("Control")
        assert t[0] == 0

    def test_key_sort_tuple_special(self):
        t = self.catalog.key_sort_tuple("Space")
        assert t[0] == 1

    def test_key_sort_tuple_empty(self):
        t = self.catalog.key_sort_tuple("")
        assert t[0] == 9

    def test_sort_main_keys(self):
        keys = ["Z", "A", "F1"]
        result = self.catalog.sort_main_keys(keys, exclude=())
        assert isinstance(result, list)
        assert len(result) == 3
