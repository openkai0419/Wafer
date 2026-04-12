from abc import abstractmethod
from dataclasses import dataclass, asdict

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
    TRIGGER_KEYS: tuple[str, ...] = ()

    @abstractmethod
    def process(self, path: str, file_info: tuple, metadata: dict) -> ParserResult: ...

    def on_notify(self) -> None:
        pass

    @staticmethod
    def notify_to(name: str) -> None:
        from ...core.commands.binding.instance_registry import InstanceRegistry

        node = InstanceRegistry.instance().resolve_node()
        if node:
            node.send("plugin.notify", dst=f"parser-{name}")


class BaseParserPlugin(BaseParser):
    BATCH_SIZE: int = 1200


class BaseSingletonParser(BaseParser):
    BATCH_SIZE: int = 300
