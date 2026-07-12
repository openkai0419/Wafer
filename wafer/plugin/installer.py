import importlib
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from enum import Enum, Flag, auto
from pathlib import Path
from collections.abc import Iterable

from ..utils.hashes import sha256_file
from ..utils.logs import AppLogger


class RestartScope(Flag):
    NONE = 0
    VIEWER = auto()
    TRAY = auto()
    ALL = VIEWER | TRAY


_SCOPE_TO_RESTART = {"tray": RestartScope.TRAY, "*": RestartScope.ALL}


def restart_scope_of(cls: type) -> RestartScope:
    return _SCOPE_TO_RESTART.get(getattr(cls, "SCOPE", "viewer"), RestartScope.VIEWER)


def restart_scope_from_plugins(plugins: Iterable[type]) -> RestartScope:
    scope = RestartScope.NONE
    for cls in plugins:
        scope |= restart_scope_of(cls)
    return scope


class InstallState(Enum):
    NO_DEPS = "no_deps"
    NOT_INSTALLED = "not_installed"
    NEEDS_POST_INSTALL = "needs_post_install"
    INSTALLED = "installed"


class InstallerCancelled(Exception):
    pass


@dataclass
class InstallResult:
    success: bool = False
    post_install_ok: bool = True
    cancelled: bool = False
    plugins: list[tuple[str, type]] = field(default_factory=list)


_PACKAGES_DIR = ".packages"
_STAMPS_DIR = ".stamps"
_PYTHON_VERSION_STAMP = ".python_version"
_LEGACY_DIRS = (".pending", ".pip_staging")

_SUBPROCESS_POLL_INTERVAL = 0.05

_POST_INSTALL_VERSION_RE = re.compile(r'^\s*POST_INSTALL_VERSION\s*=\s*["\']([^"\']*)["\']', re.MULTILINE)

_packages_lock = threading.Lock()


def _python_version() -> str:
    return platform.python_version()


def _packages_dir(extensions_dir: str) -> str:
    return os.path.join(extensions_dir, _PACKAGES_DIR)


def _stamps_dir(extensions_dir: str) -> str:
    return os.path.join(_packages_dir(extensions_dir), _STAMPS_DIR)


def cleanup_legacy_dirs(extensions_dir: str) -> None:
    for name in _LEGACY_DIRS:
        path = os.path.join(extensions_dir, name)
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
            AppLogger.info(f"[Installer] Removed legacy directory: {path}")


def _extensions_dir_from_plugin(plugin_dir: str) -> str:
    return os.path.dirname(plugin_dir)


def _stamp_path(plugin_dir: str, suffix: str) -> str:
    ext_dir = _extensions_dir_from_plugin(plugin_dir)
    name = os.path.basename(plugin_dir)
    return os.path.join(_stamps_dir(ext_dir), f"{name}{suffix}")


def _run_subprocess(cmd: list[str], on_progress=None, on_log=None, timeout: int = 0, is_cancelled=None, env=None):
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        **kwargs,
    )
    stderr_chunks: list[bytes] = []
    line_buf: list[str] = []
    buf_lock = threading.Lock()

    def _drain_stderr():
        while True:
            data = proc.stderr.read(4096)
            if not data:
                break
            stderr_chunks.append(data)

    def _drain_stdout():
        for raw in proc.stdout:
            line = raw.decode(errors="replace").rstrip("\n\r")
            if line:
                AppLogger.debug(f"[pip] {line}")
                if on_log:
                    with buf_lock:
                        line_buf.append(line)

    t_err = threading.Thread(target=_drain_stderr, daemon=True)
    t_out = threading.Thread(target=_drain_stdout, daemon=True)
    t_err.start()
    t_out.start()
    deadline = (time.monotonic() + timeout) if timeout > 0 else None
    try:
        while proc.poll() is None:
            if is_cancelled and is_cancelled():
                proc.kill()
                raise InstallerCancelled("Installation cancelled by user")
            if deadline and time.monotonic() > deadline:
                proc.kill()
                raise TimeoutError(f"Command timed out after {timeout}s")
            if on_log:
                with buf_lock:
                    lines = list(line_buf)
                    line_buf.clear()
                for ln in lines:
                    on_log(ln)
            if on_progress:
                on_progress()
            time.sleep(_SUBPROCESS_POLL_INTERVAL)
        t_err.join(timeout=5)
        t_out.join(timeout=5)
        if on_log:
            with buf_lock:
                for ln in line_buf:
                    on_log(ln)
                line_buf.clear()
        if proc.returncode != 0:
            err = b"".join(stderr_chunks).decode(errors="replace")
            raise RuntimeError(f"Command failed (exit {proc.returncode}): {err[-2000:]}")
    finally:
        if proc.stdout:
            proc.stdout.close()
        if proc.stderr:
            proc.stderr.close()


class EmbeddedPython:
    def __init__(self):
        self._exe = sys.executable

    @property
    def exe_path(self) -> str:
        return self._exe

    @property
    def is_ready(self) -> bool:
        return os.path.isfile(self._exe)

    def pip_install(self, req_file: str, target_dir: str, on_progress=None, is_cancelled=None, context: str = "", on_log=None) -> None:
        os.makedirs(target_dir, exist_ok=True)
        _run_subprocess(
            [
                self._exe,
                "-m",
                "pip",
                "install",
                "--target",
                target_dir,
                "-r",
                req_file,
                "--upgrade",
                "--upgrade-strategy",
                "only-if-needed",
                "--disable-pip-version-check",
            ],
            on_progress=on_progress,
            on_log=on_log,
            is_cancelled=is_cancelled,
        )
        importlib.invalidate_caches()
        if context:
            AppLogger.info(f"[Installer] pip install complete: {context}")


def _ensure_python_version(extensions_dir: str):
    stamps = _stamps_dir(extensions_dir)
    os.makedirs(stamps, exist_ok=True)
    ver_file = os.path.join(stamps, _PYTHON_VERSION_STAMP)
    if os.path.isfile(ver_file) and _stamp_version_matches(ver_file):
        return
    pkg_dir = _packages_dir(extensions_dir)
    if os.path.isdir(pkg_dir):
        AppLogger.info(f"[Installer] Python version changed, purging {pkg_dir}")
        shutil.rmtree(pkg_dir, ignore_errors=True)
    os.makedirs(stamps, exist_ok=True)
    _write_install_stamp(ver_file, _python_version())


def install_requirements(plugin_dir: str, extensions_dir: str, on_progress=None, is_cancelled=None, on_log=None) -> bool:
    pkg_dir = _packages_dir(extensions_dir)
    req_file = os.path.join(plugin_dir, "requirements.txt")
    with _packages_lock:
        _ensure_python_version(extensions_dir)
        if not os.path.isfile(req_file):
            _write_install_stamp(_stamp_path(plugin_dir, ".installed"), "")
            return True
        try:
            ep = EmbeddedPython()
            ep.pip_install(req_file, pkg_dir, on_progress=on_progress, is_cancelled=is_cancelled, context=os.path.basename(plugin_dir), on_log=on_log)
            _write_install_stamp(_stamp_path(plugin_dir, ".installed"), _requirements_hash(req_file))
            AppLogger.info(f"[Installer] Dependencies installed: {os.path.basename(plugin_dir)}")
            return True
        except Exception as e:
            AppLogger.warning(f"[Installer] Failed for {os.path.basename(plugin_dir)}: {e}", exc=e)
            return False


def write_post_install_stamp(plugin_dir: str):
    stamp = _stamp_path(plugin_dir, ".post_installed")
    _write_install_stamp(stamp, declared_post_install_version(plugin_dir))


def declared_post_install_version(plugin_dir: str) -> str:
    try:
        for path in sorted(Path(plugin_dir).glob("*.py")):
            match = _POST_INSTALL_VERSION_RE.search(path.read_text("utf-8", errors="replace"))
            if match:
                return match.group(1).strip()
    except OSError as e:
        AppLogger.warning(f"[Installer] Failed to read POST_INSTALL_VERSION in {plugin_dir}: {e}", exc=e)
    return ""


def _requirements_hash(req_file: str) -> str:
    try:
        return sha256_file(req_file)
    except OSError as e:
        AppLogger.warning(f"[Installer] Failed to hash {req_file}: {e}", exc=e)
        return ""


def _write_install_stamp(stamp_path: str, content: str):
    os.makedirs(os.path.dirname(stamp_path), exist_ok=True)
    Path(stamp_path).write_text(content, "utf-8")


def _read_stamp(stamp_path: str) -> str | None:
    try:
        return Path(stamp_path).read_text("utf-8").strip()
    except OSError:
        return None


def _stamp_version_matches(stamp_path: str) -> bool:
    return _read_stamp(stamp_path) == _python_version()


def needs_install(plugin_dir: str) -> bool:
    req_file = os.path.join(plugin_dir, "requirements.txt")
    if not os.path.isfile(req_file):
        return False
    extensions_dir = _extensions_dir_from_plugin(plugin_dir)
    ver_stamp = os.path.join(_stamps_dir(extensions_dir), _PYTHON_VERSION_STAMP)
    if os.path.isfile(ver_stamp) and not _stamp_version_matches(ver_stamp):
        return True
    stamp = _read_stamp(_stamp_path(plugin_dir, ".installed"))
    return stamp is None or stamp != _requirements_hash(req_file)


def needs_post_install(plugin_dir: str) -> bool:
    req_file = os.path.join(plugin_dir, "requirements.txt")
    if not os.path.isfile(req_file):
        return False
    stamp = _read_stamp(_stamp_path(plugin_dir, ".post_installed"))
    return stamp is None or stamp != declared_post_install_version(plugin_dir)


def needs_setup(plugin_dir: str) -> bool:
    return needs_install(plugin_dir) or needs_post_install(plugin_dir)


def resolve_install_state(plugin_dir: str) -> InstallState:
    req_file = os.path.join(plugin_dir, "requirements.txt")
    if not os.path.isfile(req_file):
        return InstallState.NO_DEPS
    if needs_install(plugin_dir):
        return InstallState.NOT_INSTALLED
    if needs_post_install(plugin_dir):
        return InstallState.NEEDS_POST_INSTALL
    return InstallState.INSTALLED


def has_post_install_hooks(plugins: list[tuple[str, type]]) -> bool:
    from .registry import PluginBase

    return any(hasattr(cls, "post_install") and cls.post_install.__func__ is not PluginBase.post_install.__func__ for _, cls in plugins)


def install_extension(
    plugin_dir: str,
    extensions_dir: str,
    on_progress=None,
    is_cancelled=None,
    on_phase=None,
    on_log=None,
) -> InstallResult:
    result = install_requirements_only(plugin_dir, extensions_dir, on_progress=on_progress, is_cancelled=is_cancelled, on_phase=on_phase, on_log=on_log)
    if not result.success or result.cancelled:
        return result
    return run_post_install(plugin_dir, extensions_dir, on_progress=on_progress, is_cancelled=is_cancelled, on_phase=on_phase, on_log=on_log, base_result=result)


def install_requirements_only(
    plugin_dir: str,
    extensions_dir: str,
    on_progress=None,
    is_cancelled=None,
    on_phase=None,
    on_log=None,
) -> InstallResult:
    result = InstallResult()
    if needs_install(plugin_dir):
        if is_cancelled and is_cancelled():
            result.cancelled = True
            return result
        if on_phase:
            on_phase("installing")
        if on_progress:
            on_progress(phase="Installing dependencies\u2026")
        try:
            success = install_requirements(plugin_dir, extensions_dir, on_progress, is_cancelled=is_cancelled, on_log=on_log)
        except InstallerCancelled:
            result.cancelled = True
            return result
        if not success:
            return result
    result.success = True
    return result


def run_post_install(
    plugin_dir: str,
    extensions_dir: str,
    on_progress=None,
    is_cancelled=None,
    on_phase=None,
    on_log=None,
    base_result: InstallResult | None = None,
) -> InstallResult:
    result = base_result or InstallResult(success=True)

    if is_cancelled and is_cancelled():
        result.cancelled = True
        result.success = False
        return result

    from .loader import PluginLoader

    plugins = PluginLoader.discover_extension(plugin_dir)

    pkg_dir = _packages_dir(extensions_dir)
    path_added = []
    if os.path.isdir(pkg_dir) and pkg_dir not in sys.path:
        sys.path.insert(0, pkg_dir)
        path_added.append(pkg_dir)

    post_install_ok = True
    has_hooks = has_post_install_hooks(plugins)
    if has_hooks and on_phase:
        on_phase("post_installing")
    for _key, cls in plugins:
        if has_post_install_hooks([(_key, cls)]):
            try:
                cls.post_install(plugin_dir, on_progress=on_progress, is_cancelled=is_cancelled, on_log=on_log)
            except InstallerCancelled:
                result.cancelled = True
                result.success = False
                for d in path_added:
                    if d in sys.path:
                        sys.path.remove(d)
                return result
            except Exception as e:
                AppLogger.warning(f"[Installer] post_install failed: {cls.__name__}", exc=e)
                post_install_ok = False
                break
        if is_cancelled and is_cancelled():
            result.cancelled = True
            result.success = False
            for d in path_added:
                if d in sys.path:
                    sys.path.remove(d)
            return result

    for d in path_added:
        if d in sys.path:
            sys.path.remove(d)

    if post_install_ok:
        write_post_install_stamp(plugin_dir)

    result.success = True
    result.post_install_ok = post_install_ok
    result.plugins = plugins
    return result
