from __future__ import annotations

from wafer.core.files.render_target import ResolveContext, RenderTarget
from wafer.plugin import BaseViewerPlugin

from .cache import zip_cache


class ZipViewerPlugin(BaseViewerPlugin):
    NAME = "zip"
    EXTENSIONS = (".zip",)
    PRIORITY = 80
    DEFAULT_ENABLED = True

    def resolve_target(self, path: str, viewer_resolver, context: ResolveContext) -> RenderTarget:
        real_path = zip_cache.materialize(path, purpose="viewer")
        return context.resolve_child(real_path, viewer_resolver.resolve_target)
