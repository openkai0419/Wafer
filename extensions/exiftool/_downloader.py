import os
import platform
import re
import shutil
import tempfile
import zipfile

from wafer.utils.downloader import (
    safe_download,
    fetch_text,
    validate_archive_path,
    lib_needs_download,
    write_lib_version,
)


_LIB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib")
_EXIFTOOL_EXE = "exiftool.exe"
_EXIFTOOL_PATH = os.path.join(_LIB_DIR, _EXIFTOOL_EXE)
_EXIFTOOL_PL = os.path.join(_LIB_DIR, "exiftool_files", "exiftool.pl")

_VERSION_URL = "https://exiftool.org/ver.txt"
_ARCHIVE_URL_TEMPLATE = "https://sourceforge.net/projects/exiftool/files/exiftool-{version}_64.zip/download"
_CHECKSUMS_URL_TEMPLATE = "https://exiftool.org/checksums-{version}.txt"
_ALLOWED_HOSTS = ("exiftool.org", "sourceforge.net")
_VERSION_PATTERN = re.compile(r"^\d+\.\d+$")
_MAX_VERSION_RESPONSE = 64
_MAX_CHECKSUMS_RESPONSE = 16 * 1024
_USER_AGENT = "wafer-exiftool-plugin"

_MANUAL_HINT = "Download ExifTool from https://exiftool.org/ and place exiftool.exe + exiftool_files/ in extensions/exiftool/lib/"


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


def _extract(archive_path: str):
    tmp = tempfile.mkdtemp()
    try:
        with zipfile.ZipFile(archive_path, "r") as zf:
            for info in zf.infolist():
                validate_archive_path(info.filename, tmp)
            zf.extractall(tmp)
        src = tmp
        entries = os.listdir(tmp)
        if len(entries) == 1:
            nested = os.path.join(tmp, entries[0])
            if os.path.isdir(nested):
                src = nested
        os.makedirs(_LIB_DIR, exist_ok=True)
        for item in os.listdir(src):
            dst = os.path.join(_LIB_DIR, item)
            if os.path.isdir(dst):
                shutil.rmtree(dst)
            elif os.path.exists(dst):
                os.remove(dst)
            shutil.move(os.path.join(src, item), dst)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    for name in os.listdir(_LIB_DIR):
        lower = name.lower()
        if lower.startswith("exiftool") and lower.endswith(".exe") and name != _EXIFTOOL_EXE:
            os.rename(os.path.join(_LIB_DIR, name), _EXIFTOOL_PATH)
            break


def _is_bundled_install_valid() -> bool:
    return os.path.isfile(_EXIFTOOL_PATH) and os.path.isfile(_EXIFTOOL_PL)


def get_exiftool_path() -> str | None:
    if _is_bundled_install_valid():
        return _EXIFTOOL_PATH
    system = shutil.which("exiftool")
    if system:
        return system
    return None


def _fetch_latest_version() -> str:
    text = fetch_text(
        _VERSION_URL,
        allowed_hosts=_ALLOWED_HOSTS,
        max_bytes=_MAX_VERSION_RESPONSE,
        user_agent=_USER_AGENT,
        timeout=15,
    ).strip()
    if not _VERSION_PATTERN.match(text):
        raise RuntimeError(f"Unexpected version format: {text!r}")
    return text


def _fetch_expected_sha256(version: str) -> str:
    url = _CHECKSUMS_URL_TEMPLATE.format(version=version)
    text = fetch_text(
        url,
        allowed_hosts=_ALLOWED_HOSTS,
        max_bytes=_MAX_CHECKSUMS_RESPONSE,
        user_agent=_USER_AGENT,
    )
    pattern = re.compile(
        rf"^SHA2-256\(exiftool-{re.escape(version)}_64\.zip\)=\s*([0-9a-fA-F]{{64}})\s*$",
        re.MULTILINE,
    )
    m = pattern.search(text)
    if m is None:
        raise RuntimeError(f"checksums-{version}.txt missing SHA2-256 line for exiftool-{version}_64.zip")
    return m.group(1).lower()


def ensure_exiftool(version: str = ""):
    if not lib_needs_download(_LIB_DIR, version, _EXIFTOOL_PATH, _EXIFTOOL_PL):
        write_lib_version(_LIB_DIR, version)
        return True
    if os.path.isfile(_EXIFTOOL_PATH) and not os.path.isfile(_EXIFTOOL_PL):
        _log("[exiftool] exiftool.exe found but exiftool.pl missing — removing broken install", level="warning")
        try:
            os.remove(_EXIFTOOL_PATH)
        except OSError:
            pass
    if platform.system() != "Windows":
        if shutil.which("exiftool"):
            return True
        raise RuntimeError("Auto-download is Windows-only. Install exiftool via package manager.")
    tmp = tempfile.mkdtemp()
    try:
        remote_version = _fetch_latest_version()
        archive_url = _ARCHIVE_URL_TEMPLATE.format(version=remote_version)
        _log(f"[exiftool] Fetching checksum for v{remote_version}")
        expected = _fetch_expected_sha256(remote_version)
        _log(f"[exiftool] Downloading ExifTool v{remote_version}: {archive_url}")
        archive = os.path.join(tmp, "exiftool.zip")
        safe_download(archive_url, archive, allowed_hosts=_ALLOWED_HOSTS, expected_sha256=expected)
        _log("[exiftool] archive checksum verified")
        _extract(archive)
        if not os.path.isfile(_EXIFTOOL_PATH):
            raise FileNotFoundError(f"{_EXIFTOOL_EXE} not found after extraction")
        write_lib_version(_LIB_DIR, version)
        _log("[exiftool] ExifTool installed successfully")
        return True
    except Exception as e:
        raise RuntimeError(f"Failed to acquire ExifTool: {e}. {_MANUAL_HINT}") from e
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
