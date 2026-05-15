from __future__ import annotations

from ...core.files.render_target import RenderTarget, ResolveContext
from ...utils.virtual_paths import is_virtual_path
from ..registry import DISPATCH_NORMAL, DISPATCH_OWNER, FilePluginRegistry
from .base import BaseResolverPlugin, ResolveChild


class ResolverRegistry:
    def __init__(self):
        self.registry = FilePluginRegistry()

    def resolve_target(
        self,
        path: str,
        *,
        purpose: str,
        context: ResolveContext,
        resolve_child: ResolveChild,
    ) -> RenderTarget | None:
        mode = DISPATCH_OWNER if is_virtual_path(path) else DISPATCH_NORMAL
        for plugin_cls in self.registry.resolve_chain(path, mode):
            if not plugin_cls.can_handle(path):
                continue
            instance = self.registry.instance(plugin_cls.NAME)
            if isinstance(instance, BaseResolverPlugin):
                target = instance.resolve_target(path, purpose=purpose, context=context, resolve_child=resolve_child)
                if isinstance(target, RenderTarget):
                    return target
        return None


resolver_registry = ResolverRegistry()