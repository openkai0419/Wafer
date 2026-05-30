from __future__ import annotations

from collections import Counter, OrderedDict

from PIL import Image

from wafer.plugin import BaseCollectorPlugin, CollectorResult
from wafer.plugin.imageloader.handler import image_loader_resolver
from wafer.utils.logs import AppLogger

from ._color import PALETTE_SLOTS, palette_tags, rgb_to_packed
from .settings import color_config, palette_slots

_SAMPLE_SIZE = 256
_ALPHA_MIN = 16


class ColorCollector(BaseCollectorPlugin):
    NAME = "color"
    DISPLAY_NAME = "Color"
    EXTENSIONS = ()
    PRIORITY = 40
    BATCH_SIZE = 600
    MAX_WORKERS = 4
    MAX_TIMEOUT = 300.0
    DEFAULT_ENABLED = True

    def __init__(self):
        self._settings = color_config.load()

    def on_notify(self, payload=None) -> None:
        self._settings = color_config.load()
        AppLogger.info(f"[Color] settings reloaded: {self._settings}")

    def process(self, path: str, file_info: tuple) -> CollectorResult:
        image = image_loader_resolver.load_pil(path, size=_SAMPLE_SIZE)
        if image is None:
            return CollectorResult(source=path, status=False)
        slots = palette_slots(self._settings)
        try:
            colors = extract_palette(image, max_colors=slots)
        except Exception as exc:
            AppLogger.warning(f"[Color] palette extraction failed: {path}", exc=exc)
            return CollectorResult(source=path, status=False)
        return CollectorResult(source=path, status=True, tags=palette_tags(colors, slots))


def extract_palette(image: Image.Image, max_colors: int = PALETTE_SLOTS, sample_size: int = _SAMPLE_SIZE) -> list[int]:
    work = image.copy()
    work.thumbnail((sample_size, sample_size), Image.Resampling.LANCZOS)
    rgba = work.convert("RGBA")
    pixels = [(r, g, b) for r, g, b, a in rgba.get_flattened_data() if a >= _ALPHA_MIN]
    if not pixels:
        return []
    rgb = Image.new("RGB", (len(pixels), 1))
    rgb.putdata(pixels)
    quantized = rgb.quantize(colors=max_colors, method=Image.Quantize.MEDIANCUT)
    palette = quantized.getpalette() or []
    counts = Counter(quantized.get_flattened_data())
    out: OrderedDict[int, None] = OrderedDict()
    for index, _count in counts.most_common(max_colors * 2):
        offset = int(index) * 3
        if offset + 2 >= len(palette):
            continue
        packed = rgb_to_packed(palette[offset], palette[offset + 1], palette[offset + 2])
        out.setdefault(packed, None)
        if len(out) >= max_colors:
            break
    return list(out.keys())
