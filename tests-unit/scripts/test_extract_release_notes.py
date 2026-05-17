import pytest

from scripts.extract_release_notes import extract_release_notes, normalize_tag


NOTES = """# Release Notes

Intro text.

## [v0.6.19]

Latest notes.

### Fixes
- A fix.

## [v0.6.18]

Previous notes.
"""


def test_normalize_tag_accepts_v_prefix():
    assert normalize_tag("v0.6.19") == "0.6.19"
    assert normalize_tag("V0.6.19") == "0.6.19"


def test_extract_release_notes_returns_only_target_section():
    notes = extract_release_notes(NOTES, "v0.6.19")

    assert notes.startswith("## [v0.6.19]")
    assert "Latest notes." in notes
    assert "## [v0.6.18]" not in notes


def test_extract_release_notes_accepts_plain_version():
    notes = extract_release_notes(NOTES, "0.6.18")

    assert notes.startswith("## [v0.6.18]")
    assert "Previous notes." in notes


def test_extract_release_notes_rejects_missing_section():
    with pytest.raises(ValueError, match="0.6.20"):
        extract_release_notes(NOTES, "v0.6.20")