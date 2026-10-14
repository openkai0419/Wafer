from ...core.logs import AppLogger
from ..registry import PluginRegistry
from .base import BaseSingletonParser, required_collectors


class ParserResolver:
    def __init__(self):
        self.registry = PluginRegistry()
        self.db_name = ""
        self.trigger_cache: dict[str, tuple[str, ...]] = {}

    def bind_db(self, db_name: str) -> None:
        self.db_name = db_name
        self.trigger_cache.clear()

    def refresh_trigger_keys(self) -> None:
        self.trigger_cache.clear()

    def names(self):
        return self.registry.names()

    def summary(self):
        return self.registry.summary()

    def singleton_names(self) -> list[str]:
        return [p.NAME for p in self.registry.list_all() if issubclass(p, BaseSingletonParser)]

    def per_indexer_names(self) -> list[str]:
        return [p.NAME for p in self.registry.list_all() if not issubclass(p, BaseSingletonParser)]

    def batch_size(self, name: str) -> int:
        cls = self.registry.get(name)
        return getattr(cls, "BATCH_SIZE", 1200) if cls else 1200

    def max_workers(self, name: str) -> int:
        cls = self.registry.get(name)
        return max(1, int(getattr(cls, "MAX_WORKERS", 1))) if cls else 1

    def batch_timeout(self, name: str) -> float:
        cls = self.registry.get(name)
        return float(getattr(cls, "MAX_TIMEOUT", 300.0)) if cls else 300.0

    def trigger_keys(self, name: str) -> tuple[str, ...]:
        cls = self.registry.get(name)
        if cls is None:
            return ()
        cached = self.trigger_cache.get(name)
        if cached is not None:
            return cached
        try:
            keys = tuple(cls.trigger_keys(self.db_name))
        except Exception as e:
            AppLogger.warning(f"[ParserResolver] trigger_keys failed for {name}; using TRIGGER_KEYS", exc=e)
            keys = tuple(getattr(cls, "TRIGGER_KEYS", ()))
        self.trigger_cache[name] = keys
        return keys

    def required_collectors(self, name: str) -> dict[str, list[str]]:
        return required_collectors(self.trigger_keys(name))

    def parsers_for_keys(self, keys: set[str]) -> list[str]:
        return [cls.NAME for cls in self.registry.list_all() if keys & set(self.trigger_keys(cls.NAME))]

    def status_name(self, name: str) -> str:
        return name


parser_resolver = ParserResolver()
