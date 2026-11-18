import io
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
from extensions.zip.resolver import ZipImageLoader
from wafer.core.files.render_target import RenderPlan, ResolveContext, SURFACE_IMAGE
from wafer.plugin.imageloader.base import BaseImageLoader
from wafer.core.common.formatting import natural_key
from wafer.core.common.virtual_paths import build_virtual_path, child_path


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


def test_zip_cache_default_instance_does_not_spawn_idle_sweep(tmp_path):
    zip_path = tmp_path / "sample.zip"
    _create_zip(zip_path, {"folder/image.png": b"data"})
    logical = build_virtual_path(str(zip_path), "folder/image.png")
    cache = ZipCache(tmp_path / "cache")

    cache.materialize(logical)

    assert cache._sweep_timer is None


def test_zip_cache_opt_in_idle_sweep_spawns_timer(tmp_path):
    zip_path = tmp_path / "sample.zip"
    _create_zip(zip_path, {"folder/image.png": b"data"})
    logical = build_virtual_path(str(zip_path), "folder/image.png")
    cache = ZipCache(tmp_path / "cache", enable_idle_sweep=True)

    cache.materialize(logical)

    try:
        assert cache._sweep_timer is not None
    finally:
        cache.stop_idle_sweep()


def test_zip_resolver_materializes_and_delegates(tmp_path, monkeypatch):
    zip_path = tmp_path / "sample.zip"
    logical = build_virtual_path(str(zip_path), "folder/image.png")
    calls = []

    def fake_materialize(path, purpose="render"):
        calls.append((path, purpose))
        return str(tmp_path / "image.png")

    monkeypatch.setattr("extensions.zip.resolver.zip_cache.materialize", fake_materialize)

    class StubLoader(BaseImageLoader):
        NAME = "stub_loader"

    def resolve_child(path: str, context: ResolveContext):
        return RenderPlan(source=context.source, path=context.path, resolved_path=path, handler=StubLoader())

    target = ZipImageLoader().resolve(
        logical,
        ResolveContext.create(logical, surface=SURFACE_IMAGE, resolver=resolve_child),
    )

    assert target is not None
    assert target.path == logical
    assert target.resolved_path.endswith("image.png")
    assert isinstance(target.handler, StubLoader)
    assert calls == [(logical, "image")]


def _png_bytes(width, height):
    buffer = io.BytesIO()
    Image.new("RGB", (width, height)).save(buffer, "PNG")
    return buffer.getvalue()


def test_zip_collector_returns_child_rows_and_generic_aspect(tmp_path):
    zip_path = tmp_path / "sample.zip"
    _create_zip(
        zip_path,
        {
            "wide.png": _png_bytes(400, 200),
            "notes/readme.txt": b"hello",
        },
    )

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


def test_zip_collector_uses_clean_sortable_member_paths(tmp_path):
    zip_path = tmp_path / "sample.zip"
    _create_zip(zip_path, {"folder/010.webp": b"10", "folder/002.webp": b"2", "folder/a%b::c.png": b"data"})

    results = ZipCollectorPlugin().process(str(zip_path), (0.0, zip_path.stat().st_size))
    child_members = [child_path(r.path) for r in results if r.path]

    assert "folder/a%b::c.png" in child_members
    assert sorted(child_members, key=natural_key) == ["folder/002.webp", "folder/010.webp", "folder/a%b::c.png"]


def test_zip_collector_probes_aspect_in_memory_with_one_archive_open(tmp_path, monkeypatch):
    zip_path = tmp_path / "sample.zip"
    _create_zip(zip_path, {f"{i:03d}.png": _png_bytes(300, 100) for i in range(5)} | {"notes.txt": b"text"})
    archive.list_entries(str(zip_path))
    opened = []
    real_open = archive._open_zip_with_encoding
    monkeypatch.setattr(archive, "_open_zip_with_encoding", lambda *args: opened.append(args) or real_open(*args))
    monkeypatch.setattr("extensions.zip.collector.zip_cache.materialize_member", lambda *args, **kwargs: pytest.fail("aspect probe must not write to disk"))

    results = ZipCollectorPlugin().process(str(zip_path), (0.0, zip_path.stat().st_size))

    assert [r.aspect for r in results if r.path and r.name.endswith(".png")] == [3.0] * 5
    assert len(opened) == 1


def test_zip_collector_returns_failure_on_unicode_decode_error(monkeypatch):
    def raise_unicode(_path):
        raise UnicodeDecodeError("cp932", b"\xec", 0, 1, "illegal multibyte sequence")

    monkeypatch.setattr("extensions.zip.collector.list_entries", raise_unicode)

    results = ZipCollectorPlugin().process("broken.zip", (0.0, 0))

    assert len(results) == 1
    assert results[0].source == "broken.zip"
    assert results[0].status is False


def test_zip_collector_skips_encrypted_entries(tmp_path, monkeypatch):
    zip_path = tmp_path / "locked.zip"
    _create_raw_zip(zip_path, [_raw_entry("open.png", b"open"), _raw_entry("locked.png", b"locked", flags=0x1)])
    probed = []
    monkeypatch.setattr(ZipCollectorPlugin, "_probe_aspect", lambda self, open_member, entry, logical_path: probed.append(entry.member) or 1.0)

    results = ZipCollectorPlugin().process(str(zip_path), (0.0, zip_path.stat().st_size))

    assert [child_path(result.path) for result in results[1:]] == ["open.png"]
    assert results[0].meta_info == {"entries": 1}
    assert probed == ["open.png"]
    assert [record.encrypted for record in archive.list_member_records(str(zip_path))] == [False, True]
