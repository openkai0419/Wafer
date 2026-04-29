from unittest.mock import MagicMock

from PySide6 import QtWidgets
from wafer.app.viewer.preview.meta_panel import MetaViewerWidget, _FIXED_SECTION_KEYS
from wafer.app.viewer.preview.tag_edit_service import TagEditService
from wafer.ui.panel.meta_viewer import CollapsibleCard, MetaRowWidget
from wafer.ui.panel.meta_viewer import SECTION_MARKER_META_PREFIX, SECTION_MARKER_META_ROOT, SECTION_MARKER_TAG_PREFIX, SECTION_MARKER_TAG_ROOT
from wafer.app.viewer.preview.editable_tag_card import EditableTagCard


def _sample_meta():
    return {
        "source": {"source": "/a.png", "name": "a.png"},
        "file": {"name": "a.png", "size": "1.0 MB (1048576 bytes)"},
        "tag": {"landscape": "1"},
        "tag_prefixed": {},
        "tag_prefixed_locks": {},
        "meta": {},
        "meta_locks": {},
        "prefixed": {
            "exiftool": {"width": "100", "height": "200"},
            "image": {"format": "PNG"},
        },
        "_path": "/a.png",
        "_file_hash": "",
        "_tag_locks": {},
        "_db_name": "",
    }


def test_set_data_creates_sections(qtbot):
    w = MetaViewerWidget()
    qtbot.addWidget(w)
    w.set_data(_sample_meta())
    assert "source" in w._sections
    assert "file" in w._sections
    assert "tag" in w._sections
    assert "meta:exiftool" in w._sections
    assert "meta:image" in w._sections
    assert len(w._sections) == 5


def test_tag_section_hidden_when_empty(qtbot):
    w = MetaViewerWidget()
    qtbot.addWidget(w)
    meta = _sample_meta()
    meta["tag"] = {}
    w.set_data(meta)
    assert "tag" not in w._sections


def test_header_visible_only_after_set_data(qtbot):
    w = MetaViewerWidget()
    qtbot.addWidget(w)
    assert w._header.isHidden()
    w.set_data(_sample_meta())
    assert not w._header.isHidden()
    w.clear()
    assert w._header.isHidden()


def test_reload_button_emits_signal(qtbot):
    w = MetaViewerWidget()
    qtbot.addWidget(w)
    w.set_data(_sample_meta())
    with qtbot.waitSignal(w.reload_requested, timeout=500):
        w._reload_btn.click()


def test_header_has_single_visible_add_button(qtbot):
    w = MetaViewerWidget()
    qtbot.addWidget(w)
    w.set_data(_sample_meta())
    buttons = [btn for btn in w._header.findChildren(QtWidgets.QToolButton) if not btn.isHidden()]
    assert buttons == [w._reload_btn, w._add_btn]


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
    w._restore_collapse_state({"collapsed": {"tag": False, "meta:exiftool": False}})
    for key in ("tag", "meta:exiftool"):
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
    meta = _sample_meta()
    meta["meta"] = {"memo": "hello"}
    meta["tag_prefixed"] = {"custom": {"key": "value"}}
    w.set_data(meta)
    keys = list(w._sections.keys())
    assert keys[:4] == ["source", "file", "tag", "meta"]
    assert keys[4] == "tag:custom"
    assert set(keys[5:]) == {"meta:exiftool", "meta:image"}


def test_meta_root_section_is_separate_from_standard(qtbot):
    w = MetaViewerWidget()
    qtbot.addWidget(w)
    meta = _sample_meta()
    meta["meta"] = {"memo": "hello"}
    meta["meta_locks"] = {"memo": False}
    w.set_data(meta)
    assert "meta" in w._sections
    assert isinstance(w._sections["meta"], EditableTagCard)
    assert "memo" not in meta["file"]


def test_empty_prefixed(qtbot):
    w = MetaViewerWidget()
    qtbot.addWidget(w)
    meta = {"source": {"name": "a"}, "file": {}, "tag": {}, "tag_prefixed": {}, "tag_prefixed_locks": {}, "prefixed": {}}
    w.set_data(meta)
    assert len(w._sections) == 2


def test_builtin_section_is_collapsible_card(qtbot):
    w = MetaViewerWidget()
    qtbot.addWidget(w)
    meta = {
        "source": {"name": "a"},
        "file": {},
        "tag": {"k": "v"},
        "tag_prefixed": {},
        "tag_prefixed_locks": {},
        "meta": {},
        "meta_locks": {},
        "prefixed": {"unknown_prefix": {"k": "v"}},
    }
    w.set_data(meta)
    for key in ("source", "file", "tag", "meta:unknown_prefix"):
        card = w._sections[key]
        assert isinstance(card, CollapsibleCard)
        if key in ("tag", "meta:unknown_prefix"):
            assert isinstance(card, EditableTagCard)
        else:
            assert isinstance(card.content_widget(), MetaRowWidget)


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


def test_tag_prefixed_falls_back_to_editable_tag_card(qtbot):
    w = MetaViewerWidget()
    qtbot.addWidget(w)
    meta = {
        "source": {"name": "a"},
        "file": {},
        "tag": {},
        "tag_prefixed": {"custom": {"key1": "v1"}},
        "tag_prefixed_locks": {"custom": {"key1": False}},
        "prefixed": {},
        "_path": "/a.png",
        "_file_hash": "h",
        "_tag_locks": {},
        "_db_name": "",
    }
    w.set_data(meta)
    assert "tag:custom" in w._sections
    card = w._sections["tag:custom"]
    assert isinstance(card, EditableTagCard)
    assert card._prefix == "custom"


def test_tag_and_meta_same_prefix_create_two_cards(qtbot):
    w = MetaViewerWidget()
    qtbot.addWidget(w)
    meta = {
        "source": {"name": "a"},
        "file": {},
        "tag": {},
        "tag_prefixed": {"shared": {"k": "v"}},
        "tag_prefixed_locks": {"shared": {"k": False}},
        "prefixed": {"shared": {"k2": "v2"}},
        "_path": "/a.png",
        "_file_hash": "h",
        "_tag_locks": {},
        "_db_name": "",
    }
    w.set_data(meta)
    assert "tag:shared" in w._sections
    assert "meta:shared" in w._sections
    keys = list(w._sections.keys())
    assert keys.index("tag:shared") < keys.index("meta:shared")


def test_section_marker_kinds(qtbot):
    w = MetaViewerWidget()
    qtbot.addWidget(w)
    meta = {
        "source": {"name": "a"},
        "file": {},
        "tag": {"root": "1"},
        "tag_prefixed": {"custom": {"k": "v"}},
        "tag_prefixed_locks": {"custom": {"k": False}},
        "meta": {"memo": "v"},
        "meta_locks": {"memo": False},
        "prefixed": {"user": {"note": "v"}},
        "prefixed_locks": {"user": {"note": False}},
        "_path": "/a.png",
        "_file_hash": "h",
        "_tag_locks": {},
        "_db_name": "db",
    }
    w.set_data(meta)
    assert w._sections["source"].marker_kind() == ""
    assert w._sections["tag"].marker_kind() == SECTION_MARKER_TAG_ROOT
    assert w._sections["tag:custom"].marker_kind() == SECTION_MARKER_TAG_PREFIX
    assert w._sections["meta"].marker_kind() == SECTION_MARKER_META_ROOT
    assert w._sections["meta:user"].marker_kind() == SECTION_MARKER_META_PREFIX


def test_add_metadata_uses_raw_key_without_auto_prefix(qtbot, monkeypatch):
    import wafer.app.viewer.preview.meta_panel as meta_panel_mod

    svc = TagEditService.instance()
    node = MagicMock()
    monkeypatch.setattr(svc, "_resolve_node", lambda: node)

    class _DlgStub:
        def __init__(self, *args, **kwargs):
            pass

        def exec(self):
            return QtWidgets.QDialog.Accepted

        def scope(self):
            return "meta_info"

        def values(self):
            return "memo", "hello"

    monkeypatch.setattr(meta_panel_mod, "AddTagDialog", _DlgStub)
    w = MetaViewerWidget()
    qtbot.addWidget(w)
    meta = _sample_meta()
    meta["_file_hash"] = "h"
    meta["_db_name"] = "db"
    w.set_data(meta)
    w._on_add_clicked()
    payload = node.send_reliable.call_args[0][1]
    assert payload["scope"] == "meta_info"
    assert payload["upserts"] == [{"key": "memo", "value": "hello", "locked": False}]
