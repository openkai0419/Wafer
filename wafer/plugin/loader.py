import importlib
import importlib.util
import inspect
import os
import sys

from ..utils.logs import AppLogger
from .installer import _PACKAGES_DIR, needs_setup
from .registry import RegistryBase, CommandGroupRegistry
from .viewer.base import BaseViewerPlugin
from .grid.base import BaseGridPlugin
from .collector.base import BaseCollector
from .query.base import BaseFilterPlugin, BaseSortPlugin
from .parser.base import BaseParser
from .layout.base import BaseLayoutPlugin
from .panel.base import BasePanelPlugin
from .meta_panel.base import BaseMetaPanelPlugin
from .tag_panel.base import BaseTagPanelPlugin
from .rename.base import BaseRenameSourcePlugin
from .imageloader.base import BaseImageLoader


def _build_registry_map():
    from ..core.commands.command.menu import MenuGroup

    return {
        BaseViewerPlugin: "viewer",
        BaseGridPlugin: "grid",
        BaseCollector: "collector",
        BaseParser: "parser",
        BaseFilterPlugin: "filter",
        BaseSortPlugin: "sort",
        BaseLayoutPlugin: "layout",
        BasePanelPlugin: "panel",
        BaseMetaPanelPlugin: "meta_panel",
        BaseTagPanelPlugin: "tag_panel",
        BaseRenameSourcePlugin: "rename_source",
        BaseImageLoader: "imageloader",
        MenuGroup: "command",
    }


_REGISTRY_MAP: dict | None = None


def _get_registry_map():
    global _REGISTRY_MAP
    if _REGISTRY_MAP is None:
        _REGISTRY_MAP = _build_registry_map()
    return _REGISTRY_MAP


def get_plugin_dir() -> str:
    return os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "extensions"))


def _discover_plugins(module) -> list[tuple[str, type]]:
    registry_map = _get_registry_map()
    found = []
    for _, obj in inspect.getmembers(module, inspect.isclass):
        if not getattr(obj, "NAME", ""):
            continue
        for base_cls, registry_key in registry_map.items():
            if issubclass(obj, base_cls) and obj is not base_cls:
                found.append((registry_key, obj))
    return found


def qualify_plugin_name(registry_key: str, cls: type) -> str:
    return f"{registry_key}:{cls.__name__}"


def _setup_dll_directory(folder: str):
    lib_dir = os.path.join(folder, "lib")
    if not os.path.isdir(lib_dir):
        return
    if lib_dir not in os.environ.get("PATH", "").split(os.pathsep):
        os.environ["PATH"] = lib_dir + os.pathsep + os.environ.get("PATH", "")
    if sys.platform == "win32":
        os.add_dll_directory(lib_dir)


def _setup_packages_dll_directories(packages_dir: str):
    if sys.platform != "win32" or not os.path.isdir(packages_dir):
        return
    for entry in os.scandir(packages_dir):
        if entry.is_dir(follow_symlinks=False) and entry.name.endswith(".libs"):
            if entry.path not in os.environ.get("PATH", "").split(os.pathsep):
                os.environ["PATH"] = entry.path + os.pathsep + os.environ.get("PATH", "")
            os.add_dll_directory(entry.path)


class PluginLoader:
    def __init__(self, plugin_dir: str, registries: dict[str, RegistryBase], *, enabled: set[str] | None = None):
        self._plugin_dir = plugin_dir
        self._registries = registries
        self._enabled = enabled

    def load_all(self, on_progress=None) -> list[str]:
        if not os.path.isdir(self._plugin_dir):
            return []
        packages_dir = os.path.join(self._plugin_dir, _PACKAGES_DIR)
        if os.path.isdir(packages_dir) and packages_dir not in sys.path:
            sys.path.insert(0, packages_dir)
        _setup_packages_dll_directories(packages_dir)
        loaded = []
        for name in sorted(os.listdir(self._plugin_dir)):
            folder = os.path.join(self._plugin_dir, name)
            if not os.path.isdir(folder) or name.startswith(".") or name == "__pycache__":
                continue
            try:
                count = self._load_one(name, folder, on_progress)
                if count > 0:
                    loaded.append(name)
                    AppLogger.info(f"[PluginLoader] Loaded plugin: {name} ({count} classes)")
            except Exception as e:
                AppLogger.warning(f"[PluginLoader] Failed to load plugin: {name} ({e})", exc=e)
            if on_progress:
                on_progress()
        self._fire_configure()
        return loaded

    def _fire_configure(self):
        seen = set()
        for registry in self._registries.values():
            for plugin_cls in registry.list_all():
                if id(plugin_cls) not in seen:
                    seen.add(id(plugin_cls))
                    configure = getattr(plugin_cls, "configure", None)
                    if configure is None:
                        continue
                    try:
                        configure()
                    except Exception as e:
                        AppLogger.warning(f"[PluginLoader] configure failed: {plugin_cls.NAME} ({e})", exc=e)

    def _load_one(self, name: str, folder: str, on_progress=None) -> int:
        if needs_setup(folder):
            return 0

        _setup_dll_directory(folder)

        total = self._import_and_register(name, folder)

        return total

    def _import_and_register(self, name: str, folder: str) -> int:
        total = 0
        all_found = _import_extension(name, folder)
        for registry_key, cls in all_found:
            qualified = qualify_plugin_name(registry_key, cls)
            if self._enabled is not None and qualified not in self._enabled:
                continue
            if self._enabled is None and not getattr(cls, "DEFAULT_ENABLED", False):
                continue
            registry = self._registries.get(registry_key)
            if registry is not None:
                registry.register(cls)
            total += 1
        return total

    @staticmethod
    def discover_extension(folder: str) -> list[tuple[str, type]]:
        name = os.path.basename(folder)
        extensions_dir = os.path.dirname(folder)
        packages_dir = os.path.join(extensions_dir, _PACKAGES_DIR)
        added = False
        if os.path.isdir(packages_dir) and packages_dir not in sys.path:
            sys.path.insert(0, packages_dir)
            added = True
        try:
            return _import_extension(name, folder)
        finally:
            if added and packages_dir in sys.path:
                sys.path.remove(packages_dir)


def _import_extension(name: str, folder: str) -> list[tuple[str, type]]:
    pkg_name = f"_plugins_{name}"
    if pkg_name not in sys.modules:
        init_py = os.path.join(folder, "__init__.py")
        spec = importlib.util.spec_from_file_location(
            pkg_name,
            init_py if os.path.isfile(init_py) else folder,
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

    found: list[tuple[str, type]] = []
    for filename in sorted(os.listdir(folder)):
        if not filename.endswith(".py") or filename.startswith("_"):
            continue
        module_name = f"{pkg_name}.{filename[:-3]}"
        if module_name in sys.modules:
            sub_mod = sys.modules[module_name]
        else:
            filepath = os.path.join(folder, filename)
            try:
                sub_spec = importlib.util.spec_from_file_location(module_name, filepath)
                sub_mod = importlib.util.module_from_spec(sub_spec)
                sys.modules[module_name] = sub_mod
                sub_spec.loader.exec_module(sub_mod)
            except Exception as e:
                AppLogger.warning(f"[PluginLoader] Failed to import: {module_name} ({e})", exc=e)
                continue
        found.extend(_discover_plugins(sub_mod))
    return found


def load_plugins(*, on_progress=None) -> list[str]:
    global _command_registry_ref
    from .viewer.handler import viewer_resolver
    from .grid.handler import grid_resolver
    from .collector.handler import collector_resolver
    from .parser.handler import parser_resolver
    from .query.handler import filter_registry, sort_registry
    from .layout.handler import layout_registry
    from .panel.handler import panel_registry
    from .meta_panel.handler import meta_panel_registry
    from .tag_panel.handler import tag_panel_registry
    from .rename.handler import rename_source_registry
    from .imageloader.handler import image_loader_resolver

    command_registry = CommandGroupRegistry()
    registries = {
        "viewer": viewer_resolver.registry,
        "grid": grid_resolver.registry,
        "collector": collector_resolver.registry,
        "parser": parser_resolver.registry,
        "filter": filter_registry,
        "sort": sort_registry,
        "layout": layout_registry,
        "panel": panel_registry,
        "meta_panel": meta_panel_registry,
        "tag_panel": tag_panel_registry,
        "rename_source": rename_source_registry,
        "imageloader": image_loader_resolver.registry,
        "command": command_registry,
    }
    from ..builtins.registration import register_all

    register_all(registries)

    from .settings import PluginSettings

    ps = PluginSettings()
    enabled = ps.enabled_names()

    loader = PluginLoader(get_plugin_dir(), registries, enabled=enabled)
    result = loader.load_all(on_progress=on_progress)

    for key, registry in registries.items():
        order = ps.priority_order(key)
        if order:
            registry.set_order(order)

    _command_registry_ref = command_registry
    return result


_command_registry_ref: CommandGroupRegistry | None = None


def get_command_registry() -> CommandGroupRegistry:
    if _command_registry_ref is None:
        raise RuntimeError("load_plugins() must be called before get_command_registry()")
    return _command_registry_ref
