from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import TypeVar


TARGET_IMAGE = "image"
TARGET_WIDGET = "widget"

T = TypeVar("T")


@dataclass(frozen=True)
class RenderRequest:
    logical_path: str
    render_path: str | None = None
    source_path: str | None = None

    @property
    def path(self) -> str:
        return self.render_path or self.logical_path


@dataclass(frozen=True)
class RenderTarget:
    logical_path: str
    render_path: str
    kind: str = TARGET_IMAGE
    plugin_name: str | None = None
    source_path: str | None = None

    @property
    def cache_path(self) -> str:
        return self.logical_path


@dataclass(frozen=True)
class ResolveContext:
    logical_path: str
    depth: int = 0
    max_depth: int = 4

    def child(self, logical_path: str | None = None) -> ResolveContext:
        if self.depth >= self.max_depth:
            raise RecursionError(f"render target resolution exceeded depth={self.max_depth}: {self.logical_path}")
        return replace(self, logical_path=logical_path or self.logical_path, depth=self.depth + 1)

    def resolve_child(self, path: str, callback: Callable[[str, ResolveContext], T]) -> T:
        return callback(path, self.child())
