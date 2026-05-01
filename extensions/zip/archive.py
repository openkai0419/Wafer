from __future__ import annotations

import datetime as _dt
import zipfile
from dataclasses import dataclass

from . import settings
from wafer.utils.logs import AppLogger


@dataclass(frozen=True)
class ZipEntry:
    member: str
    size: int
    modified: float | None

    @property
    def name(self) -> str:
        clean = self.member.replace("\\", "/").rstrip("/")
        return clean.rsplit("/", 1)[-1] if clean else self.member


def list_entries(zip_path: str) -> list[ZipEntry]:
    with open_zip(zip_path) as zf:
        return [_entry(info) for info in zf.infolist() if _is_file(info)]


def open_zip(zip_path: str) -> zipfile.ZipFile:
    preferred = settings.METADATA_ENCODING
    candidates = _metadata_encoding_candidates(preferred)
    last_decode_error: UnicodeDecodeError | LookupError | None = None
    for metadata_encoding in candidates:
        try:
            if metadata_encoding is None:
                return zipfile.ZipFile(zip_path)
            return zipfile.ZipFile(zip_path, metadata_encoding=metadata_encoding)
        except TypeError as e:
            AppLogger.warning(
                f"[zip] metadata_encoding is not supported by this Python build: {metadata_encoding}",
                exc=e,
            )
            return zipfile.ZipFile(zip_path)
        except (UnicodeDecodeError, LookupError) as e:
            last_decode_error = e
            AppLogger.warning(
                f"[zip] Failed metadata decoding with encoding={metadata_encoding}: {zip_path}",
                exc=e,
            )
            continue
    if last_decode_error is not None:
        raise last_decode_error
    return zipfile.ZipFile(zip_path)


def _metadata_encoding_candidates(preferred: str | None) -> list[str | None]:
    normalized = (preferred or "").strip()
    if not normalized:
        return [None]
    candidates: list[str | None] = [normalized]
    if normalized.lower() != "utf-8":
        candidates.append("utf-8")
    candidates.append(None)
    return candidates


def _is_file(info: zipfile.ZipInfo) -> bool:
    if info.is_dir():
        return False
    name = info.filename.replace("\\", "/").strip("/")
    return bool(name)


def _entry(info: zipfile.ZipInfo) -> ZipEntry:
    return ZipEntry(
        member=info.filename.replace("\\", "/"),
        size=int(info.file_size or 0),
        modified=_timestamp(info),
    )


def _timestamp(info: zipfile.ZipInfo) -> float | None:
    try:
        return _dt.datetime(*info.date_time).timestamp()
    except (TypeError, ValueError, OSError):
        return None
