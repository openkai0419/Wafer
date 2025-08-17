from PySide6 import QtCore, QtGui, QtWidgets
from numpy import uint

from ...common.funcs import uipx, human_aspect, human_size, human_time
from ...qt.debounce import qt_debounce, qt_throttle
from ...common.profiling import logger, profiler
from ...db.query import MetaInfoSearchEngine
from ...io.image_reader import ImageLoader
from .show_dict import DictListWidget
from .image_veiwer import ImageViewerWidget
from ..viewer.cachemanager import FadeLabel, MemoryLimitedPixmapCache
from ..viewer_settings import main_setting


class ViewerWidget(QtWidgets.QSplitter):
    def __init__(self, parent=None):
        super().__init__(QtCore.Qt.Vertical, parent)
        self.root = parent
        self.pixmap_cache = MemoryLimitedPixmapCache(main_setting.get('window/chache_size', 500))
        self.main_ui()
        self.path: str | None = None

    def main_ui(self):
        
        self.image_label = ImageViewerWidget(self)
        self.image_label.setMinimumSize(uipx(100), uipx(100))
        self.image_label.installEventFilter(self)
        self.addWidget(self.image_label)

        self.dict_viewer = DictListWidget()
        self.dict_viewer.set_data([{},{}])

        self.area = QtWidgets.QScrollArea(self)
        self.area.setWidgetResizable(True)
        self.area.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.area.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.area.setWidget(self.dict_viewer)

        self.addWidget(self.area)

    def eventFilter(self, watched, event):
        if event.type() == QtCore.QEvent.Resize:
            self.throttle_get_image()
        return super().eventFilter(watched, event)

    @qt_throttle(200, 800)
    def throttle_get_image(self):
        self.get_image()

    def get_image(self):
        if not self.path:
            return
        key = (self.path, None, None)
        pixmap = self.pixmap_cache.get(key)
        if pixmap is None or pixmap.isNull():
            pixmap = ImageLoader(self.path).load()
        if pixmap is None or pixmap.isNull():
            return
        self.image_label.set_pixmap(pixmap, self.path)
        self.pixmap_cache[key] = pixmap

    def set_path(self, path: str | None):
        if not path:
            return
        self.path = path
        self.set_meta()
        self.get_image()

    def set_meta(self):
        db = MetaInfoSearchEngine(self.root.dbpath)
        meta, meta_infos = db.get_metas(self.path)
        meta["aspect_ratio"] = human_aspect(meta.get("aspect_ratio"))
        meta["size"] = human_size(meta.get("size"))
        meta["mtime"] = human_time(meta.get("mtime"))
        meta["created"] = human_time(meta.get("created"))
        meta["collected_at"] = human_time(meta.get("collected_at"))
        self.dict_viewer.set_data([meta, meta_infos])
        self._last_cache_key = None