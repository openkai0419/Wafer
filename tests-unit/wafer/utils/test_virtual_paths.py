from wafer.constants import VIRTUAL_PATH_SEPARATOR
from wafer.utils.virtual_paths import (
    build_virtual_path,
    child_path,
    display_name,
    escape_member_path,
    is_virtual_path,
    leaf_extension,
    owner_extension,
    physical_paths,
    source_path,
    unescape_member_path,
)


def test_virtual_path_build_parse_and_extensions():
    path = build_virtual_path("C:/data/archive.zip", "folder/image.png")
    assert VIRTUAL_PATH_SEPARATOR == "::"
    assert path == "C:/data/archive.zip::folder/image.png"
    assert is_virtual_path(path)
    assert source_path(path) == "C:/data/archive.zip"
    assert child_path(path) == "folder/image.png"
    assert owner_extension(path) == ".zip"
    assert leaf_extension(path) == ".png"
    assert display_name(path) == "image.png"


def test_virtual_path_escapes_separator_and_percent():
    member = "a%b::c.png"
    escaped = escape_member_path(member)
    assert escaped == "a%25b%3A%3Ac.png"
    assert unescape_member_path(escaped) == member
    path = build_virtual_path("C:/data/archive.zip", member)
    assert child_path(path) == member


def test_physical_paths_dedupes_virtual_sources():
    paths = [
        build_virtual_path("C:/data/archive.zip", "a.png"),
        build_virtual_path("C:/data/archive.zip", "b.png"),
        "C:/data/plain.png",
    ]
    assert physical_paths(paths) == ["C:/data/archive.zip", "C:/data/plain.png"]


def test_is_virtual_path_accepts_separator_syntax_without_owner_registration():
    assert is_virtual_path("/tmp/a.txt::b.png") is True
    assert is_virtual_path("/tmp/foo::bar") is True


def test_split_virtual_path_returns_source_and_member_without_owner_registration():
    from wafer.utils.virtual_paths import split_virtual_path

    assert split_virtual_path("/tmp/a.txt::b.png") == ("/tmp/a.txt", "b.png")
