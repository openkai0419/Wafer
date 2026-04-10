from wafer.core.platform.folders import first_entry, first_file, make_directory


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


def test_make_directory_creates_dir(tmp_path):
    target = str(tmp_path / "new_dir")
    result = make_directory(target)
    assert result == target
    assert (tmp_path / "new_dir").is_dir()


def test_make_directory_nested(tmp_path):
    target = str(tmp_path / "a" / "b" / "c")
    result = make_directory(target)
    assert result == target
    assert (tmp_path / "a" / "b" / "c").is_dir()


def test_make_directory_existing_is_ok(tmp_path):
    target = str(tmp_path / "existing")
    (tmp_path / "existing").mkdir()
    result = make_directory(target)
    assert result == target


def test_open_file_calls_desktop_services(monkeypatch):
    from wafer.core.platform import folders
    from PySide6 import QtCore, QtGui

    opened: list[str] = []
    orig_open = QtGui.QDesktopServices.openUrl

    monkeypatch.setattr(QtGui.QDesktopServices, "openUrl", staticmethod(lambda url: opened.append(url.toLocalFile())))
    folders.open_file("/some/path")
    assert len(opened) == 1
    assert opened[0] == "/some/path"


def test_open_file_empty_path_is_noop():
    from wafer.core.platform import folders

    folders.open_file("")
