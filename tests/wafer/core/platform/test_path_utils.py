from __future__ import annotations

from pathlib import Path


def test_check_copy_conflict_same_path(tmp_path):
    from wafer.core.platform.path_utils import check_copy_conflict

    p = tmp_path / "x.txt"
    p.write_text("x", encoding="utf-8")
    assert check_copy_conflict(p, p) == "same_path"


def test_check_copy_conflict_none():
    from wafer.core.platform.path_utils import check_copy_conflict

    assert check_copy_conflict(None, "x") is None
    assert check_copy_conflict("x", None) is None
    assert check_copy_conflict(None, None) is None


def test_check_copy_conflict_subpath(tmp_path):
    from wafer.core.platform.path_utils import check_copy_conflict

    parent = tmp_path / "parent"
    parent.mkdir()
    child = parent / "child"
    assert check_copy_conflict(str(parent), str(child)) == "subpath"


def test_check_copy_conflict_no_conflict(tmp_path):
    from wafer.core.platform.path_utils import check_copy_conflict

    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("x", encoding="utf-8")
    assert check_copy_conflict(str(a), str(b)) is None


def test_sanitize_filename_windows_invalid_chars():
    from wafer.core.platform.path_utils import sanitize_filename

    assert sanitize_filename("a<b>c.txt") == "a_b_c.txt"


def test_sanitize_filename_fallback():
    from wafer.core.platform.path_utils import sanitize_filename

    assert sanitize_filename(None) == "download"
    assert sanitize_filename("") == "download"
    assert sanitize_filename("...") == "download"


def test_sanitize_filename_reserved_name():
    from wafer.core.platform.path_utils import sanitize_filename

    assert sanitize_filename("CON") == "_CON"
    assert sanitize_filename("con.txt") == "_con.txt"
    assert sanitize_filename("NUL.tar.gz") == "_NUL.tar.gz"
    assert sanitize_filename("normal.txt") == "normal.txt"


def test_unique_path_generates_increment(tmp_path):
    from wafer.core.platform.path_utils import unique_path

    d = tmp_path
    (d / "a.txt").write_text("x", encoding="utf-8")
    p = Path(unique_path(d, "a.txt"))
    assert p.name.startswith("a (") and p.suffix == ".txt"


def test_unique_path_no_conflict(tmp_path):
    from wafer.core.platform.path_utils import unique_path

    p = Path(unique_path(tmp_path, "new.txt"))
    assert p.name == "new.txt"


def test_is_http_url():
    from wafer.core.platform.path_utils import is_http_url

    assert is_http_url("http://example.com")
    assert is_http_url("https://example.com")
    assert is_http_url("  HTTPS://X  ")
    assert not is_http_url("ftp://example.com")
    assert not is_http_url("")
    assert not is_http_url("not a url")


def test_validate_filename_valid():
    from wafer.core.platform.path_utils import validate_filename

    assert validate_filename("hello.txt") == []
    assert validate_filename("my file (2).jpg") == []
    assert validate_filename("a") == []


def test_validate_filename_empty():
    from wafer.core.platform.path_utils import validate_filename

    assert "empty" in validate_filename("")
    assert "empty" in validate_filename("   ")


def test_validate_filename_invalid_chars():
    from wafer.core.platform.path_utils import validate_filename

    issues = validate_filename("a<b>.txt")
    assert "invalid_chars" in issues


def test_validate_filename_reserved_name():
    from wafer.core.platform.path_utils import validate_filename

    assert "reserved_name" in validate_filename("CON")
    assert "reserved_name" in validate_filename("con.txt")
    assert "reserved_name" in validate_filename("NUL.tar.gz")
    assert "reserved_name" in validate_filename("COM1")
    assert "reserved_name" in validate_filename("LPT9.log")
    assert "reserved_name" not in validate_filename("CONSOLE.txt")


def test_validate_filename_trailing_dot_or_space():
    from wafer.core.platform.path_utils import validate_filename

    assert "trailing_dot_or_space" in validate_filename("hello.")
    assert "trailing_dot_or_space" in validate_filename("hello ")
    assert "trailing_dot_or_space" not in validate_filename("hello.txt")


def test_validate_filename_too_long():
    from wafer.core.platform.path_utils import validate_filename

    assert "too_long" in validate_filename("a" * 256)
    assert "too_long" not in validate_filename("a" * 100)
    assert "too_long" not in validate_filename("あ" * 255)
    assert "too_long" in validate_filename("あ" * 256)


def test_get_os_new_folder_name():
    from wafer.core.platform.path_utils import get_os_new_folder_name

    name = get_os_new_folder_name()
    assert isinstance(name, str)
    assert len(name) > 0
