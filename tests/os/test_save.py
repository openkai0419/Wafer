from __future__ import annotations

from pathlib import Path


def test_execute_paste_overwrite_same_path_is_noop(tmp_path):
    from source.os.save import ClipboardFilePaster, PasteDecision, PastePlanItem

    src = tmp_path / "a.txt"
    src.write_text("x", encoding="utf-8")

    item = PastePlanItem(
        index=0,
        src=Path(src),
        is_dir=False,
        action="copy",
        dst_default=Path(src),
        conflict=True,
        suggested_dst=None,
    )

    res = ClipboardFilePaster().execute_paste([item], {0: PasteDecision(mode="overwrite")})
    assert src.exists()
    assert src.read_text(encoding="utf-8") == "x"
    assert res and res[0]["status"] == "skipped"


def test_execute_paste_overwrite_replaces_existing_file(tmp_path):
    from source.os.save import ClipboardFilePaster, PasteDecision, PastePlanItem

    src = tmp_path / "src.txt"
    src.write_text("new", encoding="utf-8")
    dst_dir = tmp_path / "dst"
    dst_dir.mkdir()
    dst = dst_dir / "src.txt"
    dst.write_text("old", encoding="utf-8")

    item = PastePlanItem(
        index=0,
        src=Path(src),
        is_dir=False,
        action="copy",
        dst_default=Path(dst),
        conflict=True,
        suggested_dst=None,
    )

    res = ClipboardFilePaster().execute_paste([item], {0: PasteDecision(mode="overwrite")})
    assert dst.read_text(encoding="utf-8") == "new"
    assert res and res[0]["status"] == "ok"


def test_execute_paste_copy_dir_subpath_is_skipped(tmp_path):
    from source.os.save import ClipboardFilePaster, PasteDecision, PastePlanItem

    src = tmp_path / "A"
    (src / "child").mkdir(parents=True)
    (src / "a.txt").write_text("x", encoding="utf-8")

    dst = src / "child" / src.name
    item = PastePlanItem(
        index=0,
        src=Path(src),
        is_dir=True,
        action="copy",
        dst_default=Path(dst),
        conflict=False,
        suggested_dst=None,
    )

    res = ClipboardFilePaster().execute_paste([item], {0: PasteDecision(mode="overwrite")})
    assert not dst.exists()
    assert res and res[0]["status"] == "skipped"


def test_execute_paste_copy_dir_rename_on_conflict_creates_unique(tmp_path):
    from source.os.save import ClipboardFilePaster, PasteDecision, PastePlanItem
    from source.os.save import unique_path

    src = tmp_path / "folder"
    src.mkdir()
    (src / "a.txt").write_text("x", encoding="utf-8")

    dst_dir = tmp_path / "dst"
    dst_dir.mkdir()
    existing = dst_dir / "folder"
    existing.mkdir()
    (existing / "old.txt").write_text("old", encoding="utf-8")

    dst_default = dst_dir / src.name
    suggested = Path(unique_path(dst_dir, src.name))
    item = PastePlanItem(
        index=0,
        src=Path(src),
        is_dir=True,
        action="copy",
        dst_default=Path(dst_default),
        conflict=True,
        suggested_dst=suggested,
    )

    res = ClipboardFilePaster().execute_paste([item], {0: PasteDecision(mode="rename")})
    assert existing.exists()
    assert (suggested / "a.txt").read_text(encoding="utf-8") == "x"
    assert (existing / "old.txt").read_text(encoding="utf-8") == "old"
    assert res and res[0]["status"] == "ok"


def test_execute_paste_overwrite_replaces_existing_dir(tmp_path):
    from source.os.save import ClipboardFilePaster, PasteDecision, PastePlanItem

    src = tmp_path / "srcdir"
    src.mkdir()
    (src / "a.txt").write_text("x", encoding="utf-8")

    dst_dir = tmp_path / "dst"
    dst_dir.mkdir()
    dst = dst_dir / "srcdir"
    dst.mkdir()
    (dst / "old.txt").write_text("old", encoding="utf-8")

    item = PastePlanItem(
        index=0,
        src=Path(src),
        is_dir=True,
        action="copy",
        dst_default=Path(dst),
        conflict=True,
        suggested_dst=None,
    )

    res = ClipboardFilePaster().execute_paste([item], {0: PasteDecision(mode="overwrite")})
    assert (dst / "a.txt").read_text(encoding="utf-8") == "x"
    assert not (dst / "old.txt").exists()
    assert res and res[0]["status"] == "ok"


def test_execute_paste_merge_dir_overwrite_child_conflict(tmp_path):
    from source.os.save import ClipboardFilePaster, PasteDecision, PastePlanItem

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

    def resolve_exists(s, d, is_dir, action):
        return PasteDecision(mode=("merge" if is_dir else "overwrite"))

    item = PastePlanItem(
        index=0,
        src=Path(src),
        is_dir=True,
        action="copy",
        dst_default=Path(dst),
        conflict=True,
        suggested_dst=None,
    )

    res = ClipboardFilePaster().execute_paste([item], {0: PasteDecision(mode="merge")}, resolve_exists=resolve_exists)
    assert (dst / "a.txt").read_text(encoding="utf-8") == "new"
    assert (dst / "sub" / "b.txt").read_text(encoding="utf-8") == "newb"
    assert res and res[0]["status"] == "ok"


def test_execute_paste_merge_dir_skip_child_conflict(tmp_path):
    from source.os.save import ClipboardFilePaster, PasteDecision, PastePlanItem

    src = tmp_path / "folder"
    src.mkdir()
    (src / "a.txt").write_text("new", encoding="utf-8")

    dst_root = tmp_path / "dst"
    dst_root.mkdir()
    dst = dst_root / "folder"
    dst.mkdir()
    (dst / "a.txt").write_text("old", encoding="utf-8")

    def resolve_exists(s, d, is_dir, action):
        return PasteDecision(mode=("merge" if is_dir else "skip"))

    item = PastePlanItem(
        index=0,
        src=Path(src),
        is_dir=True,
        action="copy",
        dst_default=Path(dst),
        conflict=True,
        suggested_dst=None,
    )

    res = ClipboardFilePaster().execute_paste([item], {0: PasteDecision(mode="merge")}, resolve_exists=resolve_exists)
    assert (dst / "a.txt").read_text(encoding="utf-8") == "old"
    assert res and res[0]["status"] == "ok"


def test_estimate_merge_conflict_count_detects_multiple(tmp_path):
    from source.os.save import ClipboardFilePaster

    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    (src / "a.txt").write_text("x", encoding="utf-8")
    (src / "b.txt").write_text("y", encoding="utf-8")
    (dst / "a.txt").write_text("old", encoding="utf-8")
    (dst / "b.txt").write_text("old", encoding="utf-8")

    n = ClipboardFilePaster().estimate_merge_conflict_count(src, dst, stop_at=2)
    assert n >= 2


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


def test_execute_paste_plans_with_ui_exists(tmp_path):
    from source.os.save import execute_paste_plans_with_ui, PastePlanItem
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


def test_resolve_conflicts_with_ui_invalid_overwrite_mode():
    from source.os.save import resolve_conflicts_with_ui
    import pytest

    with pytest.raises(ValueError, match="Invalid overwrite_mode"):
        resolve_conflicts_with_ui([], op="copy", overwrite_mode="invalid")
