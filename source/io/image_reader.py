from PIL import Image
import os
import cv2
import numpy as np
from PySide6 import QtCore, QtGui

from ..common.profiling import logger

class ImageReader:
    ext = ('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp')
    
    def __init__(self, path):
        self.path = path

    @classmethod
    def is_readable(cls, path):
        if os.path.splitext(path)[-1] in cls.ext:
            return True
        return False  

    def _get_file_ctime(self, path):
        try:
            stat = os.stat(path)
            if hasattr(stat, 'st_birthtime'):
                return stat.st_birthtime
            else:
                return stat.st_ctime
        except Exception as e:
            logger.warning(f'Failed to get ctime for {path}: {e}')
            return None

    def get_meta(self):
        p = self.path
        try:
            name = os.path.basename(p)
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
            return (p, p, name, aspect, meta_info, None)
        except Exception as e:
            logger.warning(f'Failed to process {p}: {e}')
            name = os.path.basename(p)
            return (p, p, name,  None, [], 'fail')


class ImageLoader:
    ext = ('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp')

    def __init__(self, path):
        self.path = path
    
    @classmethod
    def is_loadable(cls, path):
        return os.path.splitext(path)[-1].lower() in cls.ext
    
    def load(self, size: QtCore.QSize | None = None) -> QtGui.QPixmap | None:
        path = self.path
        try:
            # GIFはQtで読み込み
            if path.lower().endswith('.gif'):
                reader = QtGui.QImageReader(path)
                reader.setAutoTransform(True)
                image = reader.read()
                if image.isNull():
                    return None
                if size is not None:
                    image = image.scaled(size, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
                return QtGui.QPixmap.fromImage(image)

            # それ以外はOpenCVで読み込み
            img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
            if img is None:
                raise ValueError('OpenCV decode failed')

            # サイズ指定があればリサイズ
            if size is not None:
                h, w = img.shape[:2]
                if abs(w - size.width()) > 1 or abs(h - size.height()) > 1:
                    img = cv2.resize(img, (size.width(), size.height()), interpolation=cv2.INTER_AREA)

            # NumPy → QImage 変換
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

            return QtGui.QPixmap.fromImage(qimg.copy())

        except Exception as e:
            logger.warning(f'[ImageLoader] Failed to load image: {path} ({e})')
            return None
