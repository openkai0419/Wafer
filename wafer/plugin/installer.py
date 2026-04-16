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
    deferred: bool = False
    post_install_ok: bool = True
    cancelled: bool = False
    plugins: list[tuple[str, type]] = field(default_factory=list)


_PACKAGES_DIR = ".packages"
_STAMPS_DIR = ".stamps"
_PIP_STAGING = ".pip_staging"
_PENDING_DIR = ".pending"
_PYTHON_VERSION_STAMP = ".python_version"

_SUBPROCESS_POLL_INTERVAL = 0.05

_packages_lock = threading.Lock()


def _python_version() -> str:
    return platform.python_version()


def _packages_dir(extensions_dir: str) -> str:
    return os.path.join(extensions_dir, _PACKAGES_DIR)


def _pending_dir(extensions_dir: str) -> str:
    return os.path.join(extensions_dir, _PENDING_DIR)


def _stamps_dir(extensions_dir: str) -> str:
    return os.path.join(_packages_dir(extensions_dir), _STAMPS_DIR)


def _extensions_dir_from_plugin(plugin_dir: str) -> str:
    return os.path.dirname(plugin_dir)


def _stamp_path(plugin_dir: str, suffix: str) -> str:
    ext_dir = _extensions_dir_from_plugin(plugin_dir)
    name = os.path.basename(plugin_dir)
    return os.path.join(_stamps_dir(ext_dir), f"{name}{suffix}")


def _run_subprocess(cmd: list[str], on_progress=None, timeout: int = 0, is_cancelled=None, env=None):
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
    deadline = (time.monotonic() + timeout) if timeout > 0 else None
    try:
        while proc.poll() is None:
            if is_cancelled and is_cancelled():
                proc.kill()
                raise InstallerCancelled("Installation cancelled by user")
            if deadline and time.monotonic() > deadline:
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
    def __init__(self):
        self._exe = sys.executable

    @property
    def exe_path(self) -> str:
        return self._exe

    @property
    def is_ready(self) -> bool:
        return os.path.isfile(self._exe)

    def pip_install(self, req_file: str, target_dir: str, extensions_dir: str, on_progress=None, is_cancelled=None) -> bool:
        os.makedirs(target_dir, exist_ok=True)
        staging = os.path.join(os.path.dirname(target_dir), _PIP_STAGING)
        _reset_staging(staging)
        try:
            _run_subprocess(
                [
                    self._exe,
                    "-m",
                    "pip",
                    "install",
                    "--target",
                    staging,
                    "-r",
                    req_file,
                    "--quiet",
                    "--disable-pip-version-check",
                    "--no-cache-dir",
                ],
                on_progress=on_progress,
                is_cancelled=is_cancelled,
            )
            return _merge_or_defer(staging, target_dir, extensions_dir)
        finally:
            if os.path.isdir(staging):
                shutil.rmtree(staging, ignore_errors=True)


def _reset_staging(path: str):
    if os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)
    os.makedirs(path, exist_ok=True)


def _merge_dir(src: str, dst: str):
    os.makedirs(dst, exist_ok=True)
    for entry in os.scandir(src):
        dst_path = os.path.join(dst, entry.name)
        if entry.is_dir(follow_symlinks=False):
            if os.path.isdir(dst_path):
                _merge_dir(entry.path, dst_path)
            else:
                shutil.copytree(entry.path, dst_path, dirs_exist_ok=True)
        else:
            shutil.copy2(entry.path, dst_path)


def _has_locked_files(src: str, dst: str) -> bool:
    if not os.path.isdir(dst):
        return False
    for entry in os.scandir(src):
        dst_path = os.path.join(dst, entry.name)
        if entry.is_dir(follow_symlinks=False):
            if _has_locked_files(entry.path, dst_path):
                return True
        elif os.path.isfile(dst_path):
            try:
                with open(dst_path, "a+b"):
                    pass
            except PermissionError:
                return True
    return False


def _is_locked(path: str) -> bool:
    try:
        with open(path, "a+b"):
            return False
    except PermissionError:
        return True


_DIST_INFO_RE = re.compile(r"^(.+?)(-\d[^-]*)\.dist-info$")


def _dist_info_base_name(dirname: str) -> str | None:
    m = _DIST_INFO_RE.match(dirname)
    return _normalize_pkg_name(m.group(1)) if m else None


def _remove_stale_packages(staging: str, target: str):
    if not os.path.isdir(target):
        return
    incoming_names: set[str] = set()
    incoming_bases: set[str] = set()
    for entry in os.scandir(staging):
        incoming_names.add(entry.name)
        base = _dist_info_base_name(entry.name)
        if base:
            incoming_bases.add(base)
        else:
            incoming_bases.add(_normalize_pkg_name(entry.name))
    for entry in os.scandir(target):
        if entry.name.startswith("."):
            continue
        base = _dist_info_base_name(entry.name)
        if base is not None:
            if base in incoming_bases and entry.name not in incoming_names:
                shutil.rmtree(entry.path, ignore_errors=True) if entry.is_dir() else os.remove(entry.path)
        elif entry.name in incoming_names:
            if entry.is_dir(follow_symlinks=False) and not _has_locked_files(os.path.join(staging, entry.name), entry.path):
                shutil.rmtree(entry.path, ignore_errors=True)


def _merge_or_defer(staging: str, target: str, extensions_dir: str) -> bool:
    _remove_stale_packages(staging, target)
    has_deferred = False
    pending = _pending_dir(extensions_dir)
    for entry in os.scandir(staging):
        dst_path = os.path.join(target, entry.name)
        if entry.is_dir(follow_symlinks=False):
            if _has_locked_files(entry.path, dst_path):
                pending_dst = os.path.join(pending, entry.name)
                os.makedirs(pending_dst, exist_ok=True)
                _merge_dir(entry.path, pending_dst)
                has_deferred = True
            else:
                os.makedirs(dst_path, exist_ok=True)
                _merge_dir(entry.path, dst_path)
        elif os.path.isfile(dst_path) and _is_locked(dst_path):
            os.makedirs(pending, exist_ok=True)
            shutil.copy2(entry.path, os.path.join(pending, entry.name))
            has_deferred = True
        else:
            os.makedirs(target, exist_ok=True)
            shutil.copy2(entry.path, dst_path)
    if has_deferred:
        AppLogger.info("[Installer] Locked files detected, partial updates deferred to next restart")
    else:
        importlib.invalidate_caches()
    return not has_deferred


def apply_pending_packages(extensions_dir: str) -> bool:
    pending = _pending_dir(extensions_dir)
    if not os.path.isdir(pending):
        return False
    target = _packages_dir(extensions_dir)
    applied = 0
    failed_names: set[str] = set()
    with os.scandir(pending) as entries:
        for entry in entries:
            dst_path = os.path.join(target, entry.name)
            try:
                if entry.is_dir(follow_symlinks=False):
                    os.makedirs(dst_path, exist_ok=True)
                    _merge_dir(entry.path, dst_path)
                else:
                    os.makedirs(target, exist_ok=True)
                    shutil.copy2(entry.path, dst_path)
                applied += 1
            except PermissionError:
                AppLogger.warning(f"[Installer] Still locked, skipping pending: {entry.name}")
                failed_names.add(entry.name)
            except Exception as e:
                AppLogger.warning(f"[Installer] Failed to apply pending: {entry.name}", exc=e)
                failed_names.add(entry.name)
    if not failed_names:
        shutil.rmtree(pending, ignore_errors=True)
    else:
        for entry in os.scandir(pending):
            if entry.name in failed_names:
                continue
            try:
                if entry.is_dir(follow_symlinks=False):
                    shutil.rmtree(entry.path, ignore_errors=True)
                else:
                    os.remove(entry.path)
            except OSError:
                pass
    if applied > 0:
        importlib.invalidate_caches()
        AppLogger.info(f"[Installer] Pending package updates applied ({applied} entries)")
    return applied > 0


def has_pending_packages(extensions_dir: str) -> bool:
    pending = _pending_dir(extensions_dir)
    if not os.path.isdir(pending):
        return False
    with os.scandir(pending) as it:
        return any(it)


_REQ_LINE_RE = re.compile(r"^([A-Za-z0-9][\w.\-]*)")
_PIN_RE = re.compile(r"==\s*([\d][^\s,;]*)")


def _normalize_pkg_name(name: str) -> str:
    return re.sub(r"[\-_.]+", "-", name).lower()


def _parse_version_tuple(ver: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", ver))


def _merge_requirements(req_files: list[str]) -> list[str]:
    packages: dict[str, list[tuple[str, str]]] = {}
    for path in req_files:
        if not os.path.isfile(path):
            continue
        for raw_line in Path(path).read_text("utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            m = _REQ_LINE_RE.match(line)
            if not m:
                continue
            key = _normalize_pkg_name(m.group(1))
            packages.setdefault(key, []).append((line, path))

    merged: list[str] = []
    for key, entries in packages.items():
        pinned: list[tuple[str, str, str]] = []
        unpinned: list[str] = []
        for line, src in entries:
            pm = _PIN_RE.search(line)
            if pm:
                pinned.append((line, pm.group(1), src))
            else:
                unpinned.append(line)

        if pinned:
            best_line, best_ver = pinned[0][0], pinned[0][1]
            best_tuple = _parse_version_tuple(best_ver)
            for line, ver, src in pinned[1:]:
                ver_tuple = _parse_version_tuple(ver)
                if ver_tuple > best_tuple:
                    AppLogger.info(f"[Installer] Version merge: {key} {best_ver} → {ver} (taking higher from {os.path.basename(os.path.dirname(src))})")
                    best_line, best_ver, best_tuple = line, ver, ver_tuple
            merged.append(best_line)
        elif unpinned:
            merged.append(unpinned[0])
    return merged


def _collect_installed_extensions(extensions_dir: str) -> list[str]:
    stamps = _stamps_dir(extensions_dir)
    if not os.path.isdir(stamps):
        return []
    installed = []
    for f in os.listdir(stamps):
        if f.endswith(".installed"):
            name = f[: -len(".installed")]
            folder = os.path.join(extensions_dir, name)
            req = os.path.join(folder, "requirements.txt")
            if os.path.isfile(req):
                installed.append(req)
    return installed


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
    _write_install_stamp(ver_file)


def install_requirements(plugin_dir: str, extensions_dir: str, on_progress=None, is_cancelled=None) -> tuple[bool, bool]:
    pkg_dir = _packages_dir(extensions_dir)
    req_file = os.path.join(plugin_dir, "requirements.txt")
    with _packages_lock:
        _ensure_python_version(extensions_dir)
        installed_reqs = _collect_installed_extensions(extensions_dir)
        all_reqs = installed_reqs + [req_file]
        merged = _merge_requirements(all_reqs)
        if not merged:
            _write_install_stamp(_stamp_path(plugin_dir, ".installed"))
            return True, False
        tmp_req = os.path.join(extensions_dir, ".tmp_merged_req.txt")
        try:
            Path(tmp_req).write_text("\n".join(merged) + "\n", "utf-8")
            ep = EmbeddedPython()
            merged_immediately = ep.pip_install(tmp_req, pkg_dir, extensions_dir, on_progress, is_cancelled=is_cancelled)
            _write_install_stamp(_stamp_path(plugin_dir, ".installed"))
            deferred = not merged_immediately
            if deferred:
                AppLogger.info(f"[Installer] Dependencies deferred: {os.path.basename(plugin_dir)}")
            else:
                AppLogger.info(f"[Installer] Dependencies installed: {os.path.basename(plugin_dir)}")
            return True, deferred
        except Exception as e:
            AppLogger.warning(f"[Installer] Failed for {os.path.basename(plugin_dir)}: {e}", exc=e)
            return False, False
        finally:
            try:
                os.remove(tmp_req)
            except OSError:
                pass


def install_packages(
    plugin_dir: str,
    packages: list[str],
    on_progress=None,
    no_deps: bool = False,
    extra_args: list[str] | None = None,
    timeout: int = 0,
    is_cancelled=None,
) -> bool:
    extensions_dir = _extensions_dir_from_plugin(plugin_dir)
    pkg_dir = _packages_dir(extensions_dir)
    with _packages_lock:
        os.makedirs(pkg_dir, exist_ok=True)
        staging = os.path.join(os.path.dirname(pkg_dir), _PIP_STAGING)
        _reset_staging(staging)
        try:
            ep = EmbeddedPython()
            cmd = [
                ep.exe_path,
                "-m",
                "pip",
                "install",
                "--target",
                staging,
                *packages,
                "--quiet",
                "--disable-pip-version-check",
                "--no-cache-dir",
            ]
            if no_deps:
                cmd.append("--no-deps")
            if extra_args:
                cmd.extend(extra_args)
            _run_subprocess(
                cmd,
                on_progress=on_progress,
                timeout=timeout,
                is_cancelled=is_cancelled,
            )
            merged = _merge_or_defer(staging, pkg_dir, extensions_dir)
            if merged:
                AppLogger.info(f"[Installer] Packages installed to {os.path.basename(plugin_dir)}: {packages}")
            else:
                AppLogger.info(f"[Installer] Packages deferred to {os.path.basename(plugin_dir)}: {packages}")
            return merged
        except Exception as e:
            AppLogger.warning(f"[Installer] Package install failed for {os.path.basename(plugin_dir)}: {e}", exc=e)
            return False
        finally:
            if os.path.isdir(staging):
                shutil.rmtree(staging, ignore_errors=True)


def write_post_install_stamp(plugin_dir: str):
    stamp = _stamp_path(plugin_dir, ".post_installed")
    os.makedirs(os.path.dirname(stamp), exist_ok=True)
    Path(stamp).touch()


def _write_install_stamp(stamp_path: str):
    os.makedirs(os.path.dirname(stamp_path), exist_ok=True)
    Path(stamp_path).write_text(_python_version(), "utf-8")


def _stamp_version_matches(stamp_path: str) -> bool:
    try:
        return Path(stamp_path).read_text("utf-8").strip() == _python_version()
    except (OSError, ValueError):
        return False


def needs_install(plugin_dir: str) -> bool:
    req_file = os.path.join(plugin_dir, "requirements.txt")
    if not os.path.isfile(req_file):
        return False
    extensions_dir = _extensions_dir_from_plugin(plugin_dir)
    ver_stamp = os.path.join(_stamps_dir(extensions_dir), _PYTHON_VERSION_STAMP)
    if os.path.isfile(ver_stamp) and not _stamp_version_matches(ver_stamp):
        return True
    stamp = _stamp_path(plugin_dir, ".installed")
    if not os.path.isfile(stamp):
        return True
    return os.path.getmtime(req_file) > os.path.getmtime(stamp)


def needs_post_install(plugin_dir: str) -> bool:
    req_file = os.path.join(plugin_dir, "requirements.txt")
    if not os.path.isfile(req_file):
        return False
    stamp = _stamp_path(plugin_dir, ".post_installed")
    return not os.path.isfile(stamp)


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
) -> InstallResult:
    result = InstallResult()
    if needs_install(plugin_dir):
        if is_cancelled and is_cancelled():
            result.cancelled = True
            return result
        if on_phase:
            on_phase("installing")
        try:
            success, deferred = install_requirements(plugin_dir, extensions_dir, on_progress, is_cancelled=is_cancelled)
        except InstallerCancelled:
            result.cancelled = True
            return result
        if not success:
            return result
        result.deferred = deferred

    if is_cancelled and is_cancelled():
        result.cancelled = True
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
                cls.post_install(plugin_dir, on_progress=on_progress, is_cancelled=is_cancelled)
            except InstallerCancelled:
                result.cancelled = True
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
