from abc import abstractmethod
from dataclasses import dataclass, asdict

from ..registry import BasePlugin


@dataclass
class DetacherResult:
    source: str
    status: bool
    meta_info: dict | None = None
    tags: dict | None = None
    delete_keys: list[str] | None = None

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


class BaseDetacher(BasePlugin):
    TRIGGER_KEYS: tuple[str, ...] = ()

    @abstractmethod
    def process(self, path: str, file_info: tuple, metadata: dict) -> DetacherResult: ...

    def on_notify(self) -> None:
        pass

    @staticmethod
    def notify_to(name: str) -> None:
        from ...core.commands.binding.instance_registry import InstanceRegistry

        node = InstanceRegistry.instance().resolve_node()
        if node:
            node.send("plugin.notify", dst=f"detacher-{name}")


class BaseDetacherPlugin(BaseDetacher):
    BATCH_SIZE: int = 1200


class BaseSingletonDetacher(BaseDetacher):
    BATCH_SIZE: int = 300
