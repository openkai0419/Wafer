import os
import subprocess
import sys

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


@pytest.mark.parametrize(
    "result",
    [
        subprocess.TimeoutExpired("git", 5),
        subprocess.CalledProcessError(128, "git"),
        FileNotFoundError("git"),
        "not-a-version\n",
    ],
)
def test_a_checkout_whose_version_git_cannot_tell_is_unknown_with_a_reason(monkeypatch, result):
    monkeypatch.setattr(_version.subprocess, "check_output", _fake_describe(result))
    version, problem = _version.read_version()
    assert version == _version.UNKNOWN_VERSION
    assert problem


def test_a_release_tag_is_the_version(monkeypatch):
    monkeypatch.setattr(_version.subprocess, "check_output", _fake_describe("v1.2.3\n"))
    assert _version.read_version() == ("1.2.3", "")


def test_commits_after_a_tag_become_a_dev_version(monkeypatch):
    monkeypatch.setattr(_version.subprocess, "check_output", _fake_describe("v1.2.3-4-gabc1234\n"))
    assert _version.read_version() == ("1.2.3.dev4+gabc1234", "")


def test_git_runs_in_the_app_root_not_the_working_folder(monkeypatch, app_root):
    seen = {}

    def check_output(cmd, **kwargs):
        seen["cwd"] = kwargs.get("cwd")
        return "v1.2.3\n"

    monkeypatch.setattr(_version.subprocess, "check_output", check_output)
    assert _version.read_version() == ("1.2.3", "")
    assert seen["cwd"] == app_root


def test_an_app_root_without_git_uses_the_bundled_version_without_running_git(monkeypatch, app_root):
    (app_root / ".git").rmdir()

    def check_output(cmd, **kwargs):
        raise AssertionError("git must not run")

    monkeypatch.setattr(_version.subprocess, "check_output", check_output)
    assert _version.read_version() == (_version.FALLBACK_VERSION, "")


@pytest.fixture
def warnings(monkeypatch):
    from wafer.core.logs import AppLogger

    seen = []
    monkeypatch.setattr(AppLogger, "warning", lambda text, **kwargs: seen.append(text))
    return seen


def test_an_unknown_version_is_warned_with_its_reason(monkeypatch, warnings):
    monkeypatch.setattr(_version, "VERSION_PROBLEM", "git describe took more than 5s")
    _version.warn_if_version_unknown()
    assert len(warnings) == 1
    assert "git describe took more than 5s" in warnings[0]


def test_a_known_version_is_not_warned(monkeypatch, warnings):
    monkeypatch.setattr(_version, "VERSION_PROBLEM", "")
    _version.warn_if_version_unknown()
    assert warnings == []


def test_importing_the_version_does_not_start_logging():
    code = "import sys, wafer._version; print('wafer.core.logs' in sys.modules)"
    out = subprocess.check_output([sys.executable, "-c", code], cwd=os.path.dirname(os.path.dirname(_version.__file__)), text=True)
    assert out.strip() == "False"
