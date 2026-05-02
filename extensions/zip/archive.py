from __future__ import annotations

import datetime as _dt
import os
import posixpath
import struct
import threading
import zipfile
import zlib
from collections import OrderedDict
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from typing import BinaryIO

from wafer.utils.logs import AppLogger

from . import settings

_COMMON_ENCODINGS = ("utf-8", "cp932", "shift_jis", "gbk", "cp949", "big5", "cp1252")
_LOCAL_FILE_HEADER = struct.Struct("<4s5H3L2H")
_LOCAL_FILE_HEADER_SIGNATURE = b"PK\x03\x04"
_RAW_READ_SIZE = 1024 * 1024
_UNICODE_PATH_EXTRA_ID = 0x7075
_RAW_SUPPORTED_METHODS = {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
_INDEX_CACHE_MAX = 16
_EOCD_SIGNATURE = b"PK\x05\x06"
_EOCD = struct.Struct("<4s4H2LH")


@dataclass(frozen=True)
class ZipMemberRecord:
    member: str
    info: zipfile.ZipInfo
    order: int
    metadata_encoding: str | None
    header_offset: int
    crc: int
    compress_size: int
    file_size: int
    compress_type: int
    flag_bits: int
    modified: float | None
    anomalies: tuple[str, ...] = ()

    @property
    def name(self) -> str:
        clean = self.member.rstrip("/")
        return clean.rsplit("/", 1)[-1] if clean else self.member

    @property
    def size(self) -> int:
        return int(self.file_size or 0)

    @property
    def member_id(self) -> str:
        return f"o{self.header_offset}_i{self.order}_c{self.crc:08x}"


@dataclass(frozen=True)
class ZipArchiveIndex:
    zip_path: str
    signature: tuple[int, ...]
    metadata_encoding: str | None
    records: tuple[ZipMemberRecord, ...]
    by_member: dict[str, ZipMemberRecord]

    def resolve(self, member: str) -> ZipMemberRecord | None:
        for name in _name_attempts(member):
            record = self.by_member.get(_member_display_path(name))
            if record is not None:
                return record
        return None


@dataclass(frozen=True)
class ZipEntry:
    member: str
    size: int
    modified: float | None
    record: ZipMemberRecord | None = None

    @property
    def name(self) -> str:
        clean = self.member.rstrip("/")
        return clean.rsplit("/", 1)[-1] if clean else self.member


_INDEX_LOCK = threading.RLock()
_INDEX_CACHE: OrderedDict[str, ZipArchiveIndex] = OrderedDict()


def list_entries(zip_path: str) -> list[ZipEntry]:
    return [_entry(record) for record in list_member_records(zip_path)]


def list_member_records(zip_path: str) -> list[ZipMemberRecord]:
    return list(get_archive_index(zip_path).records)


def open_zip(zip_path: str) -> zipfile.ZipFile:
    last_decode_error: UnicodeDecodeError | LookupError | None = None
    for zf, _metadata_encoding in _open_zip_candidates(zip_path, extended=True):
        return zf
    for _metadata_encoding, e in _zip_open_errors(zip_path, extended=True):
        if isinstance(e, (UnicodeDecodeError, LookupError)):
            last_decode_error = e
    if last_decode_error is not None:
        raise last_decode_error
    return zipfile.ZipFile(zip_path)


@contextmanager
def open_zip_member(zip_path: str, member: str) -> Iterator[BinaryIO]:
    record = get_archive_index(zip_path).resolve(member)
    if record is None:
        e = KeyError(f"ZIP member not found: source={zip_path} member={display_member_path(member)}")
        AppLogger.warning(str(e))
        raise e
    with open_zip_member_record(zip_path, record) as src:
        yield src


@contextmanager
def open_zip_member_record(zip_path: str | os.PathLike, record: ZipMemberRecord) -> Iterator[BinaryIO]:
    zf = _open_zip_with_encoding(zip_path, record.metadata_encoding)
    src: BinaryIO | _RawZipMemberReader | None = None
    try:
        src = _open_member_stream(zip_path, zf, record.info)
        try:
            yield src
        finally:
            src.close()
    finally:
        zf.close()


def display_member_path(member: str | None) -> str:
    return _member_display_path(member or "")


def get_archive_index(zip_path: str | os.PathLike) -> ZipArchiveIndex:
    key = _index_key(zip_path)
    signature = _archive_signature(zip_path)
    with _INDEX_LOCK:
        cached = _INDEX_CACHE.get(key)
        if cached is not None and cached.signature == signature:
            _INDEX_CACHE.move_to_end(key)
            return cached
    index = _build_archive_index(str(zip_path), signature)
    with _INDEX_LOCK:
        _INDEX_CACHE[key] = index
        _INDEX_CACHE.move_to_end(key)
        while len(_INDEX_CACHE) > _INDEX_CACHE_MAX:
            _INDEX_CACHE.popitem(last=False)
    return index


def _index_key(zip_path: str | os.PathLike) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(zip_path)))


def _archive_signature(zip_path: str | os.PathLike) -> tuple[int, ...]:
    st = os.stat(zip_path)
    return (int(st.st_mtime_ns), int(st.st_size), *_central_directory_signature(zip_path, st.st_size))


def _central_directory_signature(zip_path: str | os.PathLike, size: int) -> tuple[int, ...]:
    try:
        with open(zip_path, "rb") as fp:
            fp.seek(max(0, size - (65535 + _EOCD.size)))
            data = fp.read()
    except OSError as e:
        AppLogger.debug(f"[zip] Failed to read archive signature: {zip_path} ({e})")
        return ()
    pos = data.rfind(_EOCD_SIGNATURE)
    if pos < 0 or pos + _EOCD.size > len(data):
        return ()
    _sig, disk, cd_disk, entries_disk, entries_total, cd_size, cd_offset, comment_len = _EOCD.unpack_from(data, pos)
    return (disk, cd_disk, entries_disk, entries_total, cd_size, cd_offset, comment_len)


def _build_archive_index(zip_path: str, signature: tuple[int, ...]) -> ZipArchiveIndex:
    last_decode_error: UnicodeDecodeError | LookupError | None = None
    for zf, metadata_encoding in _open_zip_candidates(zip_path, extended=True):
        try:
            return _index_from_zip(zip_path, signature, zf, metadata_encoding)
        finally:
            zf.close()
    for _metadata_encoding, e in _zip_open_errors(zip_path, extended=True):
        if isinstance(e, (UnicodeDecodeError, LookupError)):
            last_decode_error = e
    if last_decode_error is not None:
        raise last_decode_error
    with zipfile.ZipFile(zip_path) as zf:
        return _index_from_zip(zip_path, signature, zf, None)


def _index_from_zip(zip_path: str, signature: tuple[int, ...], zf: zipfile.ZipFile, metadata_encoding: str | None) -> ZipArchiveIndex:
    items: list[tuple[zipfile.ZipInfo, int, str, tuple[str, ...], tuple[str, ...]]] = []
    for order, info in enumerate(zf.infolist()):
        if info.is_dir():
            continue
        display_name = _unicode_path_name(zf, info) or info.filename
        member = _member_display_path(display_name)
        if not member:
            continue
        aliases = _display_aliases(zf, info, display_name)
        anomalies: list[str] = []
        if display_name != info.filename:
            anomalies.append("unicode_path_extra")
        if _needs_raw_member_reader(info):
            anomalies.append("zero_declared_size")
        items.append((info, order, member, aliases, tuple(anomalies)))

    records: list[ZipMemberRecord] = []
    by_member: dict[str, ZipMemberRecord] = {}
    used: set[str] = set()
    occurrences: dict[str, int] = {}
    pending_aliases: list[tuple[ZipMemberRecord, tuple[str, ...]]] = []
    for info, order, member, aliases, anomalies in items:
        occurrence = occurrences.get(member, 0) + 1
        occurrences[member] = occurrence
        if occurrence == 1 and member not in used:
            unique_member = member
        else:
            unique_member = _disambiguate_member(member, occurrence, info.header_offset, used)
        record = ZipMemberRecord(
            member=unique_member,
            info=info,
            order=order,
            metadata_encoding=metadata_encoding,
            header_offset=int(info.header_offset),
            crc=int(info.CRC),
            compress_size=int(info.compress_size or 0),
            file_size=int(info.file_size or 0),
            compress_type=int(info.compress_type),
            flag_bits=int(info.flag_bits),
            modified=_timestamp(info),
            anomalies=anomalies,
        )
        records.append(record)
        by_member[unique_member] = record
        used.add(unique_member)
        pending_aliases.append((record, aliases))
    for record, aliases in pending_aliases:
        for alias in aliases:
            by_member.setdefault(alias, record)
    return ZipArchiveIndex(
        zip_path=zip_path,
        signature=signature,
        metadata_encoding=metadata_encoding,
        records=tuple(records),
        by_member=by_member,
    )


def _display_aliases(zf: zipfile.ZipFile, info: zipfile.ZipInfo, display_name: str) -> tuple[str, ...]:
    raw_name = _local_name_bytes(zf, info)
    aliases = {_member_display_path(display_name), _member_display_path(info.filename)}
    if raw_name:
        for encoding in _metadata_encoding_candidates(settings.METADATA_ENCODING, extended=True):
            codec = encoding or "cp437"
            try:
                aliases.add(_member_display_path(raw_name.decode(codec)))
            except (UnicodeDecodeError, LookupError):
                continue
    return tuple(alias for alias in aliases if alias)


def _disambiguate_member(member: str, occurrence: int, header_offset: int, used: set[str]) -> str:
    directory, name = member.rsplit("/", 1) if "/" in member else ("", member)
    stem, suffix = posixpath.splitext(name)
    base = stem or name
    candidate_name = f"{base} [zip#{occurrence}]{suffix}"
    candidate = f"{directory}/{candidate_name}" if directory else candidate_name
    if candidate not in used:
        return candidate
    offset = f"{header_offset:x}"
    index = 2
    while True:
        candidate_name = f"{base} [zip#{occurrence}-{offset}-{index}]{suffix}"
        candidate = f"{directory}/{candidate_name}" if directory else candidate_name
        if candidate not in used:
            return candidate
        index += 1


def _metadata_encoding_candidates(preferred: str | None, *, extended: bool = False) -> list[str | None]:
    normalized = (preferred or "").strip()
    raw_candidates: list[str | None] = []
    if normalized:
        raw_candidates.append(normalized)
    else:
        raw_candidates.append(None)
    if extended:
        raw_candidates.extend(_COMMON_ENCODINGS)
    elif normalized.lower() != "utf-8":
        raw_candidates.append("utf-8")
    raw_candidates.append(None)

    candidates: list[str | None] = []
    seen: set[str] = set()
    for encoding in raw_candidates:
        key = (encoding or "").lower()
        if key in seen:
            continue
        seen.add(key)
        candidates.append(encoding)
    return candidates


def _open_zip_with_encoding(zip_path: str | os.PathLike, metadata_encoding: str | None) -> zipfile.ZipFile:
    if metadata_encoding is None:
        return zipfile.ZipFile(zip_path)
    return zipfile.ZipFile(zip_path, metadata_encoding=metadata_encoding)


def _open_zip_candidates(
    zip_path: str | os.PathLike,
    *,
    log_decode_errors: bool = False,
    extended: bool = False,
) -> Iterator[tuple[zipfile.ZipFile, str | None]]:
    for metadata_encoding in _metadata_encoding_candidates(settings.METADATA_ENCODING, extended=extended):
        try:
            zf = _open_zip_with_encoding(zip_path, metadata_encoding)
        except TypeError as e:
            AppLogger.warning(
                f"[zip] metadata_encoding is not supported by this Python build: {metadata_encoding}",
                exc=e,
            )
            yield zipfile.ZipFile(zip_path), None
            return
        except (UnicodeDecodeError, LookupError):
            if log_decode_errors:
                AppLogger.debug(f"[zip] Failed metadata decoding with encoding={metadata_encoding}: {zip_path}")
            continue
        yield zf, metadata_encoding


def _zip_open_errors(zip_path: str | os.PathLike, *, extended: bool = False) -> Iterator[tuple[str | None, Exception]]:
    for metadata_encoding in _metadata_encoding_candidates(settings.METADATA_ENCODING, extended=extended):
        try:
            zf = _open_zip_with_encoding(zip_path, metadata_encoding)
            zf.close()
        except Exception as e:
            yield metadata_encoding, e


def _name_attempts(member: str) -> tuple[str, ...]:
    normalized = str(member).replace("\\", "/")
    backslash = normalized.replace("/", "\\")
    return (normalized,) if backslash == normalized else (normalized, backslash)


def _member_display_path(member: str) -> str:
    return str(member).replace("\\", "/").strip("/")


def _entry(record: ZipMemberRecord) -> ZipEntry:
    return ZipEntry(
        member=record.member,
        size=record.size,
        modified=record.modified,
        record=record,
    )


def _timestamp(info: zipfile.ZipInfo) -> float | None:
    try:
        return _dt.datetime(*info.date_time).timestamp()
    except (TypeError, ValueError, OSError):
        return None


def _local_header_data(zf: zipfile.ZipFile, info: zipfile.ZipInfo) -> tuple[bytes, int] | None:
    fp = getattr(zf, "fp", None)
    if fp is None:
        return None
    position = fp.tell()
    try:
        fp.seek(info.header_offset)
        header = fp.read(_LOCAL_FILE_HEADER.size)
        if len(header) != _LOCAL_FILE_HEADER.size:
            return None
        values = _LOCAL_FILE_HEADER.unpack(header)
        if values[0] != _LOCAL_FILE_HEADER_SIGNATURE:
            return None
        name_length = values[-2]
        extra_length = values[-1]
        name = fp.read(name_length)
        data_offset = info.header_offset + _LOCAL_FILE_HEADER.size + name_length + extra_length
        return name, data_offset
    except Exception as e:
        AppLogger.debug(f"[zip] Failed to read local header name: {info.filename} ({e})")
        return None
    finally:
        try:
            fp.seek(position)
        except Exception as e:
            AppLogger.debug(f"[zip] Failed to restore archive position: {info.filename} ({e})")


def _local_name_bytes(zf: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    data = _local_header_data(zf, info)
    return data[0] if data else b""


def _local_data_offset(zf: zipfile.ZipFile, info: zipfile.ZipInfo) -> int | None:
    data = _local_header_data(zf, info)
    return data[1] if data else None


def _has_unicode_path_extra(extra: bytes) -> bool:
    pos = 0
    while pos + 4 <= len(extra):
        header_id, data_size = struct.unpack_from("<HH", extra, pos)
        pos += 4 + data_size
        if header_id == _UNICODE_PATH_EXTRA_ID:
            return True
    return False


def _unicode_path_name(zf: zipfile.ZipFile, info: zipfile.ZipInfo) -> str | None:
    if not _has_unicode_path_extra(info.extra):
        return None
    raw_name = _local_name_bytes(zf, info)
    if not raw_name:
        return None
    return _unicode_path_from_extra(info.extra, raw_name)


def _unicode_path_from_extra(extra: bytes, raw_name: bytes) -> str | None:
    raw_crc = zlib.crc32(raw_name) & 0xFFFFFFFF
    pos = 0
    while pos + 4 <= len(extra):
        header_id, data_size = struct.unpack_from("<HH", extra, pos)
        pos += 4
        data = extra[pos : pos + data_size]
        pos += data_size
        if header_id != _UNICODE_PATH_EXTRA_ID or len(data) < 5 or data[0] != 1:
            continue
        if struct.unpack_from("<I", data, 1)[0] != raw_crc:
            continue
        try:
            name = data[5:].decode("utf-8")
        except UnicodeDecodeError as e:
            AppLogger.debug(f"[zip] Invalid unicode path extra field: {e}")
            continue
        if name:
            return name
    return None


def _open_member_stream(zip_path: str | os.PathLike, zf: zipfile.ZipFile, info: zipfile.ZipInfo) -> BinaryIO | _RawZipMemberReader:
    if _needs_raw_member_reader(info):
        data_offset = _local_data_offset(zf, info)
        if data_offset is not None:
            with ExitStack() as stack:
                fp = stack.enter_context(open(zip_path, "rb"))
                reader = _RawZipMemberReader(fp, info, data_offset)
                stack.pop_all()
                return reader
    return zf.open(info, "r")


def _needs_raw_member_reader(info: zipfile.ZipInfo) -> bool:
    return bool(info.compress_size and info.file_size == 0 and info.compress_type in _RAW_SUPPORTED_METHODS and not info.is_dir())


class _RawZipMemberReader:
    def __init__(self, fp: BinaryIO, info: zipfile.ZipInfo, data_offset: int):
        self.fp = fp
        self.info = info
        self.remaining = int(info.compress_size)
        self.buffer = bytearray()
        self.crc = 0
        self.size = 0
        self.eof = False
        self.closed = False
        self.decompressor = zlib.decompressobj(-15) if info.compress_type == zipfile.ZIP_DEFLATED else None
        self.fp.seek(data_offset)

    def readable(self) -> bool:
        return True

    def read(self, size: int | None = -1) -> bytes:
        if self.closed:
            raise ValueError("I/O operation on closed ZIP member")
        if size is None or size < 0:
            chunks: list[bytes] = []
            while chunk := self.read(_RAW_READ_SIZE):
                chunks.append(chunk)
            return b"".join(chunks)
        if size == 0:
            return b""
        while len(self.buffer) < size and not self.eof:
            self._fill()
        data = bytes(self.buffer[:size])
        del self.buffer[:size]
        return data

    def close(self) -> None:
        self.closed = True
        self.fp.close()

    def _fill(self) -> None:
        if self.remaining:
            chunk = self.fp.read(min(_RAW_READ_SIZE, self.remaining))
            if not chunk:
                raise zipfile.BadZipFile(f"Truncated file data for file {self.info.filename!r}")
            self.remaining -= len(chunk)
            self._append(self._decompress(chunk))
            if self.buffer or self.remaining:
                return
        if self.decompressor is not None:
            self._append(self._flush_decompressor())
            if not self.decompressor.eof:
                raise zipfile.BadZipFile(f"Compressed data ended before the end-of-stream marker for file {self.info.filename!r}")
        self._finish()

    def _decompress(self, chunk: bytes) -> bytes:
        if self.decompressor is None:
            return chunk
        try:
            return self.decompressor.decompress(chunk)
        except zlib.error as e:
            raise zipfile.BadZipFile(f"Error while decompressing data for file {self.info.filename!r}") from e

    def _flush_decompressor(self) -> bytes:
        try:
            return self.decompressor.flush() if self.decompressor is not None else b""
        except zlib.error as e:
            raise zipfile.BadZipFile(f"Error while decompressing data for file {self.info.filename!r}") from e

    def _append(self, data: bytes) -> None:
        if not data:
            return
        self.crc = zlib.crc32(data, self.crc)
        self.size += len(data)
        self.buffer.extend(data)

    def _finish(self) -> None:
        self.eof = True
        actual_crc = self.crc & 0xFFFFFFFF
        if actual_crc != self.info.CRC:
            raise zipfile.BadZipFile(f"Bad CRC-32 for file {self.info.filename!r}")
        if self.info.file_size and self.size != self.info.file_size:
            raise zipfile.BadZipFile(f"Bad file size for file {self.info.filename!r}")
