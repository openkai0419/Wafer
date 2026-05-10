from wafer.builtins.mark import Mark, MarkRegistry
from wafer.builtins.mark.registry import _normalize_id
from wafer.builtins.mark.shapes import DEFAULT_SHAPE_KEY

import pytest


def test_mark_registry_singleton():
    a = MarkRegistry.instance()
    b = MarkRegistry.instance()
    assert a is b


def test_mark_registry_default_has_at_least_one_mark():
    reg = MarkRegistry.instance()
    assert len(reg.marks()) >= 1


def test_mark_tag_key_and_parse():
    assert MarkRegistry.key("3") == "mark.3"
    assert MarkRegistry.key("fav") == "mark.fav"
    assert MarkRegistry.parse_key("mark.3") == "3"
    assert MarkRegistry.parse_key("mark.fav") == "fav"
    assert MarkRegistry.parse_key("notmark.1") is None
    assert MarkRegistry.parse_key("plainkey") is None


def test_mark_registry_color_of_unknown_returns_fallback():
    reg = MarkRegistry.instance()
    c = reg.color_of("nonexistent_xyz")
    assert isinstance(c, str) and c.startswith("#")


def test_mark_registry_add_creates_unique_id():
    reg = MarkRegistry.instance()
    initial = set(reg.ids())
    a = reg.add("Favorite Test", "#112233")
    b = reg.add("Another Favorite", "#445566")
    try:
        assert a not in initial
        assert b not in initial
        assert a != b
        assert reg.color_of(a) == "#112233"
        assert reg.name_of(a) == "Favorite Test"
        assert reg.shape_key_of(a) == DEFAULT_SHAPE_KEY
    finally:
        reg.remove(a)
        reg.remove(b)


def test_mark_registry_add_duplicate_name_auto_suffixes():
    reg = MarkRegistry.instance()
    a = reg.add("Dup Test Mark", "#112233")
    b = reg.add("Dup Test Mark", "#445566")
    c = reg.add("  dup test mark  ", "#778899")
    try:
        assert reg.name_of(a) == "Dup Test Mark"
        assert reg.name_of(b) == "Dup Test Mark 2"
        assert reg.name_of(c) == "dup test mark 3"
    finally:
        reg.remove(a)
        reg.remove(b)
        reg.remove(c)


def test_mark_registry_rename_to_duplicate_auto_suffixes():
    reg = MarkRegistry.instance()
    a = reg.add("Rn Source", "#000000")
    b = reg.add("Rn Target", "#ffffff")
    try:
        final = reg.rename(a, "Rn Target")
        assert final == "Rn Target 2"
        assert reg.name_of(a) == "Rn Target 2"
        assert reg.name_of(b) == "Rn Target"
    finally:
        reg.remove(a)
        reg.remove(b)


def test_mark_registry_add_empty_raises():
    reg = MarkRegistry.instance()
    with pytest.raises(ValueError):
        reg.add("   ", "#000000")


def test_mark_registry_rename_and_set_color_emit_changed():
    reg = MarkRegistry.instance()
    mid = reg.add("Tmp Mark", "#000000")
    try:
        emitted = []
        reg.changed.connect(lambda: emitted.append(True))
        reg.rename(mid, "Renamed")
        assert reg.name_of(mid) == "Renamed"
        reg.set_color(mid, "#abcdef")
        assert reg.color_of(mid) == "#abcdef"
        assert len(emitted) >= 2
    finally:
        reg.remove(mid)


def test_mark_registry_set_shape_key_emit_changed():
    reg = MarkRegistry.instance()
    mid = reg.add("Shape Mark", "#000000", shape_key="star")
    try:
        emitted = []
        reg.changed.connect(lambda: emitted.append(True))
        assert reg.shape_key_of(mid) == "star"
        reg.set_shape_key(mid, "heart")
        assert reg.shape_key_of(mid) == "heart"
        assert emitted
    finally:
        reg.remove(mid)


def test_mark_registry_remove():
    reg = MarkRegistry.instance()
    mid = reg.add("Remove Me", "#ffffff")
    assert reg.get(mid) is not None
    reg.remove(mid)
    assert reg.get(mid) is None


def test_mark_registry_scope_defaults_and_updates():
    reg = MarkRegistry.instance()
    mid = reg.add("Scoped Mark", "#ffffff")
    try:
        assert reg.scope_of(mid) == "meta_info"
        assert reg.set_scope(mid, "tag") is True
        assert reg.scope_of(mid) == "tag"
        assert mid in reg.ids_by_scope("tag")
        assert reg.set_scope(mid, "tag") is False
    finally:
        reg.remove(mid)


def test_normalize_id_basic():
    assert _normalize_id("Hello World") == "hello_world"
    assert _normalize_id("  Leading/Trailing  ") == "leading_trailing"
    assert _normalize_id("***") == "mark"
    assert _normalize_id("") == "mark"


def test_mark_dataclass():
    m = Mark(id="x", name="X", color="#000000")
    assert m.id == "x"
    assert m.name == "X"
    assert m.color == "#000000"
    assert m.storage_scope == "meta_info"
    assert m.shape_key == DEFAULT_SHAPE_KEY
