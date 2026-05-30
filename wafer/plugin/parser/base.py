from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass, asdict
from typing import Any

from ..registry import BasePlugin


@dataclass
class ParserResult:
    source: str
    status: bool
    meta_info: dict | None = None
    tags: dict | None = None
    delete_keys: list[str] | None = None

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


class BaseParser(BasePlugin):
    SCOPE: str = "tray"
    TRIGGER_KEYS: tuple[str, ...] = ()

    @abstractmethod
    def process(self, path: str, file_info: tuple, metadata: dict) -> ParserResult: ...

    def on_notify(self, payload: dict | None = None) -> None:
        pass

    @staticmethod
    def notify_to(name: str, payload: Any = None) -> None:
        from ...core.commands.binding.instance_registry import InstanceRegistry

        node = InstanceRegistry.instance().resolve_node()
        if node:
            node.send("plugin.notify", payload, dst=f"parser-{name}")


class BaseParserPlugin(BaseParser):
    BATCH_SIZE: int = 1200
    MAX_WORKERS: int = 1
    MAX_TIMEOUT: float = 300.0


class BaseSingletonParser(BaseParser):
    BATCH_SIZE: int = 300
    MAX_WORKERS: int = 1
    MAX_TIMEOUT: float = 300.0
