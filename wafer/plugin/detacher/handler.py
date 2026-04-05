from ..registry import PluginRegistry
from .base import BaseDetacherPlugin, BaseSingletonDetacher


class DetacherResolver:

    def __init__(self):
        self.registry = PluginRegistry()

    def names(self):
        return self.registry.names()

    def summary(self):
        return self.registry.summary()

    def singleton_names(self) -> list[str]:
        return [p.NAME for p in self.registry.list_all() if issubclass(p, BaseSingletonDetacher)]

    def per_indexer_names(self) -> list[str]:
        return [p.NAME for p in self.registry.list_all() if not issubclass(p, BaseSingletonDetacher)]

    def batch_size(self, name: str) -> int:
        cls = self.registry.get(name)
        return getattr(cls, 'BATCH_SIZE', 1200) if cls else 1200

    def trigger_keys(self, name: str) -> tuple[str, ...]:
        cls = self.registry.get(name)
        return getattr(cls, 'TRIGGER_KEYS', ()) if cls else ()

    def detachers_for_keys(self, keys: set[str]) -> list[str]:
        result = []
        for cls in self.registry.list_all():
            tk = getattr(cls, 'TRIGGER_KEYS', ())
            if tk and keys & set(tk):
                result.append(cls.NAME)
        return result

    def status_name(self, name: str) -> str:
        return name


detacher_resolver = DetacherResolver()
