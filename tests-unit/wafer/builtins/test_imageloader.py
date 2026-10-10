from unittest.mock import MagicMock

from PIL import Image

from wafer.builtins.imageloader import SystemImageLoader
from wafer.plugin.imageloader.handler import image_loader_resolver


def loader_with_thumbnailer(thumbnail):
    loader = SystemImageLoader()
    loader._thumbnailer = MagicMock()
    loader._thumbnailer.get_thumbnail.return_value = thumbnail
    return loader


def test_load_pil_nonexistent_returns_none():
    assert SystemImageLoader().load_pil("/nonexistent/path.xyz") is None


def test_load_pil_passes_explicit_size():
    loader = loader_with_thumbnailer(None)
    loader.load_pil("dummy.xyz", size=400)
    loader._thumbnailer.get_thumbnail.assert_called_once_with("dummy.xyz", size=400)


def test_load_pil_defaults_to_256_and_converts_to_rgb():
    loader = loader_with_thumbnailer(Image.new("P", (8, 8)))
    result = loader.load_pil("dummy.xyz")
    loader._thumbnailer.get_thumbnail.assert_called_once_with("dummy.xyz", size=256)
    assert result.mode == "RGB"


def test_chain_system_thumbnail_is_last_for_jpg():
    chain = image_loader_resolver.resolve_chain("photo.jpg")
    assert chain[-1] is SystemImageLoader
