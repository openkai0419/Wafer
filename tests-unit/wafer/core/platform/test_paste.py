from __future__ import annotations

import py_compile
from pathlib import Path

from wafer.utils.virtual_paths import build_virtual_path


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


def test_paste_clipboard_files_rejects_virtual_destination(monkeypatch, tmp_path):
    from wafer.core.platform import paste

    class FailingPaster:
        def __init__(self):
            raise AssertionError("virtual destination should be rejected before clipboard access")

    monkeypatch.setattr(paste, "ClipboardFilePaster", FailingPaster)
    virtual_dir = build_virtual_path(str(tmp_path / "archive.zip"), "folder")

    assert paste.paste_clipboard_files(virtual_dir) == []


def test_clipboard_file_paster_build_plan_rejects_virtual_destination(tmp_path):
    from wafer.core.platform.paste import ClipboardFilePaster

    paster = object.__new__(ClipboardFilePaster)
    virtual_dir = build_virtual_path(str(tmp_path / "archive.zip"), "folder")

    assert paster.build_paste_plan(virtual_dir) == []


def test_execute_paste_plans_with_ui_rejects_virtual_plan(monkeypatch, tmp_path):
    from wafer.core.platform import paste
    from wafer.core.platform.file_operations import PastePlanItem

    def fail_if_called(**_kwargs):
        raise AssertionError("virtual plan should be rejected before conflict UI")

    monkeypatch.setattr(paste, "_resolve_conflicts_with_ui", fail_if_called)
    virtual_src = build_virtual_path(str(tmp_path / "archive.zip"), "image.png")
    plan = PastePlanItem(
        index=0,
        src=Path(virtual_src),
        is_dir=False,
        action="copy",
        dst_default=tmp_path / "image.png",
        conflict=False,
        suggested_dst=None,
    )

    results = paste.execute_paste_plans_with_ui([plan])

    assert len(results) == 1
    assert results[0].status == "skipped"
    assert results[0].error == "virtual path rejected"


def test_execute_paste_plans_with_ui_preserves_result_order_with_virtual_plan(monkeypatch, tmp_path):
    from wafer.core.platform import paste
    from wafer.core.platform.file_operations import OperationResult, PasteDecision, PastePlanItem

    called = {}

    def fake_resolve_conflicts_with_ui(*, plans, **_kwargs):
        called["resolve_indices"] = [plan.index for plan in plans]
        return {plan.index: PasteDecision(mode="overwrite") for plan in plans}

    def fake_execute_paste_items(plans, decisions, parent, op):
        called["execute_indices"] = [plan.index for plan in plans]
        called["op"] = op
        return [
            OperationResult(action="copy", src=str(plan.src), dst=str(plan.dst_default), status="ok")
            for plan in plans
        ]

    monkeypatch.setattr(paste, "_resolve_conflicts_with_ui", fake_resolve_conflicts_with_ui)
    monkeypatch.setattr(paste, "_execute_paste_items", fake_execute_paste_items)

    valid_a = tmp_path / "a.txt"
    valid_b = tmp_path / "b.txt"
    virtual_src = build_virtual_path(str(tmp_path / "archive.zip"), "image.png")
    plans = [
        PastePlanItem(index=10, src=valid_a, is_dir=False, action="copy", dst_default=tmp_path / "out-a.txt", conflict=False, suggested_dst=None),
        PastePlanItem(index=20, src=Path(virtual_src), is_dir=False, action="copy", dst_default=tmp_path / "out-virtual.txt", conflict=False, suggested_dst=None),
        PastePlanItem(index=30, src=valid_b, is_dir=False, action="copy", dst_default=tmp_path / "out-b.txt", conflict=False, suggested_dst=None),
    ]

    results = paste.execute_paste_plans_with_ui(plans)

    assert called["resolve_indices"] == [10, 30]
    assert called["execute_indices"] == [10, 30]
    assert called["op"] == "copy"
    assert [result.status for result in results] == ["ok", "skipped", "ok"]
    assert results[0].src == str(valid_a)
    assert results[1].error == "virtual path rejected"
    assert results[2].src == str(valid_b)
