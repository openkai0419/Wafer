import os
import glob
import pytest
from PIL import Image

from source.os.thumbnails import FileThumbnailer


def _find_test_image():
    dl = os.path.expanduser("~/Downloads")
    for ext in ("*.jpg", "*.jpeg", "*.png", "*.webp"):
        files = glob.glob(os.path.join(dl, ext))
        if files:
            return files[0]
    pictures = os.path.expanduser("~/Pictures")
    for ext in ("*.jpg", "*.jpeg", "*.png", "*.webp"):
        files = glob.glob(os.path.join(pictures, ext))
        if files:
            return files[0]
    return None


@pytest.fixture
def thumbnailer():
    return FileThumbnailer()


@pytest.fixture
def test_image():
    path = _find_test_image()
    if path is None:
        pytest.skip("No test image found in ~/Downloads or ~/Pictures")
    return path


class TestGetFileDimensions:
    def test_returns_tuple(self, thumbnailer, test_image):
        dims = thumbnailer.get_file_dimensions(test_image)
        assert dims is not None
        assert isinstance(dims, tuple)
        assert len(dims) == 2

    def test_positive_values(self, thumbnailer, test_image):
        w, h = thumbnailer.get_file_dimensions(test_image)
        assert w > 0
        assert h > 0

    def test_nonexistent_returns_none(self, thumbnailer):
        result = thumbnailer.get_file_dimensions("Z:/nonexistent/file.jpg")
        assert result is None

    def test_multiple_calls(self, thumbnailer, test_image):
        d1 = thumbnailer.get_file_dimensions(test_image)
        d2 = thumbnailer.get_file_dimensions(test_image)
        assert d1 == d2

    def test_forward_slash_path(self, thumbnailer, test_image):
        fwd = test_image.replace("\\", "/")
        dims = thumbnailer.get_file_dimensions(fwd)
        assert dims is not None


class TestGetThumbnail:
    def test_returns_image(self, thumbnailer, test_image):
        img = thumbnailer.get_thumbnail(test_image, size=64)
        assert img is not None
        assert isinstance(img, Image.Image)

    def test_image_size_within_bounds(self, thumbnailer, test_image):
        size = 128
        img = thumbnailer.get_thumbnail(test_image, size=size)
        assert img is not None
        assert img.width <= size
        assert img.height <= size

    def test_nonexistent_raises(self, thumbnailer):
        with pytest.raises(FileNotFoundError):
            thumbnailer.get_thumbnail("Z:/nonexistent/file.jpg")

    def test_forward_slash_path(self, thumbnailer, test_image):
        fwd = test_image.replace("\\", "/")
        img = thumbnailer.get_thumbnail(fwd, size=64)
        assert img is not None

    def test_multiple_calls_no_crash(self, thumbnailer, test_image):
        for _ in range(3):
            img = thumbnailer.get_thumbnail(test_image, size=64)
            assert img is not None

    def test_different_sizes(self, thumbnailer, test_image):
        for size in (64, 128, 256):
            img = thumbnailer.get_thumbnail(test_image, size=size)
            assert img is not None
            assert img.width <= size
            assert img.height <= size


class TestConsistency:
    def test_dimensions_match_thumbnail_aspect(self, thumbnailer, test_image):
        dims = thumbnailer.get_file_dimensions(test_image)
        img = thumbnailer.get_thumbnail(test_image, size=256)
        if dims and img:
            real_ratio = dims[0] / dims[1]
            thumb_ratio = img.width / img.height
            assert abs(real_ratio - thumb_ratio) < 0.1
