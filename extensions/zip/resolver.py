from __future__ import annotations

from wafer.core.files.render_target import RenderPlan, ResolveContext
from wafer.plugin import BaseImageLoader, WidgetGridPlugin, WidgetViewerPlugin
from wafer.utils.virtual_paths import is_virtual_path, owner_extension

from .cache import zip_cache


def can_handle_zip_virtual_path(path: str) -> bool:
    return is_virtual_path(path) and owner_extension(path) == ".zip"


class ZipViewerPlugin(WidgetViewerPlugin):
    NAME = "zip"
    EXTENSIONS = (".zip",)
    PRIORITY = 300
    DEFAULT_ENABLED = True
    WIDGET_CLASS = None

    @classmethod
    def can_handle(cls, path: str) -> bool:
        return can_handle_zip_virtual_path(path)

    def resolve(self, path: str, context: ResolveContext) -> RenderPlan | None:
        if not self.can_handle(path):
            return None
        return context.resolve_new(zip_cache.materialize(path, purpose=context.surface))


class ZipGridPlugin(WidgetGridPlugin):
    NAME = "zip"
    EXTENSIONS = (".zip",)
    PRIORITY = 300
    DEFAULT_ENABLED = True
    WIDGET_CLASS = None

    @classmethod
    def can_handle(cls, path: str) -> bool:
        return can_handle_zip_virtual_path(path)

    def resolve(self, path: str, context: ResolveContext) -> RenderPlan | None:
        if not self.can_handle(path):
            return None
        return context.resolve_new(zip_cache.materialize(path, purpose=context.surface))


class ZipImageLoader(BaseImageLoader):
    NAME = "zip"
    EXTENSIONS = (".zip",)
    PRIORITY = 300
    DEFAULT_ENABLED = True
    SCOPE = "*"

    @classmethod
    def can_handle(cls, path: str) -> bool:
        return can_handle_zip_virtual_path(path)

    def resolve(self, path: str, context: ResolveContext) -> RenderPlan | None:
        if not self.can_handle(path):
            return None
        return context.resolve_new(zip_cache.materialize(path, purpose=context.surface))