from __future__ import annotations

from pathlib import Path

from wafer.utils.virtual_paths import build_virtual_path, register_owner_extension


def test_file_executor_overwrite_same_path_is_noop(tmp_path):
    from wafer.core.platform.file_operations import FileExecutor, PasteDecision, PastePlanItem

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

    res = FileExecutor().execute_plans([item], {0: PasteDecision(mode="overwrite")})


    def test_build_drop_plans_rejects_virtual_destination(tmp_path):
        from wafer.core.platform.dragparser import ParsedItem
        from wafer.core.platform.file_operations import build_drop_plans

        register_owner_extension(".zip")
        src = tmp_path / "source.txt"
        src.write_text("x", encoding="utf-8")
        virtual_dst = build_virtual_path(str(tmp_path / "archive.zip"), "folder/image.png")

        plans = build_drop_plans(
            [ParsedItem(source=str(src), name=src.name, is_binary=False, size=src.stat().st_size)],
            virtual_dst,
            "copy",
        )

        assert plans == []
    assert src.exists()
    assert src.read_text(encoding="utf-8") == "x"
    assert res and res[0].status == "skipped"


def test_file_executor_rename_same_path_creates_copy(tmp_path):
    from wafer.core.platform.file_operations import FileExecutor, PasteDecision, PastePlanItem

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

    res = FileExecutor().execute_plans([item], {0: PasteDecision(mode="rename")})
    assert src.exists()
    assert src.read_text(encoding="utf-8") == "x"
    copies = [f for f in tmp_path.iterdir() if f.name != "a.txt" and f.suffix == ".txt"]
    assert len(copies) == 1
    assert copies[0].read_text(encoding="utf-8") == "x"
    assert res and res[0].status == "ok"


def test_file_executor_overwrite_replaces_existing_file(tmp_path):
    from wafer.core.platform.file_operations import FileExecutor, PasteDecision, PastePlanItem

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

    res = FileExecutor().execute_plans([item], {0: PasteDecision(mode="overwrite")})
    assert dst.read_text(encoding="utf-8") == "new"
    assert res and res[0].status == "ok"


def test_file_executor_copy_dir_subpath_is_skipped(tmp_path):
    from wafer.core.platform.file_operations import FileExecutor, PasteDecision, PastePlanItem

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

    res = FileExecutor().execute_plans([item], {0: PasteDecision(mode="overwrite")})
    assert not dst.exists()
    assert res and res[0].status == "skipped"


def test_delete_to_trash_with_send2trash(tmp_path, monkeypatch):
    from wafer.core.platform.file_operations import delete_to_trash

    a = tmp_path / "a.txt"
    a.write_text("x", encoding="utf-8")
    b = tmp_path / "b.txt"
    b.write_text("y", encoding="utf-8")

    trashed: list[str] = []
    import types

    fake = types.SimpleNamespace(send2trash=lambda p: trashed.append(p))
    monkeypatch.setitem(__import__("sys").modules, "send2trash", fake)
    results = delete_to_trash([str(a), str(b)])
    assert len(results) == 2
    assert all(r.status == "ok" for r in results)
    assert len(trashed) == 2


def test_delete_to_trash_send2trash_fallback(tmp_path, monkeypatch):
    from wafer.core.platform.file_operations import delete_to_trash

    f = tmp_path / "a.txt"
    f.write_text("x", encoding="utf-8")
    import types

    fake = types.SimpleNamespace(
        send2trash=lambda *_a, **_k: (_ for _ in ()).throw(OSError("boom"))
    )
    monkeypatch.setitem(__import__("sys").modules, "send2trash", fake)
    results = delete_to_trash([str(f)])
    assert results[0].status == "ok"
    assert not f.exists()


def test_delete_to_trash_folder_fallback_fails(tmp_path, monkeypatch):
    from wafer.core.platform.file_operations import delete_to_trash

    d = tmp_path / "folder"
    d.mkdir()
    (d / "child.txt").write_text("x", encoding="utf-8")
    import types

    fake = types.SimpleNamespace(
        send2trash=lambda *_a, **_k: (_ for _ in ()).throw(OSError("boom"))
    )
    monkeypatch.setitem(__import__("sys").modules, "send2trash", fake)
    results = delete_to_trash([str(d)])
    assert results[0].status == "error"
    assert d.exists()


def test_delete_to_trash_no_send2trash_file(tmp_path, monkeypatch):
    from wafer.core.platform.file_operations import delete_to_trash

    f = tmp_path / "a.txt"
    f.write_text("x", encoding="utf-8")
    monkeypatch.setitem(__import__("sys").modules, "send2trash", None)
    monkeypatch.delitem(__import__("sys").modules, "send2trash")
    import builtins

    _real_import = builtins.__import__

    def _no_s2t(name, *a, **k):
        if name == "send2trash":
            raise ImportError("no send2trash")
        return _real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _no_s2t)
    results = delete_to_trash([str(f)])
    assert results[0].status == "ok"
    assert not f.exists()


def test_delete_to_trash_missing_file(tmp_path):
    from wafer.core.platform.file_operations import delete_to_trash

    results = delete_to_trash([str(tmp_path / "nonexistent.txt")])
    assert results[0].status == "skipped"


def test_delete_to_trash_empty_list():
    from wafer.core.platform.file_operations import delete_to_trash

    assert delete_to_trash([]) == []


def test_file_executor_copy_dir_rename_on_conflict(tmp_path):
    from wafer.core.platform.file_operations import FileExecutor, PasteDecision, PastePlanItem
    from wafer.core.platform.path_utils import unique_path

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
        index=0,
        src=Path(src),
        is_dir=True,
        action="copy",
        dst_default=Path(dst_default),
        conflict=True,
        suggested_dst=Path(unique_path(dst_dir, src.name)),
    )

    res = FileExecutor().execute_plans([item], {0: PasteDecision(mode="rename")})
    assert existing.exists()
    assert (existing / "old.txt").read_text(encoding="utf-8") == "old"
    assert res and res[0].status == "ok"


def test_file_executor_overwrite_replaces_existing_dir(tmp_path):
    from wafer.core.platform.file_operations import FileExecutor, PasteDecision, PastePlanItem

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

    res = FileExecutor().execute_plans([item], {0: PasteDecision(mode="overwrite")})
    assert (dst / "a.txt").read_text(encoding="utf-8") == "x"
    assert not (dst / "old.txt").exists()
    assert res and res[0].status == "ok"


def test_file_executor_merge_dir_overwrite_child(tmp_path):
    import os
    from wafer.core.platform.file_operations import FileExecutor, PasteDecision, PastePlanItem

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
        index=0,
        src=Path(src),
        is_dir=True,
        action="copy",
        dst_default=Path(dst),
        conflict=True,
        suggested_dst=None,
    )

    res = FileExecutor().execute_plans([item], {0: PasteDecision(mode="merge", merge_decisions=merge_decisions)})
    assert (dst / "a.txt").read_text(encoding="utf-8") == "new"
    assert (dst / "sub" / "b.txt").read_text(encoding="utf-8") == "newb"
    assert res and res[0].status == "ok"


def test_file_executor_merge_dir_skip_child(tmp_path):
    from wafer.core.platform.file_operations import FileExecutor, PasteDecision, PastePlanItem

    src = tmp_path / "folder"
    src.mkdir()
    (src / "a.txt").write_text("new", encoding="utf-8")

    dst_root = tmp_path / "dst"
    dst_root.mkdir()
    dst = dst_root / "folder"
    dst.mkdir()
    (dst / "a.txt").write_text("old", encoding="utf-8")

    item = PastePlanItem(
        index=0,
        src=Path(src),
        is_dir=True,
        action="copy",
        dst_default=Path(dst),
        conflict=True,
        suggested_dst=None,
    )

    res = FileExecutor().execute_plans([item], {0: PasteDecision(mode="merge", merge_decisions={"a.txt": PasteDecision(mode="skip")})})
    assert (dst / "a.txt").read_text(encoding="utf-8") == "old"
    assert res and res[0].status == "ok"


def test_scan_merge_conflicts_detects_files(tmp_path):
    from wafer.core.platform.file_operations import scan_merge_conflicts

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
    from wafer.core.platform.file_operations import scan_merge_conflicts

    src = tmp_path / "src"
    dst = tmp_path / "dst"
    (src / "sub").mkdir(parents=True)
    (dst / "sub").mkdir(parents=True)
    (src / "sub" / "c.txt").write_text("x", encoding="utf-8")
    (dst / "sub" / "c.txt").write_text("old", encoding="utf-8")

    conflicts = scan_merge_conflicts(src, dst)
    assert len(conflicts) == 1
    assert conflicts[0].rel_path == os.path.join("sub", "c.txt")


def test_paste_cancelled_error_importable():
    from wafer.core.platform.file_operations import PasteCancelledError

    assert issubclass(PasteCancelledError, Exception)


def test_file_executor_merge_dir_rename_child(tmp_path):
    from wafer.core.platform.file_operations import FileExecutor, PasteDecision, PastePlanItem

    src = tmp_path / "folder"
    src.mkdir()
    (src / "a.txt").write_text("new", encoding="utf-8")

    dst_root = tmp_path / "dst"
    dst_root.mkdir()
    dst = dst_root / "folder"
    dst.mkdir()
    (dst / "a.txt").write_text("old", encoding="utf-8")

    item = PastePlanItem(
        index=0,
        src=Path(src),
        is_dir=True,
        action="copy",
        dst_default=Path(dst),
        conflict=True,
        suggested_dst=None,
    )

    res = FileExecutor().execute_plans([item], {0: PasteDecision(mode="merge", merge_decisions={"a.txt": PasteDecision(mode="rename")})})
    assert (dst / "a.txt").read_text(encoding="utf-8") == "old"
    renamed = [f for f in dst.iterdir() if f.name != "a.txt" and f.suffix == ".txt"]
    assert len(renamed) == 1
    assert renamed[0].read_text(encoding="utf-8") == "new"
    assert res and res[0].status == "ok"


def test_file_executor_merge_adds_new_files(tmp_path):
    from wafer.core.platform.file_operations import FileExecutor, PasteDecision, PastePlanItem

    src = tmp_path / "folder"
    src.mkdir()
    (src / "new.txt").write_text("added", encoding="utf-8")

    dst_root = tmp_path / "dst"
    dst_root.mkdir()
    dst = dst_root / "folder"
    dst.mkdir()
    (dst / "existing.txt").write_text("keep", encoding="utf-8")

    item = PastePlanItem(
        index=0,
        src=Path(src),
        is_dir=True,
        action="copy",
        dst_default=Path(dst),
        conflict=True,
        suggested_dst=None,
    )

    res = FileExecutor().execute_plans([item], {0: PasteDecision(mode="merge", merge_decisions={})})
    assert (dst / "existing.txt").read_text(encoding="utf-8") == "keep"
    assert (dst / "new.txt").read_text(encoding="utf-8") == "added"
    assert res and res[0].status == "ok"


def test_paste_executor_alias():
    from wafer.core.platform.file_operations import FileExecutor, PasteExecutor

    assert PasteExecutor is FileExecutor


def test_execute_item_case_rename(tmp_path):
    from wafer.core.platform.file_operations import FileExecutor, PasteDecision

    src = tmp_path / "hello.txt"
    src.write_text("content", encoding="utf-8")

    dst = tmp_path / "Hello.txt"
    res = FileExecutor()._execute_item(src, dst, "cut", PasteDecision(mode="overwrite"))
    assert res.status == "ok"
    actual = [f for f in tmp_path.iterdir() if f.suffix == ".txt"]
    assert len(actual) == 1
    assert actual[0].read_text(encoding="utf-8") == "content"


def test_execute_item_same_path_cut_noop(tmp_path):
    from wafer.core.platform.file_operations import FileExecutor, PasteDecision

    src = tmp_path / "a.txt"
    src.write_text("x", encoding="utf-8")

    res = FileExecutor()._execute_item(src, src, "cut", PasteDecision(mode="overwrite"))
    assert res.status == "skipped"
    assert src.exists()
    assert src.read_text(encoding="utf-8") == "x"
