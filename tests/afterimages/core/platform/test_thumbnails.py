import os
import sys
import tempfile
import zipfile
import pytest
from PIL import Image
from afterimages.core.platform.thumbnails import FileThumbnailer, get_aspect_ratios


@pytest.fixture
def thumbnailer():
    return FileThumbnailer()


def _create_temp_image(width, height, suffix=".png", fmt="PNG"):
    f = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    Image.new("RGB", (width, height)).save(f, format=fmt)
    f.close()
    return f.name


def _create_temp_zip_with_image(width, height):
    tmp_dir = tempfile.mkdtemp()
    img_path = os.path.join(tmp_dir, "image.png")
    Image.new("RGB", (width, height), color="blue").save(img_path, format="PNG")
    zip_path = os.path.join(tmp_dir, "archive.zip")
    with zipfile.ZipFile(zip_path, 'w') as zf:
        zf.write(img_path, "image.png")
    os.unlink(img_path)
    return zip_path, tmp_dir


def test_get_file_dimensions_nonexistent(thumbnailer):
    assert thumbnailer.get_file_dimensions("/nonexistent/file.jpg") is None


def test_get_thumbnail_nonexistent(thumbnailer):
    with pytest.raises(FileNotFoundError):
        thumbnailer.get_thumbnail("/nonexistent/file.jpg")


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="Windows only")
def test_get_file_dimensions_image(thumbnailer):
    path = _create_temp_image(100, 50)
    try:
        result = thumbnailer.get_file_dimensions(path)
        if result is not None:
            assert result == (100, 50)
    finally:
        os.unlink(path)


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="Windows only")
def test_get_thumbnail_returns_image(thumbnailer):
    path = _create_temp_image(200, 200)
    try:
        result = thumbnailer.get_thumbnail(path, size=64)
        if result is not None:
            assert isinstance(result, Image.Image)
            assert result.size[0] > 0 and result.size[1] > 0
    finally:
        os.unlink(path)


def test_platform_is_set(thumbnailer):
    assert thumbnailer.platform == sys.platform


def test_get_aspect_ratios_empty():
    assert get_aspect_ratios([]) == {}


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="Windows only")
def test_get_aspect_ratios_image():
    path = _create_temp_image(200, 100)
    try:
        result = get_aspect_ratios([path])
        if result:
            assert abs(result[path] - 2.0) < 0.01
    finally:
        os.unlink(path)


def test_get_aspect_ratios_nonexistent():
    assert isinstance(get_aspect_ratios(["/nonexistent/file.png"]), dict)


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="Windows only")
def test_get_aspect_ratios_zip_with_landscape_image():
    zip_path, tmp_dir = _create_temp_zip_with_image(400, 200)
    try:
        result = get_aspect_ratios([zip_path])
        assert zip_path in result
        assert abs(result[zip_path] - 2.0) < 0.1
    finally:
        os.unlink(zip_path)
        os.rmdir(tmp_dir)


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="Windows only")
def test_get_aspect_ratios_zip_with_portrait_image():
    zip_path, tmp_dir = _create_temp_zip_with_image(200, 400)
    try:
        result = get_aspect_ratios([zip_path])
        assert zip_path in result
        assert abs(result[zip_path] - 0.5) < 0.1
    finally:
        os.unlink(zip_path)
        os.rmdir(tmp_dir)


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="Windows only")
def test_get_aspect_ratios_mixed_image_and_zip():
    img_path = _create_temp_image(300, 100)
    zip_path, tmp_dir = _create_temp_zip_with_image(100, 400)
    try:
        result = get_aspect_ratios([img_path, zip_path])
        if img_path in result:
            assert abs(result[img_path] - 3.0) < 0.1
        assert zip_path in result
        assert abs(result[zip_path] - 0.25) < 0.1
    finally:
        os.unlink(img_path)
        os.unlink(zip_path)
        os.rmdir(tmp_dir)
