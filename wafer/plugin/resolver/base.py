from __future__ import annotations

from abc import ABC
from collections.abc import Callable

from ...core.files.render_target import RenderTarget, ResolveContext
from ..registry import BasePlugin


ResolveChild = Callable[[str, ResolveContext], RenderTarget]


class BaseResolverPlugin(BasePlugin, ABC):
    SCOPE: str = "*"

    def resolve_target(
        self,
        path: str,
        *,
        purpose: str,
        context: ResolveContext,
        resolve_child: ResolveChild,
    ) -> RenderTarget | None:
        return self.resolve_materialized(path, purpose=purpose, context=context, resolve_child=resolve_child)

    def resolve_materialized(
        self,
        path: str,
        *,
        purpose: str,
        context: ResolveContext,
        resolve_child: ResolveChild,
    ) -> RenderTarget:
        return context.resolve_child(self.materialize(path, purpose=purpose), resolve_child)

    def materialize(self, path: str, *, purpose: str) -> str:
        raise NotImplementedError