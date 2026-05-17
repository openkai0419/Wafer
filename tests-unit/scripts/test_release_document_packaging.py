from scripts import build, copy_clean_project


def test_release_notes_are_included_in_portable_build_metadata():
    assert "RELEASE_NOTES.md" in build.META_FILES
    assert "CHANGELOG.md" in build.META_FILES


def test_release_notes_are_included_in_clean_project_copy():
    assert "RELEASE_NOTES.md" in copy_clean_project.COPY_FILES
    assert "CHANGELOG.md" in copy_clean_project.COPY_FILES