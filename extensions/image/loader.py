import os
import struct

import cv2
import numpy as np
from PySide6 import QtCore, QtGui

from wafer.utils.logs import AppLogger
from wafer.utils.profiling import profiler


@profiler.profile
def load_image(path: str, size: QtCore.QSize | None = None) -> QtGui.QImage | None:
    ext = os.path.splitext(path)[-1].lower()
    try:
        if ext == ".gif":
            return _qt_read(path, size, keep_aspect=True)

        try:
            data = np.fromfile(path, dtype=np.uint8)
        except (OSError, MemoryError):
            with open(path, "rb") as f:
                data = np.frombuffer(f.read(), dtype=np.uint8)
        flags = _imread_flags_for_size(ext, size, data)
        arr = cv2.imdecode(data, flags)

        if _classify_opencv_array(arr, ext) != "opencv":
            img = _qt_read(path, size, keep_aspect=True)
            if img is not None:
                return img

        if arr is None:
            return _qt_read(path, size, keep_aspect=True)

        if size is not None:
            h, w = arr.shape[:2]
            if (abs(w - size.width()) + abs(h - size.height())) > 2:
                sw, sh = size.width() / w, size.height() / h
                scale = max(sw, sh)
                new_w = max(1, round(w * scale))
                new_h = max(1, round(h * scale))
                interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LANCZOS4
                arr = cv2.resize(arr, (new_w, new_h), interpolation=interp)

        return _numpy_to_qimage(arr)

    except Exception as e:
        try:
            img = _qt_read(path, size, keep_aspect=True)
            if img is not None:
                return img
        except Exception as qe:
            AppLogger.warning(f"[image/loader] Qt fallback failed: {path} ({qe})")
        AppLogger.warning(f"[image/loader] Failed to load image: {path} ({e})")
        return None


@profiler.profile
def _qt_read(path, size, keep_aspect):
    reader = QtGui.QImageReader(path)
    reader.setAutoTransform(True)
    if size is not None:
        if keep_aspect:
            sz = _approx_aspect_keep_size(reader, size)
            reader.setScaledSize(sz)
        else:
            reader.setScaledSize(size)
    image = reader.read()
    if image.isNull():
        return None
    return image


def _approx_aspect_keep_size(reader, target):
    sz = reader.size()
    if not sz.isValid():
        return target
    tw, th = target.width(), target.height()
    rw, rh = sz.width(), sz.height()
    if rw <= 0 or rh <= 0 or tw <= 0 or th <= 0:
        return target
    scale = max(tw / rw, th / rh)
    return QtCore.QSize(max(1, int(rw * scale)), max(1, int(rh * scale)))


_SOF_MARKERS = frozenset(
    (
        0xC0,
        0xC1,
        0xC2,
        0xC3,
        0xC5,
        0xC6,
        0xC7,
        0xC9,
        0xCA,
        0xCB,
        0xCD,
        0xCE,
        0xCF,
    )
)


def _jpeg_dimensions(data):
    n = len(data)
    if n < 10 or data[0] != 0xFF or data[1] != 0xD8:
        return None
    i = 2
    while i + 3 < n:
        if data[i] != 0xFF:
            return None
        i += 1
        while i < n and data[i] == 0xFF:
            i += 1
        if i >= n:
            return None
        marker = int(data[i])
        i += 1
        if marker == 0x00 or marker == 0xD9:
            return None
        if 0xD0 <= marker <= 0xD8 or marker == 0x01:
            continue
        if i + 1 >= n:
            return None
        seg_len = struct.unpack_from(">H", data, i)[0]
        if marker in _SOF_MARKERS and i + 6 < n:
            h = struct.unpack_from(">H", data, i + 3)[0]
            w = struct.unpack_from(">H", data, i + 5)[0]
            if w > 0 and h > 0:
                return w, h
        i += seg_len
    return None


def _imread_flags_for_size(ext, size, data=None):
    if size is None:
        return cv2.IMREAD_UNCHANGED
    if ext in (".jpg", ".jpeg"):
        dims = _jpeg_dimensions(data) if data is not None else None
        if dims is not None:
            ow, oh = dims
            tw, th = size.width(), size.height()
            if ow // 8 >= tw and oh // 8 >= th:
                return cv2.IMREAD_REDUCED_COLOR_8
            if ow // 4 >= tw and oh // 4 >= th:
                return cv2.IMREAD_REDUCED_COLOR_4
            if ow // 2 >= tw and oh // 2 >= th:
                return cv2.IMREAD_REDUCED_COLOR_2
        return cv2.IMREAD_COLOR
    return cv2.IMREAD_UNCHANGED


@profiler.profile
def _numpy_to_qimage(img):
    if img.dtype == np.uint16:
        img = (img >> 8).astype(np.uint8)

    if img.ndim == 2:
        buf = np.ascontiguousarray(img)
        q = QtGui.QImage(buf.data, buf.shape[1], buf.shape[0], buf.strides[0], QtGui.QImage.Format_Grayscale8)
        q._buf = buf
        return q

    if img.ndim == 3:
        h, w, c = img.shape
        if c == 2:
            g, a = cv2.split(img)
            rgba = np.ascontiguousarray(np.dstack([cv2.cvtColor(g, cv2.COLOR_GRAY2RGB), a]))
            q = QtGui.QImage(rgba.data, w, h, rgba.strides[0], QtGui.QImage.Format_RGBA8888)
            q._buf = rgba
            return q
        if c == 3:
            rgb = np.ascontiguousarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
            q = QtGui.QImage(rgb.data, w, h, rgb.strides[0], QtGui.QImage.Format_RGB888)
            q._buf = rgb
            return q
        if c == 4:
            rgba = np.ascontiguousarray(cv2.cvtColor(img, cv2.COLOR_BGRA2RGBA))
            q = QtGui.QImage(rgba.data, w, h, rgba.strides[0], QtGui.QImage.Format_RGBA8888)
            q._buf = rgba
            return q

    raise ValueError("Unsupported image dimensions/channels")


def _classify_opencv_array(arr, ext):
    if arr is None or arr.ndim not in (2, 3):
        return "qt"
    if arr.dtype in (np.float16, np.float32, np.float64):
        return "qt"
    if arr.ndim == 3:
        c = arr.shape[2]
        if c not in (2, 3, 4):
            return "qt"
        if ext in (".jpg", ".jpeg") and c == 4:
            return "qt"
        if ext == ".png" and (c == 2 or arr.dtype == np.uint16):
            return "qt"
    if arr.dtype not in (np.uint8, np.uint16):
        return "qt"
    return "opencv"
