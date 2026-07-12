import pytest

from wafer.builtins.updater.versioning import is_newer_version, normalize_version, parse_version


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0.6.18", "0.6.18"),
        ("v0.6.18", "0.6.18"),
        ("0.6.18.dev5+gabc", "0.6.18"),
        ("0.6.18-rc1", "0.6.18"),
        ("bad", "bad"),
    ],
)
def test_normalize_version(value, expected):
    assert normalize_version(value) == expected


@pytest.mark.parametrize(
    ("current", "latest", "expected"),
    [
        ("0.6.18", "0.6.18", False),
        ("0.6.18.dev5+gabc", "0.6.18", False),
        ("0.6.18", "0.6.19", True),
        ("0.6.18", "0.7.0", True),
        ("0.6.18", "1.0.0", True),
        ("0.6.19", "0.6.18", False),
        ("0.6.18", "0.6.19-rc1", True),
        ("0.6.19rc1", "0.6.19", False),
        ("bad", "0.6.19", False),
        ("0.6.18", "bad", False),
    ],
)
def test_is_newer_version(current, latest, expected):
    assert is_newer_version(current, latest) is expected


def test_include_prerelease_flag_does_not_change_tag_only_comparison():
    assert is_newer_version("0.6.18", "0.6.19-rc1", include_prerelease=False) is True
    assert is_newer_version("0.6.18", "0.6.19-rc1", include_prerelease=True) is True


def test_parse_invalid_returns_none():
    assert parse_version("") is None
    assert parse_version("0.6") is None
