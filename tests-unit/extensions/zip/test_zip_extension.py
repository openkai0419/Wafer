import os
import struct
import time
import zipfile
import zlib

import pytest
from PIL import Image

from extensions.zip import archive
from extensions.zip.cache import ZipCache
from extensions.zip.collector import ZipCollectorPlugin
from wafer.utils.formatting import natural_key
from wafer.utils.virtual_paths import build_virtual_path, child_path


def _create_zip(path, entries):
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)


def _create_raw_zip(path, entries):
    locals_data = []
    centrals = []
    offset = 0
    for entry in entries:
        name_bytes, data, flags = entry[:3]
        extra = entry[3] if len(entry) > 3 else b""
        crc = zlib.crc32(data) & 0xFFFFFFFF
        local = struct.pack("<IHHHHHIIIHH", 0x04034B50, 20, flags, 0, 0, 0, crc, len(data), len(data), len(name_bytes), len(extra))
        central = struct.pack(
            "<IHHHHHHIIIHHHHHII",
            0x02014B50,
            20,
            20,
            flags,
            0,
            0,
            0,
            crc,
            len(data),
            len(data),
            len(name_bytes),
            len(extra),
            0,
            0,
            0,
            0,
            offset,
        )
        record = local + name_bytes + extra + data
        locals_data.append(record)
        centrals.append(central + name_bytes + extra)
        offset += len(record)
    central_data = b"".join(centrals)
    local_data = b"".join(locals_data)
    end = struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, len(entries), len(entries), len(central_data), len(local_data), 0)
    path.write_bytes(local_data + central_data + end)


def _raw_entry(name: str, data: bytes, encoding: str = "utf-8", flags: int = 0):
    return name.encode(encoding), data, flags


def _unicode_path_extra(raw_name: bytes, name: str):
    body = b"\x01" + struct.pack("<I", zlib.crc32(raw_name) & 0xFFFFFFFF) + name.encode("utf-8")
    return struct.pack("<HH", 0x7075, len(body)) + body


def _create_deflated_zip(path, name: str, data: bytes, *, file_size: int | None = None, crc: int | None = None):
    name_bytes = name.encode("utf-8")
    compressor = zlib.compressobj(wbits=-15)
    compressed = compressor.compress(data) + compressor.flush()
    file_size = len(data) if file_size is None else file_size
    crc = zlib.crc32(data) & 0xFFFFFFFF if crc is None else crc
    local = struct.pack("<IHHHHHIIIHH", 0x04034B50, 20, 0, 8, 0, 0, crc, len(compressed), file_size, len(name_bytes), 0)
    central = struct.pack(
        "<IHHHHHHIIIHHHHHII",
        0x02014B50,
        20,
        20,
        0,
        8,
        0,
        0,
        crc,
        len(compressed),
        file_size,
        len(name_bytes),
        0,
        0,
        0,
        0,
        0,
        0,
    )
    local_data = local + name_bytes + compressed
    central_data = central + name_bytes
    end = struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, 1, 1, len(central_data), len(local_data), 0)
    path.write_bytes(local_data + central_data + end)


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
    by_child = {archive.display_member_path(child_path(r.path)): r for r in child_results}
    assert by_child["wide.png"].aspect == 2.0
    assert by_child["wide.png"].meta_info is None
    assert by_child["notes/readme.txt"].aspect == 1.0
    assert by_child["notes/readme.txt"].meta_info is None


def test_zip_collector_uses_clean_sortable_member_paths(tmp_path, monkeypatch):
    zip_path = tmp_path / "sample.zip"
    _create_zip(zip_path, {"folder/010.webp": b"10", "folder/002.webp": b"2", "folder/a%b::c.png": b"data"})
    cache = ZipCache(tmp_path / "cache")
    monkeypatch.setattr("extensions.zip.collector.zip_cache", cache)
    monkeypatch.setattr("extensions.zip.collector.image_loader_resolver.load_pil", lambda _path, size=None: None)

    results = ZipCollectorPlugin().process(str(zip_path), (0.0, zip_path.stat().st_size))
    child_members = [child_path(r.path) for r in results if r.path]

    assert "folder/a%b::c.png" in child_members
    assert sorted(child_members, key=natural_key) == ["folder/002.webp", "folder/010.webp", "folder/a%b::c.png"]


def test_zip_collector_materializes_aspect_from_member_record(tmp_path, monkeypatch):
    zip_path = tmp_path / "sample.zip"
    _create_zip(zip_path, {"wide.png": b"image-bytes"})
    materialized = tmp_path / "materialized.png"
    calls = []

    def fake_materialize_member(source, member, purpose="render", name=None):
        materialized.write_bytes(b"data")
        calls.append((source, member.member, member.member_id, purpose, name))
        return str(materialized)

    def fail_materialize(_logical_path, purpose="render"):
        raise AssertionError("collector should use member record materialization")

    monkeypatch.setattr("extensions.zip.collector.zip_cache.materialize_member", fake_materialize_member)
    monkeypatch.setattr("extensions.zip.collector.zip_cache.materialize", fail_materialize)
    monkeypatch.setattr("extensions.zip.collector.image_loader_resolver.load_pil", lambda _path, size=None: Image.new("RGB", (300, 100)))

    results = ZipCollectorPlugin().process(str(zip_path), (0.0, zip_path.stat().st_size))
    child = next(r for r in results if r.path)

    assert calls and calls[0][1] == "wide.png"
    assert calls[0][2].startswith("o")
    assert calls[0][3] == "aspect"
    assert child.aspect == 3.0


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


def test_zip_cache_materializes_legacy_cp932_member_after_setting_changes(tmp_path, monkeypatch):
    zip_path = tmp_path / "cp932.zip"
    member = "日本語/readme.txt"
    _create_raw_zip(zip_path, [_raw_entry(member, b"cp932", "cp932")])
    monkeypatch.setattr("extensions.zip.archive.settings.METADATA_ENCODING", "utf-8")
    logical = build_virtual_path(str(zip_path), member)
    cache = ZipCache(tmp_path / "cache")

    real_path = cache.materialize(logical)

    assert open(real_path, "rb").read() == b"cp932"


def test_zip_cache_materializes_legacy_cp437_member_after_wrong_preference(tmp_path, monkeypatch):
    zip_path = tmp_path / "cp437.zip"
    member = "ÉGÄΦ/readme.txt"
    _create_raw_zip(zip_path, [_raw_entry(member, b"cp437", "cp437")])
    monkeypatch.setattr("extensions.zip.archive.settings.METADATA_ENCODING", "cp932")
    logical = build_virtual_path(str(zip_path), member)
    cache = ZipCache(tmp_path / "cache")

    real_path = cache.materialize(logical)

    assert open(real_path, "rb").read() == b"cp437"


def test_zip_cache_materializes_utf8_flag_member(tmp_path, monkeypatch):
    zip_path = tmp_path / "utf8.zip"
    member = "日本語/readme.txt"
    _create_raw_zip(zip_path, [_raw_entry(member, b"utf8", "utf-8", flags=0x800)])
    monkeypatch.setattr("extensions.zip.archive.settings.METADATA_ENCODING", "cp932")
    logical = build_virtual_path(str(zip_path), member)
    cache = ZipCache(tmp_path / "cache")

    real_path = cache.materialize(logical)

    assert open(real_path, "rb").read() == b"utf8"


def test_zip_cache_display_path_survives_encoding_setting_changes(tmp_path, monkeypatch):
    zip_path = tmp_path / "stable.zip"
    member = "日本語/readme.txt"
    _create_raw_zip(zip_path, [_raw_entry(member, b"stable", "cp932")])
    monkeypatch.setattr("extensions.zip.archive.settings.METADATA_ENCODING", "cp932")
    entry = archive.list_entries(str(zip_path))[0]
    logical = build_virtual_path(str(zip_path), entry.member)
    monkeypatch.setattr("extensions.zip.archive.settings.METADATA_ENCODING", "utf-8")
    cache = ZipCache(tmp_path / "cache")

    real_path = cache.materialize(logical)

    assert archive.display_member_path(child_path(logical)) == member
    assert open(real_path, "rb").read() == b"stable"


def test_zip_unicode_path_extra_recovers_display_and_extraction(tmp_path, monkeypatch):
    zip_path = tmp_path / "unicode-extra.zip"
    raw_name = b"\x81.bin"
    member = "正しい名前.bin"
    _create_raw_zip(zip_path, [(raw_name, b"unicode-extra", 0, _unicode_path_extra(raw_name, member))])
    monkeypatch.setattr("extensions.zip.archive.settings.METADATA_ENCODING", "cp932")

    entry = archive.list_entries(str(zip_path))[0]
    cache = ZipCache(tmp_path / "cache")
    real_path = cache.materialize(build_virtual_path(str(zip_path), entry.member))

    assert entry.member == member
    assert entry.name == member
    assert open(real_path, "rb").read() == b"unicode-extra"


def test_zip_duplicate_display_paths_are_stable_and_resolvable(tmp_path):
    zip_path = tmp_path / "duplicates.zip"
    raw_name = b"folder/same.txt"
    _create_raw_zip(zip_path, [(raw_name, b"first", 0), (raw_name, b"second", 0)])

    entries = archive.list_entries(str(zip_path))
    contents = []
    for entry in entries:
        with archive.open_zip_member(str(zip_path), entry.member) as src:
            contents.append(src.read())

    assert [entry.member for entry in entries] == ["folder/same.txt", "folder/same [zip#2].txt"]
    assert contents == [b"first", b"second"]


def test_zip_archive_index_cache_invalidates_on_archive_change(tmp_path):
    zip_path = tmp_path / "changing.zip"
    _create_zip(zip_path, {"a.txt": b"a"})
    first = archive.get_archive_index(str(zip_path))
    assert archive.get_archive_index(str(zip_path)) is first

    time.sleep(0.01)
    _create_zip(zip_path, {"b.txt": b"bb"})
    second = archive.get_archive_index(str(zip_path))

    assert second is not first
    assert [record.member for record in second.records] == ["b.txt"]


def test_zip_cache_materializes_deflated_member_with_invalid_zero_file_size(tmp_path):
    zip_path = tmp_path / "zero-size.zip"
    member = "book/224.jpg"
    data = b"JPEG" * 1024
    _create_deflated_zip(zip_path, member, data, file_size=0)
    cache = ZipCache(tmp_path / "cache")

    real_path = cache.materialize(build_virtual_path(str(zip_path), member))

    assert open(real_path, "rb").read() == data


def test_zip_cache_preserves_badzipfile_from_member_read(tmp_path):
    zip_path = tmp_path / "bad-crc.zip"
    member = "book/224.jpg"
    _create_deflated_zip(zip_path, member, b"broken", crc=0x12345678)
    cache = ZipCache(tmp_path / "cache")

    with pytest.raises(zipfile.BadZipFile):
        cache.materialize(build_virtual_path(str(zip_path), member))


def test_zip_cache_materializes_backslash_member_from_normalized_legacy_path(tmp_path):
    zip_path = tmp_path / "backslash.zip"
    _create_zip(zip_path, {"folder\\image.png": b"backslash"})
    logical = build_virtual_path(str(zip_path), "folder/image.png")
    cache = ZipCache(tmp_path / "cache")

    real_path = cache.materialize(logical)

    assert open(real_path, "rb").read() == b"backslash"


def test_zip_collector_returns_failure_on_unicode_decode_error(monkeypatch):
    def raise_unicode(_path):
        raise UnicodeDecodeError("cp932", b"\xec", 0, 1, "illegal multibyte sequence")

    monkeypatch.setattr("extensions.zip.collector.list_entries", raise_unicode)

    results = ZipCollectorPlugin().process("broken.zip", (0.0, 0))

    assert len(results) == 1
    assert results[0].source == "broken.zip"
    assert results[0].status is False
