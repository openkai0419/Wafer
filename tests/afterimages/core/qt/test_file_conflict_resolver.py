from pathlib import Path


def _make_plan(index, src, dst, is_dir=False, conflict=True, action="copy", suggested_dst=None):
    from afterimages.core.platform.file_operations import PastePlanItem

    return PastePlanItem(
        index=index, src=Path(src), is_dir=is_dir, action=action,
        dst_default=Path(dst), conflict=conflict, suggested_dst=suggested_dst,
    )


def test_file_apply_all_overwrite(monkeypatch, tmp_path):
    from afterimages.core.qt import file_conflict_resolver as r

    calls = {"n": 0}

    def ask(*args, **kwargs):
        calls["n"] += 1
        return ("上書き", True)

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
    from afterimages.core.qt import file_conflict_resolver as r

    calls = {"n": 0}

    def ask(*args, **kwargs):
        calls["n"] += 1
        return ("スキップ", True)

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
    from afterimages.core.platform.file_operations import PasteCancelledError
    from afterimages.core.qt import file_conflict_resolver as r

    def ask(*args, **kwargs):
        return ("キャンセル", False)

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
    from afterimages.core.qt import file_conflict_resolver as r

    folder_calls = {"n": 0}
    file_calls = {"n": 0}

    def folder_ask(*args, **kwargs):
        folder_calls["n"] += 1
        return ("マージ", False)

    def file_ask(*args, **kwargs):
        file_calls["n"] += 1
        return ("上書き", True)

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
    from afterimages.core.qt import file_conflict_resolver as r

    calls = {"n": 0}

    def ask(*args, **kwargs):
        calls["n"] += 1
        return ("スキップ", True)

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
    from afterimages.core.qt import file_conflict_resolver as r

    calls = {"n": 0}

    def ask(*args, **kwargs):
        calls["n"] += 1
        return ("別名で保存", True)

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
    from afterimages.core.platform.file_operations import PasteCancelledError
    from afterimages.core.qt import file_conflict_resolver as r

    def ask(*args, **kwargs):
        return ("キャンセル", False)

    monkeypatch.setattr(r.FileConflictDialog, "ask", staticmethod(ask))

    p = tmp_path / "a.txt"
    p.write_text("x", encoding="utf-8")

    plans = [_make_plan(0, p, p, conflict=False)]
    resolver = r.ConflictResolver(op="copy", overwrite_mode="ask", parent=None, folder_message="")

    with pytest.raises(PasteCancelledError):
        resolver.resolve_plans(plans)


def test_same_path_overwrite_mode_forces_skip(tmp_path):
    from afterimages.core.qt import file_conflict_resolver as r

    p = tmp_path / "a.txt"
    p.write_text("x", encoding="utf-8")

    plans = [_make_plan(0, p, p, conflict=False)]
    resolver = r.ConflictResolver(op="copy", overwrite_mode="overwrite", parent=None, folder_message="")
    decisions = resolver.resolve_plans(plans)

    assert decisions[0].mode == "skip"


def test_same_path_rename_mode_forces_rename(tmp_path):
    from afterimages.core.qt import file_conflict_resolver as r

    p = tmp_path / "a.txt"
    p.write_text("x", encoding="utf-8")

    plans = [_make_plan(0, p, p, conflict=False)]
    resolver = r.ConflictResolver(op="copy", overwrite_mode="rename", parent=None, folder_message="")
    decisions = resolver.resolve_plans(plans)

    assert decisions[0].mode == "rename"


def test_overwrite_mode_forces_decision(tmp_path):
    from afterimages.core.qt import file_conflict_resolver as r

    src = tmp_path / "a.txt"
    src.write_text("x", encoding="utf-8")
    dst_dir = tmp_path / "dst"
    dst_dir.mkdir()
    (dst_dir / "a.txt").write_text("old", encoding="utf-8")

    plans = [_make_plan(0, src, dst_dir / "a.txt")]
    resolver = r.ConflictResolver(op="copy", overwrite_mode="overwrite", parent=None, folder_message="")
    decisions = resolver.resolve_plans(plans)

    assert decisions[0].mode == "overwrite"


def test_no_conflict_plans_get_overwrite_decision(tmp_path):
    from afterimages.core.qt import file_conflict_resolver as r

    src = tmp_path / "a.txt"
    src.write_text("x", encoding="utf-8")
    dst_dir = tmp_path / "dst"
    dst_dir.mkdir()

    plans = [_make_plan(0, src, dst_dir / "a.txt", conflict=False)]
    resolver = r.ConflictResolver(op="copy", overwrite_mode="ask", parent=None, folder_message="")
    decisions = resolver.resolve_plans(plans)

    assert decisions[0].mode == "overwrite"


def test_resolve_paste_plans_with_ui_empty():
    from afterimages.core.qt.file_conflict_resolver import resolve_paste_plans_with_ui

    result = resolve_paste_plans_with_ui(plans=[], overwrite_mode="ask", parent=None)
    assert result == {}
