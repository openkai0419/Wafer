import importlib
import importlib.util
import inspect
import os
import subprocess
import sys
import time
from pathlib import Path

from ..utils.logs import AppLogger
from .registry import PluginRegistry
from .viewer.base import BaseViewerPlugin
from .grid.base import BaseGridPlugin
from .collector.base import BaseCollectorPlugin


_REGISTRY_MAP = {
    BaseViewerPlugin: 'viewer',
    BaseGridPlugin: 'grid',
    BaseCollectorPlugin: 'collector',
}

_PACKAGES_DIR = '.packages'
_INSTALL_STAMP = '.installed'
_API_MODULE_NAME = 'afterimages'


def get_plugin_dir() -> str:
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, 'plugins')


def _register_api_module():
    if _API_MODULE_NAME not in sys.modules:
        from . import api
        sys.modules[_API_MODULE_NAME] = api


def _needs_install(plugin_dir: str) -> bool:
    req_file = os.path.join(plugin_dir, 'requirements.txt')
    if not os.path.isfile(req_file):
        return False
    vendor_dir = os.path.join(plugin_dir, _PACKAGES_DIR)
    stamp = os.path.join(vendor_dir, _INSTALL_STAMP)
    if not os.path.isfile(stamp):
        return True
    return os.path.getmtime(req_file) > os.path.getmtime(stamp)


def _run_subprocess(cmd: list[str], on_progress=None):
    kwargs = {}
    if sys.platform == 'win32':
        kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, **kwargs)
    while proc.poll() is None:
        if on_progress:
            on_progress()
        time.sleep(0.05)
    if proc.returncode != 0:
        stderr_out = proc.stderr.read().decode(errors='replace') if proc.stderr else ''
        raise RuntimeError(f'pip exited with code {proc.returncode}: {stderr_out}')


def _install_requirements(plugin_dir: str, on_progress=None) -> bool:
    vendor_dir = os.path.join(plugin_dir, _PACKAGES_DIR)
    req_file = os.path.join(plugin_dir, 'requirements.txt')
    os.makedirs(vendor_dir, exist_ok=True)
    try:
        if getattr(sys, 'frozen', False):
            cmd = [sys.executable, '--install-deps', plugin_dir]
        else:
            cmd = [
                sys.executable, '-m', 'pip',
                'install', '--target', vendor_dir,
                '-r', req_file,
                '--quiet', '--disable-pip-version-check',
            ]
        _run_subprocess(cmd, on_progress)
        Path(vendor_dir, _INSTALL_STAMP).touch()
        AppLogger.info(f'[PluginLoader] Installed dependencies: {os.path.basename(plugin_dir)}')
        return True
    except Exception as e:
        AppLogger.warning(f'[PluginLoader] pip install failed for {os.path.basename(plugin_dir)}: {e}', exc=e)
        return False


def _run_pip_frozen(args: list[str]):
    import io as _io
    from pip._internal.cli.main import main as pip_main
    from pip._vendor.distlib.scripts import ScriptMaker
    orig_make_multiple = ScriptMaker.make_multiple
    ScriptMaker.make_multiple = lambda self, specs, options=None: []
    buf = _io.StringIO()
    saved = sys.stdout, sys.stderr
    sys.stdout = sys.stderr = buf
    try:
        ret = pip_main(args)
    except SystemExit as e:
        ret = e.code if isinstance(e.code, int) else 1
    finally:
        sys.stdout, sys.stderr = saved
        ScriptMaker.make_multiple = orig_make_multiple
    output = buf.getvalue()
    if ret != 0:
        raise RuntimeError(f'pip exited with code {ret}: {output}')


def install_plugin_deps(plugin_dir: str) -> int:
    vendor_dir = os.path.join(plugin_dir, _PACKAGES_DIR)
    req_file = os.path.join(plugin_dir, 'requirements.txt')
    os.makedirs(vendor_dir, exist_ok=True)
    pip_args = [
        'install', '--target', vendor_dir,
        '-r', req_file,
        '--quiet', '--disable-pip-version-check',
        '--no-cache-dir',
    ]
    try:
        _run_pip_frozen(pip_args)
        Path(vendor_dir, _INSTALL_STAMP).touch()
        return 0
    except Exception as e:
        AppLogger.warning(f'[PluginLoader] pip install failed: {e}', exc=e)
        return 1


def _discover_plugins(module) -> list[tuple[str, type]]:
    found = []
    for _, obj in inspect.getmembers(module, inspect.isclass):
        if not getattr(obj, 'NAME', ''):
            continue
        for base_cls, registry_key in _REGISTRY_MAP.items():
            if issubclass(obj, base_cls) and obj is not base_cls:
                found.append((registry_key, obj))
    return found


def _discover_command_classes(module) -> list[type]:
    from source.core.actions.command.menu import discover_command_classes
    return discover_command_classes(module)


def _setup_dll_directory(folder: str):
    lib_dir = os.path.join(folder, 'lib')
    if not os.path.isdir(lib_dir):
        return
    if lib_dir not in os.environ.get('PATH', ''):
        os.environ['PATH'] = lib_dir + os.pathsep + os.environ.get('PATH', '')
    if sys.platform == 'win32':
        os.add_dll_directory(lib_dir)


class PluginLoader:

    def __init__(self, plugin_dir: str, registries: dict[str, PluginRegistry], *, skip_install: bool = False):
        self._plugin_dir = plugin_dir
        self._registries = registries
        self._skip_install = skip_install

    def load_all(self, on_progress=None) -> list[str]:
        _register_api_module()
        if not os.path.isdir(self._plugin_dir):
            AppLogger.debug(f'[PluginLoader] Plugin directory not found: {self._plugin_dir}')
            return []
        loaded = []
        for name in sorted(os.listdir(self._plugin_dir)):
            folder = os.path.join(self._plugin_dir, name)
            if not os.path.isdir(folder) or name.startswith('.') or name == '__pycache__':
                continue
            try:
                count = self._load_one(name, folder, on_progress)
                if count > 0:
                    loaded.append(name)
                    AppLogger.info(f'[PluginLoader] Loaded plugin: {name} ({count} classes)')
            except Exception as e:
                AppLogger.warning(f'[PluginLoader] Failed to load plugin: {name} ({e})', exc=e)
            if on_progress:
                on_progress()
        return loaded

    def _load_one(self, name: str, folder: str, on_progress=None) -> int:
        if not self._skip_install and _needs_install(folder):
            if not _install_requirements(folder, on_progress):
                return 0

        vendor_dir = os.path.join(folder, _PACKAGES_DIR)
        if os.path.isdir(vendor_dir) and vendor_dir not in sys.path:
            sys.path.insert(0, vendor_dir)

        _setup_dll_directory(folder)

        pkg_name = f'_plugins_{name}'
        if pkg_name not in sys.modules:
            spec = importlib.util.spec_from_file_location(
                pkg_name,
                os.path.join(folder, '__init__.py') if os.path.isfile(os.path.join(folder, '__init__.py')) else folder,
                submodule_search_locations=[folder],
            )
            if spec is None:
                spec = importlib.machinery.ModuleSpec(pkg_name, None, is_package=True)
                spec.submodule_search_locations = [folder]
            mod = importlib.util.module_from_spec(spec)
            mod.__path__ = [folder]
            sys.modules[pkg_name] = mod
            if spec.loader is not None:
                spec.loader.exec_module(mod)

        total = 0
        for filename in sorted(os.listdir(folder)):
            if not filename.endswith('.py') or filename.startswith('_'):
                continue
            module_name = f'{pkg_name}.{filename[:-3]}'
            if module_name in sys.modules:
                continue
            filepath = os.path.join(folder, filename)
            try:
                sub_spec = importlib.util.spec_from_file_location(
                    module_name, filepath,
                    submodule_search_locations=[],
                )
                sub_mod = importlib.util.module_from_spec(sub_spec)
                sys.modules[module_name] = sub_mod
                sub_spec.loader.exec_module(sub_mod)

                for registry_key, plugin_cls in _discover_plugins(sub_mod):
                    registry = self._registries.get(registry_key)
                    if registry is not None:
                        registry.register(plugin_cls)
                        total += 1
                for cmd_cls in _discover_command_classes(sub_mod):
                    try:
                        cmd_cls.register()
                        total += 1
                    except Exception as e:
                        AppLogger.warning(
                            f'[PluginLoader] Failed to register command: {cmd_cls.__name__} ({e})', exc=e
                        )
            except Exception as e:
                AppLogger.warning(
                    f'[PluginLoader] Failed to load module: {module_name} ({e})', exc=e
                )
        return total


def any_needs_install() -> bool:
    plugin_dir = get_plugin_dir()
    if not os.path.isdir(plugin_dir):
        return False
    for name in os.listdir(plugin_dir):
        folder = os.path.join(plugin_dir, name)
        if os.path.isdir(folder) and not name.startswith('.') and name != '__pycache__':
            if _needs_install(folder):
                return True
    return False


def load_plugins(*, skip_install: bool = False, on_progress=None) -> list[str]:
    from .viewer.handler import viewer_resolver
    from .grid.handler import grid_resolver
    from .collector.handler import collector_resolver
    registries = {
        'viewer': viewer_resolver.registry,
        'grid': grid_resolver.registry,
        'collector': collector_resolver.registry,
    }
    loader = PluginLoader(get_plugin_dir(), registries, skip_install=skip_install)
    return loader.load_all(on_progress=on_progress)
