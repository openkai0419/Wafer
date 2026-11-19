from pathlib import Path


def _make_plan(index, src, dst, is_dir=False, conflict=True, action="copy", suggested_dst=None):
    from wafer.core.platform.file_operations import PastePlanItem

    return PastePlanItem(
        index=index,
        src=Path(src),
        is_dir=is_dir,
        action=action,
        dst_default=Path(dst),
        conflict=conflict,
        suggested_dst=suggested_dst,
    )


def test_file_apply_all_overwrite(monkeypatch, tmp_path):
    from wafer.qt.transfer import conflict_resolver as r

    calls = {"n": 0}

    def ask(*args, **kwargs):
        calls["n"] += 1
        return ("overwrite", True)

    monkeypatch.setattr(r.FileConflictDialog, "ask", staticmethod(ask))

    src1 = tmp_path / "a.txt"
    src2 = tmp_path / "b.txt"
    dst_dir = tmp_path / "dst"
    src1.write_text("x", encoding="utf-8")
    src2.write_text("y", encoding="utf-8")
    dst_dir.mkdir()
    (dst_dir / "a.txt").write_text("old", encoding="utf-8")
    (dst_dir / "b.txt").write_text("old", encoding="utf-8")

    plans = [
        _make_plan(0, src1, dst_dir / "a.txt"),
        _make_plan(1, src2, dst_dir / "b.txt"),
    ]

    resolver = r.ConflictResolver(op="copy", overwrite_mode="ask", parent=None, folder_message="")
    decisions = resolver.resolve_plans(plans)

    assert decisions[0].mode == "overwrite"
    assert decisions[1].mode == "overwrite"
    assert calls["n"] == 1


def test_file_apply_all_skip(monkeypatch, tmp_path):
    from wafer.qt.transfer import conflict_resolver as r

    calls = {"n": 0}

    def ask(*args, **kwargs):
        calls["n"] += 1
        return ("skip", True)

    monkeypatch.setattr(r.FileConflictDialog, "ask", staticmethod(ask))

    src1 = tmp_path / "a.txt"
    src2 = tmp_path / "b.txt"
    dst_dir = tmp_path / "dst"
    src1.write_text("x", encoding="utf-8")
    src2.write_text("y", encoding="utf-8")
    dst_dir.mkdir()
    (dst_dir / "a.txt").write_text("old", encoding="utf-8")
    (dst_dir / "b.txt").write_text("old", encoding="utf-8")

    plans = [
        _make_plan(0, src1, dst_dir / "a.txt"),
        _make_plan(1, src2, dst_dir / "b.txt"),
    ]

    resolver = r.ConflictResolver(op="copy", overwrite_mode="ask", parent=None, folder_message="")
    decisions = resolver.resolve_plans(plans)

    assert decisions[0].mode == "skip"
    assert decisions[1].mode == "skip"
    assert calls["n"] == 1


def test_cancel_raises_paste_cancelled_error(monkeypatch, tmp_path):
    import pytest
    from wafer.core.platform.file_operations import PasteCancelledError
    from wafer.qt.transfer import conflict_resolver as r

    def ask(*args, **kwargs):
        return ("cancel", False)

    monkeypatch.setattr(r.FileConflictDialog, "ask", staticmethod(ask))

    src = tmp_path / "a.txt"
    src.write_text("x", encoding="utf-8")
    dst_dir = tmp_path / "dst"
    dst_dir.mkdir()
    (dst_dir / "a.txt").write_text("old", encoding="utf-8")

    plans = [_make_plan(0, src, dst_dir / "a.txt")]
    resolver = r.ConflictResolver(op="copy", overwrite_mode="ask", parent=None, folder_message="")

    with pytest.raises(PasteCancelledError):
        resolver.resolve_plans(plans)


def test_folder_conflict_merge_then_file_conflicts(monkeypatch, tmp_path):
    from wafer.qt.transfer import conflict_resolver as r

    folder_calls = {"n": 0}
    file_calls = {"n": 0}

    def folder_ask(*args, **kwargs):
        folder_calls["n"] += 1
        return ("merge", False)

    def file_ask(*args, **kwargs):
        file_calls["n"] += 1
        return ("overwrite", True)

    monkeypatch.setattr(r.FolderConflictDialog, "ask", staticmethod(folder_ask))
    monkeypatch.setattr(r.FileConflictDialog, "ask", staticmethod(file_ask))

    src = tmp_path / "folder"
    src.mkdir()
    (src / "a.txt").write_text("new", encoding="utf-8")
    (src / "b.txt").write_text("new2", encoding="utf-8")

    dst_dir = tmp_path / "dst"
    dst_dir.mkdir()
    dst = dst_dir / "folder"
    dst.mkdir()
    (dst / "a.txt").write_text("old", encoding="utf-8")
    (dst / "b.txt").write_text("old2", encoding="utf-8")

    plans = [_make_plan(0, src, dst, is_dir=True)]
    resolver = r.ConflictResolver(op="copy", overwrite_mode="ask", parent=None, folder_message="test")
    decisions = resolver.resolve_plans(plans)

    assert decisions[0].mode == "merge"
    assert decisions[0].merge_decisions is not None
    assert decisions[0].merge_decisions["a.txt"].mode == "overwrite"
    assert decisions[0].merge_decisions["b.txt"].mode == "overwrite"
    assert folder_calls["n"] == 1
    assert file_calls["n"] == 1


def test_same_path_apply_all_skip(monkeypatch, tmp_path):
    from wafer.qt.transfer import conflict_resolver as r

    calls = {"n": 0}

    def ask(*args, **kwargs):
        calls["n"] += 1
        return ("skip", True)

    monkeypatch.setattr(r.FileConflictDialog, "ask", staticmethod(ask))

    p = tmp_path / "a.txt"
    p.write_text("x", encoding="utf-8")

    plans = [
        _make_plan(0, p, p, conflict=False),
        _make_plan(1, p, p, conflict=False),
    ]

    resolver = r.ConflictResolver(op="copy", overwrite_mode="ask", parent=None, folder_message="")
    decisions = resolver.resolve_plans(plans)

    assert decisions[0].mode == "skip"
    assert decisions[1].mode == "skip"
    assert calls["n"] == 1


def test_same_path_apply_all_rename(monkeypatch, tmp_path):
    from wafer.qt.transfer import conflict_resolver as r

    calls = {"n": 0}

    def ask(*args, **kwargs):
        calls["n"] += 1
        return ("rename", True)

    monkeypatch.setattr(r.FileConflictDialog, "ask", staticmethod(ask))

    p = tmp_path / "a.txt"
    p.write_text("x", encoding="utf-8")

    plans = [
        _make_plan(0, p, p, conflict=False),
        _make_plan(1, p, p, conflict=False),
    ]

    resolver = r.ConflictResolver(op="copy", overwrite_mode="ask", parent=None, folder_message="")
    decisions = resolver.resolve_plans(plans)

    assert decisions[0].mode == "rename"
    assert decisions[1].mode == "rename"
    assert calls["n"] == 1


def test_same_path_cancel_raises(monkeypatch, tmp_path):
    import pytest
    from wafer.core.platform.file_operations import PasteCancelledError
    from wafer.qt.transfer import conflict_resolver as r

    def ask(*args, **kwargs):
        return ("cancel", False)

    monkeypatch.setattr(r.FileConflictDialog, "ask", staticmethod(ask))

    p = tmp_path / "a.txt"
    p.write_text("x", encoding="utf-8")

    plans = [_make_plan(0, p, p, conflict=False)]
    resolver = r.ConflictResolver(op="copy", overwrite_mode="ask", parent=None, folder_message="")

    with pytest.raises(PasteCancelledError):
        resolver.resolve_plans(plans)


def test_same_path_overwrite_mode_forces_skip(tmp_path):
    from wafer.qt.transfer import conflict_resolver as r

    p = tmp_path / "a.txt"
    p.write_text("x", encoding="utf-8")

    plans = [_make_plan(0, p, p, conflict=False)]
    resolver = r.ConflictResolver(op="copy", overwrite_mode="overwrite", parent=None, folder_message="")
    decisions = resolver.resolve_plans(plans)

    assert decisions[0].mode == "skip"


def test_same_path_rename_mode_forces_rename(tmp_path):
    from wafer.qt.transfer import conflict_resolver as r

    p = tmp_path / "a.txt"
    p.write_text("x", encoding="utf-8")

    plans = [_make_plan(0, p, p, conflict=False)]
    resolver = r.ConflictResolver(op="copy", overwrite_mode="rename", parent=None, folder_message="")
    decisions = resolver.resolve_plans(plans)

    assert decisions[0].mode == "rename"


def test_case_only_move_renames_the_file(tmp_path):
    from wafer.qt.transfer import conflict_resolver as r
    from wafer.core.platform.file_operations import FileExecutor

    src = tmp_path / "Photo.PNG"
    src.write_text("x", encoding="utf-8")
    plan = _make_plan(0, src, tmp_path / "photo.png", conflict=False, action="cut")
    resolver = r.ConflictResolver(op="move", overwrite_mode="ask", parent=None, folder_message="")
    decision = resolver.resolve_plans([plan])[0]

    result = FileExecutor()._execute_item(plan.src, plan.dst_default, "cut", decision)

    assert result.status == "ok"
    assert [f.name for f in tmp_path.iterdir()] == ["photo.png"]


def test_overwrite_mode_forces_decision(tmp_path):
    from wafer.qt.transfer import conflict_resolver as r

    src = tmp_path / "a.txt"
    src.write_text("x", encoding="utf-8")
    dst_dir = tmp_path / "dst"
    dst_dir.mkdir()
    (dst_dir / "a.txt").write_text("old", encoding="utf-8")

    plans = [_make_plan(0, src, dst_dir / "a.txt")]
    resolver = r.ConflictResolver(op="copy", overwrite_mode="overwrite", parent=None, folder_message="")
    decisions = resolver.resolve_plans(plans)

    assert decisions[0].mode == "overwrite"


def test_no_conflict_plans_never_replace_what_appears_after_planning(tmp_path):
    from wafer.core.platform.file_operations import FileExecutor
    from wafer.qt.transfer import conflict_resolver as r

    src = tmp_path / "a.txt"
    src.write_text("new", encoding="utf-8")
    dst_dir = tmp_path / "dst"
    dst_dir.mkdir()

    plans = [_make_plan(0, src, dst_dir / "a.txt", conflict=False, action="cut")]
    resolver = r.ConflictResolver(op="move", overwrite_mode="ask", parent=None, folder_message="")
    decisions = resolver.resolve_plans(plans)
    (dst_dir / "a.txt").write_text("appeared", encoding="utf-8")
    result = FileExecutor().execute_plans(plans, decisions)[0]

    assert result.status == "ok"
    assert (dst_dir / "a.txt").read_text(encoding="utf-8") == "appeared"
    assert Path(result.dst).read_text(encoding="utf-8") == "new"
    assert Path(result.dst) != dst_dir / "a.txt"


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


def _files_under(root):
    return sorted((str(p.relative_to(root)), p.read_text(encoding="utf-8")) for p in root.rglob("*") if p.is_file())


def test_cutting_same_named_files_from_two_folders_asks_instead_of_overwriting(monkeypatch, tmp_path):
    from wafer.core.common.paths import normalize_path
    from wafer.core.platform.file_operations import FileExecutor
    from wafer.qt.transfer import conflict_resolver as r
    from wafer.qt.transfer.paste import ClipboardFilePaster

    asked = []

    def ask(message, **kwargs):
        asked.append(kwargs)
        return ("rename", False)

    monkeypatch.setattr(r.FileConflictDialog, "ask", staticmethod(ask))
    sources, dst_dir = _same_named_sources(tmp_path)
    plans = ClipboardFilePaster.build_paste_plan(dst_dir, ("cut", sources))

    decisions = r.ConflictResolver(op="move", overwrite_mode="ask", parent=None, folder_message="").resolve_plans(plans)
    results = FileExecutor().execute_plans(plans, decisions)

    assert [res.status for res in results] == ["ok", "ok"]
    assert len(asked) == 1
    assert asked[0]["src_path"] == normalize_path(str(sources[1]))
    assert asked[0]["dst_path"] == normalize_path(str(sources[0]))
    assert sorted(text for _, text in _files_under(dst_dir)) == ["from A", "from B"]


def test_three_same_named_files_offer_apply_to_all(monkeypatch, tmp_path):
    from wafer.core.platform.file_operations import FileExecutor
    from wafer.qt.transfer import conflict_resolver as r
    from wafer.qt.transfer.paste import ClipboardFilePaster

    asked = []

    def ask(message, **kwargs):
        asked.append(kwargs)
        return ("rename", True)

    monkeypatch.setattr(r.FileConflictDialog, "ask", staticmethod(ask))
    sources, dst_dir = _same_named_sources(tmp_path, ("A", "B", "C"))
    plans = ClipboardFilePaster.build_paste_plan(dst_dir, ("copy", sources))

    decisions = r.ConflictResolver(op="copy", overwrite_mode="ask", parent=None, folder_message="").resolve_plans(plans)
    FileExecutor().execute_plans(plans, decisions)

    assert len(asked) == 1
    assert asked[0]["show_apply_all"] is True
    assert sorted(text for _, text in _files_under(dst_dir)) == ["from A", "from B", "from C"]


def test_same_named_folders_are_asked_and_merge_asks_about_files_from_the_first_folder(monkeypatch, tmp_path):
    from wafer.core.common.paths import normalize_path
    from wafer.core.platform.file_operations import FileExecutor
    from wafer.qt.transfer import conflict_resolver as r
    from wafer.qt.transfer.paste import ClipboardFilePaster

    folder_asked = []
    file_asked = []

    def folder_ask(message, **kwargs):
        folder_asked.append(kwargs)
        return ("merge", False)

    def file_ask(message, **kwargs):
        file_asked.append(kwargs)
        return ("rename", False)

    monkeypatch.setattr(r.FolderConflictDialog, "ask", staticmethod(folder_ask))
    monkeypatch.setattr(r.FileConflictDialog, "ask", staticmethod(file_ask))
    sources, dst_dir = _same_named_sources(tmp_path, is_dir=True)
    plans = ClipboardFilePaster.build_paste_plan(dst_dir, ("cut", sources))

    decisions = r.ConflictResolver(op="move", overwrite_mode="ask", parent=None, folder_message="").resolve_plans(plans)
    results = FileExecutor().execute_plans(plans, decisions)

    assert [res.status for res in results] == ["ok", "ok"]
    assert [k["dst_path"] for k in folder_asked] == [normalize_path(str(sources[0]))]
    assert [k["dst_path"] for k in file_asked] == [normalize_path(str(sources[0] / "inner.txt"))]
    assert sorted(text for _, text in _files_under(dst_dir)) == ["from A", "from B"]


def test_overwrite_mode_keeps_both_same_named_items_of_one_paste(tmp_path):
    from wafer.core.platform.file_operations import FileExecutor
    from wafer.qt.transfer import conflict_resolver as r
    from wafer.qt.transfer.paste import ClipboardFilePaster

    files, dst_dir = _same_named_sources(tmp_path / "files")
    folders, folder_dst = _same_named_sources(tmp_path / "folders", is_dir=True)

    for sources, dst in ((files, dst_dir), (folders, folder_dst)):
        plans = ClipboardFilePaster.build_paste_plan(dst, ("cut", sources))
        decisions = r.ConflictResolver(op="move", overwrite_mode="overwrite", parent=None, folder_message="").resolve_plans(plans)
        FileExecutor().execute_plans(plans, decisions)
        assert sorted(text for _, text in _files_under(dst)) == ["from A", "from B"]


def test_a_skipped_first_item_leaves_the_second_to_face_only_the_existing_file(monkeypatch, tmp_path):
    from wafer.core.common.paths import normalize_path
    from wafer.qt.transfer import conflict_resolver as r
    from wafer.qt.transfer.paste import ClipboardFilePaster

    asked = []

    def ask(message, **kwargs):
        asked.append(kwargs)
        return ("skip", False)

    monkeypatch.setattr(r.FileConflictDialog, "ask", staticmethod(ask))
    sources, dst_dir = _same_named_sources(tmp_path)
    (dst_dir / "image.png").write_text("existing", encoding="utf-8")
    plans = ClipboardFilePaster.build_paste_plan(dst_dir, ("cut", sources))

    r.ConflictResolver(op="move", overwrite_mode="ask", parent=None, folder_message="").resolve_plans(plans)

    existing = normalize_path(str(dst_dir / "image.png"))
    assert [k["dst_path"] for k in asked] == [existing, existing]


def test_an_item_saved_under_a_new_name_leaves_the_name_to_the_first(monkeypatch, tmp_path):
    from wafer.qt.transfer import conflict_resolver as r
    from wafer.qt.transfer.paste import ClipboardFilePaster

    asked = []

    def ask(message, **kwargs):
        asked.append(kwargs)
        return ("rename", False)

    monkeypatch.setattr(r.FileConflictDialog, "ask", staticmethod(ask))
    sources, dst_dir = _same_named_sources(tmp_path, ("A", "B", "C"))
    plans = ClipboardFilePaster.build_paste_plan(dst_dir, ("copy", sources))

    decisions = r.ConflictResolver(op="copy", overwrite_mode="ask", parent=None, folder_message="").resolve_plans(plans)

    assert [decisions[i].mode for i in range(3)] == ["create", "rename", "rename"]
    assert len(asked) == 2


def test_same_named_drops_are_asked_too(monkeypatch, tmp_path):
    from wafer.core.platform.file_operations import FileExecutor, build_drop_plans
    from wafer.qt.transfer import conflict_resolver as r
    from wafer.qt.transfer.dragparser import ParsedItem

    asked = []
    monkeypatch.setattr(r.FileConflictDialog, "ask", staticmethod(lambda message, **kw: (asked.append(kw), ("skip", False))[1]))
    sources, dst_dir = _same_named_sources(tmp_path)
    items = [ParsedItem(source=str(src), name=src.name) for src in sources]
    plans = build_drop_plans(items, str(dst_dir), "move")

    decisions = r.ConflictResolver(op="move", overwrite_mode="ask", parent=None, folder_message="").resolve_plans(plans)
    FileExecutor().execute_plans(plans, decisions)

    assert len(asked) == 1
    assert _files_under(dst_dir) == [("image.png", "from A")]
    assert sources[1].read_text(encoding="utf-8") == "from B"


def test_resolve_paste_plans_with_ui_empty():
    from wafer.qt.transfer.conflict_resolver import resolve_paste_plans_with_ui

    result = resolve_paste_plans_with_ui(plans=[], overwrite_mode="ask", parent=None)
    assert result == {}


def _file_conflict(tmp_path, name="a.txt"):
    src = tmp_path / name
    src.write_text("x", encoding="utf-8")
    dst_dir = tmp_path / "dst"
    dst_dir.mkdir(exist_ok=True)
    (dst_dir / name).write_text("old", encoding="utf-8")
    return _make_plan(0, src, dst_dir / name)


def _folder_conflict(tmp_path, files):
    src = tmp_path / "folder"
    dst = tmp_path / "dst" / "folder"
    src.mkdir()
    dst.mkdir(parents=True)
    for name in files:
        (src / name).write_text("new", encoding="utf-8")
        (dst / name).write_text("old", encoding="utf-8")
    return _make_plan(0, src, dst, is_dir=True)


def test_closing_the_file_dialog_cancels_the_paste(monkeypatch, tmp_path):
    import pytest
    from wafer.core.platform.file_operations import PasteCancelledError
    from wafer.qt.transfer import conflict_resolver as r

    monkeypatch.setattr(r.FileConflictDialog, "ask", staticmethod(lambda *a, **k: (None, False)))
    resolver = r.ConflictResolver(op="copy", overwrite_mode="ask", parent=None, folder_message="")

    with pytest.raises(PasteCancelledError):
        resolver.resolve_plans([_file_conflict(tmp_path)])


def test_closing_the_folder_dialog_cancels_the_paste(monkeypatch, tmp_path):
    import pytest
    from wafer.core.platform.file_operations import PasteCancelledError
    from wafer.qt.transfer import conflict_resolver as r

    monkeypatch.setattr(r.FolderConflictDialog, "ask", staticmethod(lambda *a, **k: (None, False)))
    resolver = r.ConflictResolver(op="copy", overwrite_mode="ask", parent=None, folder_message="")

    with pytest.raises(PasteCancelledError):
        resolver.resolve_plans([_folder_conflict(tmp_path, ["a.txt"])])


def test_closing_the_same_path_dialog_cancels_the_paste(monkeypatch, tmp_path):
    import pytest
    from wafer.core.platform.file_operations import PasteCancelledError
    from wafer.qt.transfer import conflict_resolver as r

    monkeypatch.setattr(r.FileConflictDialog, "ask", staticmethod(lambda *a, **k: (None, False)))
    src = tmp_path / "a.txt"
    src.write_text("x", encoding="utf-8")
    resolver = r.ConflictResolver(op="copy", overwrite_mode="ask", parent=None, folder_message="")

    with pytest.raises(PasteCancelledError):
        resolver.resolve_plans([_make_plan(0, src, src)])


def _count_scans(monkeypatch, r):
    scans = []
    real = r.scan_merge_conflicts

    def counting(src, dst, **kwargs):
        found = real(src, dst, **kwargs)
        scans.append((kwargs.get("limit"), len(found)))
        return found

    monkeypatch.setattr(r, "scan_merge_conflicts", counting)
    return scans


def test_folder_conflict_is_not_scanned_unless_asking(monkeypatch, tmp_path):
    from wafer.qt.transfer import conflict_resolver as r

    scans = _count_scans(monkeypatch, r)
    resolver = r.ConflictResolver(op="copy", overwrite_mode="overwrite", parent=None, folder_message="")

    decisions = resolver.resolve_plans([_folder_conflict(tmp_path, ["a.txt", "b.txt"])])

    assert decisions[0].mode == "merge"
    assert scans == []


def test_folder_conflict_count_stops_early_and_full_scan_runs_once(monkeypatch, tmp_path):
    from wafer.qt.transfer import conflict_resolver as r

    scans = _count_scans(monkeypatch, r)
    monkeypatch.setattr(r.FolderConflictDialog, "ask", staticmethod(lambda *a, **k: ("merge", False)))
    monkeypatch.setattr(r.FileConflictDialog, "ask", staticmethod(lambda *a, **k: ("overwrite", False)))
    resolver = r.ConflictResolver(op="copy", overwrite_mode="ask", parent=None, folder_message="")

    decisions = resolver.resolve_plans([_folder_conflict(tmp_path, ["a.txt", "b.txt", "c.txt"])])

    assert scans == [(2, 2), (None, 3)]
    assert sorted(decisions[0].merge_decisions) == ["a.txt", "b.txt", "c.txt"]


def test_small_folder_conflict_is_scanned_once(monkeypatch, tmp_path):
    from wafer.qt.transfer import conflict_resolver as r

    scans = _count_scans(monkeypatch, r)
    monkeypatch.setattr(r.FolderConflictDialog, "ask", staticmethod(lambda *a, **k: ("merge", False)))
    monkeypatch.setattr(r.FileConflictDialog, "ask", staticmethod(lambda *a, **k: ("overwrite", False)))
    resolver = r.ConflictResolver(op="copy", overwrite_mode="ask", parent=None, folder_message="")

    decisions = resolver.resolve_plans([_folder_conflict(tmp_path, ["a.txt"])])

    assert scans == [(2, 1)]
    assert list(decisions[0].merge_decisions) == ["a.txt"]
