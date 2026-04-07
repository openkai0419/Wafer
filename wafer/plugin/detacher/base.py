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


class BaseDetacherPlugin(BaseDetacher):
    BATCH_SIZE: int = 1200


class BaseSingletonDetacher(BaseDetacher):
    BATCH_SIZE: int = 300
