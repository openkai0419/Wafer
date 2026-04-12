import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import urlparse

from ..utils.logs import AppLogger

_DIR_NAME = "_python"
_PACKAGES_DIR = ".packages"
_SHARED_DIR = ".shared_packages"
_INSTALL_STAMP = ".installed"
_POST_INSTALL_STAMP = ".post_installed"

_PYTHON_VERSION = "3.10.9"
_PTH_NAME = "python310._pth"

_EMBED_DEFS = {
    "win_amd64": {
        "url": f"https://www.python.org/ftp/python/{_PYTHON_VERSION}/python-{_PYTHON_VERSION}-embed-amd64.zip",
        "sha256": "8712433e84811fb8fcf877beabe12f86cb843c94bb1cac62c43e2d717a87b2ad",
    },
}

_ALLOWED_HOSTS = frozenset({"www.python.org", "bootstrap.pypa.io"})
_MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024
_SUBPROCESS_POLL_INTERVAL = 0.05

_GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"
_GET_PIP_SHA256 = "feba1c697df45be1b539b40d93c102c9ee9dde1d966303323b830b06f3fbca3c"


def _platform_key() -> str | None:
    if sys.platform != "win32":
        return None
    import struct

    return "win_amd64" if struct.calcsize("P") * 8 == 64 else None


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _validate_url(url: str):
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(f"Only HTTPS URLs allowed: {url}")
    if parsed.hostname not in _ALLOWED_HOSTS:
        raise ValueError(f"Untrusted host: {parsed.hostname}")


def _download_file(url: str, dest: str, *, max_bytes: int = _MAX_DOWNLOAD_BYTES, on_progress=None):
    _validate_url(url)
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=60) as resp:
        length = int(resp.headers.get("Content-Length", 0))
        if length > max_bytes:
            raise ValueError(f"File too large: {length} > {max_bytes}")
        received = 0
        with open(dest, "wb") as f:
            while True:
                chunk = resp.read(8192)
                if not chunk:
                    break
                received += len(chunk)
                if received > max_bytes:
                    raise ValueError(f"Download exceeded {max_bytes} bytes")
                f.write(chunk)
                if on_progress:
                    on_progress()
    if received == 0:
        raise ValueError("Empty download")
    return received


def _run_subprocess(cmd: list[str], on_progress=None, timeout: int = 300, env=None):
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=env, **kwargs)
    stderr_chunks: list[bytes] = []

    def _drain():
        while True:
            data = proc.stderr.read(4096)
            if not data:
                break
            stderr_chunks.append(data)

    t = threading.Thread(target=_drain, daemon=True)
    t.start()
    deadline = time.monotonic() + timeout
    try:
        while proc.poll() is None:
            if time.monotonic() > deadline:
                proc.kill()
                raise TimeoutError(f"Command timed out after {timeout}s")
            if on_progress:
                on_progress()
            time.sleep(_SUBPROCESS_POLL_INTERVAL)
        t.join(timeout=5)
        if proc.returncode != 0:
            err = b"".join(stderr_chunks).decode(errors="replace")
            raise RuntimeError(f"Command failed (exit {proc.returncode}): {err[:1000]}")
    finally:
        if proc.stderr:
            proc.stderr.close()


class EmbeddedPython:
    def __init__(self, base_dir: str | None = None):
        if base_dir is None:
            from ..utils.paths import resolve_data_path

            base_dir = resolve_data_path(_DIR_NAME)
        self._dir = str(base_dir)
        self._exe = os.path.join(self._dir, "python.exe")

    @property
    def exe_path(self) -> str:
        return self._exe

    @property
    def is_available(self) -> bool:
        return os.path.isfile(self._exe)

    @property
    def has_pip(self) -> bool:
        return self.is_available and os.path.isfile(os.path.join(self._dir, "Scripts", "pip.exe"))

    @property
    def is_ready(self) -> bool:
        return self.is_available and self.has_pip

    def ensure_ready(self, on_progress=None) -> bool:
        if self.is_ready:
            return True
        key = _platform_key()
        if key is None:
            AppLogger.warning("[Installer] Unsupported platform for embedded Python")
            return False
        defn = _EMBED_DEFS.get(key)
        if defn is None:
            AppLogger.warning(f"[Installer] No embedded Python package for platform: {key}")
            return False
        try:
            if not self.is_available:
                self._download_and_extract(defn["url"], defn["sha256"], on_progress)
            if not self.has_pip:
                self._setup_pip(on_progress)
            return self.is_ready
        except Exception as e:
            AppLogger.error(f"[Installer] Setup failed: {e}", exc=e)
            return False

    def _download_and_extract(self, url: str, expected_hash: str, on_progress=None):
        os.makedirs(self._dir, exist_ok=True)
        fd, tmp = tempfile.mkstemp(suffix=".zip", dir=self._dir)
        try:
            os.close(fd)
            AppLogger.info(f"[Installer] Downloading embedded Python from {url}")
            _download_file(url, tmp, on_progress=on_progress)

            if expected_hash:
                actual = _sha256_file(tmp)
                if actual != expected_hash:
                    raise ValueError(f"SHA256 mismatch: expected {expected_hash}, got {actual}")
                AppLogger.info("[Installer] SHA256 verified")

            staging = tempfile.mkdtemp(dir=self._dir, prefix=".extract_")
            try:
                with zipfile.ZipFile(tmp, "r") as zf:
                    for info in zf.infolist():
                        norm = os.path.normpath(info.filename)
                        if norm.startswith("..") or os.path.isabs(norm):
                            raise ValueError(f"Path traversal detected in zip: {info.filename}")
                        if os.sep != "/":
                            norm = norm.replace("/", os.sep)
                        resolved = os.path.normpath(os.path.join(staging, norm))
                        if not resolved.startswith(staging):
                            raise ValueError(f"Path traversal detected in zip: {info.filename}")
                    zf.extractall(staging)
                for name in os.listdir(staging):
                    src = os.path.join(staging, name)
                    dst = os.path.join(self._dir, name)
                    if os.path.isdir(src):
                        if os.path.exists(dst):
                            shutil.rmtree(dst)
                        shutil.move(src, dst)
                    else:
                        shutil.move(src, dst)
            finally:
                if os.path.isdir(staging):
                    shutil.rmtree(staging, ignore_errors=True)
            AppLogger.info("[Installer] Extraction complete")
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def _setup_pip(self, on_progress=None):
        pth = os.path.join(self._dir, _PTH_NAME)
        if os.path.isfile(pth):
            text = Path(pth).read_text("utf-8")
            if "#import site" in text:
                text = text.replace("#import site", "import site")
                Path(pth).write_text(text, "utf-8")
        fd, get_pip = tempfile.mkstemp(suffix=".py", dir=self._dir)
        try:
            os.close(fd)
            AppLogger.info("[Installer] Downloading get-pip.py...")
            _download_file(_GET_PIP_URL, get_pip, on_progress=on_progress)
            actual = _sha256_file(get_pip)
            if actual != _GET_PIP_SHA256:
                raise ValueError(f"get-pip.py SHA256 mismatch: expected {_GET_PIP_SHA256}, got {actual}. Update _GET_PIP_SHA256 in installer.py if bootstrap.pypa.io has been updated.")
            AppLogger.info("[Installer] get-pip.py SHA256 verified")
            AppLogger.info("[Installer] Running get-pip.py...")
            _run_subprocess(
                [self._exe, get_pip, "--no-warn-script-location"],
                on_progress=on_progress,
                timeout=120,
            )
        finally:
            if os.path.exists(get_pip):
                os.unlink(get_pip)
        AppLogger.info("[Installer] pip enabled")

    def pip_install(self, req_file: str, target_dir: str, on_progress=None):
        if not self.is_ready:
            raise RuntimeError("Embedded Python is not ready")
        os.makedirs(target_dir, exist_ok=True)
        env = _pip_env(target_dir)
        _run_subprocess(
            [
                self._exe,
                "-m",
                "pip",
                "install",
                "--target",
                target_dir,
                "--upgrade",
                "-r",
                req_file,
                "--quiet",
                "--disable-pip-version-check",
                "--no-cache-dir",
            ],
            on_progress=on_progress,
            timeout=600,
            env=env,
        )


def _pip_env(target_dir: str) -> dict[str, str] | None:
    if sys.platform != "win32":
        return None
    target_drive = os.path.splitdrive(os.path.abspath(target_dir))[0]
    temp_drive = os.path.splitdrive(tempfile.gettempdir())[0]
    if target_drive.upper() == temp_drive.upper():
        return None
    tmp = os.path.join(target_drive + os.sep, "Temp", "pip_work")
    os.makedirs(tmp, exist_ok=True)
    env = os.environ.copy()
    env["TEMP"] = tmp
    env["TMP"] = tmp
    return env


def install_requirements(plugin_dir: str, on_progress=None) -> bool:
    vendor_dir = os.path.join(plugin_dir, _PACKAGES_DIR)
    req_file = os.path.join(plugin_dir, "requirements.txt")
    os.makedirs(vendor_dir, exist_ok=True)
    try:
        ep = EmbeddedPython()
        if not ep.ensure_ready(on_progress):
            return False
        ep.pip_install(req_file, vendor_dir, on_progress)
        Path(vendor_dir, _INSTALL_STAMP).touch()
        AppLogger.info(f"[Installer] Dependencies installed: {os.path.basename(plugin_dir)}")
        return True
    except Exception as e:
        AppLogger.warning(f"[Installer] Failed for {os.path.basename(plugin_dir)}: {e}", exc=e)
        return False


def install_packages(plugin_dir: str, packages: list[str], on_progress=None, no_deps: bool = False) -> bool:
    vendor_dir = os.path.join(plugin_dir, _PACKAGES_DIR)
    os.makedirs(vendor_dir, exist_ok=True)
    try:
        ep = EmbeddedPython()
        if not ep.ensure_ready(on_progress):
            return False
        if not ep.is_ready:
            raise RuntimeError("Embedded Python is not ready")
        env = _pip_env(vendor_dir)
        cmd = [
            ep.exe_path,
            "-m",
            "pip",
            "install",
            "--target",
            vendor_dir,
            "--upgrade",
            *packages,
            "--quiet",
            "--disable-pip-version-check",
            "--no-cache-dir",
        ]
        if no_deps:
            cmd.append("--no-deps")
        _run_subprocess(
            cmd,
            on_progress=on_progress,
            timeout=600,
            env=env,
        )
        AppLogger.info(f"[Installer] Packages installed to {os.path.basename(plugin_dir)}: {packages}")
        return True
    except Exception as e:
        AppLogger.warning(f"[Installer] Package install failed for {os.path.basename(plugin_dir)}: {e}", exc=e)
        return False


def write_post_install_stamp(plugin_dir: str):
    vendor_dir = os.path.join(plugin_dir, _PACKAGES_DIR)
    os.makedirs(vendor_dir, exist_ok=True)
    Path(vendor_dir, _POST_INSTALL_STAMP).touch()


def needs_install(plugin_dir: str) -> bool:
    req_file = os.path.join(plugin_dir, "requirements.txt")
    if not os.path.isfile(req_file):
        return False
    vendor_dir = os.path.join(plugin_dir, _PACKAGES_DIR)
    stamp = os.path.join(vendor_dir, _INSTALL_STAMP)
    if not os.path.isfile(stamp):
        return True
    return os.path.getmtime(req_file) > os.path.getmtime(stamp)


def needs_post_install(plugin_dir: str) -> bool:
    req_file = os.path.join(plugin_dir, "requirements.txt")
    if not os.path.isfile(req_file):
        return False
    vendor_dir = os.path.join(plugin_dir, _PACKAGES_DIR)
    stamp = os.path.join(vendor_dir, _POST_INSTALL_STAMP)
    return not os.path.isfile(stamp)


def needs_setup(plugin_dir: str) -> bool:
    return needs_install(plugin_dir) or needs_post_install(plugin_dir)


def has_post_install_hooks(plugins: list[tuple[str, type]]) -> bool:
    from .registry import PluginBase

    return any(hasattr(cls, "post_install") and cls.post_install.__func__ is not PluginBase.post_install.__func__ for _, cls in plugins)


def install_extension(
    plugin_dir: str,
    extensions_dir: str,
    on_progress=None,
    is_cancelled=None,
) -> tuple[bool, bool, list[tuple[str, type]]]:
    if needs_install(plugin_dir):
        if shared_needs_install(extensions_dir):
            if not install_shared_requirements(extensions_dir, on_progress):
                return False, False, []
        if is_cancelled and is_cancelled():
            return False, False, []
        if not install_requirements(plugin_dir, on_progress):
            return False, False, []

    if is_cancelled and is_cancelled():
        return False, False, []

    from .loader import PluginLoader

    plugins = PluginLoader.discover_extension(plugin_dir)

    vendor_dir = os.path.join(plugin_dir, _PACKAGES_DIR)
    shared_dir = os.path.join(extensions_dir, _SHARED_DIR)
    path_added = []
    for d in (vendor_dir, shared_dir):
        if os.path.isdir(d) and d not in sys.path:
            sys.path.insert(0, d)
            path_added.append(d)

    post_install_ok = True
    for _key, cls in plugins:
        if has_post_install_hooks([(_key, cls)]):
            try:
                cls.post_install(plugin_dir)
            except Exception as e:
                AppLogger.warning(f"[Installer] post_install failed: {cls.__name__}", exc=e)
                post_install_ok = False
                break
        if is_cancelled and is_cancelled():
            return False, False, []

    for d in path_added:
        if d in sys.path:
            sys.path.remove(d)

    if post_install_ok:
        write_post_install_stamp(plugin_dir)

    return True, post_install_ok, plugins


def shared_needs_install(extensions_dir: str) -> bool:
    req_file = os.path.join(extensions_dir, "requirements.txt")
    if not os.path.isfile(req_file):
        return False
    stamp = os.path.join(extensions_dir, _SHARED_DIR, _INSTALL_STAMP)
    if not os.path.isfile(stamp):
        return True
    return os.path.getmtime(req_file) > os.path.getmtime(stamp)


_shared_install_lock = threading.Lock()


def install_shared_requirements(extensions_dir: str, on_progress=None) -> bool:
    req_file = os.path.join(extensions_dir, "requirements.txt")
    if not os.path.isfile(req_file):
        return True
    with _shared_install_lock:
        if not shared_needs_install(extensions_dir):
            return True
        vendor_dir = os.path.join(extensions_dir, _SHARED_DIR)
        os.makedirs(vendor_dir, exist_ok=True)
        try:
            ep = EmbeddedPython()
            if not ep.ensure_ready(on_progress):
                return False
            ep.pip_install(req_file, vendor_dir, on_progress)
            Path(vendor_dir, _INSTALL_STAMP).touch()
            AppLogger.info("[Installer] Shared dependencies installed")
            return True
        except Exception as e:
            AppLogger.warning(f"[Installer] Shared install failed: {e}", exc=e)
            return False
