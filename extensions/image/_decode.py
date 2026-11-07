import os
import struct

import cv2
import numpy as np
from PIL import Image

from wafer.core.logs import AppLogger


def decode_numpy(path: str, size: int | None = None) -> np.ndarray | None:
    ext = os.path.splitext(path)[-1].lower()
    try:
        try:
            data = np.fromfile(path, dtype=np.uint8)
        except (OSError, MemoryError):
            with open(path, "rb") as f:
                data = np.frombuffer(f.read(), dtype=np.uint8)
        flags = _imread_flags_for_size(ext, size, data)
        arr = cv2.imdecode(data, flags)

        if arr is None or _classify_opencv_array(arr, ext) != "opencv":
            result = _pil_read_numpy(path, size)
            if result is None:
                AppLogger.debug(f"[image/loader] cv2+PIL both returned None: {path} (cv2_arr={'None' if arr is None else f'{arr.shape}/{arr.dtype}'}, data_len={len(data)})")
            return result

        if size is not None:
            h, w = arr.shape[:2]
            scale = max(size / w, size / h)
            if abs(scale - 1.0) > 0.01:
                new_w = max(1, round(w * scale))
                new_h = max(1, round(h * scale))
                interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LANCZOS4
                arr = cv2.resize(arr, (new_w, new_h), interpolation=interp)

        return _bgr_to_standard(arr)

    except Exception as e:
        try:
            result = _pil_read_numpy(path, size)
            if result is not None:
                return result
        except Exception as pe:
            AppLogger.warning(f"[image/loader] PIL fallback failed: {path} ({pe})")
        AppLogger.warning(f"[image/loader] Failed to load image: {path} ({e})")
        return None


def _pil_read_numpy(path: str, size: int | None = None) -> np.ndarray | None:
    try:
        img = Image.open(path)
        img.load()
    except Exception:
        return None
    if size is not None:
        w, h = img.size
        if w > 0 and h > 0:
            scale = max(size / w, size / h)
            new_w = max(1, round(w * scale))
            new_h = max(1, round(h * scale))
            img = img.resize((new_w, new_h), Image.LANCZOS)
    if img.mode not in ("RGB", "RGBA", "L"):
        img = img.convert("RGB")
    return np.array(img)


def _bgr_to_standard(arr) -> np.ndarray:
    if arr.dtype == np.uint16:
        arr = (arr >> 8).astype(np.uint8)

    if arr.ndim == 2:
        return arr

    if arr.ndim == 3:
        _h, _w, c = arr.shape
        if c == 2:
            g, a = cv2.split(arr)
            return np.dstack([cv2.cvtColor(g, cv2.COLOR_GRAY2RGB), a])
        if c == 3:
            return cv2.cvtColor(arr, cv2.COLOR_BGR2RGB)
        if c == 4:
            return cv2.cvtColor(arr, cv2.COLOR_BGRA2RGBA)

    raise ValueError("Unsupported image dimensions/channels")


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
    if isinstance(size, int):
        tw = th = size
    else:
        tw, th = size.width(), size.height()
    if ext in (".jpg", ".jpeg"):
        dims = _jpeg_dimensions(data) if data is not None else None
        if dims is not None:
            ow, oh = dims
            if ow // 8 >= tw and oh // 8 >= th:
                return cv2.IMREAD_REDUCED_COLOR_8
            if ow // 4 >= tw and oh // 4 >= th:
                return cv2.IMREAD_REDUCED_COLOR_4
            if ow // 2 >= tw and oh // 2 >= th:
                return cv2.IMREAD_REDUCED_COLOR_2
        return cv2.IMREAD_COLOR
    return cv2.IMREAD_UNCHANGED


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
