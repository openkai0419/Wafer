import numpy as np
from PIL import Image
from PySide6 import QtGui

from ...core.files.render_target import RenderPlan, ResolveContext, SURFACE_IMAGE
from ...core.qt.image import numpy_to_qimage, pil_to_qimage
from ...utils.logs import AppLogger
from ...utils.profiling import profiler
from ..registry import FilePluginRegistry
from .base import BaseImageLoader


class ImageLoaderResolver:
    def __init__(self):
        self.registry = FilePluginRegistry()

    def resolve(self, path: str) -> type[BaseImageLoader] | None:
        return self.registry.resolve(path)

    def resolve_chain(self, path: str) -> list[type[BaseImageLoader]]:
        return self.registry.resolve_chain(path)

    def resolve_plan(self, path: str, context: ResolveContext | None = None) -> RenderPlan[BaseImageLoader] | None:
        return next(self._plans(path, context), None)

    @profiler.profile
    def load(self, path: str, size: int | None = None) -> np.ndarray | None:
        for plan in self._plans(path):
            instance = plan.handler
            result = instance.load(plan.resolved_path, size)
            if result is not None:
                return result
            pil = instance.load_pil(plan.resolved_path, size)
            if pil is not None:
                if pil.mode not in ("RGB", "RGBA", "L"):
                    pil = pil.convert("RGB")
                return np.asarray(pil)
        return None

    @profiler.profile
    def load_pil(self, path: str, size: int | None = None) -> Image.Image | None:
        for plan in self._plans(path):
            instance = plan.handler
            pil = instance.load_pil(plan.resolved_path, size)
            if pil is not None:
                return pil
            arr = instance.load(plan.resolved_path, size)
            if arr is not None:
                mode = "L" if arr.ndim == 2 else ("RGBA" if arr.ndim == 3 and arr.shape[2] == 4 else "RGB")
                return Image.fromarray(arr, mode=mode)
        return None

    @profiler.profile
    def load_qimage(self, path: str, size: int | None = None) -> QtGui.QImage | None:
        for plan in self._plans(path):
            instance = plan.handler
            image = instance.load_qimage(plan.resolved_path, size)
            if image is not None and not image.isNull():
                return image
            pil = instance.load_pil(plan.resolved_path, size)
            if pil is not None:
                return pil_to_qimage(pil)
            arr = instance.load(plan.resolved_path, size)
            if arr is not None:
                return numpy_to_qimage(arr)
        return None

    def _plans(self, path: str, context: ResolveContext | None = None):
        delegated_plans: list[RenderPlan[BaseImageLoader]] = []

        def resolve_delegated(new_path: str, child_context: ResolveContext):
            delegated_plans[:] = list(self._plans(new_path, child_context))
            return delegated_plans[0] if delegated_plans else None

        context = context or ResolveContext.create(path, surface=SURFACE_IMAGE, resolver=resolve_delegated)
        if context.resolver is not resolve_delegated:
            context = ResolveContext(
                source=context.source,
                path=context.path,
                surface=context.surface,
                resolver=resolve_delegated,
                depth=context.depth,
                max_depth=context.max_depth,
            )
        for plugin_cls in self.registry.resolve_chain(path):
            delegated_plans.clear()
            instance = self.registry.instance(plugin_cls.NAME)
            if not isinstance(instance, BaseImageLoader):
                continue
            try:
                plan = instance.resolve(path, context)
            except Exception as exc:
                AppLogger.warning(f"[ImageLoaderResolver] resolve failed: plugin={plugin_cls.NAME} path={path} error={type(exc).__name__}: {exc}", exc=exc)
                continue
            if delegated_plans:
                yield from delegated_plans
                return
            if isinstance(plan, RenderPlan) and isinstance(plan.handler, BaseImageLoader):
                yield plan


image_loader_resolver = ImageLoaderResolver()
