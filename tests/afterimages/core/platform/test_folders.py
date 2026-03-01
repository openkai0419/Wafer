from afterimages.core.platform.folders import first_entry, first_file


def test_first_file_returns_none_for_missing(tmp_path):
    p = tmp_path / "missing"
    assert first_file(str(p)) is None


def test_first_file_returns_file(tmp_path):
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("x", encoding="utf-8")
    b.write_text("y", encoding="utf-8")
    out = first_file(str(tmp_path))
    assert out in {str(a), str(b)}


def test_first_file_returns_none_for_empty(tmp_path):
    out = first_file(str(tmp_path))
    assert out is None


def test_first_entry_returns_file_or_folder(tmp_path):
    sub = tmp_path / "d"
    sub.mkdir()
    a = tmp_path / "a.txt"
    a.write_text("x", encoding="utf-8")
    out = first_entry(str(tmp_path))
    assert out in {str(a), str(sub)}
