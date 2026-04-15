import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from ..utils.logs import AppLogger

_PACKAGES_DIR = ".packages"
_STAMPS_DIR = ".stamps"
_PIP_STAGING = ".pip_staging"
_PYTHON_VERSION_STAMP = ".python_version"

_SUBPROCESS_POLL_INTERVAL = 0.05

_packages_lock = threading.Lock()


def _python_version() -> str:
    return platform.python_version()


def _packages_dir(extensions_dir: str) -> str:
    return os.path.join(extensions_dir, _PACKAGES_DIR)


def _stamps_dir(extensions_dir: str) -> str:
    return os.path.join(_packages_dir(extensions_dir), _STAMPS_DIR)


def _extensions_dir_from_plugin(plugin_dir: str) -> str:
    return os.path.dirname(plugin_dir)


def _stamp_path(plugin_dir: str, suffix: str) -> str:
    ext_dir = _extensions_dir_from_plugin(plugin_dir)
    name = os.path.basename(plugin_dir)
    return os.path.join(_stamps_dir(ext_dir), f"{name}{suffix}")


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
    def __init__(self):
        self._exe = sys.executable

    @property
    def exe_path(self) -> str:
        return self._exe

    @property
    def is_ready(self) -> bool:
        return os.path.isfile(self._exe)

    def pip_install(self, req_file: str, target_dir: str, on_progress=None):
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
                timeout=600,
            )
            _merge_dir(staging, target_dir)
        finally:
            shutil.rmtree(staging, ignore_errors=True)


def _reset_staging(path: str):
    if os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)
    os.makedirs(path, exist_ok=True)


def _merge_dir(src: str, dst: str):
    for entry in os.scandir(src):
        dst_path = os.path.join(dst, entry.name)
        if entry.is_dir(follow_symlinks=False):
            if os.path.isdir(dst_path):
                _merge_dir(entry.path, dst_path)
            else:
                shutil.copytree(entry.path, dst_path, dirs_exist_ok=True)
        else:
            try:
                shutil.copy2(entry.path, dst_path)
            except PermissionError:
                bak = dst_path + ".old"
                try:
                    os.replace(dst_path, bak)
                except OSError:
                    pass
                try:
                    shutil.copy2(entry.path, dst_path)
                except OSError:
                    AppLogger.warning(f"[Installer] Locked file skipped: {entry.name}")


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


def install_requirements(plugin_dir: str, extensions_dir: str, on_progress=None) -> bool:
    pkg_dir = _packages_dir(extensions_dir)
    req_file = os.path.join(plugin_dir, "requirements.txt")
    with _packages_lock:
        _ensure_python_version(extensions_dir)
        installed_reqs = _collect_installed_extensions(extensions_dir)
        all_reqs = installed_reqs + [req_file]
        merged = _merge_requirements(all_reqs)
        if not merged:
            _write_install_stamp(_stamp_path(plugin_dir, ".installed"))
            return True
        tmp_req = os.path.join(extensions_dir, ".tmp_merged_req.txt")
        try:
            Path(tmp_req).write_text("\n".join(merged) + "\n", "utf-8")
            ep = EmbeddedPython()
            ep.pip_install(tmp_req, pkg_dir, on_progress)
            _write_install_stamp(_stamp_path(plugin_dir, ".installed"))
            AppLogger.info(f"[Installer] Dependencies installed: {os.path.basename(plugin_dir)}")
            return True
        except Exception as e:
            AppLogger.warning(f"[Installer] Failed for {os.path.basename(plugin_dir)}: {e}", exc=e)
            return False
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
    timeout: int = 1800,
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
            )
            _merge_dir(staging, pkg_dir)
            AppLogger.info(f"[Installer] Packages installed to {os.path.basename(plugin_dir)}: {packages}")
            return True
        except Exception as e:
            AppLogger.warning(f"[Installer] Package install failed for {os.path.basename(plugin_dir)}: {e}", exc=e)
            return False
        finally:
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
        if is_cancelled and is_cancelled():
            return False, False, []
        if not install_requirements(plugin_dir, extensions_dir, on_progress):
            return False, False, []

    if is_cancelled and is_cancelled():
        return False, False, []

    from .loader import PluginLoader

    plugins = PluginLoader.discover_extension(plugin_dir)

    pkg_dir = _packages_dir(extensions_dir)
    path_added = []
    if os.path.isdir(pkg_dir) and pkg_dir not in sys.path:
        sys.path.insert(0, pkg_dir)
        path_added.append(pkg_dir)

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
