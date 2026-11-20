from pathlib import Path

import pytest


def _make_plan(index, src, dst, is_dir=False, conflict=True, action="copy"):
    from wafer.core.platform.file_operations import PastePlanItem

    return PastePlanItem(index=index, src=Path(src), is_dir=is_dir, action=action, dst_default=Path(dst), conflict=conflict, suggested_dst=None)


def _paste(plans, *, op, overwrite_mode="ask"):
    from wafer.core.platform.file_operations import FileExecutor
    from wafer.qt.transfer import conflict_resolver as r

    decisions = r.precheck_paste_plans_with_ui(plans=plans, overwrite_mode=overwrite_mode, parent=None, op=op)
    asker = r.ConflictAsker(op=op, overwrite_mode=overwrite_mode, parent=None, item_count=len(plans))
    return FileExecutor(ask_conflict=asker).execute_plans(plans, decisions)


def _record_dialog(monkeypatch, dialog_name, answers):
    from wafer.qt.transfer import conflict_resolver as r

    asked = []
    pending = list(answers)

    def ask(message, **kwargs):
        asked.append({"message": message, **kwargs})
        return pending.pop(0) if len(pending) > 1 else pending[0]

    monkeypatch.setattr(getattr(r, dialog_name), "ask", staticmethod(ask))
    return asked


def _files_under(root):
    return sorted((str(p.relative_to(root)), p.read_text(encoding="utf-8")) for p in root.rglob("*") if p.is_file())


def _same_named_sources(tmp_path, folders=("A", "B"), *, is_dir=False):
    sources = []
    for folder in folders:
        src = tmp_path / folder / "image.png"
        if is_dir:
            src.mkdir(parents=True)
            (src / "inner.txt").write_text(f"from {folder}", encoding="utf-8")
        else:
            src.parent.mkdir(parents=True)
            src.write_text(f"from {folder}", encoding="utf-8")
        sources.append(src)
    dst_dir = tmp_path / "dst"
    dst_dir.mkdir()
    return sources, dst_dir


def _existing_files(tmp_path, names=("a.txt", "b.txt")):
    dst_dir = tmp_path / "dst"
    dst_dir.mkdir()
    plans = []
    for i, name in enumerate(names):
        src = tmp_path / name
        src.write_text(f"new {name}", encoding="utf-8")
        (dst_dir / name).write_text(f"old {name}", encoding="utf-8")
        plans.append(_make_plan(i, src, dst_dir / name))
    return plans, dst_dir


def _paste_plans(dst_dir, action, sources):
    from wafer.qt.transfer.paste import ClipboardFilePaster

    return ClipboardFilePaster.build_paste_plan(dst_dir, (action, sources))


def test_a_file_skipped_inside_a_merge_is_not_overwritten_by_a_later_same_named_folder(monkeypatch, tmp_path):
    from wafer.core.common.paths import normalize_path

    _record_dialog(monkeypatch, "FolderConflictDialog", [("merge", False)])
    file_asked = _record_dialog(monkeypatch, "FileConflictDialog", [("skip", False)])
    dst_dir = tmp_path / "dst"
    (dst_dir / "F").mkdir(parents=True)
    (dst_dir / "F" / "x.png").write_text("existing", encoding="utf-8")
    sources = []
    for folder in ("A", "B"):
        (tmp_path / folder / "F").mkdir(parents=True)
        (tmp_path / folder / "F" / "x.png").write_text(f"from {folder}", encoding="utf-8")
        sources.append(tmp_path / folder / "F")

    _paste(_paste_plans(dst_dir, "copy", sources), op="copy")

    assert (dst_dir / "F" / "x.png").read_text(encoding="utf-8") == "existing"
    existing = normalize_path(str(dst_dir / "F" / "x.png"))
    assert [(a["dst_path"], a["message"]) for a in file_asked] == [(existing, "An item with the same name already exists.")] * 2


def test_a_file_overwritten_inside_a_merge_is_asked_as_another_selected_item(monkeypatch, tmp_path):
    _record_dialog(monkeypatch, "FolderConflictDialog", [("merge", False)])
    file_asked = _record_dialog(monkeypatch, "FileConflictDialog", [("overwrite", False), ("skip", False)])
    dst_dir = tmp_path / "dst"
    (dst_dir / "F").mkdir(parents=True)
    (dst_dir / "F" / "x.png").write_text("existing", encoding="utf-8")
    sources = []
    for folder in ("A", "B"):
        (tmp_path / folder / "F").mkdir(parents=True)
        (tmp_path / folder / "F" / "x.png").write_text(f"from {folder}", encoding="utf-8")
        sources.append(tmp_path / folder / "F")

    _paste(_paste_plans(dst_dir, "copy", sources), op="copy")

    assert (dst_dir / "F" / "x.png").read_text(encoding="utf-8") == "from A"
    assert [a["message"] for a in file_asked] == ["An item with the same name already exists.", "Another selected item has the same name."]


def test_file_apply_all_overwrite_asks_once(monkeypatch, tmp_path):
    asked = _record_dialog(monkeypatch, "FileConflictDialog", [("overwrite", True)])
    plans, dst_dir = _existing_files(tmp_path)

    _paste(plans, op="copy")

    assert len(asked) == 1
    assert asked[0]["show_apply_all"] is True
    assert _files_under(dst_dir) == [("a.txt", "new a.txt"), ("b.txt", "new b.txt")]


def test_file_apply_all_skip_asks_once(monkeypatch, tmp_path):
    asked = _record_dialog(monkeypatch, "FileConflictDialog", [("skip", True)])
    plans, dst_dir = _existing_files(tmp_path)

    results = _paste(plans, op="copy")

    assert len(asked) == 1
    assert [r.status for r in results] == ["skipped", "skipped"]
    assert _files_under(dst_dir) == [("a.txt", "old a.txt"), ("b.txt", "old b.txt")]


def test_a_single_conflict_does_not_offer_apply_to_all(monkeypatch, tmp_path):
    asked = _record_dialog(monkeypatch, "FileConflictDialog", [("skip", False)])
    plans, _ = _existing_files(tmp_path, ("a.txt",))

    _paste(plans, op="copy")

    assert asked[0]["show_apply_all"] is False


@pytest.mark.parametrize("answer", [("cancel", False), (None, False)])
def test_cancelling_a_file_conflict_stops_the_remaining_items(monkeypatch, tmp_path, answer):
    from wafer.core.platform.file_operations import CANCELLED

    _record_dialog(monkeypatch, "FileConflictDialog", [answer])
    plans, dst_dir = _existing_files(tmp_path)
    fresh = tmp_path / "c.txt"
    fresh.write_text("new c.txt", encoding="utf-8")
    plans.append(_make_plan(2, fresh, dst_dir / "c.txt", conflict=False))

    results = _paste(plans, op="copy")

    assert [r.error for r in results] == [CANCELLED, CANCELLED, CANCELLED]
    assert _files_under(dst_dir) == [("a.txt", "old a.txt"), ("b.txt", "old b.txt")]


def test_closing_the_folder_dialog_cancels_the_paste(monkeypatch, tmp_path):
    from wafer.core.platform.file_operations import CANCELLED

    _record_dialog(monkeypatch, "FolderConflictDialog", [(None, False)])
    src = tmp_path / "folder"
    src.mkdir()
    (src / "a.txt").write_text("new", encoding="utf-8")
    (tmp_path / "dst" / "folder").mkdir(parents=True)

    results = _paste([_make_plan(0, src, tmp_path / "dst" / "folder", is_dir=True)], op="copy")

    assert results[0].error == CANCELLED
    assert list((tmp_path / "dst" / "folder").iterdir()) == []


def test_merging_a_folder_asks_each_file_inside_with_apply_to_all(monkeypatch, tmp_path):
    folder_asked = _record_dialog(monkeypatch, "FolderConflictDialog", [("merge", False)])
    file_asked = _record_dialog(monkeypatch, "FileConflictDialog", [("overwrite", True)])
    src = tmp_path / "folder"
    dst = tmp_path / "dst" / "folder"
    src.mkdir()
    dst.mkdir(parents=True)
    for name in ("a.txt", "b.txt"):
        (src / name).write_text("new", encoding="utf-8")
        (dst / name).write_text("old", encoding="utf-8")
    (dst / "only_old.txt").write_text("old", encoding="utf-8")

    _paste([_make_plan(0, src, dst, is_dir=True)], op="copy")

    assert len(folder_asked) == 1
    assert folder_asked[0]["show_apply_all"] is False
    assert len(file_asked) == 1
    assert file_asked[0]["show_apply_all"] is True
    assert _files_under(dst) == [("a.txt", "new"), ("b.txt", "new"), ("only_old.txt", "old")]


def test_a_file_that_appears_after_planning_is_asked_about(monkeypatch, tmp_path):
    asked = _record_dialog(monkeypatch, "FileConflictDialog", [("skip", False)])
    src = tmp_path / "a.txt"
    src.write_text("new", encoding="utf-8")
    dst_dir = tmp_path / "dst"
    dst_dir.mkdir()
    plans = [_make_plan(0, src, dst_dir / "a.txt", conflict=False, action="cut")]
    (dst_dir / "a.txt").write_text("appeared", encoding="utf-8")

    _paste(plans, op="move")

    assert len(asked) == 1
    assert (dst_dir / "a.txt").read_text(encoding="utf-8") == "appeared"
    assert src.read_text(encoding="utf-8") == "new"


@pytest.mark.parametrize(("mode", "expected"), [("overwrite", ["new a.txt", "new b.txt"]), ("skip", ["old a.txt", "old b.txt"])])
def test_a_fixed_overwrite_mode_answers_without_a_dialog(monkeypatch, tmp_path, mode, expected):
    asked = _record_dialog(monkeypatch, "FileConflictDialog", [("cancel", False)])
    plans, dst_dir = _existing_files(tmp_path)

    _paste(plans, op="copy", overwrite_mode=mode)

    assert asked == []
    assert [text for _, text in _files_under(dst_dir)] == expected


def test_rename_mode_keeps_the_existing_file(tmp_path):
    plans, dst_dir = _existing_files(tmp_path, ("a.txt",))

    _paste(plans, op="copy", overwrite_mode="rename")

    assert sorted(text for _, text in _files_under(dst_dir)) == ["new a.txt", "old a.txt"]


def test_moving_same_named_files_asks_about_the_moved_first_and_does_not_offer_overwrite(monkeypatch, tmp_path):
    from wafer.core.common.paths import normalize_path

    asked = _record_dialog(monkeypatch, "FileConflictDialog", [("rename", False)])
    sources, dst_dir = _same_named_sources(tmp_path)

    results = _paste(_paste_plans(dst_dir, "cut", sources), op="move")

    assert [res.status for res in results] == ["ok", "ok"]
    assert len(asked) == 1
    assert asked[0]["src_path"] == normalize_path(str(sources[1]))
    assert asked[0]["dst_path"] == normalize_path(str(dst_dir / "image.png"))
    assert asked[0]["message"] == "Another selected item has the same name."
    assert "overwrite" not in asked[0]["choices"]
    assert sorted(text for _, text in _files_under(dst_dir)) == ["from A", "from B"]


def test_copying_same_named_files_offers_overwrite(monkeypatch, tmp_path):
    asked = _record_dialog(monkeypatch, "FileConflictDialog", [("rename", False)])
    sources, dst_dir = _same_named_sources(tmp_path)

    _paste(_paste_plans(dst_dir, "copy", sources), op="copy")

    assert "overwrite" in asked[0]["choices"]


def test_three_same_named_files_offer_apply_to_all(monkeypatch, tmp_path):
    asked = _record_dialog(monkeypatch, "FileConflictDialog", [("rename", True)])
    sources, dst_dir = _same_named_sources(tmp_path, ("A", "B", "C"))

    _paste(_paste_plans(dst_dir, "copy", sources), op="copy")

    assert len(asked) == 1
    assert asked[0]["show_apply_all"] is True
    assert sorted(text for _, text in _files_under(dst_dir)) == ["from A", "from B", "from C"]


def test_each_same_named_item_saved_under_a_new_name_is_asked(monkeypatch, tmp_path):
    asked = _record_dialog(monkeypatch, "FileConflictDialog", [("rename", False)])
    sources, dst_dir = _same_named_sources(tmp_path, ("A", "B", "C"))

    _paste(_paste_plans(dst_dir, "copy", sources), op="copy")

    assert len(asked) == 2
    assert sorted(text for _, text in _files_under(dst_dir)) == ["from A", "from B", "from C"]


def test_moving_same_named_folders_merges_without_offering_to_overwrite_moved_files(monkeypatch, tmp_path):
    from wafer.core.common.paths import normalize_path

    folder_asked = _record_dialog(monkeypatch, "FolderConflictDialog", [("merge", False)])
    file_asked = _record_dialog(monkeypatch, "FileConflictDialog", [("rename", False)])
    sources, dst_dir = _same_named_sources(tmp_path, is_dir=True)

    results = _paste(_paste_plans(dst_dir, "cut", sources), op="move")

    assert [res.status for res in results] == ["ok", "ok"]
    assert [a["dst_path"] for a in folder_asked] == [normalize_path(str(dst_dir / "image.png"))]
    assert [a["dst_path"] for a in file_asked] == [normalize_path(str(dst_dir / "image.png" / "inner.txt"))]
    assert "overwrite" not in file_asked[0]["choices"]
    assert sorted(text for _, text in _files_under(dst_dir)) == ["from A", "from B"]


def test_overwrite_mode_keeps_both_same_named_moved_items(tmp_path):
    files, dst_dir = _same_named_sources(tmp_path / "files")
    folders, folder_dst = _same_named_sources(tmp_path / "folders", is_dir=True)

    for sources, dst in ((files, dst_dir), (folders, folder_dst)):
        _paste(_paste_plans(dst, "cut", sources), op="move", overwrite_mode="overwrite")
        assert sorted(text for _, text in _files_under(dst)) == ["from A", "from B"]


def test_overwrite_applied_to_all_never_overwrites_another_moved_item(monkeypatch, tmp_path):
    asked = _record_dialog(monkeypatch, "FileConflictDialog", [("overwrite", True)])
    sources, dst_dir = _same_named_sources(tmp_path)
    other = tmp_path / "A" / "other.png"
    other.write_text("new other", encoding="utf-8")
    (dst_dir / "other.png").write_text("old other", encoding="utf-8")

    _paste(_paste_plans(dst_dir, "cut", [other, *sources]), op="move")

    assert len(asked) == 1
    assert sorted(text for _, text in _files_under(dst_dir)) == ["from A", "from B", "new other"]


def test_overwrite_applied_to_all_overwrites_each_same_named_copy(monkeypatch, tmp_path):
    asked = _record_dialog(monkeypatch, "FileConflictDialog", [("overwrite", True)])
    sources, dst_dir = _same_named_sources(tmp_path, ("A", "B", "C"))

    _paste(_paste_plans(dst_dir, "copy", sources), op="copy")

    assert len(asked) == 1
    assert _files_under(dst_dir) == [("image.png", "from C")]
    assert [src.read_text(encoding="utf-8") for src in sources] == ["from A", "from B", "from C"]


def test_apply_to_all_answers_every_remaining_file_conflict(monkeypatch, tmp_path):
    asked = _record_dialog(monkeypatch, "FileConflictDialog", [("rename", True)])
    sources, dst_dir = _same_named_sources(tmp_path)
    other = tmp_path / "B" / "other.png"
    other.write_text("new other", encoding="utf-8")
    (dst_dir / "other.png").write_text("old other", encoding="utf-8")

    _paste(_paste_plans(dst_dir, "copy", [*sources, other]), op="copy")

    assert len(asked) == 1
    assert sorted(text for _, text in _files_under(dst_dir)) == ["from A", "from B", "new other", "old other"]


def test_same_named_drops_of_files_are_asked(monkeypatch, tmp_path):
    from wafer.core.platform.file_operations import build_drop_plans
    from wafer.qt.transfer.dragparser import ParsedItem

    asked = _record_dialog(monkeypatch, "FileConflictDialog", [("skip", False)])
    sources, dst_dir = _same_named_sources(tmp_path)
    items = [ParsedItem(source=str(src), name=src.name) for src in sources]

    _paste(build_drop_plans(items, str(dst_dir), "move"), op="move")

    assert len(asked) == 1
    assert _files_under(dst_dir) == [("image.png", "from A")]
    assert sources[1].read_text(encoding="utf-8") == "from B"


def test_same_named_dropped_data_is_never_overwritten(monkeypatch, tmp_path):
    from wafer.core.platform.file_operations import build_drop_plans
    from wafer.qt.transfer.dragparser import ParsedItem

    asked = _record_dialog(monkeypatch, "FileConflictDialog", [("rename", False)])
    for mode in ("overwrite", "ask"):
        dst = tmp_path / mode
        dst.mkdir()
        items = [ParsedItem(source=b"first", name="image.png", is_binary=True), ParsedItem(source=b"second", name="image.png", is_binary=True)]

        _paste(build_drop_plans(items, str(dst), "copy"), op="copy", overwrite_mode=mode)

        assert sorted(p.read_bytes() for p in dst.iterdir()) == [b"first", b"second"]
    assert len(asked) == 1
    assert asked[0]["message"] == "Another selected item has the same name."
    assert "overwrite" not in asked[0]["choices"]


@pytest.mark.parametrize(("answer", "mode"), [("skip", "skip"), ("rename", "rename")])
def test_same_path_apply_to_all_asks_once(monkeypatch, tmp_path, answer, mode):
    from wafer.qt.transfer import conflict_resolver as r

    asked = _record_dialog(monkeypatch, "FileConflictDialog", [(answer, True)])
    p = tmp_path / "a.txt"
    p.write_text("x", encoding="utf-8")

    decisions = r.precheck_paste_plans_with_ui(plans=[_make_plan(0, p, p, conflict=False), _make_plan(1, p, p, conflict=False)], overwrite_mode="ask", parent=None, op="copy")

    assert [decisions[0].mode, decisions[1].mode] == [mode, mode]
    assert len(asked) == 1


@pytest.mark.parametrize("answer", [("cancel", False), (None, False)])
def test_cancelling_the_same_path_dialog_cancels_before_anything_runs(monkeypatch, tmp_path, answer):
    from wafer.core.platform.file_operations import PasteCancelledError
    from wafer.qt.transfer import conflict_resolver as r

    _record_dialog(monkeypatch, "FileConflictDialog", [answer])
    p = tmp_path / "a.txt"
    p.write_text("x", encoding="utf-8")

    with pytest.raises(PasteCancelledError):
        r.precheck_paste_plans_with_ui(plans=[_make_plan(0, p, p, conflict=False)], overwrite_mode="ask", parent=None, op="copy")


@pytest.mark.parametrize(("overwrite_mode", "mode"), [("overwrite", "skip"), ("skip", "skip"), ("rename", "rename")])
def test_same_path_in_a_fixed_mode_is_decided_without_a_dialog(tmp_path, overwrite_mode, mode):
    from wafer.qt.transfer import conflict_resolver as r

    p = tmp_path / "a.txt"
    p.write_text("x", encoding="utf-8")

    decisions = r.precheck_paste_plans_with_ui(plans=[_make_plan(0, p, p, conflict=False)], overwrite_mode=overwrite_mode, parent=None, op="copy")

    assert decisions[0].mode == mode


def test_case_only_move_renames_the_file(tmp_path):
    src = tmp_path / "Photo.PNG"
    src.write_text("x", encoding="utf-8")

    results = _paste([_make_plan(0, src, tmp_path / "photo.png", conflict=False, action="cut")], op="move")

    assert results[0].status == "ok"
    assert [f.name for f in tmp_path.iterdir()] == ["photo.png"]


def test_precheck_of_no_plans_is_empty():
    from wafer.qt.transfer.conflict_resolver import precheck_paste_plans_with_ui

    assert precheck_paste_plans_with_ui(plans=[], overwrite_mode="ask", parent=None) == {}
