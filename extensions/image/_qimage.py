import os

import cv2
import numpy as np
from PySide6 import QtCore, QtGui

from wafer.core.logs import AppLogger
from wafer.core.profiling import profiler

from ._decode import _classify_opencv_array, _imread_flags_for_size


@profiler.profile
def load_image(path: str, size: int | QtCore.QSize | None = None) -> QtGui.QImage | None:
    size = _coerce_qimage_size(size)
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


def _coerce_qimage_size(size: int | QtCore.QSize | None) -> QtCore.QSize | None:
    if size is None or isinstance(size, QtCore.QSize):
        return size
    size = int(size)
    if size <= 0:
        return None
    return QtCore.QSize(size, size)


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
