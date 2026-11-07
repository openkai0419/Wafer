import os
from configparser import ConfigParser

import pytest

from wafer.core.common.ini_io import write_ini


def _parser(value: str) -> ConfigParser:
    parser = ConfigParser()
    parser["section"] = {"key": value}
    return parser


def _read(path) -> str:
    parser = ConfigParser()
    parser.read(path, encoding="utf-8")
    return parser["section"]["key"]


def test_writes_the_file_and_creates_its_folder(tmp_path):
    path = tmp_path / "new" / "settings.ini"
    write_ini(str(path), _parser("1"))
    assert _read(path) == "1"
    assert os.listdir(path.parent) == ["settings.ini"]


def test_a_failed_write_keeps_the_old_file_and_leaves_no_temp(tmp_path, monkeypatch):
    path = tmp_path / "settings.ini"
    write_ini(str(path), _parser("old"))

    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr("wafer.core.common.ini_io.os.fsync", fail)
    with pytest.raises(OSError):
        write_ini(str(path), _parser("new"))

    assert _read(path) == "old"
    assert os.listdir(tmp_path) == ["settings.ini"]
