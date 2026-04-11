import os
import platform
import shutil
import tempfile
import urllib.request
import zipfile

_LIB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib")
_EXIFTOOL_EXE = "exiftool.exe"
_EXIFTOOL_PATH = os.path.join(_LIB_DIR, _EXIFTOOL_EXE)

_EXIFTOOL_VERSION = "13.25"
_ARCHIVE_URL = f"https://sourceforge.net/projects/exiftool/files/exiftool-{_EXIFTOOL_VERSION}_64.zip/download"
_ALLOWED_HOSTS = ("sourceforge.net",)

_MANUAL_HINT = (
    "Download ExifTool from https://exiftool.org/ "
    "and place exiftool.exe + exiftool_files/ in extensions/exiftool/lib/"
)


def _log(msg, *, level="info", exc=None):
    try:
        from wafer.utils.logs import AppLogger

        fn = getattr(AppLogger, level, AppLogger.info)
        if exc and level in ("error", "warning"):
            fn(msg, exc=exc)
        else:
            fn(msg)
    except Exception:
        pass


def _validate_url(url: str, allowed_hosts: tuple[str, ...]) -> str:
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(f"Insecure URL scheme: {parsed.scheme}")
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL has no hostname")
    if not any(hostname == h or hostname.endswith("." + h) for h in allowed_hosts):
        raise ValueError(f"Untrusted host: {hostname}")
    return url


def _safe_download(url: str, dest: str, *, allowed_hosts: tuple[str, ...] | None = None):
    if allowed_hosts:
        _validate_url(url, allowed_hosts)
    tmp_dest = dest + ".tmp"
    try:
        urllib.request.urlretrieve(url, tmp_dest)
        shutil.move(tmp_dest, dest)
    finally:
        if os.path.isfile(tmp_dest):
            try:
                os.remove(tmp_dest)
            except OSError:
                pass


def _validate_archive_path(name: str, base_dir: str):
    resolved = os.path.normpath(os.path.join(base_dir, name))
    base = os.path.normpath(base_dir)
    if not resolved.startswith(base + os.sep) and resolved != base:
        raise ValueError(f"Path traversal detected: {name}")


def _extract(archive_path: str):
    os.makedirs(_LIB_DIR, exist_ok=True)
    with zipfile.ZipFile(archive_path, "r") as zf:
        for info in zf.infolist():
            _validate_archive_path(info.filename, _LIB_DIR)
        zf.extractall(_LIB_DIR)
    for name in os.listdir(_LIB_DIR):
        lower = name.lower()
        if lower.startswith("exiftool") and lower.endswith(".exe") and name != _EXIFTOOL_EXE:
            os.rename(os.path.join(_LIB_DIR, name), _EXIFTOOL_PATH)
            break


def get_exiftool_path() -> str | None:
    if os.path.isfile(_EXIFTOOL_PATH):
        return _EXIFTOOL_PATH
    system = shutil.which("exiftool")
    if system:
        return system
    return None


def ensure_exiftool():
    if os.path.isfile(_EXIFTOOL_PATH):
        return True
    if platform.system() != "Windows":
        if shutil.which("exiftool"):
            return True
        raise RuntimeError(
            "Auto-download is Windows-only. Install exiftool via package manager."
        )
    tmp = tempfile.mkdtemp()
    try:
        _log(f"[exiftool] Downloading ExifTool: {_ARCHIVE_URL}")
        archive = os.path.join(tmp, "exiftool.zip")
        _safe_download(_ARCHIVE_URL, archive, allowed_hosts=_ALLOWED_HOSTS)
        _extract(archive)
        if not os.path.isfile(_EXIFTOOL_PATH):
            raise FileNotFoundError(f"{_EXIFTOOL_EXE} not found after extraction")
        _log("[exiftool] ExifTool installed successfully")
        return True
    except Exception as e:
        raise RuntimeError(
            f"Failed to acquire ExifTool: {e}. {_MANUAL_HINT}"
        ) from e
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
