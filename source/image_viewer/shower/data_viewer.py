from PySide6 import QtCore, QtGui, QtWidgets
from numpy import uint
from natsort import natsorted

from ...common.funcs import uipx, human_aspect_string, human_size_string, human_time
from ...qt.debounce import qt_debounce, qt_throttle
from ...common.profiling import logger, profiler
from ...db.query import MetaInfoSearchEngine
from ...io.manager import LoaderClass
from .dict_viewer import DictListWidget
from .image_veiwer import ImageViewerWidget
from ..viewer.cachemanager import FadeLabel, MemoryLimitedImageCache
from ..viewer_settings import main_setting


class ViewerWidget(QtWidgets.QSplitter):
    def __init__(self, parent=None):
        super().__init__(QtCore.Qt.Vertical, parent)
        self.root = parent
        self.image_cache = MemoryLimitedImageCache(main_setting.get('window/chache_size', 500))
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
        image = self.image_cache.get(key)
        if image is None or image.isNull():
            image = LoaderClass.load(self.path)
        if image is None or image.isNull():
            return
        self.image_viewer.set_image(image, self.path)
        self.image_cache[key] = image

    def set_path(self, path: str | None):
        if not path:
            return
        self.path = path
        self.set_meta()
        self.get_image()

    def set_meta(self):
        db = MetaInfoSearchEngine(self.root.dbpath)
        source, image, tags, meta_infos = db.get_metas(self.path)
        # cleaunp for viewing
        if source.get("status"):
            source.pop("status")
        if image.get("source"):
            image.pop("source")
        if image.get("aspect_ratio"):
            image["aspect_ratio"] = human_aspect_string(image.get("aspect_ratio"))
        source["size"] = human_size_string(source.get("size"))
        source["modified"] = human_time(source.get("modified"))
        source["created"] = human_time(source.get("created"))
        source["collected"] = human_time(source.get("collected"))
        meta_infos = {k: meta_infos[k] for k in natsorted(meta_infos)}
        tags = {k: tags[k] for k in natsorted(tags)}
        self.dict_viewer.set_data([source, image, tags, meta_infos])
        self._last_cache_key = None
