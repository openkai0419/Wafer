from __future__ import annotations

from wafer.core.files.render_target import ResolveContext, RenderTarget
from wafer.plugin import BaseGridPlugin

from .cache import zip_cache


class ZipGridPlugin(BaseGridPlugin):
    NAME = "zip"
    EXTENSIONS = (".zip",)
    PRIORITY = 80
    DEFAULT_ENABLED = True

    def resolve_target(self, path: str, grid_resolver, context: ResolveContext) -> RenderTarget:
        real_path = zip_cache.materialize(path, purpose="grid")
        return context.resolve_child(real_path, grid_resolver.resolve_target)
