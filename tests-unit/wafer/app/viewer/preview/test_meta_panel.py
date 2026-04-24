from unittest.mock import patch, MagicMock
from PySide6 import QtWidgets
from wafer.app.viewer.preview.meta_panel import MetaViewerWidget, _FIXED_SECTION_KEYS
from wafer.ui.panel.meta_viewer import CollapsibleCard, MetaRowWidget


def _sample_meta():
    return {
        "source": {"source": "/a.png", "name": "a.png"},
        "file": {"name": "a.png", "size": "1.0 MB (1048576 bytes)"},
        "tag": {"landscape": "1"},
        "prefixed": {
            "exiftool": {"width": "100", "height": "200"},
            "image": {"format": "PNG"},
        },
    }


def test_set_data_creates_sections(qtbot):
    w = MetaViewerWidget()
    qtbot.addWidget(w)
    w.set_data(_sample_meta())
    assert "source" in w._sections
    assert "file" in w._sections
    assert "tag" in w._sections
    assert "exiftool" in w._sections
    assert "image" in w._sections
    assert len(w._sections) == 5


def test_sections_default_expanded(qtbot):
    w = MetaViewerWidget()
    qtbot.addWidget(w)
    w.set_data(_sample_meta())
    for card in w._sections.values():
        if isinstance(card, CollapsibleCard):
            assert card.expanded is True


def test_collapse_state_persists(qtbot):
    w = MetaViewerWidget()
    qtbot.addWidget(w)
    w.set_data(_sample_meta())
    card = w._sections["tag"]
    if isinstance(card, CollapsibleCard):
        card.set_expanded(False)
        w._on_section_toggled("tag", False)
    state = w._save_collapse_state()
    assert "tag" in state["collapsed"]
    assert state["collapsed"]["tag"] is False


def test_restore_collapse_state(qtbot):
    w = MetaViewerWidget()
    qtbot.addWidget(w)
    w.set_data(_sample_meta())
    w._restore_collapse_state({"collapsed": {"tag": False, "exiftool": False}})
    for key in ("tag", "exiftool"):
        card = w._sections[key]
        if isinstance(card, CollapsibleCard):
            assert card.expanded is False
    source_card = w._sections["source"]
    if isinstance(source_card, CollapsibleCard):
        assert source_card.expanded is True


def test_update_reuses_existing_sections(qtbot):
    w = MetaViewerWidget()
    qtbot.addWidget(w)
    w.set_data(_sample_meta())
    first_sections = dict(w._sections)
    w.set_data(_sample_meta())
    for key, card in w._sections.items():
        assert card is first_sections[key]


def test_sections_order(qtbot):
    w = MetaViewerWidget()
    qtbot.addWidget(w)
    w.set_data(_sample_meta())
    keys = list(w._sections.keys())
    assert keys[:3] == ["source", "file", "tag"]
    assert set(keys[3:]) == {"exiftool", "image"}


def test_empty_prefixed(qtbot):
    w = MetaViewerWidget()
    qtbot.addWidget(w)
    meta = {"source": {"name": "a"}, "file": {}, "tag": {}, "prefixed": {}}
    w.set_data(meta)
    assert len(w._sections) == 3


def test_builtin_section_is_collapsible_card(qtbot):
    w = MetaViewerWidget()
    qtbot.addWidget(w)
    meta = {"source": {"name": "a"}, "file": {}, "tag": {}, "prefixed": {"unknown_prefix": {"k": "v"}}}
    w.set_data(meta)
    for key in ("source", "file", "tag", "unknown_prefix"):
        card = w._sections[key]
        assert isinstance(card, CollapsibleCard)
        if key == "tag":
            from wafer.app.viewer.preview.editable_tag_card import EditableTagCard
            assert isinstance(card, EditableTagCard)
        else:
            assert isinstance(card.content_widget(), MetaRowWidget)


def test_section_titles_are_lowercase(qtbot):
    w = MetaViewerWidget()
    qtbot.addWidget(w)
    meta = {"source": {"name": "a"}, "file": {}, "tag": {}, "prefixed": {"my_plugin": {"k": "v"}}}
    w.set_data(meta)
    for key in ("source", "file", "tag", "my_plugin"):
        card = w._sections[key]
        assert isinstance(card, CollapsibleCard)
        assert key in card.title()


def test_clear_hides_sections_and_shows_placeholder(qtbot):
    w = MetaViewerWidget()
    qtbot.addWidget(w)
    w.set_data(_sample_meta())
    assert w._placeholder.isHidden()
    for sec in w._sections.values():
        assert not sec.isHidden()
    w.clear()
    assert not w._placeholder.isHidden()
    for sec in w._sections.values():
        assert sec.isHidden()


def test_set_data_after_clear_hides_placeholder(qtbot):
    w = MetaViewerWidget()
    qtbot.addWidget(w)
    w.set_data(_sample_meta())
    w.clear()
    assert not w._placeholder.isHidden()
    w.set_data(_sample_meta())
    assert w._placeholder.isHidden()


def test_placeholder_visible_on_init(qtbot):
    w = MetaViewerWidget()
    qtbot.addWidget(w)
    assert not w._placeholder.isHidden()
