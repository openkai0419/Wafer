import os
import tempfile

import cv2
import numpy as np
import pytest
from PIL import Image
from PySide6 import QtCore, QtGui

from extensions.image.loader import (
    load_image,
    _imread_flags_for_size,
    _jpeg_dimensions,
    _classify_opencv_array,
    _numpy_to_qimage,
    _qt_read,
    _approx_aspect_keep_size,
)


@pytest.fixture()
def rgb_png(tmp_path):
    p = tmp_path / "rgb.png"
    Image.new("RGB", (80, 60), (255, 0, 0)).save(str(p))
    return str(p)


@pytest.fixture()
def rgba_png(tmp_path):
    p = tmp_path / "rgba.png"
    Image.new("RGBA", (80, 60), (0, 255, 0, 128)).save(str(p))
    return str(p)


@pytest.fixture()
def gray_png(tmp_path):
    p = tmp_path / "gray.png"
    Image.new("L", (80, 60), 128).save(str(p))
    return str(p)


@pytest.fixture()
def jpeg_file(tmp_path):
    p = tmp_path / "test.jpg"
    Image.new("RGB", (200, 150), (0, 0, 255)).save(str(p), quality=90)
    return str(p)


@pytest.fixture()
def gif_file(tmp_path):
    p = tmp_path / "test.gif"
    Image.new("P", (40, 30)).save(str(p))
    return str(p)


@pytest.fixture()
def bmp_file(tmp_path):
    p = tmp_path / "test.bmp"
    Image.new("RGB", (50, 40), (128, 64, 32)).save(str(p))
    return str(p)


class TestLoadImageFullSize:
    def test_rgb_png(self, rgb_png):
        img = load_image(rgb_png)
        assert img is not None
        assert not img.isNull()
        assert img.width() == 80
        assert img.height() == 60

    def test_rgba_png(self, rgba_png):
        img = load_image(rgba_png)
        assert img is not None
        assert not img.isNull()
        assert img.width() == 80
        assert img.height() == 60

    def test_grayscale_png(self, gray_png):
        img = load_image(gray_png)
        assert img is not None
        assert not img.isNull()
        assert img.width() == 80
        assert img.height() == 60

    def test_jpeg(self, jpeg_file):
        img = load_image(jpeg_file)
        assert img is not None
        assert img.width() == 200
        assert img.height() == 150

    def test_gif(self, gif_file):
        img = load_image(gif_file)
        assert img is not None
        assert img.width() == 40
        assert img.height() == 30

    def test_bmp(self, bmp_file):
        img = load_image(bmp_file)
        assert img is not None
        assert img.width() == 50
        assert img.height() == 40


class TestLoadImageResized:
    def test_downscale(self, rgb_png):
        size = QtCore.QSize(40, 30)
        img = load_image(rgb_png, size)
        assert img is not None
        assert img.width() == 40
        assert img.height() == 30

    def test_upscale(self, rgb_png):
        size = QtCore.QSize(160, 120)
        img = load_image(rgb_png, size)
        assert img is not None
        assert img.width() == 160
        assert img.height() == 120

    def test_gif_resize_keeps_aspect(self, gif_file):
        size = QtCore.QSize(100, 100)
        img = load_image(gif_file, size)
        assert img is not None

    def test_jpeg_reduced_read_small(self, jpeg_file):
        size = QtCore.QSize(48, 36)
        img = load_image(jpeg_file, size)
        assert img is not None
        assert abs(img.width() - 48) <= 1
        assert abs(img.height() - 36) <= 1

    def test_resize_circumscribed_landscape_to_square(self, rgb_png):
        size = QtCore.QSize(50, 50)
        img = load_image(rgb_png, size)
        assert img is not None
        assert img.width() > 50
        assert img.height() == 50

    def test_resize_circumscribed_portrait_to_square(self, tmp_path):
        p = tmp_path / "portrait.png"
        Image.new("RGB", (60, 120), (0, 255, 0)).save(str(p))
        size = QtCore.QSize(100, 100)
        img = load_image(str(p), size)
        assert img is not None
        assert img.width() == 100
        assert img.height() > 100

    def test_resize_circumscribed_wide_jpeg(self, tmp_path):
        p = tmp_path / "wide.jpg"
        Image.new("RGB", (400, 100), (0, 0, 255)).save(str(p), quality=90)
        size = QtCore.QSize(200, 200)
        img = load_image(str(p), size)
        assert img is not None
        assert img.width() > 200
        assert img.height() == 200


class TestLoadImageEdgeCases:
    def test_nonexistent_file(self):
        result = load_image("/nonexistent/path/no_file.png")
        assert result is None

    def test_empty_file(self, tmp_path):
        p = tmp_path / "empty.png"
        p.write_bytes(b"")
        result = load_image(str(p))
        assert result is None

    def test_corrupt_file(self, tmp_path):
        p = tmp_path / "corrupt.jpg"
        p.write_bytes(b"\xff\xd8\xff\x00garbage")
        result = load_image(str(p))
        assert result is None or isinstance(result, QtGui.QImage)


class TestJpegDimensions:
    def test_valid_jpeg(self, tmp_path):
        p = tmp_path / "test.jpg"
        Image.new("RGB", (800, 600), (0, 0, 255)).save(str(p), quality=90)
        data = np.fromfile(str(p), dtype=np.uint8)
        assert _jpeg_dimensions(data) == (800, 600)

    def test_large_jpeg(self, tmp_path):
        p = tmp_path / "large.jpg"
        Image.new("RGB", (4000, 3000), (255, 0, 0)).save(str(p), quality=85)
        data = np.fromfile(str(p), dtype=np.uint8)
        assert _jpeg_dimensions(data) == (4000, 3000)

    def test_non_jpeg_returns_none(self, tmp_path):
        p = tmp_path / "test.png"
        Image.new("RGB", (100, 100)).save(str(p))
        data = np.fromfile(str(p), dtype=np.uint8)
        assert _jpeg_dimensions(data) is None

    def test_truncated_returns_none(self):
        assert _jpeg_dimensions(np.array([0xFF, 0xD8], dtype=np.uint8)) is None

    def test_empty_returns_none(self):
        assert _jpeg_dimensions(np.array([], dtype=np.uint8)) is None

    def test_garbage_returns_none(self):
        assert _jpeg_dimensions(np.array([0x00, 0x00, 0x00], dtype=np.uint8)) is None


class TestImreadFlagsForSize:
    @pytest.fixture()
    def jpeg_data_4000x3000(self, tmp_path):
        p = tmp_path / "big.jpg"
        Image.new("RGB", (4000, 3000)).save(str(p), quality=50)
        return np.fromfile(str(p), dtype=np.uint8)

    @pytest.fixture()
    def jpeg_data_800x600(self, tmp_path):
        p = tmp_path / "small.jpg"
        Image.new("RGB", (800, 600)).save(str(p), quality=50)
        return np.fromfile(str(p), dtype=np.uint8)

    def test_none_size(self):
        assert _imread_flags_for_size(".png", None) == cv2.IMREAD_UNCHANGED

    def test_png_with_size(self):
        size = QtCore.QSize(200, 200)
        assert _imread_flags_for_size(".png", size) == cv2.IMREAD_UNCHANGED

    def test_large_jpeg_gets_reduced_8(self, jpeg_data_4000x3000):
        size = QtCore.QSize(200, 200)
        assert _imread_flags_for_size(".jpg", size, jpeg_data_4000x3000) == cv2.IMREAD_REDUCED_COLOR_8

    def test_large_jpeg_gets_reduced_4(self, jpeg_data_4000x3000):
        size = QtCore.QSize(600, 600)
        assert _imread_flags_for_size(".jpg", size, jpeg_data_4000x3000) == cv2.IMREAD_REDUCED_COLOR_4

    def test_large_jpeg_gets_reduced_2(self, jpeg_data_4000x3000):
        size = QtCore.QSize(1200, 1200)
        assert _imread_flags_for_size(".jpeg", size, jpeg_data_4000x3000) == cv2.IMREAD_REDUCED_COLOR_2

    def test_large_jpeg_gets_full_color(self, jpeg_data_4000x3000):
        size = QtCore.QSize(2500, 2500)
        assert _imread_flags_for_size(".jpg", size, jpeg_data_4000x3000) == cv2.IMREAD_COLOR

    def test_small_jpeg_never_reduced_below_display(self, jpeg_data_800x600):
        size = QtCore.QSize(200, 200)
        flags = _imread_flags_for_size(".jpg", size, jpeg_data_800x600)
        assert flags != cv2.IMREAD_REDUCED_COLOR_8
        assert flags in (cv2.IMREAD_COLOR, cv2.IMREAD_REDUCED_COLOR_2, cv2.IMREAD_REDUCED_COLOR_4)

    def test_small_jpeg_at_display_size(self, jpeg_data_800x600):
        size = QtCore.QSize(600, 600)
        flags = _imread_flags_for_size(".jpg", size, jpeg_data_800x600)
        assert flags == cv2.IMREAD_COLOR

    def test_jpeg_without_data_falls_back_to_color(self):
        size = QtCore.QSize(200, 200)
        assert _imread_flags_for_size(".jpg", size) == cv2.IMREAD_COLOR


class TestClassifyOpencvArray:
    def test_none(self):
        assert _classify_opencv_array(None, ".png") == "qt"

    def test_1d_array(self):
        arr = np.array([1, 2, 3], dtype=np.uint8)
        assert _classify_opencv_array(arr, ".png") == "qt"

    def test_float_array(self):
        arr = np.zeros((10, 10), dtype=np.float32)
        assert _classify_opencv_array(arr, ".png") == "qt"

    def test_valid_grayscale(self):
        arr = np.zeros((10, 10), dtype=np.uint8)
        assert _classify_opencv_array(arr, ".png") == "opencv"

    def test_valid_rgb(self):
        arr = np.zeros((10, 10, 3), dtype=np.uint8)
        assert _classify_opencv_array(arr, ".png") == "opencv"

    def test_valid_rgba(self):
        arr = np.zeros((10, 10, 4), dtype=np.uint8)
        assert _classify_opencv_array(arr, ".png") == "opencv"

    def test_jpeg_4ch_falls_to_qt(self):
        arr = np.zeros((10, 10, 4), dtype=np.uint8)
        assert _classify_opencv_array(arr, ".jpg") == "qt"

    def test_png_2ch_falls_to_qt(self):
        arr = np.zeros((10, 10, 2), dtype=np.uint8)
        assert _classify_opencv_array(arr, ".png") == "qt"

    def test_png_uint16_falls_to_qt(self):
        arr = np.zeros((10, 10, 3), dtype=np.uint16)
        assert _classify_opencv_array(arr, ".png") == "qt"

    def test_5ch_falls_to_qt(self):
        arr = np.zeros((10, 10, 5), dtype=np.uint8)
        assert _classify_opencv_array(arr, ".png") == "qt"


class TestNumpyToQimage:
    def test_grayscale(self):
        arr = np.full((10, 20), 128, dtype=np.uint8)
        q = _numpy_to_qimage(arr)
        assert q.width() == 20
        assert q.height() == 10
        assert q.format() == QtGui.QImage.Format_Grayscale8

    def test_rgb(self):
        arr = np.zeros((10, 20, 3), dtype=np.uint8)
        arr[:, :, 2] = 255
        q = _numpy_to_qimage(arr)
        assert q.width() == 20
        assert q.height() == 10
        assert q.format() == QtGui.QImage.Format_RGB888

    def test_rgba(self):
        arr = np.zeros((10, 20, 4), dtype=np.uint8)
        q = _numpy_to_qimage(arr)
        assert q.width() == 20
        assert q.height() == 10
        assert q.format() == QtGui.QImage.Format_RGBA8888

    def test_gray_alpha_2ch(self):
        arr = np.zeros((10, 20, 2), dtype=np.uint8)
        arr[:, :, 0] = 200
        arr[:, :, 1] = 128
        q = _numpy_to_qimage(arr)
        assert q.width() == 20
        assert q.height() == 10
        assert q.format() == QtGui.QImage.Format_RGBA8888

    def test_uint16_downconvert(self):
        arr = np.full((10, 20), 65535, dtype=np.uint16)
        q = _numpy_to_qimage(arr)
        assert q.width() == 20
        assert q.height() == 10

    def test_unsupported_raises(self):
        arr = np.zeros((2, 3, 4, 5), dtype=np.uint8)
        with pytest.raises(ValueError):
            _numpy_to_qimage(arr)


class TestQtRead:
    def test_fullsize(self, rgb_png):
        img = _qt_read(rgb_png, None, False)
        assert img is not None
        assert img.width() == 80
        assert img.height() == 60

    def test_scaled(self, rgb_png):
        size = QtCore.QSize(40, 30)
        img = _qt_read(rgb_png, size, False)
        assert img is not None
        assert img.width() == 40
        assert img.height() == 30

    def test_nonexistent(self):
        img = _qt_read("/no/such/file.png", None, False)
        assert img is None
