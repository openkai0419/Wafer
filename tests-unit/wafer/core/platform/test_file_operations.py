from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from wafer.core.common.virtual_paths import build_virtual_path



def _answers(*, folder="merge", files=None, default="overwrite"):
    files = files or {}

    def ask(conflict):
        if conflict.folders:
            return folder
        return files.get(conflict.name, default)

    return ask


def test_pasting_a_file_onto_itself_keeps_it_and_saves_a_copy(tmp_path):
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

    res = FileExecutor(ask_conflict=_answers()).execute_plans([item], {})
    assert src.read_text(encoding="utf-8") == "x"
    assert res and res[0].status == "ok"
    assert Path(res[0].dst) != src
    assert Path(res[0].dst).read_text(encoding="utf-8") == "x"


def test_build_drop_plans_rejects_virtual_destination(tmp_path):
    from wafer.qt.transfer.dragparser import ParsedItem
    from wafer.core.platform.file_operations import build_drop_plans

    src = tmp_path / "source.txt"
    src.write_text("x", encoding="utf-8")
    virtual_dst = build_virtual_path(str(tmp_path / "archive.zip"), "folder/image.png")

    plans = build_drop_plans(
        [ParsedItem(source=str(src), name=src.name, is_binary=False, size=src.stat().st_size)],
        virtual_dst,
        "copy",
    )

    assert plans == []


def test_file_executor_rejects_virtual_source(tmp_path):
    from wafer.core.platform.file_operations import FileExecutor, PasteDecision, PastePlanItem

    virtual_src = build_virtual_path(str(tmp_path / "archive.zip"), "image.png")
    dst = tmp_path / "image.png"
    item = PastePlanItem(
        index=0,
        src=Path(virtual_src),
        is_dir=False,
        action="copy",
        dst_default=dst,
        conflict=False,
        suggested_dst=None,
    )

    res = FileExecutor(ask_conflict=_answers()).execute_plans([item], {0: PasteDecision(mode="create")})

    assert res and res[0].status == "skipped"
    assert res[0].error == "virtual path rejected"
    assert not dst.exists()


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

    res = FileExecutor(ask_conflict=_answers()).execute_plans([item], {0: PasteDecision(mode="create")})
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

    res = FileExecutor(ask_conflict=_answers()).execute_plans([item], {0: PasteDecision(mode="create")})
    assert not dst.exists()
    assert res and res[0].status == "skipped"


def _fake_send2trash(monkeypatch, fn):
    import sys
    import types

    monkeypatch.setitem(sys.modules, "send2trash", types.SimpleNamespace(send2trash=fn))


def test_delete_to_trash_sends_all_paths_in_one_call(tmp_path, monkeypatch):
    from wafer.core.platform.file_operations import delete_to_trash

    a = tmp_path / "a.txt"
    a.write_text("x", encoding="utf-8")
    b = tmp_path / "b.txt"
    b.write_text("y", encoding="utf-8")
    calls: list = []
    _fake_send2trash(monkeypatch, calls.append)

    results = delete_to_trash([str(a), str(b), str(tmp_path / "gone.txt")])

    assert calls == [[str(a), str(b)]]
    assert [r.status for r in results] == ["ok", "ok", "skipped"]


def test_delete_to_trash_never_deletes_permanently(tmp_path, monkeypatch):
    from wafer.core.platform.file_operations import delete_to_trash

    f = tmp_path / "a.txt"
    f.write_text("x", encoding="utf-8")

    def refuse(_paths):
        raise OSError("boom")

    _fake_send2trash(monkeypatch, refuse)
    results = delete_to_trash([str(f)])
    assert results[0].status == "error"
    assert f.exists()


def test_delete_to_trash_retries_one_by_one_and_continues_after_a_locked_file(tmp_path, monkeypatch):
    from wafer.core.platform.file_operations import delete_to_trash

    files = [tmp_path / f"f{i}.txt" for i in range(4)]
    for f in files:
        f.write_text("x", encoding="utf-8")
    locked = str(files[1])

    def send(paths):
        if isinstance(paths, list):
            os.remove(paths[0])
            raise PermissionError("in use")
        if paths == locked:
            raise PermissionError("in use")
        os.remove(paths)

    _fake_send2trash(monkeypatch, send)
    results = delete_to_trash([str(f) for f in files])

    assert [r.status for r in results] == ["ok", "error", "ok", "ok"]
    assert [f.exists() for f in files] == [False, True, False, False]


def test_delete_to_trash_folder_failure_keeps_folder(tmp_path, monkeypatch):
    from wafer.core.platform.file_operations import delete_to_trash

    d = tmp_path / "folder"
    d.mkdir()
    (d / "child.txt").write_text("x", encoding="utf-8")

    def refuse(_paths):
        raise OSError("boom")

    _fake_send2trash(monkeypatch, refuse)
    results = delete_to_trash([str(d)])
    assert results[0].status == "error"
    assert d.exists()


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


def test_a_folder_pasted_onto_a_same_named_folder_is_merged(tmp_path):
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

    res = FileExecutor(ask_conflict=_answers()).execute_plans([item], {0: PasteDecision(mode="create")})
    assert (dst / "a.txt").read_text(encoding="utf-8") == "x"
    assert (dst / "old.txt").read_text(encoding="utf-8") == "old"
    assert res and res[0].status == "ok"


def test_file_executor_merge_dir_overwrite_child(tmp_path):
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

    item = PastePlanItem(
        index=0,
        src=Path(src),
        is_dir=True,
        action="copy",
        dst_default=Path(dst),
        conflict=True,
        suggested_dst=None,
    )

    res = FileExecutor(ask_conflict=_answers()).execute_plans([item], {})
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

    res = FileExecutor(ask_conflict=_answers(files={"a.txt": "skip"})).execute_plans([item], {})
    assert (dst / "a.txt").read_text(encoding="utf-8") == "old"
    assert res and res[0].status == "ok"


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

    res = FileExecutor(ask_conflict=_answers(files={"a.txt": "rename"})).execute_plans([item], {})
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

    res = FileExecutor(ask_conflict=_answers()).execute_plans([item], {})
    assert (dst / "existing.txt").read_text(encoding="utf-8") == "keep"
    assert (dst / "new.txt").read_text(encoding="utf-8") == "added"
    assert res and res[0].status == "ok"


def test_execute_item_case_rename(tmp_path):
    from wafer.core.platform.file_operations import FileExecutor, PasteDecision

    src = tmp_path / "hello.txt"
    src.write_text("content", encoding="utf-8")

    dst = tmp_path / "Hello.txt"
    res = FileExecutor(ask_conflict=_answers())._execute_item(src, dst, "cut", PasteDecision(mode="create"))
    assert res.status == "ok"
    actual = [f for f in tmp_path.iterdir() if f.suffix == ".txt"]
    assert len(actual) == 1
    assert actual[0].read_text(encoding="utf-8") == "content"


def test_execute_item_same_path_cut_noop(tmp_path):
    from wafer.core.platform.file_operations import FileExecutor, PasteDecision

    src = tmp_path / "a.txt"
    src.write_text("x", encoding="utf-8")

    res = FileExecutor(ask_conflict=_answers())._execute_item(src, src, "cut", PasteDecision(mode="create"))
    assert res.status == "skipped"
    assert src.exists()
    assert src.read_text(encoding="utf-8") == "x"


def _overwrite_plan(src, dst):
    from wafer.core.platform.file_operations import PastePlanItem

    return PastePlanItem(index=0, src=src, is_dir=src.is_dir(), action="copy", dst_default=dst, conflict=True, suggested_dst=None)


def test_overwrite_cancelled_before_copy_keeps_the_old_file(tmp_path):
    from wafer.core.platform.file_operations import FileExecutor, PasteDecision

    src = tmp_path / "src" / "a.txt"
    src.parent.mkdir()
    src.write_text("new", encoding="utf-8")
    dst = tmp_path / "a.txt"
    dst.write_text("old", encoding="utf-8")

    res = FileExecutor(ask_conflict=_answers(), cancel_check=lambda: True).execute_one(_overwrite_plan(src, dst), PasteDecision(mode="create"))

    assert res.error == "cancelled"
    assert dst.read_text(encoding="utf-8") == "old"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.txt", "src"]


def test_overwrite_with_unreadable_source_keeps_the_old_file(tmp_path):
    from wafer.core.platform.file_operations import FileExecutor, PasteDecision

    dst = tmp_path / "a.txt"
    dst.write_text("old", encoding="utf-8")

    res = FileExecutor(ask_conflict=_answers())._execute_item(tmp_path / "missing" / "a.txt", dst, "copy", PasteDecision(mode="create"))

    assert res.status == "error"
    assert dst.read_text(encoding="utf-8") == "old"
    assert [p.name for p in tmp_path.iterdir()] == ["a.txt"]


def test_overwrite_replaces_the_file(tmp_path):
    from wafer.core.platform.file_operations import FileExecutor, PasteDecision

    src = tmp_path / "src" / "a.txt"
    src.parent.mkdir()
    src.write_text("new", encoding="utf-8")
    dst = tmp_path / "a.txt"
    dst.write_text("old", encoding="utf-8")

    res = FileExecutor(ask_conflict=_answers()).execute_one(_overwrite_plan(src, dst), PasteDecision(mode="create"))

    assert res.status == "ok"
    assert dst.read_text(encoding="utf-8") == "new"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.txt", "src"]


def test_overwrite_never_replaces_a_folder_with_a_file(tmp_path):
    from wafer.core.platform.file_operations import FileExecutor, PasteDecision

    src = tmp_path / "src" / "export"
    src.parent.mkdir()
    src.write_text("file", encoding="utf-8")
    folder = tmp_path / "export"
    folder.mkdir()
    (folder / "keep.txt").write_text("keep", encoding="utf-8")

    res = FileExecutor(ask_conflict=_answers()).execute_one(_overwrite_plan(src, folder), PasteDecision(mode="create"))

    assert res.status == "ok"
    assert (folder / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert Path(res.dst) != folder
    assert Path(res.dst).read_text(encoding="utf-8") == "file"


def test_merge_overwrite_keeps_a_folder_that_shares_a_file_name(tmp_path):
    from wafer.core.platform.file_operations import FileExecutor, PasteDecision

    src = tmp_path / "src" / "d"
    src.mkdir(parents=True)
    (src / "x").write_text("file", encoding="utf-8")
    dst = tmp_path / "d"
    (dst / "x").mkdir(parents=True)
    (dst / "x" / "keep.txt").write_text("keep", encoding="utf-8")

    res = FileExecutor(ask_conflict=_answers())._execute_item(src, dst, "copy", PasteDecision(mode="create"))

    assert res.status == "ok"
    assert (dst / "x" / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert sorted(p.name for p in dst.iterdir()) == ["x", "x (2)"]


def test_merge_cancel_keeps_every_destination_file(tmp_path):
    from wafer.core.platform.file_operations import FileExecutor, PasteDecision

    src = tmp_path / "src" / "d"
    src.mkdir(parents=True)
    dst = tmp_path / "d"
    dst.mkdir()
    for i in range(3):
        (src / f"f{i}").write_text(f"new{i}", encoding="utf-8")
        (dst / f"f{i}").write_text(f"old{i}", encoding="utf-8")
    copies = []

    executor = FileExecutor(progress_callback=copies.append, cancel_check=lambda: len(copies) >= 1, ask_conflict=_answers())
    res = executor._execute_item(src, dst, "copy", PasteDecision(mode="create"))

    assert res.error == "cancelled"
    assert sorted(p.name for p in dst.iterdir()) == ["f0", "f1", "f2"]
    assert [(dst / f"f{i}").read_text(encoding="utf-8") for i in range(3)] == ["new0", "old1", "old2"]


def _album(root, files, text):
    root.mkdir(parents=True)
    for name in files:
        (root / name).write_text(f"{text} {name}", encoding="utf-8")
    return {name: f"{text} {name}" for name in files}


def _contents(*roots):
    found = {}
    for root in roots:
        for p in root.rglob("*") if root.exists() else ():
            if p.is_file():
                found.setdefault(p.read_text(encoding="utf-8"), []).append(p)
    return found


def _assert_nothing_lost(originals, *roots):
    found = _contents(*roots)
    missing = [text for text in originals.values() if text not in found]
    assert missing == []


windows_only = pytest.mark.skipif(sys.platform != "win32", reason="an open file blocks rename and delete only on Windows")


@windows_only
def test_merging_a_moved_folder_with_an_open_file_loses_nothing(tmp_path):
    from wafer.core.platform.file_operations import FileExecutor, PasteDecision

    src = tmp_path / "src" / "album"
    dst = tmp_path / "dst" / "album"
    originals = {**_album(src, ["a.txt", "b.txt", "c.txt"], "new"), **_album(dst, ["old.txt"], "old")}

    with open(src / "b.txt", "rb"):
        res = FileExecutor(ask_conflict=_answers())._execute_item(src, dst, "cut", PasteDecision(mode="create"))

    assert res.status == "error"
    _assert_nothing_lost(originals, src, dst)
    assert "b.txt" in [p.name for p in src.iterdir()]
    assert sorted(p.name for p in dst.parent.iterdir()) == ["album"]


@windows_only
def test_overwrite_move_of_an_open_file_loses_nothing(tmp_path):
    from wafer.core.platform.file_operations import FileExecutor, PasteDecision

    src = tmp_path / "src" / "a.txt"
    src.parent.mkdir()
    src.write_text("new", encoding="utf-8")
    dst = tmp_path / "dst" / "a.txt"
    dst.parent.mkdir()
    dst.write_text("old", encoding="utf-8")

    with open(src, "rb"):
        res = FileExecutor(ask_conflict=_answers())._execute_item(src, dst, "cut", PasteDecision(mode="create"))

    assert res.status == "error"
    assert src.read_text(encoding="utf-8") == "new"
    assert dst.read_text(encoding="utf-8") == "old"
    assert [p.name for p in dst.parent.iterdir()] == ["a.txt"]


def test_create_saves_under_a_new_name_when_the_destination_appeared(tmp_path):
    from wafer.core.platform.file_operations import FileExecutor, PasteDecision

    src = tmp_path / "src" / "a.txt"
    src.parent.mkdir()
    src.write_text("new", encoding="utf-8")
    dst = tmp_path / "a.txt"
    dst.write_text("appeared", encoding="utf-8")

    res = FileExecutor()._execute_item(src, dst, "cut", PasteDecision(mode="create"))

    assert res.status == "ok"
    assert dst.read_text(encoding="utf-8") == "appeared"
    assert Path(res.dst).read_text(encoding="utf-8") == "new"


def test_create_never_merges_into_a_folder_that_appeared(tmp_path):
    from wafer.core.platform.file_operations import FileExecutor, PasteDecision

    src = tmp_path / "src" / "d"
    _album(src, ["x.txt"], "new")
    dst = tmp_path / "d"
    _album(dst, ["x.txt"], "appeared")

    res = FileExecutor()._execute_item(src, dst, "copy", PasteDecision(mode="create"))

    assert res.status == "ok"
    assert (dst / "x.txt").read_text(encoding="utf-8") == "appeared x.txt"
    assert (Path(res.dst) / "x.txt").read_text(encoding="utf-8") == "new x.txt"


def test_create_moves_to_a_free_destination_and_renames_by_case(tmp_path):
    from wafer.core.platform.file_operations import FileExecutor, PasteDecision

    src = tmp_path / "Photo.PNG"
    src.write_text("x", encoding="utf-8")

    res = FileExecutor()._execute_item(src, tmp_path / "photo.png", "cut", PasteDecision(mode="create"))

    assert res.status == "ok"
    assert [p.name for p in tmp_path.iterdir()] == ["photo.png"]


def test_remote_create_never_replaces_a_file_that_appeared(tmp_path):
    from wafer.core.platform.file_operations import FileExecutor, PasteDecision

    plan = _remote_plan(tmp_path, b"new", binary=True)
    (tmp_path / "image.png").write_bytes(b"appeared")

    res = FileExecutor().execute_one(plan, PasteDecision(mode="create"))

    assert res.status == "ok"
    assert (tmp_path / "image.png").read_bytes() == b"appeared"
    assert Path(res.dst).read_bytes() == b"new"


class _FakeResponse:
    def __init__(self, status_code, chunks=()):
        self.status_code = status_code
        self._chunks = chunks

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_content(self, chunk_size):
        yield from self._chunks


def _remote_plan(tmp_path, source, *, binary=False):
    from wafer.core.platform.file_operations import DropPlanItem
    from wafer.qt.transfer.dragparser import ParsedItem

    dst = tmp_path / "image.png"
    item = ParsedItem(source=source, name=dst.name, is_binary=binary, mime_type="" if binary else "url")
    return DropPlanItem(index=0, src=None, name=dst.name, is_dir=False, action="copy", dst_default=dst, conflict=dst.exists(), suggested_dst=None, parsed_item=item)


def test_remote_overwrite_keeps_the_old_file_when_the_download_fails(tmp_path, monkeypatch):
    import requests

    from wafer.core.platform.file_operations import FileExecutor, PasteDecision

    (tmp_path / "image.png").write_bytes(b"old")
    monkeypatch.setattr(requests.Session, "get", lambda self, url, **kw: _FakeResponse(403))

    res = FileExecutor(ask_conflict=_answers()).execute_one(_remote_plan(tmp_path, "https://example.com/image.png"), PasteDecision(mode="create"))

    assert res.status == "error"
    assert (tmp_path / "image.png").read_bytes() == b"old"
    assert [p.name for p in tmp_path.iterdir()] == ["image.png"]


def test_remote_overwrite_replaces_the_file_after_download(tmp_path, monkeypatch):
    import requests

    from wafer.core.platform.file_operations import FileExecutor, PasteDecision

    (tmp_path / "image.png").write_bytes(b"old")
    monkeypatch.setattr(requests.Session, "get", lambda self, url, **kw: _FakeResponse(200, [b"ne", b"w"]))

    res = FileExecutor(ask_conflict=_answers()).execute_one(_remote_plan(tmp_path, "https://example.com/image.png"), PasteDecision(mode="create"))

    assert res.status == "ok"
    assert (tmp_path / "image.png").read_bytes() == b"new"
    assert [p.name for p in tmp_path.iterdir()] == ["image.png"]


def test_remote_drop_failure_mid_download_leaves_no_partial_file(tmp_path, monkeypatch):
    import requests

    from wafer.core.platform.file_operations import FileExecutor, PasteDecision

    def broken_chunks():
        yield b"half"
        raise requests.ConnectionError("reset")

    monkeypatch.setattr(requests.Session, "get", lambda self, url, **kw: _FakeResponse(200, broken_chunks()))

    res = FileExecutor(ask_conflict=_answers()).execute_one(_remote_plan(tmp_path, "https://example.com/image.png"), PasteDecision(mode="create"))

    assert res.status == "error"
    assert list(tmp_path.iterdir()) == []


def test_binary_drop_skip_and_rename(tmp_path):
    from wafer.core.platform.file_operations import FileExecutor, PasteDecision

    (tmp_path / "image.png").write_bytes(b"old")
    plan = _remote_plan(tmp_path, b"new", binary=True)

    skipped = FileExecutor().execute_one(plan, PasteDecision(mode="skip"))
    renamed = FileExecutor().execute_one(plan, PasteDecision(mode="rename"))

    assert skipped.status == "skipped"
    assert renamed.status == "ok"
    assert (tmp_path / "image.png").read_bytes() == b"old"
    assert Path(renamed.dst).read_bytes() == b"new"


@pytest.fixture
def debug_profile(monkeypatch, tmp_path):
    import wafer.core.common.paths as paths
    from wafer.core.common.paths import scratch_root
    from wafer.core.common.profile import current_profile

    root = str(tmp_path / "appdata")

    class _TmpPlatformDirs:
        def __init__(self, appname=None):
            self.user_data_dir = root
            self.user_config_dir = root

    monkeypatch.setattr(paths, "PlatformDirs", _TmpPlatformDirs)
    sample = tmp_path / "sample"
    sample.mkdir()
    monkeypatch.setenv("WAFER_DEBUG_SAMPLE_ROOT", str(sample))
    monkeypatch.setattr(sys, "argv", ["main.py", "--profile", "debug-fo"])
    current_profile.cache_clear()
    scratch = scratch_root("debug-fo")
    scratch.mkdir(parents=True, exist_ok=True)
    yield sample, scratch
    current_profile.cache_clear()


def test_delete_to_trash_refuses_sample_in_profile(debug_profile):
    from wafer.core.platform.file_operations import delete_to_trash

    sample, _ = debug_profile
    target = sample / "keep.txt"
    target.write_text("x", encoding="utf-8")
    results = delete_to_trash([target])
    assert [r.status for r in results] == ["error"]
    assert target.exists()


def test_paste_into_scratch_is_allowed_in_profile(debug_profile):
    from wafer.core.platform.file_operations import FileExecutor, PasteDecision, PastePlanItem

    sample, scratch = debug_profile
    src = sample / "a.txt"
    src.write_text("x", encoding="utf-8")
    dst = scratch / "a.txt"
    plan = PastePlanItem(index=0, src=src, is_dir=False, action="copy", dst_default=dst, conflict=False, suggested_dst=None)
    results = FileExecutor(ask_conflict=_answers()).execute_plans([plan], {0: PasteDecision(mode="create")})
    assert results[0].status == "ok"
    assert dst.read_text(encoding="utf-8") == "x"


def test_paste_outside_scratch_is_refused_in_profile(debug_profile, tmp_path):
    from wafer.core.platform.file_operations import FileExecutor, PasteDecision, PastePlanItem

    sample, scratch = debug_profile
    src = scratch / "a.txt"
    src.write_text("x", encoding="utf-8")
    copy_dst = sample / "copied.txt"
    cut_plan = PastePlanItem(index=1, src=sample / "b.txt", is_dir=False, action="cut", dst_default=scratch / "b.txt", conflict=False, suggested_dst=None)
    (sample / "b.txt").write_text("y", encoding="utf-8")
    copy_plan = PastePlanItem(index=0, src=src, is_dir=False, action="copy", dst_default=copy_dst, conflict=False, suggested_dst=None)
    results = FileExecutor(ask_conflict=_answers()).execute_plans([copy_plan, cut_plan], {0: PasteDecision(mode="create"), 1: PasteDecision(mode="create")})
    assert [r.status for r in results] == ["error", "error"]
    assert not copy_dst.exists()
    assert (sample / "b.txt").exists()


def test_file_operations_unchanged_without_profile(tmp_path):
    from wafer.core.platform.file_operations import FileExecutor, PasteDecision, PastePlanItem

    src = tmp_path / "a.txt"
    src.write_text("x", encoding="utf-8")
    plan = PastePlanItem(index=0, src=src, is_dir=False, action="copy", dst_default=tmp_path / "b.txt", conflict=False, suggested_dst=None)
    assert FileExecutor(ask_conflict=_answers()).execute_plans([plan], {0: PasteDecision(mode="create")})[0].status == "ok"


def test_remote_drop_outside_scratch_is_refused_in_profile(debug_profile, monkeypatch):
    import requests

    from wafer.core.platform.file_operations import FileExecutor, PasteDecision

    sample, scratch = debug_profile
    monkeypatch.setattr(requests.Session, "get", lambda self, url, **kw: _FakeResponse(200, [b"new"]))

    refused = FileExecutor(ask_conflict=_answers()).execute_one(_remote_plan(sample, "https://example.com/image.png"), PasteDecision(mode="create"))
    allowed = FileExecutor(ask_conflict=_answers()).execute_one(_remote_plan(scratch, "https://example.com/image.png"), PasteDecision(mode="create"))

    assert refused.status == "error"
    assert not (sample / "image.png").exists()
    assert allowed.status == "ok"
    assert (scratch / "image.png").read_bytes() == b"new"
