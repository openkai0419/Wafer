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


class PluginRegistry:

    def __init__(self):
        self._plugins: list[type[BasePlugin]] = []

    def register(self, plugin_cls: type[BasePlugin]):
        self._plugins.append(plugin_cls)
        self._plugins.sort(key=lambda c: c.PRIORITY, reverse=True)

    def resolve(self, path: str) -> type[BasePlugin] | None:
        for p in self._plugins:
            if p.match(path):
                return p
        return None

    def resolve_all(self, path: str) -> list[type[BasePlugin]]:
        return [p for p in self._plugins if p.match(path)]

    def plugins(self) -> list[type[BasePlugin]]:
        return list(self._plugins)

    def names(self) -> list[str]:
        return [p.NAME for p in self._plugins]

    def get(self, name: str) -> type[BasePlugin] | None:
        for p in self._plugins:
            if p.NAME == name:
                return p
        return None

    def info(self) -> list[tuple[str, tuple[str, ...]]]:
        return [(p.NAME, p.EXTENSIONS) for p in self._plugins]
