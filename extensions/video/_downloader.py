import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request

_LIB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib")
_DLL_NAME = "libmpv-2.dll"
_DLL_PATH = os.path.join(_LIB_DIR, _DLL_NAME)

_PINNED_TAG = "20260307"
_PINNED_ASSET = "mpv-dev-x86_64-20260307-git-f9190e5.7z"
_PINNED_URL = f"https://github.com/shinchiro/mpv-winbuild-cmake/releases/download/{_PINNED_TAG}/{_PINNED_ASSET}"
_ALLOWED_HOSTS = ("github.com", "objects.githubusercontent.com")

_7ZR_URL = "https://www.7-zip.org/a/7zr.exe"
_7ZR_PATH = os.path.join(_LIB_DIR, "7zr.exe")

_MANUAL_HINT = "Download libmpv-2.dll from https://sourceforge.net/projects/mpv-player-windows/files/libmpv/ and place it in plugins/video/lib/"


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


def _find_asset_url() -> str:
    return _PINNED_URL


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
    _log(f"[video] Downloading 7zr.exe from {_7ZR_URL}")
    os.makedirs(_LIB_DIR, exist_ok=True)
    _safe_download(_7ZR_URL, _7ZR_PATH)
    return _7ZR_PATH


def _run_7z(exe: str, archive_path: str):
    os.makedirs(_LIB_DIR, exist_ok=True)
    result = subprocess.run(
        [exe, "e", archive_path, f"-o{_LIB_DIR}", _DLL_NAME, "-r", "-y"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"7z extraction failed (rc={result.returncode}): {result.stderr.strip()}")
    if not os.path.isfile(_DLL_PATH):
        raise FileNotFoundError(f"{_DLL_NAME} not found after 7z extraction")


def _validate_archive_path(name: str, base_dir: str):
    resolved = os.path.normpath(os.path.join(base_dir, name))
    if not resolved.startswith(os.path.normpath(base_dir) + os.sep) and resolved != os.path.normpath(base_dir):
        raise ValueError(f"Path traversal detected: {name}")


def _extract_dll_py7zr(archive_path: str):
    import py7zr

    os.makedirs(_LIB_DIR, exist_ok=True)
    with py7zr.SevenZipFile(archive_path, "r") as z:
        all_names = z.getnames()
        for name in all_names:
            _validate_archive_path(name, _LIB_DIR)
        targets = [n for n in all_names if os.path.basename(n) == _DLL_NAME]
        if not targets:
            raise FileNotFoundError(f"{_DLL_NAME} not found in archive")
        z.extract(_LIB_DIR, targets)

    for t in targets:
        extracted = os.path.join(_LIB_DIR, t)
        final = _DLL_PATH
        if os.path.normpath(extracted) != os.path.normpath(final):
            shutil.move(extracted, final)
            parent = os.path.dirname(extracted)
            while os.path.normpath(parent) != os.path.normpath(_LIB_DIR):
                try:
                    os.rmdir(parent)
                except OSError:
                    break
                parent = os.path.dirname(parent)
        break


def _extract_dll(archive_path: str):
    try:
        _extract_dll_py7zr(archive_path)
        return
    except Exception as e:
        _log(f"[video] py7zr failed ({type(e).__name__}: {e}), trying external 7z", level="debug")
    exe = _find_7z_exe()
    if exe is None:
        exe = _ensure_7zr()
    _run_7z(exe, archive_path)


def _setup_dll_path():
    path_dirs = os.environ.get("PATH", "").split(os.pathsep)
    if _LIB_DIR not in path_dirs:
        os.environ["PATH"] = _LIB_DIR + os.pathsep + os.environ.get("PATH", "")
    if sys.platform == "win32" and hasattr(os, "add_dll_directory"):
        os.add_dll_directory(_LIB_DIR)


def ensure_mpv_dll():
    if os.path.isfile(_DLL_PATH):
        _setup_dll_path()
        return True
    tmp = tempfile.mkdtemp()
    try:
        url = _find_asset_url()
        if url is None:
            raise RuntimeError(f"mpv-dev asset not found. {_MANUAL_HINT}")
        _log(f"[video] Downloading mpv DLL: {url}")
        archive = os.path.join(tmp, "mpv-dev.7z")
        _safe_download(url, archive, allowed_hosts=_ALLOWED_HOSTS)
        _extract_dll(archive)
        _setup_dll_path()
        _log("[video] mpv DLL installed successfully")
        return True
    except Exception as e:
        raise RuntimeError(f"Failed to acquire mpv DLL: {e}. {_MANUAL_HINT}") from e
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
