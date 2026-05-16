from __future__ import annotations

from typing import TYPE_CHECKING

from PIL import Image

from ...core.files.render_target import RenderPlan, ResolveContext
from ..registry import BasePlugin

if TYPE_CHECKING:
    import numpy as np
    from PySide6 import QtGui


class BaseImageLoader(BasePlugin):
    SCOPE: str = "*"

    def resolve(self, path: str, context: ResolveContext) -> RenderPlan | None:
        if not type(self).can_handle(path):
            return None
        return RenderPlan(source=context.source, path=context.path, resolved_path=path, handler=self)

    def load(self, path: str, size: int | None = None) -> np.ndarray | None:
        return None

    def load_pil(self, path: str, size: int | None = None) -> Image.Image | None:
        return None

    def load_qimage(self, path: str, size: int | None = None) -> QtGui.QImage | None:
        return None
