import os
import sys
import tempfile
import pytest
from PIL import Image
from source.os.thumbnails import FileThumbnailer


@pytest.fixture
def thumbnailer():
    return FileThumbnailer()


def test_get_file_dimensions_nonexistent(thumbnailer):
    result = thumbnailer.get_file_dimensions("/nonexistent/file.jpg")
    assert result is None


def test_get_thumbnail_nonexistent(thumbnailer):
    with pytest.raises(FileNotFoundError):
        thumbnailer.get_thumbnail("/nonexistent/file.jpg")


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="Windows only")
def test_get_file_dimensions_image(thumbnailer):
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        img = Image.new("RGB", (100, 50))
        img.save(f, format="PNG")
        path = f.name
    try:
        result = thumbnailer.get_file_dimensions(path)
        if result is not None:
            w, h = result
            assert w == 100
            assert h == 50
    finally:
        os.unlink(path)


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="Windows only")
def test_get_thumbnail_returns_image(thumbnailer):
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        img = Image.new("RGB", (200, 200), color="red")
        img.save(f, format="PNG")
        path = f.name
    try:
        result = thumbnailer.get_thumbnail(path, size=64)
        if result is not None:
            assert isinstance(result, Image.Image)
            assert result.size[0] > 0
            assert result.size[1] > 0
    finally:
        os.unlink(path)


def test_platform_is_set(thumbnailer):
    assert thumbnailer.platform == sys.platform
