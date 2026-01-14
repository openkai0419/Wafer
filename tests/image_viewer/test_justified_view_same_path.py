import os

from source.os.drop import check_copy_conflict


def test_check_copy_conflict_same_path(tmp_path):
    p = tmp_path / "A" / "b.txt"
    p.parent.mkdir(parents=True)
    p.write_text("x", encoding="utf-8")

    a = str(p)
    b = os.path.normpath(str(p)).replace("\\", "/")

    assert check_copy_conflict(a, b) == "same_path"


def test_check_copy_conflict_none():
    assert check_copy_conflict(None, "x") is None
    assert check_copy_conflict("x", None) is None
    assert check_copy_conflict(None, None) is None


def test_check_copy_conflict_subpath(tmp_path):
    parent = tmp_path / "parent"
    parent.mkdir()
    child = parent / "child"
    assert check_copy_conflict(str(parent), str(child)) == "subpath"


def test_check_copy_conflict_no_conflict(tmp_path):
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("x", encoding="utf-8")
    assert check_copy_conflict(str(a), str(b)) is None
