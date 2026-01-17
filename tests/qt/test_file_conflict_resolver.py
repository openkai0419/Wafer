def test_conflict_session_apply_all_overwrite(monkeypatch):
    from source.qt import file_conflict_resolver as r

    calls = {"n": 0}

    def ask(*args, **kwargs):
        calls["n"] += 1
        return ("上書き", True)

    monkeypatch.setattr(r.FileConflictDialog, "ask", staticmethod(ask))

    s = r.make_session(op="copy", parent=None, item_count=3)
    m1 = s.resolve_exists(src_path="a", dst_path="b", name="x", src_bytes=None, default_mode="ask")
    m2 = s.resolve_exists(src_path="a", dst_path="c", name="x", src_bytes=None, default_mode="ask")

    assert m1 == "overwrite"
    assert m2 == "overwrite"
    assert calls["n"] == 1


def test_conflict_session_same_path_apply_all(monkeypatch, tmp_path):
    from source.qt import file_conflict_resolver as r

    calls = {"n": 0}

    def ask(*args, **kwargs):
        calls["n"] += 1
        return ("OK", True)

    monkeypatch.setattr(r.SingleFileConflictDialog, "ask", staticmethod(ask))

    p = tmp_path / "a.txt"
    p.write_text("x", encoding="utf-8")

    s = r.make_session(op="copy", parent=None, item_count=2)
    assert s.resolve_copy_conflict(src_path=str(p), dst_path=str(p), name="a.txt") is True
    assert s.resolve_copy_conflict(src_path=str(p), dst_path=str(p), name="a.txt") is True
    assert calls["n"] == 1
