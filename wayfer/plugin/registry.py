import os
from abc import ABC, abstractmethod


class BasePlugin(ABC):
    NAME: str = ''
    EXTENSIONS: tuple[str, ...] = ()
    PRIORITY: int = 0

    @classmethod
    def match(cls, path: str) -> bool:
        if not cls.EXTENSIONS:
            return True
        ext = os.path.splitext(path)[1].lower()
        return ext in cls.EXTENSIONS

    @classmethod
    def post_install(cls, plugin_dir: str, on_progress=None):
        pass

    @classmethod
    def configure(cls):
        pass


class PluginRegistry:

    def __init__(self):
        self._plugins: list[type[BasePlugin]] = []
        self._instances: dict[str, BasePlugin] = {}
        self._ext_cache: dict[str, type[BasePlugin]] = {}

    def _rebuild_ext_cache(self):
        cache: dict[str, type[BasePlugin]] = {}
        for p in self._plugins:
            for ext in p.EXTENSIONS:
                cache.setdefault(ext, p)
        self._ext_cache = cache

    def register(self, plugin_cls: type[BasePlugin]):
        existing = next((i for i, p in enumerate(self._plugins) if p.NAME == plugin_cls.NAME), None)
        if existing is not None:
            self._plugins[existing] = plugin_cls
        else:
            self._plugins.append(plugin_cls)
        self._plugins.sort(key=lambda c: c.PRIORITY, reverse=True)
        self._instances[plugin_cls.NAME] = plugin_cls()
        self._rebuild_ext_cache()

    def resolve(self, path: str) -> type[BasePlugin] | None:
        ext = os.path.splitext(path)[1].lower()
        if ext:
            cached = self._ext_cache.get(ext)
            if cached is not None:
                return cached
        for p in self._plugins:
            if not p.EXTENSIONS and p.match(path):
                return p
        return None

    def resolve_instance(self, path: str) -> BasePlugin | None:
        cls = self.resolve(path)
        return self._instances.get(cls.NAME) if cls else None

    def resolve_all(self, path: str) -> list[type[BasePlugin]]:
        return [p for p in self._plugins if p.match(path)]

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
        return self._instances.get(name)

    def summary(self) -> list[tuple[str, tuple[str, ...]]]:
        return [(p.NAME, p.EXTENSIONS) for p in self._plugins]
