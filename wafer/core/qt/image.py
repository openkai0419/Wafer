import numpy as np
from PySide6 import QtGui

from PIL import Image


def numpy_to_qimage(arr: np.ndarray) -> QtGui.QImage:
    if arr.dtype == np.uint16:
        arr = (arr >> 8).astype(np.uint8)
    if not arr.flags["C_CONTIGUOUS"]:
        arr = np.ascontiguousarray(arr)
    if arr.ndim == 2:
        h, w = arr.shape
        q = QtGui.QImage(arr.data, w, h, arr.strides[0], QtGui.QImage.Format_Grayscale8)
    elif arr.ndim == 3:
        h, w, c = arr.shape
        if c == 3:
            q = QtGui.QImage(arr.data, w, h, arr.strides[0], QtGui.QImage.Format_RGB888)
        elif c == 4:
            q = QtGui.QImage(arr.data, w, h, arr.strides[0], QtGui.QImage.Format_RGBA8888)
        else:
            raise ValueError(f"Unsupported channel count: {c}")
    else:
        raise ValueError(f"Unsupported array ndim: {arr.ndim}")
    q._buf = arr
    return q


_PIL_MODE_FORMAT = {
    "RGB": QtGui.QImage.Format_RGB888,
    "RGBA": QtGui.QImage.Format_RGBA8888,
    "L": QtGui.QImage.Format_Grayscale8,
}


def pil_to_qimage(img: Image.Image) -> QtGui.QImage:
    qt_fmt = _PIL_MODE_FORMAT.get(img.mode)
    if qt_fmt is None:
        img = img.convert("RGBA")
        qt_fmt = QtGui.QImage.Format_RGBA8888
    arr = np.asarray(img)
    if not arr.flags["C_CONTIGUOUS"]:
        arr = np.ascontiguousarray(arr)
    h, w = arr.shape[:2]
    q = QtGui.QImage(arr.data, w, h, arr.strides[0], qt_fmt)
    q._buf = (arr, img)
    return q
