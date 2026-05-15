import os
from abc import ABC, abstractmethod
from ..utils.profiling import profiler
from ..utils.virtual_paths import leaf_extension, owner_extension


DISPATCH_NORMAL = "normal"
DISPATCH_OWNER = "owner"
DISPATCH_LEAF = "leaf"


class PluginBase:
    NAME: str = ""
    PRIORITY: int = 0
    SCOPE: str = "viewer"
    DEFAULT_ENABLED: bool = False

    @classmethod
    def post_install(cls, plugin_dir: str, on_progress=None, is_cancelled=None, on_log=None):
        pass

    @classmethod
    def configure(cls):
        pass

    def shutdown(self):
        pass


class BasePlugin(PluginBase, ABC):
    EXTENSIONS: tuple[str, ...] = ()
    OWNS_VIRTUAL_CHILDREN: bool = False

    @classmethod
    def match(cls, path: str) -> bool:
        if not cls.EXTENSIONS:
            return True
        ext = os.path.splitext(path)[1].lower()
        return ext in cls.EXTENSIONS

    @classmethod
    def can_handle(cls, path: str) -> bool:
        return True


class RegistryBase(ABC):
    def __init__(self):
        self._order: list[str] = []

    @abstractmethod
    def register(self, cls: type[PluginBase]): ...

    @abstractmethod
    def list_all(self) -> list[type[PluginBase]]: ...

    def set_order(self, order: list[str]):
        self._order = list(order)

    def names(self) -> list[str]:
        return [p.NAME for p in self.list_all()]


class PluginRegistry(RegistryBase):
    def __init__(self):
        super().__init__()
        self._plugins: dict[str, type[PluginBase]] = {}
        self._instances: dict[str, PluginBase] = {}

    def _sort_key(self, cls: type[PluginBase]):
        if self._order:
            try:
                return (1, len(self._order) - self._order.index(cls.NAME))
            except ValueError:
                return (0, cls.PRIORITY)
        return (0, cls.PRIORITY)

    def register(self, plugin_cls: type[PluginBase]):
        existing = self._plugins.get(plugin_cls.NAME)
        if existing is not None and plugin_cls.PRIORITY < existing.PRIORITY:
            return
        self._plugins[plugin_cls.NAME] = plugin_cls
        self._instances.pop(plugin_cls.NAME, None)

    def get(self, name: str) -> type[PluginBase] | None:
        return self._plugins.get(name)

    def list_all(self) -> list[type[PluginBase]]:
        return sorted(self._plugins.values(), key=self._sort_key, reverse=True)

    def instance(self, name: str) -> PluginBase | None:
        inst = self._instances.get(name)
        if inst is None:
            cls = self.get(name)
            if cls is not None:
                inst = cls()
                self._instances[name] = inst
        return inst


class FilePluginRegistry(PluginRegistry):
    def __init__(self):
        super().__init__()
        self._ext_cache: dict[str, list[type[BasePlugin]]] = {}
        self._chain_cache: dict[str, list[type[BasePlugin]]] = {}

    def _rebuild_ext_cache(self):
        cache: dict[str, list[type[BasePlugin]]] = {}
        for p in self.list_all():
            for ext in p.EXTENSIONS:
                cache.setdefault(ext, []).append(p)
        self._ext_cache = cache

    def _invalidate_caches(self):
        self._rebuild_ext_cache()
        self._chain_cache.clear()

    def register(self, plugin_cls: type[BasePlugin]):
        super().register(plugin_cls)
        self._invalidate_caches()

    def set_order(self, order: list[str]):
        super().set_order(order)
        self._invalidate_caches()

    def _extension(self, path: str, mode: str = DISPATCH_NORMAL) -> str:
        if mode == DISPATCH_OWNER:
            return owner_extension(path)
        if mode == DISPATCH_LEAF:
            return leaf_extension(path)
        return os.path.splitext(path)[1].lower()

    @profiler.profile
    def resolve(self, path: str, mode: str = DISPATCH_NORMAL) -> type[BasePlugin] | None:
        ext = self._extension(path, mode)
        if ext:
            for p in self._ext_cache.get(ext, []):
                if p.can_handle(path):
                    return p
        for p in self.list_all():
            if not p.EXTENSIONS and p.match(path) and p.can_handle(path):
                return p
        return None

    @profiler.profile
    def resolve_chain(self, path: str, mode: str = DISPATCH_NORMAL) -> list[type[BasePlugin]]:
        ext = self._extension(path, mode)
        cache_key = f"{mode}:{ext}"
        cached = self._chain_cache.get(cache_key)
        if cached is not None:
            return cached
        candidates = list(self._ext_cache.get(ext, [])) if ext else []
        for p in self.list_all():
            if not p.EXTENSIONS and p.match(path) and p not in candidates:
                candidates.append(p)
        self._chain_cache[cache_key] = candidates
        return candidates

    def resolve_instance(self, path: str, mode: str = DISPATCH_NORMAL) -> BasePlugin | None:
        cls = self.resolve(path, mode)
        return self.instance(cls.NAME) if cls else None

    def resolve_all(self, path: str) -> list[type[BasePlugin]]:
        return [p for p in self.list_all() if p.match(path) and p.can_handle(path)]

    def all_classes(self) -> list[tuple[str, type[BasePlugin]]]:
        return [(p.NAME, p) for p in self.list_all()]

    def summary(self) -> list[tuple[str, tuple[str, ...]]]:
        return [(p.NAME, p.EXTENSIONS) for p in self.list_all()]


class CommandGroupRegistry(RegistryBase):
    def __init__(self):
        super().__init__()
        self._groups: list[type[PluginBase]] = []
        self._seen: set[type] = set()
        self._activated: set[type] = set()

    def register(self, cls: type[PluginBase]):
        if cls in self._seen:
            return
        self._seen.add(cls)
        self._groups.append(cls)

    def set_order(self, order: list[str]):
        super().set_order(order)
        from ..core.commands.command.menu import MenuHub

        MenuHub.instance().set_menu_order(order)

    def activate(self, scope: str):
        from ..utils.logs import AppLogger

        for cls in sorted(self._groups, key=lambda c: c.PRIORITY):
            if cls in self._activated:
                continue
            cls_scope = getattr(cls, "SCOPE", "viewer")
            if cls_scope != "*" and cls_scope != scope:
                continue
            try:
                cls.register()
                self._activated.add(cls)
            except Exception as e:
                AppLogger.warning(f"[CommandGroupRegistry] Failed to register: {getattr(cls, '__name__', str(cls))} ({e})", exc=e)

    def list_all(self) -> list[type[PluginBase]]:
        if self._order:
            order_map = {name: i for i, name in enumerate(self._order)}
            return sorted(self._groups, key=lambda c: (0, order_map[c.NAME]) if c.NAME in order_map else (1, -c.PRIORITY))
        return sorted(self._groups, key=lambda c: c.PRIORITY, reverse=True)

    def names(self) -> list[str]:
        seen: list[str] = []
        for p in self.list_all():
            if p.NAME and p.NAME not in seen:
                seen.append(p.NAME)
        return seen
