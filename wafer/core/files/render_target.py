from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Generic, TypeVar

from ...utils.virtual_paths import source_path


SURFACE_VIEWER = "viewer"
SURFACE_GRID = "grid"
SURFACE_IMAGE = "image"

T = TypeVar("T")


@dataclass(frozen=True)
class RenderPlan(Generic[T]):
    source: str
    path: str
    resolved_path: str
    handler: T


ResolveCallback = Callable[[str, "ResolveContext"], RenderPlan | None]


@dataclass(frozen=True)
class ResolveContext:
    source: str
    path: str
    surface: str
    resolver: ResolveCallback
    depth: int = 0
    max_depth: int = 4

    @classmethod
    def create(
        cls,
        path: str,
        *,
        surface: str,
        resolver: ResolveCallback,
        source: str | None = None,
        max_depth: int = 4,
    ) -> ResolveContext:
        return cls(
            source=source or source_path(path),
            path=path,
            surface=surface,
            resolver=resolver,
            max_depth=max_depth,
        )

    def child(self) -> ResolveContext:
        if self.depth >= self.max_depth:
            raise RecursionError(f"render plan resolution exceeded depth={self.max_depth}: {self.path}")
        return replace(self, depth=self.depth + 1)

    def resolve_new(self, path: str) -> RenderPlan | None:
        return self.resolver(path, self.child())


__all__ = ["SURFACE_GRID", "SURFACE_IMAGE", "SURFACE_VIEWER", "RenderPlan", "ResolveContext"]
