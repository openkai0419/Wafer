from unittest.mock import patch, MagicMock
from wafer.app.viewer.preview.meta_panel import MetaViewerWidget, _FIXED_SECTIONS
from wafer.app.viewer.preview.meta_viewer import CollapsibleSection, MetaRowWidget


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
    for sec in w._sections.values():
        assert sec.expanded is True


def test_collapse_state_persists(qtbot):
    w = MetaViewerWidget()
    qtbot.addWidget(w)
    w.set_data(_sample_meta())
    w._sections["tag"].set_expanded(False)
    w._on_section_toggled("tag", False)
    state = w._save_collapse_state()
    assert "tag" in state["collapsed"]
    assert state["collapsed"]["tag"] is False


def test_restore_collapse_state(qtbot):
    w = MetaViewerWidget()
    qtbot.addWidget(w)
    w.set_data(_sample_meta())
    w._restore_collapse_state({"collapsed": {"tag": False, "exiftool": False}})
    assert w._sections["tag"].expanded is False
    assert w._sections["exiftool"].expanded is False
    assert w._sections["source"].expanded is True


def test_update_reuses_existing_sections(qtbot):
    w = MetaViewerWidget()
    qtbot.addWidget(w)
    w.set_data(_sample_meta())
    first_sections = dict(w._sections)
    w.set_data(_sample_meta())
    for key, sec in w._sections.items():
        assert sec is first_sections[key]


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


def test_section_content_is_meta_row_widget(qtbot):
    w = MetaViewerWidget()
    qtbot.addWidget(w)
    meta = {"source": {"name": "a"}, "file": {}, "tag": {}, "prefixed": {"unknown_prefix": {"k": "v"}}}
    w.set_data(meta)
    for key in ("source", "file", "tag", "unknown_prefix"):
        assert isinstance(w._sections[key].content_widget(), MetaRowWidget)
