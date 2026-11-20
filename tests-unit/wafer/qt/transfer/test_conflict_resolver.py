from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _no_real_dialogs(monkeypatch):
    from wafer.qt.transfer import conflict_resolver as r

    def unexpected(message, **kwargs):
        raise AssertionError(f"unexpected dialog: {message}")

    for dialog in (r.FileConflictDialog, r.FolderConflictDialog, r.SingleFileConflictDialog):
        monkeypatch.setattr(dialog, "ask", staticmethod(unexpected))


def _make_plan(index, src, dst, is_dir=False, conflict=True, action="copy"):
    from wafer.core.platform.file_operations import PastePlanItem

    return PastePlanItem(index=index, src=Path(src), is_dir=is_dir, action=action, dst_default=Path(dst), conflict=conflict, suggested_dst=None)


def _paste(plans, *, op, overwrite_mode="ask"):
    from wafer.core.platform.file_operations import FileExecutor
    from wafer.qt.transfer import conflict_resolver as r

    decisions = r.precheck_paste_plans_with_ui(plans=plans, overwrite_mode=overwrite_mode, parent=None, op=op)
    asker = r.ConflictAsker(op=op, overwrite_mode=overwrite_mode, parent=None, item_count=len(plans))
    selection = [plan.src for plan in plans if plan.src is not None]
    return FileExecutor(ask_conflict=asker, selection=selection).execute_plans(plans, decisions)


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


def test_moving_same_named_files_asks_about_the_moved_first_with_every_choice(monkeypatch, tmp_path):
    from wafer.core.common.paths import normalize_path

    asked = _record_dialog(monkeypatch, "FileConflictDialog", [("rename", False)])
    sources, dst_dir = _same_named_sources(tmp_path)

    results = _paste(_paste_plans(dst_dir, "cut", sources), op="move")

    assert [res.status for res in results] == ["ok", "ok"]
    assert len(asked) == 1
    assert asked[0]["src_path"] == normalize_path(str(sources[1]))
    assert asked[0]["dst_path"] == normalize_path(str(dst_dir / "image.png"))
    assert asked[0]["message"] == "Another selected item has the same name."
    assert asked[0]["choices"] == ("overwrite", "rename", "skip", "cancel")
    assert sorted(text for _, text in _files_under(dst_dir)) == ["from A", "from B"]


def test_moving_a_same_named_file_over_the_first_replaces_it_when_answered(monkeypatch, tmp_path):
    _record_dialog(monkeypatch, "FileConflictDialog", [("overwrite", False)])
    sources, dst_dir = _same_named_sources(tmp_path)

    _paste(_paste_plans(dst_dir, "cut", sources), op="move")

    assert _files_under(dst_dir) == [("image.png", "from B")]


def test_a_selected_item_already_in_the_destination_is_asked_before_it_is_replaced(monkeypatch, tmp_path):
    from wafer.core.common.paths import normalize_path

    for op, action in (("copy", "copy"), ("move", "cut")):
        root = tmp_path / op
        (root / "S1").mkdir(parents=True)
        (root / "S2").mkdir()
        (root / "S1" / "img.png").write_text("S1 original", encoding="utf-8")
        (root / "S2" / "img.png").write_text("S2 original", encoding="utf-8")
        same_path = _record_dialog(monkeypatch, "FileConflictDialog", [("skip", False), ("rename", False)])

        _paste(_paste_plans(root / "S1", action, [root / "S1" / "img.png", root / "S2" / "img.png"]), op=op, overwrite_mode="ask")

        assert same_path[1]["message"] == "Another selected item has the same name."
        assert same_path[1]["dst_path"] == normalize_path(str(root / "S1" / "img.png"))
        assert sorted(text for _, text in _files_under(root / "S1")) == ["S1 original", "S2 original"]


def test_overwrite_mode_still_asks_before_replacing_a_selected_item(monkeypatch, tmp_path):
    asked = _record_dialog(monkeypatch, "FileConflictDialog", [("rename", False)])
    files, dst_dir = _same_named_sources(tmp_path / "files")
    folders, folder_dst = _same_named_sources(tmp_path / "folders", is_dir=True)

    for sources, dst in ((files, dst_dir), (folders, folder_dst)):
        _paste(_paste_plans(dst, "cut", sources), op="move", overwrite_mode="overwrite")
        assert sorted(text for _, text in _files_under(dst)) == ["from A", "from B"]
    assert [a["message"] for a in asked] == ["Another selected item has the same name."] * 2


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


def test_moving_same_named_folders_merges_and_asks_about_moved_files_with_every_choice(monkeypatch, tmp_path):
    from wafer.core.common.paths import normalize_path

    folder_asked = _record_dialog(monkeypatch, "FolderConflictDialog", [("merge", False)])
    file_asked = _record_dialog(monkeypatch, "FileConflictDialog", [("rename", False)])
    sources, dst_dir = _same_named_sources(tmp_path, is_dir=True)

    results = _paste(_paste_plans(dst_dir, "cut", sources), op="move")

    assert [res.status for res in results] == ["ok", "ok"]
    assert [a["dst_path"] for a in folder_asked] == [normalize_path(str(dst_dir / "image.png"))]
    assert [a["dst_path"] for a in file_asked] == [normalize_path(str(dst_dir / "image.png" / "inner.txt"))]
    assert file_asked[0]["choices"] == ("overwrite", "rename", "skip", "cancel")
    assert sorted(text for _, text in _files_under(dst_dir)) == ["from A", "from B"]


def test_overwrite_for_all_existing_files_still_asks_before_replacing_a_selected_item(monkeypatch, tmp_path):
    asked = _record_dialog(monkeypatch, "FileConflictDialog", [("overwrite", True), ("rename", False)])
    sources, dst_dir = _same_named_sources(tmp_path)
    other = tmp_path / "A" / "other.png"
    other.write_text("new other", encoding="utf-8")
    (dst_dir / "other.png").write_text("old other", encoding="utf-8")

    _paste(_paste_plans(dst_dir, "cut", [other, *sources]), op="move")

    assert [a["message"] for a in asked] == ["An item with the same name already exists.", "Another selected item has the same name."]
    assert sorted(text for _, text in _files_under(dst_dir)) == ["from A", "from B", "new other"]


def test_overwrite_applied_to_all_same_named_copies_overwrites_each_of_them(monkeypatch, tmp_path):
    asked = _record_dialog(monkeypatch, "FileConflictDialog", [("overwrite", True)])
    sources, dst_dir = _same_named_sources(tmp_path, ("A", "B", "C"))

    _paste(_paste_plans(dst_dir, "copy", sources), op="copy")

    assert len(asked) == 1
    assert _files_under(dst_dir) == [("image.png", "from C")]
    assert [src.read_text(encoding="utf-8") for src in sources] == ["from A", "from B", "from C"]


def test_apply_to_all_answers_only_the_same_kind_of_conflict(monkeypatch, tmp_path):
    asked = _record_dialog(monkeypatch, "FileConflictDialog", [("rename", True)])
    sources, dst_dir = _same_named_sources(tmp_path, ("A", "B", "C"))
    other = tmp_path / "B" / "other.png"
    other.write_text("new other", encoding="utf-8")
    (dst_dir / "other.png").write_text("old other", encoding="utf-8")
    third = tmp_path / "C" / "other.png"
    third.write_text("third other", encoding="utf-8")

    _paste(_paste_plans(dst_dir, "copy", [*sources, other, third]), op="copy")

    assert [a["message"] for a in asked] == ["Another selected item has the same name.", "An item with the same name already exists."]
    assert sorted(text for _, text in _files_under(dst_dir)) == ["from A", "from B", "from C", "new other", "old other", "third other"]


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


def test_same_named_dropped_data_is_asked_with_every_choice_in_any_mode(monkeypatch, tmp_path):
    from wafer.core.platform.file_operations import build_drop_plans
    from wafer.qt.transfer.dragparser import ParsedItem

    asked = _record_dialog(monkeypatch, "FileConflictDialog", [("rename", False)])
    for mode in ("overwrite", "ask"):
        dst = tmp_path / mode
        dst.mkdir()
        items = [ParsedItem(source=b"first", name="image.png", is_binary=True), ParsedItem(source=b"second", name="image.png", is_binary=True)]

        _paste(build_drop_plans(items, str(dst), "copy"), op="copy", overwrite_mode=mode)

        assert sorted(p.read_bytes() for p in dst.iterdir()) == [b"first", b"second"]
    assert [a["message"] for a in asked] == ["Another selected item has the same name."] * 2
    assert all(a["choices"] == ("overwrite", "rename", "skip", "cancel") for a in asked)


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


SELECTED = "Another selected item has the same name."
EXISTING = "An item with the same name already exists."
FOLDER = "Folder with the same name already exists. Proceed?"
FILE_CHOICES = ("overwrite", "rename", "skip", "cancel")

ARRANGEMENTS = {
    "same_named": {"existing": [], "items": [("X", "n"), ("Y", "n"), ("Z", "n")]},
    "selected_at_destination": {"existing": [], "items": [("D", "n"), ("X", "n")]},
    "existing_and_selected": {"existing": ["n"], "items": [("X", "n"), ("Y", "n")]},
    "mixed": {"existing": ["e"], "items": [("X", "e"), ("Y", "n"), ("Z", "n")]},
}
SOURCES = [("copy", "files"), ("copy", "folders"), ("move", "files"), ("move", "folders"), ("drop", "files")]
MODES = [
    ("overwrite", "overwrite", False),
    ("overwrite", "overwrite", True),
    ("overwrite", "rename", False),
    ("rename", None, False),
    ("skip", None, False),
    *[("ask", answer, apply_all) for answer in ("overwrite", "rename", "skip", "cancel", "cycle") for apply_all in (False, True)],
]


def _combinations():
    for source, kind in SOURCES:
        for arrangement in ARRANGEMENTS:
            if source == "drop" and arrangement == "selected_at_destination":
                continue
            for reverse in (False, True):
                for mode, answer, apply_all in MODES:
                    same_path_answers = ("rename", "skip") if arrangement == "selected_at_destination" and mode == "ask" else (None,)
                    for same_path_answer in same_path_answers:
                        yield pytest.param(
                            source,
                            kind,
                            arrangement,
                            reverse,
                            mode,
                            answer,
                            apply_all,
                            same_path_answer,
                            id=f"{source}-{kind}-{arrangement}-{'reverse' if reverse else 'forward'}-{mode}-{answer}-{'all' if apply_all else 'one'}-{same_path_answer}",
                        )


def _write_item(path, label, kind):
    if kind == "folders":
        path.mkdir(parents=True)
        (path / "inner.txt").write_text(f"{label}:inner", encoding="utf-8")
        (path / f"only_{label.replace('/', '_')}.txt").write_text(f"{label}:only", encoding="utf-8")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{label}:file", encoding="utf-8")


def _all_contents(root):
    return sorted(p.read_text(encoding="utf-8") for p in root.rglob("*") if p.is_file())


def _held_at(path):
    if path.is_dir():
        return _all_contents(path)
    return [path.read_text(encoding="utf-8")] if path.is_file() else []


@pytest.mark.parametrize(("source", "kind", "arrangement", "reverse", "mode", "answer", "apply_all", "same_path_answer"), list(_combinations()))
def test_every_combination_loses_only_what_was_answered_overwrite(monkeypatch, tmp_path, source, kind, arrangement, reverse, mode, answer, apply_all, same_path_answer):
    from wafer.core.common.paths import normalize_path
    from wafer.core.platform.file_operations import CANCELLED, FileExecutor, PasteCancelledError, build_drop_plans
    from wafer.qt.transfer import conflict_resolver as r
    from wafer.qt.transfer.dragparser import ParsedItem

    spec = ARRANGEMENTS[arrangement]
    dst = tmp_path / "D"
    dst.mkdir()
    for name in spec["existing"]:
        _write_item(dst / name, f"D/{name}", kind)
    items = list(reversed(spec["items"])) if reverse else spec["items"]
    selected_sources = []
    dropped = []
    if source == "drop":
        parsed = [ParsedItem(source=f"{folder}/{name}:drop".encode(), name=name, is_binary=True) for folder, name in items]
        plans = build_drop_plans(parsed, str(dst), "copy")
        dropped = [f"{folder}/{name}:drop" for folder, name in items]
    else:
        for folder, name in items:
            path = tmp_path / folder / name
            if not path.exists():
                _write_item(path, f"{folder}/{name}", kind)
            selected_sources.append(path)
        plans = _paste_plans(dst, "cut" if source == "move" else "copy", selected_sources)
    originals = set(_all_contents(tmp_path)) | set(dropped)
    existed_before = set(tmp_path.rglob("*"))
    selected_labels = {f"{folder}/{name}" for folder, name in items}
    op = "move" if source == "move" else "copy"

    def really_selected(path):
        if any(path == s or s in path.parents for s in selected_sources):
            return True
        if path.is_dir():
            return path not in existed_before
        return path.read_text(encoding="utf-8").rsplit(":", 1)[0] in selected_labels

    current = {}
    dialogs = []
    cycle = iter(["overwrite", "rename", "skip"] * 100)

    def next_answer():
        return next(cycle) if answer == "cycle" else answer

    def file_dialog(message, **kw):
        if "overwrite" not in kw["choices"]:
            dialogs.append({"kind": "same_path", "choice": same_path_answer})
            return (same_path_answer, False)
        conflict = current["conflict"]
        assert kw["choices"] == FILE_CHOICES
        assert message == (SELECTED if conflict.selected_item else EXISTING)
        assert kw["dst_path"] == normalize_path(str(conflict.dst))
        choice = next_answer()
        dialogs.append({"kind": "file", "message": message, "choice": choice})
        return (choice, apply_all)

    def folder_dialog(message, **kw):
        conflict = current["conflict"]
        assert message == (SELECTED if conflict.selected_item else FOLDER)
        assert kw["dst_path"] == normalize_path(str(conflict.dst))
        choice = next_answer()
        choice = "merge" if choice == "overwrite" else choice
        dialogs.append({"kind": "folder", "message": message, "choice": choice})
        return (choice, apply_all)

    monkeypatch.setattr(r.FileConflictDialog, "ask", staticmethod(file_dialog))
    monkeypatch.setattr(r.FolderConflictDialog, "ask", staticmethod(folder_dialog))

    asker = r.ConflictAsker(op=op, overwrite_mode=mode, parent=None, item_count=len(plans))
    asked = []

    wrong = []

    def recording_asker(conflict):
        selected = really_selected(conflict.dst)
        if conflict.selected_item != selected:
            wrong.append(f"{conflict.dst}: selected_item={conflict.selected_item}, really {selected}")
        current["conflict"] = conflict
        held = _held_at(conflict.dst)
        dialogs_before = len(dialogs)
        try:
            result = asker(conflict)
        except AssertionError as e:
            wrong.append(str(e))
            raise PasteCancelledError() from e
        asked.append({"conflict": conflict, "selected": selected, "answer": result, "held": held, "by_dialog": len(dialogs) > dialogs_before})
        return result

    try:
        decisions = r.precheck_paste_plans_with_ui(plans=plans, overwrite_mode=mode, parent=None, op=op)
        results = FileExecutor(ask_conflict=recording_asker, selection=selected_sources).execute_plans(plans, decisions)
    except PasteCancelledError:
        results = []

    assert wrong == []
    assert [res for res in results if res.status == "error"] == []
    not_saved_by_choice ={dropped[i] for i, result in enumerate(results) if dropped and result.status == "skipped"}
    lost = originals - set(_all_contents(tmp_path)) - not_saved_by_choice
    answered_overwrite = {text for a in asked if a["answer"] == "overwrite" for text in a["held"]}
    assert lost <= answered_overwrite, f"lost without an overwrite answer: {sorted(lost - answered_overwrite)}"

    selected_overwrite_applied_to_all = False
    for a in asked:
        if a["selected"] and not a["conflict"].folders and a["answer"] == "overwrite":
            assert a["by_dialog"] or selected_overwrite_applied_to_all, f"{a['conflict'].dst} was a selected item and was overwritten without a dialog"
            if a["by_dialog"] and apply_all:
                selected_overwrite_applied_to_all = True

    if mode in ("rename", "skip"):
        assert dialogs == []
        assert lost == set()
    if mode == "overwrite":
        assert [d for d in dialogs if d["kind"] == "file" and d["message"] != SELECTED] == []

    cancelled_at = next((i for i, d in enumerate(dialogs) if d.get("choice") == "cancel"), None)
    if cancelled_at is not None:
        assert len(dialogs) == cancelled_at + 1
        assert results[-1].error == CANCELLED
    assert [p for p in tmp_path.rglob("*") if "wafer-partial" in p.name] == []
