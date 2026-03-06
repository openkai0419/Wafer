from __future__ import annotations

import py_compile


def test_compile():
    py_compile.compile('wayfer/core/platform/paste.py')


def test_paste_clipboard_files_exists():
    from wayfer.core.platform.paste import paste_clipboard_files
    assert callable(paste_clipboard_files)


def test_execute_paste_plans_with_ui_exists():
    from wayfer.core.platform.paste import execute_paste_plans_with_ui
    assert callable(execute_paste_plans_with_ui)


def test_drop_files_with_ui_exists():
    from wayfer.core.platform.paste import drop_files_with_ui
    assert callable(drop_files_with_ui)


def test_drop_files_with_ui_invalid_op():
    from wayfer.core.platform.paste import drop_files_with_ui
    import pytest

    with pytest.raises(ValueError, match="Invalid op"):
        drop_files_with_ui([], ".", "invalid_op")


def test_drop_files_with_ui_invalid_overwrite_mode():
    from wayfer.core.platform.paste import drop_files_with_ui
    import pytest

    with pytest.raises(ValueError, match="Invalid overwrite_mode"):
        drop_files_with_ui([], ".", "copy", overwrite_mode="invalid")


def test_drop_files_with_ui_empty_items(tmp_path):
    from wayfer.core.platform.paste import drop_files_with_ui

    res = drop_files_with_ui([], str(tmp_path), "copy")
    assert res == []


def test_clipboard_file_paster_importable():
    from wayfer.core.platform.paste import ClipboardFilePaster
    assert ClipboardFilePaster is not None
