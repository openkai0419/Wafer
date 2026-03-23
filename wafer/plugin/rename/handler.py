from __future__ import annotations

from .base import BaseRenameSourcePlugin


class RenameSourceRegistry:

    def __init__(self):
        self._sources: dict[str, type[BaseRenameSourcePlugin]] = {}

    def register(self, cls: type[BaseRenameSourcePlugin]):
        self._sources[cls.NAME] = cls

    def get(self, name: str) -> type[BaseRenameSourcePlugin] | None:
        return self._sources.get(name)

    def list_all(self) -> list[type[BaseRenameSourcePlugin]]:
        return sorted(self._sources.values(), key=lambda c: c.PRIORITY, reverse=True)

    def deserialise(self, data: dict) -> BaseRenameSourcePlugin:
        src_cls = self.get(data.get('type', '')) or self.get('name')
        if src_cls is None:
            raise ValueError('No rename source plugins registered')
        inst = src_cls()
        inst._apply(data)
        return inst


rename_source_registry = RenameSourceRegistry()
