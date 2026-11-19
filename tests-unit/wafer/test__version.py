import subprocess

import pytest

from wafer import _version


@pytest.fixture(autouse=True)
def app_root(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(_version, "get_app_root_dir", lambda: tmp_path)
    return tmp_path


def _fake_describe(result):
    def check_output(cmd, **kwargs):
        assert kwargs["timeout"] == _version.GIT_DESCRIBE_TIMEOUT
        if isinstance(result, BaseException):
            raise result
        return result

    return check_output


@pytest.fixture
def warnings(monkeypatch):
    seen = []
    monkeypatch.setattr(_version.AppLogger, "warning", lambda text, **kwargs: seen.append(text))
    return seen


@pytest.mark.parametrize(
    "result",
    [
        subprocess.TimeoutExpired("git", 5),
        subprocess.CalledProcessError(128, "git"),
        FileNotFoundError("git"),
        "not-a-version\n",
    ],
)
def test_a_checkout_whose_version_git_cannot_tell_is_unknown_and_warns(monkeypatch, warnings, result):
    monkeypatch.setattr(_version.subprocess, "check_output", _fake_describe(result))
    assert _version.get_version() == _version.UNKNOWN_VERSION
    assert len(warnings) == 1


def test_a_release_tag_is_the_version(monkeypatch):
    monkeypatch.setattr(_version.subprocess, "check_output", _fake_describe("v1.2.3\n"))
    assert _version.get_version() == "1.2.3"


def test_commits_after_a_tag_become_a_dev_version(monkeypatch):
    monkeypatch.setattr(_version.subprocess, "check_output", _fake_describe("v1.2.3-4-gabc1234\n"))
    assert _version.get_version() == "1.2.3.dev4+gabc1234"


def test_git_runs_in_the_app_root_not_the_working_folder(monkeypatch, app_root):
    seen = {}

    def check_output(cmd, **kwargs):
        seen["cwd"] = kwargs.get("cwd")
        return "v1.2.3\n"

    monkeypatch.setattr(_version.subprocess, "check_output", check_output)
    assert _version.get_version() == "1.2.3"
    assert seen["cwd"] == app_root


def test_an_app_root_without_git_uses_the_bundled_version_without_running_git(monkeypatch, app_root, warnings):
    (app_root / ".git").rmdir()

    def check_output(cmd, **kwargs):
        raise AssertionError("git must not run")

    monkeypatch.setattr(_version.subprocess, "check_output", check_output)
    assert _version.get_version() == _version.FALLBACK_VERSION
    assert warnings == []
