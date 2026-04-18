import numpy as np
from PIL import Image

from ..registry import BasePlugin


class BaseImageLoader(BasePlugin):
    SCOPE: str = "*"

    def load(self, path: str, size: int | None = None) -> np.ndarray | None:
        return None

    def load_pil(self, path: str, size: int | None = None) -> Image.Image | None:
        return None
