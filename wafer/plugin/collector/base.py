from abc import abstractmethod
from dataclasses import dataclass, asdict

from ..registry import BasePlugin


@dataclass
class CollectorResult:
    source: str
    status: bool
    path: str | None = None
    name: str | None = None
    aspect: float | None = None
    file_hash: str | None = None
    meta_info: dict | None = None
    tags: dict | None = None

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


class BaseCollector(BasePlugin):
    @abstractmethod
    def process(self, path: str, file_info: tuple[float, int]) -> CollectorResult | list[CollectorResult]: ...


class BaseCollectorPlugin(BaseCollector):
    BATCH_SIZE: int = 1200


class BaseSingletonCollector(BaseCollector):
    BATCH_SIZE: int = 300
