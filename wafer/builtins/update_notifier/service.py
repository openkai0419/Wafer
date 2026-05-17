from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlparse

import requests

from ..._version import __version__
from ...utils.json_io import read_json_file, write_json_file
from ...utils.logs import AppLogger
from ...utils.paths import resolve_cache_path
from .versioning import is_newer_version, normalize_version, parse_version


REPOSITORY = "openkai0419/Wafer"
LATEST_RELEASE_API_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
CHANGELOG_RAW_BASE_URL = f"https://raw.githubusercontent.com/{REPOSITORY}"
DEFAULT_TIMEOUT = 5.0
USER_AGENT = "Wafer Update Notifier"
_ALLOWED_HOSTS = {"api.github.com", "github.com", "raw.githubusercontent.com", "objects.githubusercontent.com"}


@dataclass(frozen=True)
class UpdateInfo:
    current_version: str
    latest_version: str
    tag_name: str
    release_url: str
    download_url: str
    published_at: str
    release_notes: str
    changelog_markdown: str
    is_newer: bool
    from_cache: bool = False


@dataclass(frozen=True)
class UpdateCheckResult:
    info: UpdateInfo | None = None
    error: str = ""
    from_cache: bool = False


def latest_release_cache_path() -> Path:
    return Path(resolve_cache_path("updates/latest.json"))


def changelog_cache_path(tag_name: str) -> Path:
    safe_tag = re.sub(r"[^A-Za-z0-9._-]+", "_", tag_name or "latest")
    return Path(resolve_cache_path(f"updates/changelog/{safe_tag}.md"))


def validate_external_url(url: str) -> str:
    parsed = urlparse(str(url or ""))
    if parsed.scheme != "https" or parsed.hostname not in _ALLOWED_HOSTS:
        return ""
    return parsed.geturl()


def fetch_latest_release(*, timeout: float = DEFAULT_TIMEOUT) -> dict:
    response = requests.get(
        LATEST_RELEASE_API_URL,
        timeout=timeout,
        headers={"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT},
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("GitHub release response is not an object")
    return data


def fetch_changelog(tag_name: str, *, timeout: float = DEFAULT_TIMEOUT) -> str:
    if not tag_name:
        raise ValueError("release tag is empty")
    url = validate_external_url(f"{CHANGELOG_RAW_BASE_URL}/{quote(tag_name, safe='')}/CHANGELOG.md")
    if not url:
        raise ValueError("invalid changelog URL")
    response = requests.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    return response.text


def read_cached_latest_release() -> dict | None:
    data = read_json_file(latest_release_cache_path(), default=None)
    return data if isinstance(data, dict) else None


def write_cached_latest_release(data: dict) -> None:
    try:
        write_json_file(latest_release_cache_path(), data)
    except Exception as e:
        AppLogger.warning("Failed to write update release cache", exc=e)


def read_cached_changelog(tag_name: str) -> str:
    try:
        path = changelog_cache_path(tag_name)
        return path.read_text(encoding="utf-8") if path.is_file() else ""
    except Exception as e:
        AppLogger.warning("Failed to read cached update changelog", exc=e)
        return ""


def write_cached_changelog(tag_name: str, text: str) -> None:
    try:
        path = changelog_cache_path(tag_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text or "", encoding="utf-8")
    except Exception as e:
        AppLogger.warning("Failed to write update changelog cache", exc=e)


def build_update_info(release: dict, changelog_markdown: str, *, current_version: str = __version__, from_cache: bool = False) -> UpdateInfo:
    tag_name = str(release.get("tag_name") or "")
    latest_version = normalize_version(tag_name or release.get("name") or "")
    if parse_version(latest_version) is None:
        raise ValueError("latest release tag is not a supported version")
    release_url = validate_external_url(str(release.get("html_url") or ""))
    return UpdateInfo(
        current_version=str(current_version or ""),
        latest_version=latest_version,
        tag_name=tag_name,
        release_url=release_url,
        download_url=release_url,
        published_at=str(release.get("published_at") or ""),
        release_notes=str(release.get("body") or ""),
        changelog_markdown=changelog_markdown or str(release.get("body") or ""),
        is_newer=is_newer_version(current_version, latest_version),
        from_cache=from_cache,
    )


def should_notify_update(info: UpdateInfo | None, skipped_version: str = "") -> bool:
    if info is None or not info.is_newer:
        return False
    return str(skipped_version or "") != info.latest_version


def check_for_updates(*, current_version: str = __version__, timeout: float = DEFAULT_TIMEOUT, use_cache: bool = True) -> UpdateCheckResult:
    release = None
    from_cache = False
    try:
        release = fetch_latest_release(timeout=timeout)
        write_cached_latest_release(release)
    except Exception as e:
        AppLogger.warning("Update release check failed", exc=e)
        if use_cache:
            release = read_cached_latest_release()
            from_cache = release is not None
        if release is None:
            return UpdateCheckResult(error=str(e))

    try:
        tag_name = str(release.get("tag_name") or "")
        changelog = fetch_changelog(tag_name, timeout=timeout)
        write_cached_changelog(tag_name, changelog)
    except Exception as e:
        AppLogger.warning("Update changelog fetch failed", exc=e)
        changelog = read_cached_changelog(str(release.get("tag_name") or "")) if use_cache else ""

    try:
        info = build_update_info(release, changelog, current_version=current_version, from_cache=from_cache)
    except Exception as e:
        AppLogger.warning("Update release response could not be parsed", exc=e)
        return UpdateCheckResult(error=str(e), from_cache=from_cache)
    return UpdateCheckResult(info=info, from_cache=from_cache)
