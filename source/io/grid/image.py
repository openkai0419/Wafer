import os
import cv2
import numpy as np
from PySide6 import QtCore, QtGui

from ...common.logs import AppLogger
from ...common.helpers import call_int0
from .base import BaseGridPlugin


class ImageGridPlugin(BaseGridPlugin):
    NAME = 'image'
    EXTENSIONS = ('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp')
    PRIORITY = 100

    def load(self, path: str, size=None) -> QtGui.QImage | None:
        ext = os.path.splitext(path)[-1].lower()
        try:
            if ext == '.gif':
                return self._qt_read(path, size, keep_aspect=True)

            flags = self._imread_flags_for_size(ext, size)
            try:
                data = np.fromfile(path, dtype=np.uint8)
            except Exception:
                with open(path, 'rb') as f:
                    data = np.frombuffer(f.read(), dtype=np.uint8)
            arr = cv2.imdecode(data, flags)

            if self._classify_opencv_array(arr, ext) != 'opencv':
                img = self._qt_read(path, size, keep_aspect=False)
                if img is not None:
                    return img

            if arr is None:
                return self._qt_read(path, size, keep_aspect=False)

            if size is not None:
                h, w = arr.shape[:2]
                if (abs(w - size.width()) + abs(h - size.height())) > 2:
                    interp = cv2.INTER_AREA if (size.width() < w or size.height() < h) else cv2.INTER_LANCZOS4
                    arr = cv2.resize(arr, (size.width(), size.height()), interpolation=interp)

            return self._numpy_to_qimage(arr)

        except Exception as e:
            try:
                img = self._qt_read(path, size, keep_aspect=(ext == '.gif'))
                if img is not None:
                    return img
            except Exception as qe:
                AppLogger.warning(f'[ImageGridPlugin] Qt fallback failed: {path} ({qe})')
            AppLogger.warning(f'[ImageGridPlugin] Failed to load image: {path} ({e})')
            return None

    def _qt_read(self, path, size, keep_aspect):
        reader = QtGui.QImageReader(path)
        reader.setAutoTransform(True)
        if size is not None:
            if keep_aspect:
                sz = self._approx_aspect_keep_size(reader, size)
                reader.setScaledSize(sz)
            else:
                reader.setScaledSize(size)
        image = reader.read()
        if image.isNull():
            return None
        return image

    def _approx_aspect_keep_size(self, reader, target):
        sz = reader.size()
        if not sz.isValid():
            return target
        tw, th = target.width(), target.height()
        rw, rh = sz.width(), sz.height()
        if rw <= 0 or rh <= 0 or tw <= 0 or th <= 0:
            return target
        scale = tw / rw if rw >= rh else th / rh
        return QtCore.QSize(max(1, int(rw * scale)), max(1, int(rh * scale)))

    def _imread_flags_for_size(self, ext, size):
        if size is None:
            return cv2.IMREAD_UNCHANGED
        if ext in ('.jpg', '.jpeg'):
            longest = max(call_int0(size, 'width', 0), call_int0(size, 'height', 0))
            if longest <= 256:
                return cv2.IMREAD_REDUCED_COLOR_8
            if longest <= 512:
                return cv2.IMREAD_REDUCED_COLOR_4
            if longest <= 1024:
                return cv2.IMREAD_REDUCED_COLOR_2
            return cv2.IMREAD_COLOR
        return cv2.IMREAD_UNCHANGED

    def _numpy_to_qimage(self, img):
        if img.dtype == np.uint16:
            img = (img >> 8).astype(np.uint8)

        if img.ndim == 2:
            buf = np.ascontiguousarray(img)
            q = QtGui.QImage(buf.data, buf.shape[1], buf.shape[0], buf.strides[0],
                             QtGui.QImage.Format_Grayscale8)
            q._buf = buf
            return q

        if img.ndim == 3:
            h, w, c = img.shape
            if c == 2:
                g, a = cv2.split(img)
                rgba = np.ascontiguousarray(np.dstack([cv2.cvtColor(g, cv2.COLOR_GRAY2RGB), a]))
                q = QtGui.QImage(rgba.data, w, h, rgba.strides[0],
                                 QtGui.QImage.Format_RGBA8888)
                q._buf = rgba
                return q
            if c == 3:
                rgb = np.ascontiguousarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
                q = QtGui.QImage(rgb.data, w, h, rgb.strides[0],
                                 QtGui.QImage.Format_RGB888)
                q._buf = rgb
                return q
            if c == 4:
                rgba = np.ascontiguousarray(cv2.cvtColor(img, cv2.COLOR_BGRA2RGBA))
                q = QtGui.QImage(rgba.data, w, h, rgba.strides[0],
                                 QtGui.QImage.Format_RGBA8888)
                q._buf = rgba
                return q

        raise ValueError('Unsupported image dimensions/channels')

    def _classify_opencv_array(self, arr, ext):
        if arr is None or arr.ndim not in (2, 3):
            return 'qt'
        if arr.dtype in (np.float16, np.float32, np.float64):
            return 'qt'
        if arr.ndim == 3:
            c = arr.shape[2]
            if c not in (2, 3, 4):
                return 'qt'
            if ext in ('.jpg', '.jpeg') and c == 4:
                return 'qt'
            if ext == '.png' and (c == 2 or arr.dtype == np.uint16):
                return 'qt'
        if arr.dtype not in (np.uint8, np.uint16):
            return 'qt'
        return 'opencv'
