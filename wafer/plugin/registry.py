import os
from abc import ABC, abstractmethod
from ..utils.profiling import profiler


class PluginBase:
    NAME: str = ''
    PRIORITY: int = 0
    DEFAULT_ENABLED: bool = False

    @classmethod
    def post_install(cls, plugin_dir: str, on_progress=None):
        pass

    @classmethod
    def configure(cls):
        pass


class BasePlugin(PluginBase, ABC):
    EXTENSIONS: tuple[str, ...] = ()

    @classmethod
    def match(cls, path: str) -> bool:
        if not cls.EXTENSIONS:
            return True
        ext = os.path.splitext(path)[1].lower()
        return ext in cls.EXTENSIONS

    @classmethod
    def can_handle(cls, path: str) -> bool:
        return True


class PluginRegistry:

    def __init__(self):
        self._plugins: dict[str, type[PluginBase]] = {}
        self._order: list[str] = []

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

    def set_order(self, order: list[str]):
        self._order = list(order)

    def get(self, name: str) -> type[PluginBase] | None:
        return self._plugins.get(name)

    def list_all(self) -> list[type[PluginBase]]:
        return sorted(self._plugins.values(), key=self._sort_key, reverse=True)

    def names(self) -> list[str]:
        return [p.NAME for p in self.list_all()]


class FilePluginRegistry(PluginRegistry):

    def __init__(self):
        super().__init__()
        self._instances: dict[str, BasePlugin] = {}
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
        self._instances.pop(plugin_cls.NAME, None)
        self._invalidate_caches()

    def set_order(self, order: list[str]):
        super().set_order(order)
        self._invalidate_caches()

    @profiler.profile
    def resolve(self, path: str) -> type[BasePlugin] | None:
        ext = os.path.splitext(path)[1].lower()
        if ext:
            for p in self._ext_cache.get(ext, []):
                if p.can_handle(path):
                    return p
        for p in self.list_all():
            if not p.EXTENSIONS and p.match(path) and p.can_handle(path):
                return p
        return None

    @profiler.profile
    def resolve_chain(self, path: str) -> list[type[BasePlugin]]:
        ext = os.path.splitext(path)[1].lower()
        cached = self._chain_cache.get(ext)
        if cached is not None:
            return cached
        candidates = list(self._ext_cache.get(ext, [])) if ext else []
        for p in self.list_all():
            if not p.EXTENSIONS and p.match(path) and p not in candidates:
                candidates.append(p)
        self._chain_cache[ext] = candidates
        return candidates

    def instance(self, name: str) -> BasePlugin | None:
        inst = self._instances.get(name)
        if inst is None:
            cls = self.get(name)
            if cls is not None:
                inst = cls()
                self._instances[name] = inst
        return inst

    def resolve_instance(self, path: str) -> BasePlugin | None:
        cls = self.resolve(path)
        return self.instance(cls.NAME) if cls else None

    def resolve_all(self, path: str) -> list[type[BasePlugin]]:
        return [p for p in self.list_all() if p.match(path) and p.can_handle(path)]

    def all_classes(self) -> list[tuple[str, type[BasePlugin]]]:
        return [(p.NAME, p) for p in self.list_all()]

    def summary(self) -> list[tuple[str, tuple[str, ...]]]:
        return [(p.NAME, p.EXTENSIONS) for p in self.list_all()]


class CommandGroupRegistry:

    def __init__(self):
        self._pending: list[type] = []
        self._activated: list[type] = []
        self._order: list[str] = []

    def register(self, cls):
        self._pending.append(cls)

    def activate(self, scope: str):
        from ..utils.logs import AppLogger
        for cls in self._pending:
            cls_scope = getattr(cls, 'SCOPE', 'viewer')
            if cls_scope != '*' and cls_scope != scope:
                continue
            try:
                cls.register()
                self._activated.append(cls)
            except Exception as e:
                AppLogger.warning(
                    f'[CommandGroupRegistry] Failed to register: {getattr(cls, "__name__", str(cls))} ({e})', exc=e
                )
        self._pending.clear()

    def set_order(self, order: list[str]):
        self._order = list(order)

    def list_all(self) -> list[type]:
        return list(self._pending) + list(self._activated)

    def names(self) -> list[str]:
        return [getattr(cls, 'NAME', '') for cls in self.list_all()]
