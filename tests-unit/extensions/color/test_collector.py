from __future__ import annotations


from PIL import Image

from extensions.color._color import rgb_to_packed
from extensions.color.collector import ColorCollector, extract_palette


def test_extract_palette_from_simple_image():
    image = Image.new("RGB", (20, 10), "red")
    colors = extract_palette(image)
    assert colors
    assert colors[0] == rgb_to_packed(255, 0, 0)


def test_color_collector_reloads_settings_and_uses_palette_slots(monkeypatch):
    image = Image.new("RGB", (4, 4), "red")
    collector = ColorCollector()
    collector._settings = {"palette_slots": 3}
    calls = {}

    monkeypatch.setattr("extensions.color.collector.image_loader_resolver.load_pil", lambda path, size: image)

    def fake_extract_palette(img, max_colors, sample_size=256):
        calls["max_colors"] = max_colors
        return [rgb_to_packed(255, 0, 0)] * max_colors

    monkeypatch.setattr("extensions.color.collector.extract_palette", fake_extract_palette)
    result = collector.process("sample.jpg", ())
    assert calls["max_colors"] == 3
    assert tuple(result.tags.keys()) == ("palette.1", "palette.2", "palette.3")

    monkeypatch.setattr("extensions.color.collector.color_config.load", lambda: {"palette_slots": 4})
    collector.on_notify({"palette_slots": 4})
    assert collector._settings == {"palette_slots": 4}
