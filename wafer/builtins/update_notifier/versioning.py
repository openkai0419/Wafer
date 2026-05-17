from __future__ import annotations

import re
from dataclasses import dataclass


_VERSION_RE = re.compile(r"^\s*v?(\d+)\.(\d+)\.(\d+)(?:[.-]?(?:dev|a|alpha|b|beta|rc)\d*)?(?:\+[^\s]+)?\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class VersionParts:
    major: int
    minor: int
    patch: int

    @property
    def release(self) -> tuple[int, int, int]:
        return self.major, self.minor, self.patch

    @property
    def normalized(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


def parse_version(value: str | None) -> VersionParts | None:
    if not value:
        return None
    match = _VERSION_RE.match(str(value))
    if not match:
        return None
    major, minor, patch = match.groups()
    return VersionParts(
        major=int(major),
        minor=int(minor),
        patch=int(patch),
    )


def normalize_version(value: str | None) -> str:
    parsed = parse_version(value)
    return parsed.normalized if parsed else str(value or "").strip().lstrip("v")


def is_newer_version(current: str | None, latest: str | None, *, include_prerelease: bool = False) -> bool:
    current_parts = parse_version(current)
    latest_parts = parse_version(latest)
    if current_parts is None or latest_parts is None:
        return False
    return latest_parts.release > current_parts.release
