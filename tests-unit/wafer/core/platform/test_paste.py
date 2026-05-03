from __future__ import annotations

import py_compile


def test_compile():
    py_compile.compile("wafer/core/platform/paste.py")


def test_paste_clipboard_files_exists():
    from wafer.core.platform.paste import paste_clipboard_files

    assert callable(paste_clipboard_files)


def test_execute_paste_plans_with_ui_exists():
    from wafer.core.platform.paste import execute_paste_plans_with_ui

    assert callable(execute_paste_plans_with_ui)


def test_drop_files_with_ui_exists():
    from wafer.core.platform.paste import drop_files_with_ui

    assert callable(drop_files_with_ui)


def test_drop_files_with_ui_invalid_op():
    from wafer.core.platform.paste import drop_files_with_ui
    import pytest

    with pytest.raises(ValueError, match="Invalid op"):
        drop_files_with_ui([], ".", "invalid_op")


def test_drop_files_with_ui_invalid_overwrite_mode():
    from wafer.core.platform.paste import drop_files_with_ui
    import pytest

    with pytest.raises(ValueError, match="Invalid overwrite_mode"):
        drop_files_with_ui([], ".", "copy", overwrite_mode="invalid")


def test_drop_files_with_ui_empty_items(tmp_path):
    from wafer.core.platform.paste import drop_files_with_ui

    res = drop_files_with_ui([], str(tmp_path), "copy")
    assert res == []


def test_resolve_drop_operation_with_ui_fixed_operation():
    from wafer.core.platform.paste import resolve_drop_operation_with_ui

    assert resolve_drop_operation_with_ui("copy") == "copy"
    assert resolve_drop_operation_with_ui("move") == "move"


def test_resolve_drop_operation_with_ui_ask_saves_selection(monkeypatch):
    from wafer.core.platform import paste
    from wafer.ui.dialogs import DropOperationDialog


    saved = {}
    monkeypatch.setattr(paste.app_settings, "get", lambda key, default=None, value_type=None: "copy")
    monkeypatch.setattr(paste.app_settings, "save_immediate", lambda key, value: saved.__setitem__(key, value))
    monkeypatch.setattr(DropOperationDialog, "ask", staticmethod(lambda message, default="copy", title="Drop Files", parent=None: "move"))

    assert paste.resolve_drop_operation_with_ui("ask", message="Drop?") == "move"
    assert saved[paste.DROP_OPERATION_SETTING_KEY] == "move"


def test_clipboard_file_paster_importable():
    from wafer.core.platform.paste import ClipboardFilePaster

    assert ClipboardFilePaster is not None
