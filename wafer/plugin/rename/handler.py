from __future__ import annotations

from ..registry import PluginRegistry
from .base import BaseRenameSourcePlugin


class RenameSourceRegistry(PluginRegistry):
    def deserialise(self, data: dict) -> BaseRenameSourcePlugin:
        src_cls = self.get(data.get("type", "")) or self.get("name")
        if src_cls is None:
            raise ValueError("No rename source plugins registered")
        inst = src_cls()
        inst._apply(data)
        return inst


rename_source_registry = RenameSourceRegistry()
