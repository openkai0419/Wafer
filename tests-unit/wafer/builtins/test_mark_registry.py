from wafer.builtins.mark import MarkRegistry


def test_mark_registry_singleton():
    a = MarkRegistry.instance()
    b = MarkRegistry.instance()
    assert a is b


def test_mark_registry_default_ids():
    reg = MarkRegistry.instance()
    ids = reg.ids()
    assert len(ids) >= 9
    for mid in ("1", "2", "9"):
        assert mid in ids


def test_mark_tag_key_and_parse():
    assert MarkRegistry.tag_key("3") == "mark.3" if hasattr(MarkRegistry, "tag_key") else MarkRegistry.tag_key("3")
    assert MarkRegistry.tag_key("3") == "mark.3"
    assert MarkRegistry.parse_key("mark.3") == "3"
    assert MarkRegistry.parse_key("notmark.1") is None
    assert MarkRegistry.parse_key("plainkey") is None


def test_mark_registry_color_for_known():
    reg = MarkRegistry.instance()
    c = reg.color_for("1")
    assert isinstance(c, str)
    assert c.startswith("#")


def test_mark_registry_color_for_unknown():
    reg = MarkRegistry.instance()
    c = reg.color_for("nonexistent_id_xyz")
    assert isinstance(c, str)
    assert c.startswith("#")


def test_mark_registry_set_color_changes_state(qtbot=None):
    reg = MarkRegistry.instance()
    original = reg.color_for("1")
    try:
        emitted = []
        reg.changed.connect(lambda: emitted.append(True))
        reg.set_color("1", "#123456")
        assert reg.color_for("1") == "#123456"
        assert emitted
    finally:
        reg.set_color("1", original)
