import json
import os

import pytest

from wafer.plugin import install_status


@pytest.fixture
def tmp_status(tmp_path, monkeypatch):
    target = tmp_path / "install_status.json"
    cancel_target = tmp_path / "install_cancel.flag"
    monkeypatch.setattr(install_status, "status_path", lambda: str(target))
    monkeypatch.setattr(install_status, "cancel_flag_path", lambda: str(cancel_target))
    yield target


def test_cancel_request_round_trip(tmp_status):
    assert install_status.is_cancel_requested() is False
    install_status.request_cancel()
    assert install_status.is_cancel_requested() is True
    install_status.clear_cancel()
    assert install_status.is_cancel_requested() is False


def test_writer_initial_flush_creates_file(tmp_status):
    install_status.InstallStatusWriter(total=2)
    assert tmp_status.is_file()
    data = json.loads(tmp_status.read_text(encoding="utf-8"))
    assert data["phase"] == "pending"
    assert data["current"]["total"] == 2


def test_begin_item_updates_phase_and_name(tmp_status):
    w = install_status.InstallStatusWriter(total=2)
    w.begin_item(1, "foo", "pip")
    data = install_status.read_status()
    assert data["phase"] == "pip"
    assert data["current"]["name"] == "foo"
    assert data["current"]["index"] == 1


def test_log_tail_capped(tmp_status):
    w = install_status.InstallStatusWriter(total=1)
    for i in range(install_status._LOG_TAIL_MAX + 50):
        w.append_log(f"line-{i}")
    data = install_status.read_status()
    tail = data["log_tail"]
    assert len(tail) == install_status._LOG_TAIL_MAX
    assert tail[-1] == f"line-{install_status._LOG_TAIL_MAX + 49}"


def test_finish_with_error_sets_phase_and_message(tmp_status):
    w = install_status.InstallStatusWriter(total=1)
    w.finish(error="boom")
    data = install_status.read_status()
    assert data["phase"] == "error"
    assert data["message"] == "boom"


def test_finish_without_error_marks_done(tmp_status):
    w = install_status.InstallStatusWriter(total=1)
    w.finish()
    assert install_status.read_status()["phase"] == "done"


def test_clear_status_removes_file(tmp_status):
    install_status.InstallStatusWriter(total=1)
    assert os.path.isfile(tmp_status)
    install_status.clear_status()
    assert not os.path.isfile(tmp_status)


def test_clear_status_retries_on_transient_lock(tmp_status, monkeypatch):
    install_status.InstallStatusWriter(total=1)
    calls = {"n": 0}
    real_remove = os.remove

    def flaky_remove(path):
        calls["n"] += 1
        if calls["n"] < 3:
            raise OSError("locked")
        real_remove(path)

    monkeypatch.setattr(install_status.os, "remove", flaky_remove)
    monkeypatch.setattr(install_status.time, "sleep", lambda _s: None)
    install_status.clear_status()
    assert not os.path.isfile(tmp_status)
    assert calls["n"] == 3


def test_clear_status_warns_when_all_retries_fail(tmp_status, monkeypatch):
    install_status.InstallStatusWriter(total=1)

    def always_locked(_path):
        raise OSError("locked")

    warnings = []
    monkeypatch.setattr(install_status.os, "remove", always_locked)
    monkeypatch.setattr(install_status.time, "sleep", lambda _s: None)
    monkeypatch.setattr(install_status.AppLogger, "warning", lambda *a, **kw: warnings.append(a))
    install_status.clear_status()
    assert len(warnings) == 1


def test_read_status_returns_none_when_missing(tmp_status):
    assert install_status.read_status() is None
