import os
import time
import zipfile

from PIL import Image

from extensions.zip import archive
from extensions.zip.cache import ZipCache
from extensions.zip.collector import ZipCollectorPlugin
from wafer.utils.virtual_paths import build_virtual_path, child_path


def _create_zip(path, entries):
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)


def test_zip_cache_materializes_suffix_preserved(tmp_path):
    zip_path = tmp_path / "sample.zip"
    _create_zip(zip_path, {"folder/image.png": b"data"})
    logical = build_virtual_path(str(zip_path), "folder/image.png")
    cache = ZipCache(tmp_path / "cache")

    real_path = cache.materialize(logical)
    assert real_path.endswith(".png")
    assert open(real_path, "rb").read() == b"data"
    assert cache.materialize(logical) == real_path


def test_zip_collector_returns_child_rows_and_generic_aspect(tmp_path, monkeypatch):
    zip_path = tmp_path / "sample.zip"
    _create_zip(
        zip_path,
        {
            "wide.png": b"image-bytes",
            "notes/readme.txt": b"hello",
        },
    )
    cache = ZipCache(tmp_path / "cache")
    monkeypatch.setattr("extensions.zip.collector.zip_cache", cache)

    def fake_load_pil(path, size=None):
        if path.endswith(".png"):
            return Image.new("RGB", (400, 200))
        return None

    monkeypatch.setattr("extensions.zip.collector.image_loader_resolver.load_pil", fake_load_pil)

    results = ZipCollectorPlugin().process(str(zip_path), (0.0, zip_path.stat().st_size))
    child_results = [r for r in results if r.path]

    assert results[0].source == str(zip_path)
    assert results[0].status is True
    assert len(child_results) == 2
    by_child = {child_path(r.path): r for r in child_results}
    assert by_child["wide.png"].size == len(b"image-bytes")
    assert by_child["wide.png"].modified is not None
    assert by_child["wide.png"].aspect == 2.0
    assert by_child["wide.png"].meta_info is None
    assert by_child["notes/readme.txt"].aspect == 1.0
    assert by_child["notes/readme.txt"].meta_info is None

def test_zip_cache_sweep_removes_idle_entries(tmp_path):
    zip_path = tmp_path / "sample.zip"
    _create_zip(zip_path, {"a.png": b"x", "b.png": b"y"})
    cache = ZipCache(tmp_path / "cache")
    a_real = cache.materialize(build_virtual_path(str(zip_path), "a.png"))
    b_real = cache.materialize(build_virtual_path(str(zip_path), "b.png"))
    past = time.time() - 3600
    os.utime(a_real, (past, past))
    idle, lru = cache.sweep(idle_seconds=600, size_limit_bytes=10 * 1024 * 1024 * 1024)
    assert idle == 1
    assert lru == 0
    assert not os.path.exists(a_real)
    assert os.path.exists(b_real)


def test_zip_cache_sweep_lru_evicts_when_over_size_cap(tmp_path):
    zip_path = tmp_path / "sample.zip"
    _create_zip(zip_path, {"a.png": b"x" * 1000, "b.png": b"y" * 1000, "c.png": b"z" * 1000})
    cache = ZipCache(tmp_path / "cache")
    a_real = cache.materialize(build_virtual_path(str(zip_path), "a.png"))
    time.sleep(0.01)
    b_real = cache.materialize(build_virtual_path(str(zip_path), "b.png"))
    time.sleep(0.01)
    c_real = cache.materialize(build_virtual_path(str(zip_path), "c.png"))
    idle, lru = cache.sweep(idle_seconds=3600, size_limit_bytes=2500)
    assert idle == 0
    assert lru >= 1
    assert not os.path.exists(a_real)
    assert os.path.exists(c_real)


def test_open_zip_fallbacks_from_cp932_to_utf8(monkeypatch):
    calls = []
    expected = object()

    def fake_zip_file(_path, metadata_encoding=None):
        calls.append(metadata_encoding)
        if metadata_encoding == "cp932":
            raise UnicodeDecodeError("cp932", b"\xec", 0, 1, "illegal multibyte sequence")
        return expected

    monkeypatch.setattr("extensions.zip.archive.settings.METADATA_ENCODING", "cp932")
    monkeypatch.setattr("extensions.zip.archive.zipfile.ZipFile", fake_zip_file)

    actual = archive.open_zip("dummy.zip")

    assert actual is expected
    assert calls == ["cp932", "utf-8"]


def test_zip_collector_returns_failure_on_unicode_decode_error(monkeypatch):
    def raise_unicode(_path):
        raise UnicodeDecodeError("cp932", b"\xec", 0, 1, "illegal multibyte sequence")

    monkeypatch.setattr("extensions.zip.collector.list_entries", raise_unicode)

    results = ZipCollectorPlugin().process("broken.zip", (0.0, 0))

    assert len(results) == 1
    assert results[0].source == "broken.zip"
    assert results[0].status is False
