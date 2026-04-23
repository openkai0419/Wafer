import os

import pytest

from wafer.plugin import failed_installs


@pytest.fixture
def ext_dir(tmp_path):
    d = tmp_path / "extensions"
    d.mkdir()
    return str(d)


def test_empty_returns_empty_set(ext_dir):
    assert failed_installs.failed_names(ext_dir) == set()
    assert failed_installs.failure_info(ext_dir, "anything") is None


def test_mark_and_read(ext_dir):
    failed_installs.mark_failed(ext_dir, "ext_a", "pip failed")
    assert failed_installs.failed_names(ext_dir) == {"ext_a"}
    info = failed_installs.failure_info(ext_dir, "ext_a")
    assert info["reason"] == "pip failed"
    assert "failed_at" in info


def test_mark_overwrites(ext_dir):
    failed_installs.mark_failed(ext_dir, "ext_a", "first")
    failed_installs.mark_failed(ext_dir, "ext_a", "second")
    assert failed_installs.failure_info(ext_dir, "ext_a")["reason"] == "second"


def test_clear_removes_specified(ext_dir):
    failed_installs.mark_failed(ext_dir, "a", "x")
    failed_installs.mark_failed(ext_dir, "b", "y")
    failed_installs.clear(ext_dir, ["a"])
    assert failed_installs.failed_names(ext_dir) == {"b"}


def test_clear_all_removes_file(ext_dir):
    failed_installs.mark_failed(ext_dir, "a", "x")
    path = os.path.join(ext_dir, ".installer_queue", "failed.json")
    assert os.path.isfile(path)
    failed_installs.clear(ext_dir, ["a"])
    assert not os.path.isfile(path)


def test_clear_unknown_is_noop(ext_dir):
    failed_installs.mark_failed(ext_dir, "a", "x")
    failed_installs.clear(ext_dir, ["nonexistent"])
    assert failed_installs.failed_names(ext_dir) == {"a"}


def test_clear_empty_iterable_is_noop(ext_dir):
    failed_installs.mark_failed(ext_dir, "a", "x")
    failed_installs.clear(ext_dir, [])
    assert failed_installs.failed_names(ext_dir) == {"a"}


def test_corrupted_file_returns_empty(ext_dir):
    path = os.path.join(ext_dir, ".installer_queue", "failed.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("not json{{{")
    assert failed_installs.failed_names(ext_dir) == set()
