from __future__ import annotations

from pathlib import Path


def test_paste_executor_overwrite_same_path_is_noop(tmp_path):
    from source.os.save import PasteDecision, PasteExecutor, PastePlanItem

    src = tmp_path / "a.txt"
    src.write_text("x", encoding="utf-8")

    item = PastePlanItem(
        index=0, src=Path(src), is_dir=False, action="copy",
        dst_default=Path(src), conflict=True, suggested_dst=None,
    )

    res = PasteExecutor().execute_plans([item], {0: PasteDecision(mode="overwrite")})
    assert src.exists()
    assert src.read_text(encoding="utf-8") == "x"
    assert res and res[0]["status"] == "skipped"


def test_paste_executor_rename_same_path_creates_copy(tmp_path):
    from source.os.save import PasteDecision, PasteExecutor, PastePlanItem

    src = tmp_path / "a.txt"
    src.write_text("x", encoding="utf-8")

    item = PastePlanItem(
        index=0, src=Path(src), is_dir=False, action="copy",
        dst_default=Path(src), conflict=True, suggested_dst=None,
    )

    res = PasteExecutor().execute_plans([item], {0: PasteDecision(mode="rename")})
    assert src.exists()
    assert src.read_text(encoding="utf-8") == "x"
    copies = [f for f in tmp_path.iterdir() if f.name != "a.txt" and f.suffix == ".txt"]
    assert len(copies) == 1
    assert copies[0].read_text(encoding="utf-8") == "x"
    assert res and res[0]["status"] == "ok"


def test_paste_executor_overwrite_replaces_existing_file(tmp_path):
    from source.os.save import PasteDecision, PasteExecutor, PastePlanItem

    src = tmp_path / "src.txt"
    src.write_text("new", encoding="utf-8")
    dst_dir = tmp_path / "dst"
    dst_dir.mkdir()
    dst = dst_dir / "src.txt"
    dst.write_text("old", encoding="utf-8")

    item = PastePlanItem(
        index=0, src=Path(src), is_dir=False, action="copy",
        dst_default=Path(dst), conflict=True, suggested_dst=None,
    )

    res = PasteExecutor().execute_plans([item], {0: PasteDecision(mode="overwrite")})
    assert dst.read_text(encoding="utf-8") == "new"
    assert res and res[0]["status"] == "ok"


def test_paste_executor_copy_dir_subpath_is_skipped(tmp_path):
    from source.os.save import PasteDecision, PasteExecutor, PastePlanItem

    src = tmp_path / "A"
    (src / "child").mkdir(parents=True)
    (src / "a.txt").write_text("x", encoding="utf-8")

    dst = src / "child" / src.name
    item = PastePlanItem(
        index=0, src=Path(src), is_dir=True, action="copy",
        dst_default=Path(dst), conflict=False, suggested_dst=None,
    )

    res = PasteExecutor().execute_plans([item], {0: PasteDecision(mode="overwrite")})
    assert not dst.exists()
    assert res and res[0]["status"] == "skipped"


def test_paste_executor_copy_dir_rename_on_conflict(tmp_path):
    from source.os.save import PasteDecision, PasteExecutor, PastePlanItem, unique_path

    src = tmp_path / "folder"
    src.mkdir()
    (src / "a.txt").write_text("x", encoding="utf-8")

    dst_dir = tmp_path / "dst"
    dst_dir.mkdir()
    existing = dst_dir / "folder"
    existing.mkdir()
    (existing / "old.txt").write_text("old", encoding="utf-8")

    dst_default = dst_dir / src.name
    item = PastePlanItem(
        index=0, src=Path(src), is_dir=True, action="copy",
        dst_default=Path(dst_default), conflict=True,
        suggested_dst=Path(unique_path(dst_dir, src.name)),
    )

    res = PasteExecutor().execute_plans([item], {0: PasteDecision(mode="rename")})
    assert existing.exists()
    assert (existing / "old.txt").read_text(encoding="utf-8") == "old"
    assert res and res[0]["status"] == "ok"


def test_paste_executor_overwrite_replaces_existing_dir(tmp_path):
    from source.os.save import PasteDecision, PasteExecutor, PastePlanItem

    src = tmp_path / "srcdir"
    src.mkdir()
    (src / "a.txt").write_text("x", encoding="utf-8")

    dst_dir = tmp_path / "dst"
    dst_dir.mkdir()
    dst = dst_dir / "srcdir"
    dst.mkdir()
    (dst / "old.txt").write_text("old", encoding="utf-8")

    item = PastePlanItem(
        index=0, src=Path(src), is_dir=True, action="copy",
        dst_default=Path(dst), conflict=True, suggested_dst=None,
    )

    res = PasteExecutor().execute_plans([item], {0: PasteDecision(mode="overwrite")})
    assert (dst / "a.txt").read_text(encoding="utf-8") == "x"
    assert not (dst / "old.txt").exists()
    assert res and res[0]["status"] == "ok"


def test_paste_executor_merge_dir_overwrite_child(tmp_path):
    import os
    from source.os.save import PasteDecision, PasteExecutor, PastePlanItem

    src = tmp_path / "folder"
    src.mkdir()
    (src / "a.txt").write_text("new", encoding="utf-8")
    (src / "sub").mkdir()
    (src / "sub" / "b.txt").write_text("newb", encoding="utf-8")

    dst_root = tmp_path / "dst"
    dst_root.mkdir()
    dst = dst_root / "folder"
    dst.mkdir()
    (dst / "a.txt").write_text("old", encoding="utf-8")
    (dst / "sub").mkdir()
    (dst / "sub" / "b.txt").write_text("oldb", encoding="utf-8")

    merge_decisions = {
        "a.txt": PasteDecision(mode="overwrite"),
        os.path.join("sub", "b.txt"): PasteDecision(mode="overwrite"),
    }

    item = PastePlanItem(
        index=0, src=Path(src), is_dir=True, action="copy",
        dst_default=Path(dst), conflict=True, suggested_dst=None,
    )

    res = PasteExecutor().execute_plans(
        [item], {0: PasteDecision(mode="merge", merge_decisions=merge_decisions)}
    )
    assert (dst / "a.txt").read_text(encoding="utf-8") == "new"
    assert (dst / "sub" / "b.txt").read_text(encoding="utf-8") == "newb"
    assert res and res[0]["status"] == "ok"


def test_paste_executor_merge_dir_skip_child(tmp_path):
    from source.os.save import PasteDecision, PasteExecutor, PastePlanItem

    src = tmp_path / "folder"
    src.mkdir()
    (src / "a.txt").write_text("new", encoding="utf-8")

    dst_root = tmp_path / "dst"
    dst_root.mkdir()
    dst = dst_root / "folder"
    dst.mkdir()
    (dst / "a.txt").write_text("old", encoding="utf-8")

    item = PastePlanItem(
        index=0, src=Path(src), is_dir=True, action="copy",
        dst_default=Path(dst), conflict=True, suggested_dst=None,
    )

    res = PasteExecutor().execute_plans(
        [item], {0: PasteDecision(mode="merge", merge_decisions={"a.txt": PasteDecision(mode="skip")})}
    )
    assert (dst / "a.txt").read_text(encoding="utf-8") == "old"
    assert res and res[0]["status"] == "ok"


def test_scan_merge_conflicts_detects_files(tmp_path):
    from source.os.save import scan_merge_conflicts

    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    (src / "a.txt").write_text("x", encoding="utf-8")
    (src / "b.txt").write_text("y", encoding="utf-8")
    (dst / "a.txt").write_text("old", encoding="utf-8")
    (dst / "b.txt").write_text("old", encoding="utf-8")

    conflicts = scan_merge_conflicts(src, dst)
    assert len(conflicts) == 2
    rel_paths = {c.rel_path for c in conflicts}
    assert "a.txt" in rel_paths
    assert "b.txt" in rel_paths


def test_scan_merge_conflicts_recurses_into_dirs(tmp_path):
    import os
    from source.os.save import scan_merge_conflicts

    src = tmp_path / "src"
    dst = tmp_path / "dst"
    (src / "sub").mkdir(parents=True)
    (dst / "sub").mkdir(parents=True)
    (src / "sub" / "c.txt").write_text("x", encoding="utf-8")
    (dst / "sub" / "c.txt").write_text("old", encoding="utf-8")

    conflicts = scan_merge_conflicts(src, dst)
    assert len(conflicts) == 1
    assert conflicts[0].rel_path == os.path.join("sub", "c.txt")


def test_unique_path_generates_increment(tmp_path):
    from source.os.save import unique_path

    d = tmp_path
    (d / "a.txt").write_text("x", encoding="utf-8")
    p = Path(unique_path(d, "a.txt"))
    assert p.name.startswith("a (") and p.suffix == ".txt"


def test_check_copy_conflict_same_path(tmp_path):
    from source.os.save import check_copy_conflict

    p = tmp_path / "x.txt"
    p.write_text("x", encoding="utf-8")
    assert check_copy_conflict(p, p) == "same_path"


def test_sanitize_filename_windows_invalid_chars():
    from source.os.save import sanitize_filename

    assert sanitize_filename("a<b>c.txt") == "a_b_c.txt"


def test_execute_paste_plans_with_ui_exists():
    from source.os.save import execute_paste_plans_with_ui
    assert callable(execute_paste_plans_with_ui)


def test_drop_files_with_ui_exists():
    from source.os.save import drop_files_with_ui
    assert callable(drop_files_with_ui)


def test_paste_clipboard_files_exists():
    from source.os.save import paste_clipboard_files
    assert callable(paste_clipboard_files)


def test_drop_files_with_ui_invalid_op():
    from source.os.save import drop_files_with_ui
    import pytest

    with pytest.raises(ValueError, match="Invalid op"):
        drop_files_with_ui([], ".", "invalid_op")


def test_drop_files_with_ui_invalid_overwrite_mode():
    from source.os.save import drop_files_with_ui
    import pytest

    with pytest.raises(ValueError, match="Invalid overwrite_mode"):
        drop_files_with_ui([], ".", "copy", overwrite_mode="invalid")


def test_drop_files_with_ui_empty_items(tmp_path):
    from source.os.save import drop_files_with_ui

    res = drop_files_with_ui([], str(tmp_path), "copy")
    assert res == []


def test_paste_cancelled_error_importable():
    from source.os.save import PasteCancelledError
    assert issubclass(PasteCancelledError, Exception)


def test_paste_executor_merge_dir_rename_child(tmp_path):
    from source.os.save import PasteDecision, PasteExecutor, PastePlanItem

    src = tmp_path / "folder"
    src.mkdir()
    (src / "a.txt").write_text("new", encoding="utf-8")

    dst_root = tmp_path / "dst"
    dst_root.mkdir()
    dst = dst_root / "folder"
    dst.mkdir()
    (dst / "a.txt").write_text("old", encoding="utf-8")

    item = PastePlanItem(
        index=0, src=Path(src), is_dir=True, action="copy",
        dst_default=Path(dst), conflict=True, suggested_dst=None,
    )

    res = PasteExecutor().execute_plans(
        [item], {0: PasteDecision(mode="merge", merge_decisions={"a.txt": PasteDecision(mode="rename")})}
    )
    assert (dst / "a.txt").read_text(encoding="utf-8") == "old"
    renamed = [f for f in dst.iterdir() if f.name != "a.txt" and f.suffix == ".txt"]
    assert len(renamed) == 1
    assert renamed[0].read_text(encoding="utf-8") == "new"
    assert res and res[0]["status"] == "ok"


def test_paste_executor_merge_adds_new_files(tmp_path):
    from source.os.save import PasteDecision, PasteExecutor, PastePlanItem

    src = tmp_path / "folder"
    src.mkdir()
    (src / "new.txt").write_text("added", encoding="utf-8")

    dst_root = tmp_path / "dst"
    dst_root.mkdir()
    dst = dst_root / "folder"
    dst.mkdir()
    (dst / "existing.txt").write_text("keep", encoding="utf-8")

    item = PastePlanItem(
        index=0, src=Path(src), is_dir=True, action="copy",
        dst_default=Path(dst), conflict=True, suggested_dst=None,
    )

    res = PasteExecutor().execute_plans(
        [item], {0: PasteDecision(mode="merge", merge_decisions={})}
    )
    assert (dst / "existing.txt").read_text(encoding="utf-8") == "keep"
    assert (dst / "new.txt").read_text(encoding="utf-8") == "added"
    assert res and res[0]["status"] == "ok"
