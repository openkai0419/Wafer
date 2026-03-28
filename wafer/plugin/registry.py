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
        self._plugins: list[type[BasePlugin]] = []
        self._instances: dict[str, BasePlugin] = {}
        self._ext_cache: dict[str, list[type[BasePlugin]]] = {}
        self._chain_cache: dict[str, list[type[BasePlugin]]] = {}

    def _rebuild_ext_cache(self):
        cache: dict[str, list[type[BasePlugin]]] = {}
        for p in self._plugins:
            for ext in p.EXTENSIONS:
                cache.setdefault(ext, []).append(p)
        self._ext_cache = cache

    def register(self, plugin_cls: type[BasePlugin]):
        existing = next((i for i, p in enumerate(self._plugins) if p.NAME == plugin_cls.NAME), None)
        if existing is not None:
            self._plugins[existing] = plugin_cls
        else:
            self._plugins.append(plugin_cls)
        self._plugins.sort(key=lambda c: c.PRIORITY, reverse=True)
        self._instances.pop(plugin_cls.NAME, None)
        self._rebuild_ext_cache()
        self._chain_cache.clear()

    @profiler.profile
    def resolve(self, path: str) -> type[BasePlugin] | None:
        ext = os.path.splitext(path)[1].lower()
        if ext:
            for p in self._ext_cache.get(ext, []):
                if p.can_handle(path):
                    return p
        for p in self._plugins:
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
        for p in self._plugins:
            if not p.EXTENSIONS and p.match(path) and p not in candidates:
                candidates.append(p)
        self._chain_cache[ext] = candidates
        return candidates

    def resolve_instance(self, path: str) -> BasePlugin | None:
        cls = self.resolve(path)
        return self.instance(cls.NAME) if cls else None

    def resolve_all(self, path: str) -> list[type[BasePlugin]]:
        return [p for p in self._plugins if p.match(path) and p.can_handle(path)]

    def list_all(self) -> list[type[BasePlugin]]:
        return list(self._plugins)

    def names(self) -> list[str]:
        return [p.NAME for p in self._plugins]

    def get(self, name: str) -> type[BasePlugin] | None:
        for p in self._plugins:
            if p.NAME == name:
                return p
        return None

    def instance(self, name: str) -> BasePlugin | None:
        inst = self._instances.get(name)
        if inst is None:
            cls = self.get(name)
            if cls is not None:
                inst = cls()
                self._instances[name] = inst
        return inst

    def all_classes(self) -> list[tuple[str, type[BasePlugin]]]:
        return [(p.NAME, p) for p in self._plugins]

    def summary(self) -> list[tuple[str, tuple[str, ...]]]:
        return [(p.NAME, p.EXTENSIONS) for p in self._plugins]
