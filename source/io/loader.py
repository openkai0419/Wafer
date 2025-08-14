from PIL import Image
import cv2
import os
import time
import numpy as np
from PySide6 import QtCore, QtGui

from ..common.funcs import uipx
from ..common.profiling import logger, profiler

class ImageLoaderRunnable(QtCore.QRunnable):

    def __init__(self, index, path, size, receiver):
        super().__init__()
        self.index = index
        self.path = path
        self.margin = uipx(3)
        self.size = size - QtCore.QSize(self.margin * 2, self.margin * 2)
        self.receiver = receiver
        self._cancelled = False
        self.isended = False

    def cancel(self):
        self._cancelled = True

    @profiler.profile
    def run(self):
        if self._cancelled:
            return
        cache_key = (self.path, self.size.width(), self.size.height())
        if cache_key in self.receiver.pixmap_cache:
            pixmap = self.receiver.pixmap_cache[cache_key]
        else:
            pixmap = None
            if self._cancelled:
                return
            try:
                if self.path.lower().endswith('.gif'):
                    reader = QtGui.QImageReader(self.path)
                    reader.setAutoTransform(True)
                    image = reader.read()
                    if not image.isNull():
                        image = image.scaled(self.size, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
                        pixmap = QtGui.QPixmap.fromImage(image)
                else:
                    img = cv2.imdecode(np.fromfile(self.path, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
                    if img is None:
                        raise ValueError('OpenCV decode failed')
                    h, w = img.shape[:2]
                    if abs(w - self.size.width()) > 1 or abs(h - self.size.height()) > 1:
                        img = cv2.resize(img, (self.size.width(), self.size.height()), interpolation=cv2.INTER_AREA)
                    if img.ndim == 2:
                        qimg = QtGui.QImage(img.data, img.shape[1], img.shape[0], img.strides[0], QtGui.QImage.Format_Grayscale8)
                    elif img.ndim == 3:
                        if img.shape[2] == 3:
                            img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                            qimg = QtGui.QImage(img.data, img.shape[1], img.shape[0], img.strides[0], QtGui.QImage.Format_RGB888)
                        elif img.shape[2] == 4:
                            img = cv2.cvtColor(img, cv2.COLOR_BGRA2RGBA)
                            qimg = QtGui.QImage(img.data, img.shape[1], img.shape[0], img.strides[0], QtGui.QImage.Format_RGBA8888)
                        else:
                            raise ValueError('Unsupported channel format')
                    else:
                        raise ValueError('Unsupported image dimensions')
                    pixmap = QtGui.QPixmap.fromImage(qimg.copy())
                if pixmap is None or pixmap.isNull():
                    raise ValueError('Empty pixmap')
                self.receiver.pixmap_cache[cache_key] = pixmap
            except Exception as e:
                logger.warning(f'[ImageLoaderRunnable] Failed to load image: {self.path} ({e})')
                pixmap = self.receiver.error_placeholder.scaled(self.size, QtCore.Qt.IgnoreAspectRatio, QtCore.Qt.SmoothTransformation)
        if self._cancelled:
            return
        QtCore.QMetaObject.invokeMethod(self.receiver, '_on_pixmap_ready', QtCore.Qt.QueuedConnection, QtCore.Q_ARG(int, self.index), QtCore.Q_ARG(QtGui.QPixmap, pixmap))


def get_file_ctime(path):
    try:
        stat = os.stat(path)
        if hasattr(stat, 'st_birthtime'):
            return stat.st_birthtime
        else:
            return stat.st_ctime
    except Exception as e:
        logger.warning(f'Failed to get ctime for {path}: {e}')
        return None


def process_image(p, file_info):
    try:
        name = os.path.basename(p)
        mtime, fsize = file_info.get(p, (None, None))
        ctime = get_file_ctime(p)
        collected_at = time.time()
        with Image.open(p) as img:
            width, height = img.size
            exif = img.getexif()
            orientation = exif.get(274, 1) if exif else 1
            if orientation in (5, 6, 7, 8):
                width, height = (height, width)
            aspect = width / height if height else 1.0
            info = dict(img.info)
        meta_info = [(str(p), str(k), str(v)) for k, v in info.items()]
        meta_info.append((str(p), '__filepath__', str(p)))
        parent = p
        return (p, parent, name, aspect, mtime, fsize, ctime, collected_at, meta_info, None)
    except Exception as e:
        logger.warning(f'Failed to process {p}: {e}')
        mtime, fsize = file_info.get(p, (None, None))
        name = os.path.basename(p)
        parent = p
        return (p, parent, name,  None, mtime, fsize, None, time.time(), [], 'fail')
