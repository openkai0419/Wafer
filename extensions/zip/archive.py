from __future__ import annotations

import datetime as _dt
import zipfile
from dataclasses import dataclass


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
    with zipfile.ZipFile(zip_path) as zf:
        return [_entry(info) for info in zf.infolist() if _is_file(info)]


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
