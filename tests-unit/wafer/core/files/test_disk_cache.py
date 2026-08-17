from __future__ import annotations

import time

from wafer.core.files.disk_cache import DiskCache


def _writer(content: bytes):
    def produce(out_path: str) -> bool:
        with open(out_path, "wb") as f:
            f.write(content)
        return True

    return produce


def test_get_or_create_writes_and_reuses(tmp_path):
    cache = DiskCache(tmp_path, size_limit_bytes=1024)
    calls = {"n": 0}

    def produce(out_path: str) -> bool:
        calls["n"] += 1
        with open(out_path, "wb") as f:
            f.write(b"data")
        return True

    p1 = cache.get_or_create("k", produce, ".bin")
    p2 = cache.get_or_create("k", produce, ".bin")
    assert p1 == p2
    assert p1 is not None and p1.read_bytes() == b"data"
    assert calls["n"] == 1


def test_failed_producer_returns_none_and_no_file(tmp_path):
    cache = DiskCache(tmp_path, size_limit_bytes=1024)
    result = cache.get_or_create("k", lambda _p: False, ".bin")
    assert result is None
    assert not cache.path_for("k", ".bin").exists()
    assert not any(tmp_path.rglob("*.tmp"))


def test_sweep_evicts_over_size_cap(tmp_path):
    cache = DiskCache(tmp_path, size_limit_bytes=250)
    for i in range(5):
        cache.get_or_create(f"k{i}", _writer(b"x" * 100), ".bin")
        time.sleep(0.01)
    removed = cache.sweep()
    assert removed >= 1
    total = sum(p.stat().st_size for p in tmp_path.rglob("*.bin"))
    assert total <= 250


def test_sweep_removes_idle_entries(tmp_path):
    cache = DiskCache(tmp_path, size_limit_bytes=10 * 1024, idle_seconds=0)
    path = cache.get_or_create("k", _writer(b"data"), ".bin")
    assert path is not None
    time.sleep(0.01)
    removed = cache.sweep()
    assert removed == 1
    assert not path.exists()
