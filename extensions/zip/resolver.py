from __future__ import annotations

from wafer.core.files.render_target import RenderTarget, ResolveContext
from wafer.plugin import BaseResolverPlugin
from wafer.utils.virtual_paths import is_virtual_path

from .cache import zip_cache


class ZipResolverPlugin(BaseResolverPlugin):
    NAME = "zip"
    EXTENSIONS = (".zip",)
    OWNS_VIRTUAL_CHILDREN = True
    PRIORITY = 80
    DEFAULT_ENABLED = True

    @classmethod
    def can_handle(cls, path: str) -> bool:
        return is_virtual_path(path)

    def resolve_target(self, path: str, *, purpose: str, context: ResolveContext, resolve_child) -> RenderTarget | None:
        return self.resolve_materialized(path, purpose=purpose, context=context, resolve_child=resolve_child)

    def materialize(self, path: str, *, purpose: str) -> str:
        return zip_cache.materialize(path, purpose=purpose)