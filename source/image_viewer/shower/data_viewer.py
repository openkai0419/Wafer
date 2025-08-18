from PySide6 import QtCore, QtGui, QtWidgets
from numpy import uint

from ...common.funcs import uipx, human_aspect_string, human_size_string, human_time
from ...qt.debounce import qt_debounce, qt_throttle
from ...common.profiling import logger, profiler
from ...db.query import MetaInfoSearchEngine
from ...io.manager import LoaderClass
from .dict_viewer import DictListWidget
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
        self.image_viewer = ImageViewerWidget(self)
        self.image_viewer.setMinimumSize(uipx(200), uipx(200))
        self.image_viewer.set_contain(main_setting.get("window/sub_fitmode", True))
        self.image_viewer.resized.connect(self.throttle_get_image)
        self.addWidget(self.image_viewer)

        self.dict_viewer = DictListWidget()

        self.area = QtWidgets.QScrollArea(self)
        self.area.setWidgetResizable(True)
        self.area.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.area.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.area.setWidget(self.dict_viewer)
        self.addWidget(self.area)
        self.setSizes(main_setting.get("window/sub_splitter", [10, 800]))

        QtWidgets.QApplication.instance().aboutToQuit.connect(self.on_exit)

    def on_exit(self):
        logger.info(self.image_viewer.is_contain())
        main_setting.set("window/sub_fitmode", self.image_viewer.is_contain())
        main_setting.set("window/sub_splitter", self.sizes())
        main_setting.commit()

    @qt_throttle(100, 200)
    def throttle_get_image(self):
        self.get_image()

    def get_image(self):
        if not self.path:
            return
        key = (self.path, None, None)
        pixmap = self.pixmap_cache.get(key)
        if pixmap is None or pixmap.isNull():
            pixmap = LoaderClass.load(self.path)
        if pixmap is None or pixmap.isNull():
            return
        self.image_viewer.set_pixmap(pixmap, self.path)
        self.pixmap_cache[key] = pixmap

    def set_path(self, path: str | None):
        if not path:
            return
        self.path = path
        self.set_meta()
        self.get_image()

    def set_meta(self):
        db = MetaInfoSearchEngine(self.root.dbpath)
        meta, tags, meta_infos = db.get_metas(self.path)
        meta["aspect_ratio"] = human_aspect_string(meta.get("aspect_ratio"))
        meta["size"] = human_size_string(meta.get("size"))
        meta["mtime"] = human_time(meta.get("mtime"))
        meta["created"] = human_time(meta.get("created"))
        meta["collected_at"] = human_time(meta.get("collected_at"))
        self.dict_viewer.set_data([meta, tags, meta_infos])
        self._last_cache_key = None