from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass, asdict
from typing import Any

from ..registry import BasePlugin


@dataclass
class CollectorResult:
    source: str
    status: bool
    path: str | None = None
    name: str | None = None
    size: int | None = None
    modified: float | None = None
    created: float | None = None
    aspect: float | None = None
    file_hash: str | None = None
    meta_info: dict | None = None
    tags: dict | None = None

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


class BaseCollector(BasePlugin):
    SCOPE: str = "tray"

    @abstractmethod
    def process(self, path: str, file_info: tuple[float, int]) -> CollectorResult | list[CollectorResult]: ...

    def on_notify(self, payload: dict | None = None) -> None:
        pass

    def on_request(self, action: str, payload: dict, msg) -> Any:
        return None

    @staticmethod
    def notify_to(name: str, payload: Any = None) -> None:
        from ...core.commands.binding.instance_registry import InstanceRegistry

        node = InstanceRegistry.instance().resolve_node()
        if node:
            node.send("plugin.notify", payload, dst=f"collector-{name}")


class BaseCollectorPlugin(BaseCollector):
    BATCH_SIZE: int = 1200
    CHUNK_TIMEOUT: float = 300.0


class BaseSingletonCollector(BaseCollector):
    BATCH_SIZE: int = 300
    CHUNK_TIMEOUT: float = 600.0
