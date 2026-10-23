import subprocess

from wafer import _version


def _fake_describe(result):
    def check_output(cmd, **kwargs):
        assert kwargs["timeout"] == _version.GIT_DESCRIBE_TIMEOUT
        if isinstance(result, BaseException):
            raise result
        return result

    return check_output


def test_a_hanging_git_falls_back_to_the_bundled_version(monkeypatch):
    monkeypatch.setattr(_version.subprocess, "check_output", _fake_describe(subprocess.TimeoutExpired("git", 5)))
    assert _version.get_version() == _version.FALLBACK_VERSION


def test_a_release_tag_is_the_version(monkeypatch):
    monkeypatch.setattr(_version.subprocess, "check_output", _fake_describe("v1.2.3\n"))
    assert _version.get_version() == "1.2.3"


def test_commits_after_a_tag_become_a_dev_version(monkeypatch):
    monkeypatch.setattr(_version.subprocess, "check_output", _fake_describe("v1.2.3-4-gabc1234\n"))
    assert _version.get_version() == "1.2.3.dev4+gabc1234"
