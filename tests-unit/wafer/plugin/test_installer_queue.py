import pytest

from wafer.core.common.profile import current_profile
from wafer.core.logs import AppLogger
from wafer.core.platform.process_lock import file_lock
from wafer.plugin import installer_queue


@pytest.fixture
def ext_dir(tmp_path):
    return str(tmp_path)


def _lock_path(ext_dir):
    return f"{installer_queue._queue_path(ext_dir)}.lock"


def _probe_lock_while_reading(monkeypatch, ext_dir):
    original = installer_queue._read
    probed = []

    def probing(extensions_dir):
        with pytest.raises(TimeoutError):
            with file_lock(_lock_path(ext_dir), timeout=0.05):
                pass
        probed.append(True)
        return original(extensions_dir)

    monkeypatch.setattr(installer_queue, "_read", probing)
    return probed


def test_enqueue_holds_the_process_lock(ext_dir, monkeypatch):
    probed = _probe_lock_while_reading(monkeypatch, ext_dir)
    installer_queue.enqueue(ext_dir, "ext_a", "/ext/a")
    assert probed == [True]
    monkeypatch.undo()
    assert installer_queue.queued_names(ext_dir) == {"ext_a"}


def test_remove_entries_holds_the_process_lock(ext_dir, monkeypatch):
    installer_queue.enqueue(ext_dir, "ext_a", "/ext/a")
    installer_queue.enqueue(ext_dir, "ext_b", "/ext/b")
    probed = _probe_lock_while_reading(monkeypatch, ext_dir)
    installer_queue.remove_entries(ext_dir, ["ext_a"])
    assert probed == [True]
    monkeypatch.undo()
    assert installer_queue.queued_names(ext_dir) == {"ext_b"}


def test_dequeue_last_entry_clears_the_queue(ext_dir):
    installer_queue.enqueue(ext_dir, "ext_a", "/ext/a")
    assert installer_queue.dequeue(ext_dir, "ext_a")
    assert not installer_queue.has_pending_queue(ext_dir)
    assert not installer_queue.dequeue(ext_dir, "ext_a")


def test_enqueue_adds_entry_without_profile(tmp_path):
    installer_queue.enqueue(str(tmp_path), "ext_a", str(tmp_path / "ext_a"))
    assert installer_queue.queued_names(str(tmp_path)) == {"ext_a"}


def test_enqueue_is_refused_in_profile(tmp_path, monkeypatch):
    warnings = []
    monkeypatch.setattr("sys.argv", ["main.py", "--profile", "debug-a"])
    monkeypatch.setattr(AppLogger, "warning", staticmethod(lambda msg, *a, **k: warnings.append(msg)))
    current_profile.cache_clear()
    try:
        installer_queue.enqueue(str(tmp_path), "ext_a", str(tmp_path / "ext_a"))
    finally:
        current_profile.cache_clear()
    assert installer_queue.queued_names(str(tmp_path)) == set()
    assert warnings == ["Extensions cannot be installed from a debug profile"]
