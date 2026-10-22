from wafer.app.viewer.widgets.workspace_labels import (
    format_iso,
    slot_subtitle,
    slot_summary,
    slot_title,
    slot_tooltip,
    window_title,
)
from wafer.constants import APP_NAME
from wafer.core.store.workspace import WindowSlot


def _slot(**kwargs) -> WindowSlot:
    return WindowSlot(slot_id="s1", path={"database_name": "db", "selected": ["F:/a/photos", "F:/b/images"]}, **kwargs)


def test_window_title_named_workspace_shows_name_only():
    assert window_title("Work", ["F:/a/photos"], "main") == "Work"


def test_window_title_unnamed_uses_folders_then_db_then_app():
    assert window_title("", ["F:/a/photos", "F:/b/images"], "main") == "photos, images"
    assert window_title("", [], "main") == "main"
    assert window_title("  ", [], "") == APP_NAME


def test_format_iso_handles_empty_and_invalid():
    assert format_iso("") == ""
    assert format_iso("not a date") == "not a date"
    assert len(format_iso("2026-04-27T10:00:00+00:00")) == len("2026-04-27 10:00")


def test_slot_summary_lists_database_and_first_folder():
    assert slot_summary(_slot()) == "db / photos +1"
    assert slot_summary(WindowSlot(slot_id="s2")) == "No database"


def test_slot_title_prefers_name_over_summary():
    assert slot_title(_slot(name="Work")) == "Work"
    assert slot_title(_slot()) == "db / photos +1"


def test_slot_subtitle_and_tooltip_include_summary_for_named_slot():
    named = _slot(name="Work", updated_at="2026-04-27T10:00:00+00:00")
    assert slot_subtitle(named).startswith("db / photos +1 / ")
    tooltip = slot_tooltip(named)
    assert "Work" in tooltip and "db / photos +1" in tooltip and "slot_id: s1" in tooltip
