import os

import pytest

from wafer.core.common import atomic_file
from wafer.core.common.atomic_file import write_text_atomic


def test_writes_the_file_and_creates_its_folder(tmp_path):
    path = tmp_path / "new" / "a.txt"
    write_text_atomic(path, "hello")
    assert path.read_text(encoding="utf-8") == "hello"
    assert os.listdir(path.parent) == ["a.txt"]


def test_retries_replace_while_the_target_is_held(tmp_path, monkeypatch):
    path = tmp_path / "a.txt"
    path.write_text("old", encoding="utf-8")
    real_replace = os.replace
    calls = []

    def flaky_replace(src, dst):
        calls.append(src)
        if len(calls) < 3:
            raise PermissionError("in use")
        real_replace(src, dst)

    monkeypatch.setattr(atomic_file.os, "replace", flaky_replace)
    write_text_atomic(path, "new")

    assert len(calls) == 3
    assert path.read_text(encoding="utf-8") == "new"
    assert os.listdir(tmp_path) == ["a.txt"]


def test_gives_up_on_replace_and_keeps_the_old_file(tmp_path, monkeypatch):
    path = tmp_path / "a.txt"
    path.write_text("old", encoding="utf-8")

    def held(src, dst):
        raise PermissionError("in use")

    monkeypatch.setattr(atomic_file.os, "replace", held)
    monkeypatch.setattr(atomic_file, "_REPLACE_TIMEOUT", 0.0)
    with pytest.raises(PermissionError):
        write_text_atomic(path, "new")

    assert path.read_text(encoding="utf-8") == "old"
    assert os.listdir(tmp_path) == ["a.txt"]
