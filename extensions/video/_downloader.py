import os
import re
import shutil
import sys
import tempfile

from wafer.utils.downloader import (
    safe_download,
    fetch_json,
    extract_7z_members,
    lib_needs_download,
    write_lib_version,
)


_LIB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib")
_DLL_NAME = "libmpv-2.dll"
_DLL_PATH = os.path.join(_LIB_DIR, _DLL_NAME)

_RELEASES_API_URL = "https://api.github.com/repos/shinchiro/mpv-winbuild-cmake/releases/latest"
_ASSET_PATTERN = re.compile(r"^mpv-dev-x86_64-\d{8}-git-[0-9a-f]+\.7z$")
_ALLOWED_HOSTS = ("github.com", "objects.githubusercontent.com", "api.github.com")
_MAX_RELEASE_RESPONSE = 2 * 1024 * 1024
_USER_AGENT = "wafer-video-plugin"

_MANUAL_HINT = "Download libmpv-2.dll from https://sourceforge.net/projects/mpv-player-windows/files/libmpv/ and place it in extensions/video/lib/"


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


def _find_asset() -> tuple[str, str, str]:
    meta = fetch_json(
        _RELEASES_API_URL,
        allowed_hosts=_ALLOWED_HOSTS,
        max_bytes=_MAX_RELEASE_RESPONSE,
        user_agent=_USER_AGENT,
        extra_headers={"Accept": "application/vnd.github+json"},
    )
    tag = str(meta.get("tag_name") or "?")
    for asset in meta.get("assets") or ():
        name = str(asset.get("name") or "")
        if not _ASSET_PATTERN.fullmatch(name):
            continue
        url = str(asset.get("browser_download_url") or "")
        digest = str(asset.get("digest") or "")
        if not url or not digest.startswith("sha256:"):
            continue
        sha = digest.split(":", 1)[1].strip().lower()
        if len(sha) != 64:
            continue
        return url, sha, f"{tag}/{name}"
    raise RuntimeError(f"mpv-dev-x86_64 asset not found in release {tag}")


def _setup_dll_path():
    path_dirs = os.environ.get("PATH", "").split(os.pathsep)
    if _LIB_DIR not in path_dirs:
        os.environ["PATH"] = _LIB_DIR + os.pathsep + os.environ.get("PATH", "")
    if sys.platform == "win32" and hasattr(os, "add_dll_directory"):
        os.add_dll_directory(_LIB_DIR)


def ensure_mpv_dll(version: str = ""):
    if not lib_needs_download(_LIB_DIR, version, _DLL_PATH):
        write_lib_version(_LIB_DIR, version)
        _setup_dll_path()
        return True
    tmp = tempfile.mkdtemp()
    try:
        _log(f"[video] Resolving latest mpv-dev asset via {_RELEASES_API_URL}")
        url, expected, label = _find_asset()
        _log(f"[video] Downloading mpv DLL: {label}")
        archive = os.path.join(tmp, "mpv-dev.7z")
        safe_download(url, archive, allowed_hosts=_ALLOWED_HOSTS, expected_sha256=expected)
        _log("[video] archive checksum verified")
        extract_7z_members(archive, _LIB_DIR, (_DLL_NAME,))
        write_lib_version(_LIB_DIR, version)
        _setup_dll_path()
        _log("[video] mpv DLL installed successfully")
        return True
    except Exception as e:
        raise RuntimeError(f"Failed to acquire mpv DLL: {e}. {_MANUAL_HINT}") from e
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
