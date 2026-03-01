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


class BaseCollectorPlugin(BasePlugin):

    @abstractmethod
    def process(self, path: str, file_info: tuple):
        ...
