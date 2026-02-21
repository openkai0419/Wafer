from ..common.profiling import profiler
from ..common.logs import AppLogger


def pil_to_qimage(img):
    from PySide6 import QtGui
    if img.mode != 'RGBA':
        img = img.convert('RGBA')
    data = img.tobytes('raw', 'BGRA')
    qimage = QtGui.QImage(data, img.width, img.height, img.width * 4, QtGui.QImage.Format_ARGB32)
    return qimage.copy()


class AutoRegister(type):
    def __init__(cls, name, bases, ns):
        super().__init__(name, bases, ns)
        if hasattr(cls, 'is_readable'):
            ReaderClass.add(cls)
        if hasattr(cls, 'is_loadable'):
            LoaderClass.add(cls)

class ReaderClass:
    _readers = []

    @classmethod
    def read(cls, path, *args, **kwargs):
        for reader in cls._readers:
            if reader.is_readable(path):
                return reader().read(path, *args, **kwargs)

    @classmethod    
    def add(cls, cl):
        cls._readers.append(cl)

class LoaderClass:
    _loaders = []
    _thumbnailer = None

    @classmethod
    def load(cls, path, *args, **kwargs):
        for loader in cls._loaders:
            if loader.is_loadable(path):
                return loader().load(path, *args, **kwargs)
        return cls._load_thumbnail(path, *args, **kwargs)

    @classmethod
    def _get_thumbnailer(cls):
        if cls._thumbnailer is None:
            from ..os.thumbnails import FileThumbnailer
            cls._thumbnailer = FileThumbnailer()
        return cls._thumbnailer

    @classmethod
    def _load_thumbnail(cls, path, size=None, **kwargs):
        from PySide6 import QtCore
        try:
            thumb_size = 256
            if size is not None:
                thumb_size = max(size.width(), size.height(), 256)
            pil_img = cls._get_thumbnailer().get_thumbnail(path, size=thumb_size)
            if pil_img is None:
                return None
            qimage = pil_to_qimage(pil_img)
            if size is not None:
                qimage = qimage.scaled(size, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
            return qimage
        except Exception:
            return None
    
    @classmethod 
    def add(cls, cl):
        cls._loaders.append(cl)

class BaseReader(metaclass=AutoRegister):
    def read(path, *args, **kwargs):
        return None
    
    def is_readable(path):
        return False

class BaseLoader(metaclass=AutoRegister):
    def load(path, *args, **kwargs):
        return None
    
    def is_loadable(path):
        return False
