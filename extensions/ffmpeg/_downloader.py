import os
import re
import shutil
import tempfile

from wafer.utils.downloader import (
    safe_download,
    fetch_text,
    extract_7z_members,
)


_LIB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib")
_FFPROBE_NAME = "ffprobe.exe"
_FFMPEG_NAME = "ffmpeg.exe"
_FFPROBE_PATH = os.path.join(_LIB_DIR, _FFPROBE_NAME)
_FFMPEG_PATH = os.path.join(_LIB_DIR, _FFMPEG_NAME)
_BINARIES = (_FFPROBE_NAME, _FFMPEG_NAME)

_ARCHIVE_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.7z"
_SHA256_URL = _ARCHIVE_URL + ".sha256"
_ALLOWED_HOSTS = ("www.gyan.dev",)
_SHA256_HEX_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_MAX_SHA256_RESPONSE = 256
_USER_AGENT = "wafer-ffmpeg-plugin"

_MANUAL_HINT = "Download ffmpeg essentials from https://www.gyan.dev/ffmpeg/builds/ and place ffprobe.exe + ffmpeg.exe in extensions/ffmpeg/lib/"


def _log(msg, *, level="info", exc=None):
    try:
        from wafer.utils.logs import AppLogger

        fn = getattr(AppLogger, level, AppLogger.info)
        if exc and level in ("error", "warning"):
            fn(msg, exc=exc)
        else:
            fn(msg)
    except (ImportError, AttributeError):
        pass


def _fetch_expected_sha256() -> str:
    text = fetch_text(
        _SHA256_URL,
        allowed_hosts=_ALLOWED_HOSTS,
        max_bytes=_MAX_SHA256_RESPONSE,
        user_agent=_USER_AGENT,
    ).strip()
    token = text.split()[0] if text else ""
    if not _SHA256_HEX_RE.fullmatch(token):
        raise RuntimeError(f"Unexpected .sha256 format: {text!r}")
    return token.lower()


def get_ffprobe_path() -> str | None:
    if os.path.isfile(_FFPROBE_PATH):
        return _FFPROBE_PATH
    return None


def get_ffmpeg_path() -> str | None:
    if os.path.isfile(_FFMPEG_PATH):
        return _FFMPEG_PATH
    return None


def ensure_ffmpeg():
    if os.path.isfile(_FFPROBE_PATH) and os.path.isfile(_FFMPEG_PATH):
        return True
    tmp = tempfile.mkdtemp()
    try:
        _log(f"[ffmpeg] Fetching checksum: {_SHA256_URL}")
        expected = _fetch_expected_sha256()
        _log(f"[ffmpeg] Downloading ffmpeg essentials: {_ARCHIVE_URL}")
        archive = os.path.join(tmp, "ffmpeg-essentials.7z")
        safe_download(_ARCHIVE_URL, archive, allowed_hosts=_ALLOWED_HOSTS, expected_sha256=expected)
        _log("[ffmpeg] archive checksum verified")
        extract_7z_members(archive, _LIB_DIR, _BINARIES)
        _log("[ffmpeg] ffprobe + ffmpeg installed successfully")
        return True
    except Exception as e:
        raise RuntimeError(f"Failed to acquire ffmpeg: {e}. {_MANUAL_HINT}") from e
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
