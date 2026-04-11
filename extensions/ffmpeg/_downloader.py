import os
import shutil
import subprocess
import tempfile
import urllib.request

_LIB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib")
_FFPROBE_NAME = "ffprobe.exe"
_FFMPEG_NAME = "ffmpeg.exe"
_FFPROBE_PATH = os.path.join(_LIB_DIR, _FFPROBE_NAME)
_FFMPEG_PATH = os.path.join(_LIB_DIR, _FFMPEG_NAME)

_FFMPEG_VERSION = "8.1"
_ARCHIVE_URL = f"https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-{_FFMPEG_VERSION}-essentials_build.7z"
_ALLOWED_HOSTS = ("www.gyan.dev",)

_7ZR_URL = "https://www.7-zip.org/a/7zr.exe"
_7ZR_PATH = os.path.join(_LIB_DIR, "7zr.exe")

_BINARIES = (_FFPROBE_NAME, _FFMPEG_NAME)

_MANUAL_HINT = (
    f"Download ffmpeg essentials from https://www.gyan.dev/ffmpeg/builds/ "
    f"and place ffprobe.exe + ffmpeg.exe in extensions/ffmpeg/lib/"
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


def _find_7z_exe() -> str | None:
    if shutil.which("7z"):
        return "7z"
    for env_key in ("ProgramFiles", "ProgramFiles(x86)"):
        prog_dir = os.environ.get(env_key, "")
        if prog_dir:
            path = os.path.join(prog_dir, "7-Zip", "7z.exe")
            if os.path.isfile(path):
                return path
    return None


def _ensure_7zr() -> str:
    if os.path.isfile(_7ZR_PATH):
        return _7ZR_PATH
    _log(f"[ffmpeg] Downloading 7zr.exe from {_7ZR_URL}")
    os.makedirs(_LIB_DIR, exist_ok=True)
    _safe_download(_7ZR_URL, _7ZR_PATH)
    return _7ZR_PATH


def _run_7z(exe: str, archive_path: str):
    os.makedirs(_LIB_DIR, exist_ok=True)
    for name in _BINARIES:
        result = subprocess.run(
            [exe, "e", archive_path, f"-o{_LIB_DIR}", name, "-r", "-y"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"7z extraction failed for {name} (rc={result.returncode}): {result.stderr.strip()}")
    _verify_binaries()


def _validate_archive_path(name: str, base_dir: str):
    resolved = os.path.normpath(os.path.join(base_dir, name))
    if not resolved.startswith(os.path.normpath(base_dir) + os.sep) and resolved != os.path.normpath(base_dir):
        raise ValueError(f"Path traversal detected: {name}")


def _extract_py7zr(archive_path: str):
    import py7zr

    os.makedirs(_LIB_DIR, exist_ok=True)
    with py7zr.SevenZipFile(archive_path, "r") as z:
        all_names = z.getnames()
        for name in all_names:
            _validate_archive_path(name, _LIB_DIR)
        targets = [n for n in all_names if os.path.basename(n) in _BINARIES]
        if not targets:
            raise FileNotFoundError(f"ffprobe/ffmpeg not found in archive")
        z.extract(_LIB_DIR, targets)

    for t in targets:
        extracted = os.path.join(_LIB_DIR, t)
        final = os.path.join(_LIB_DIR, os.path.basename(t))
        if os.path.normpath(extracted) != os.path.normpath(final):
            shutil.move(extracted, final)
    _cleanup_subdirs()


def _cleanup_subdirs():
    for entry in os.listdir(_LIB_DIR):
        full = os.path.join(_LIB_DIR, entry)
        if os.path.isdir(full):
            try:
                shutil.rmtree(full)
            except OSError:
                pass


def _extract(archive_path: str):
    try:
        _extract_py7zr(archive_path)
        return
    except Exception as e:
        _log(f"[ffmpeg] py7zr failed ({type(e).__name__}: {e}), trying external 7z", level="debug")
    exe = _find_7z_exe()
    if exe is None:
        exe = _ensure_7zr()
    _run_7z(exe, archive_path)


def _verify_binaries():
    missing = [n for n in _BINARIES if not os.path.isfile(os.path.join(_LIB_DIR, n))]
    if missing:
        raise FileNotFoundError(f"Missing after extraction: {', '.join(missing)}")


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
        _log(f"[ffmpeg] Downloading ffmpeg essentials: {_ARCHIVE_URL}")
        archive = os.path.join(tmp, "ffmpeg-essentials.7z")
        _safe_download(_ARCHIVE_URL, archive, allowed_hosts=_ALLOWED_HOSTS)
        _extract(archive)
        _verify_binaries()
        _log("[ffmpeg] ffprobe + ffmpeg installed successfully")
        return True
    except Exception as e:
        raise RuntimeError(
            f"Failed to acquire ffmpeg: {e}. {_MANUAL_HINT}"
        ) from e
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
