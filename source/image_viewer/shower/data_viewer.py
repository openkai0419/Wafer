from PySide6 import QtCore, QtGui, QtWidgets
from natsort import natsorted

from ...common.funcs import uipx, human_aspect_string, human_size_string, human_time
from ...qt.debounce import qt_debounce, qt_throttle
from ...common.profiling import logger, profiler
from ...db.query import MetaInfoSearchEngine
from ...io.manager import LoaderClass
from ...qt.thread import CancellableRunnable, main_thread
from .dict_viewer import DictListWidget
from .image_viewer import ImageViewerWidget
from .data_model import DataViewModel
from ..viewer.cachemanager import MemoryLimitedImageCache
from ..viewer_settings import main_setting


class _ImageWorker(CancellableRunnable):
    def __init__(self, path):
        super().__init__()
        self.path = path

    @profiler.profile
    def execute(self):
        image = LoaderClass.load(self.path)
        if image is None or image.isNull():
            return None
        return (self.path, image)


class _MetaWorker(CancellableRunnable):
    def __init__(self, dbpath, path):
        super().__init__()
        self.engine = MetaInfoSearchEngine(dbpath)
        self.path = path

    @profiler.profile
    def execute(self):
        source, image, tags, meta_infos = self.engine.get_metas(self.path)
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
        return [source, image, tags, meta_infos]


class ViewerWidget(QtWidgets.QSplitter):

    def __init__(self, model: DataViewModel, parent=None):
        super().__init__(QtCore.Qt.Vertical, parent)
        self.model = model
        self.image_cache = MemoryLimitedImageCache(main_setting.get('window/chache_size', 500))
        self._meta_worker = None
        self._image_worker = None
        self._pending_meta = None
        self._pending_image = None
        self._loading_path = None
        self.main_ui()
        self.model.pathChanged.connect(self._on_path_changed)

    @property
    def path(self) -> str | None:
        return self.model.path()

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
        main_setting.set("window/sub_fitmode", self.image_viewer.is_contain())
        main_setting.set("window/sub_splitter", self.sizes())
        main_setting.commit()

    @qt_throttle(100, 200)
    def throttle_get_image(self):
        self._load_and_show_image(self.model.path())

    def _on_path_changed(self, path):
        if not path:
            return
        self._loading_path = path
        self._pending_meta = None
        self._pending_image = None
        self._update_meta(path)
        self._load_and_show_image(path)

    def _try_show(self):
        if self._pending_image is None or self._pending_meta is None:
            return
        path, image = self._pending_image
        self._pending_image = None
        meta = self._pending_meta
        self._pending_meta = None
        self.image_viewer.set_image(image, path)
        self.dict_viewer.set_data(meta)

    def _load_and_show_image(self, path):
        if not path:
            return
        key = (path, None, None)
        image = self.image_cache.get(key)
        if image is not None and not image.isNull():
            self._pending_image = (path, image)
            self._try_show()
            return
        if self._image_worker:
            self._image_worker.cancel()
        worker = _ImageWorker(path)
        worker.signals.finished.connect(self._on_image_finished)
        self._image_worker = worker
        main_thread.start(worker)

    @QtCore.Slot(object)
    def _on_image_finished(self, result):
        self._image_worker = None
        if result is None:
            return
        path, image = result
        self.image_cache[(path, None, None)] = image
        if path != self._loading_path:
            return
        self._pending_image = (path, image)
        self._try_show()

    def set_path(self, path: str | None):
        if not path:
            return
        self.model.set_path(path)

    def _update_meta(self, path):
        dbpath = self.model.dbpath
        if not dbpath:
            return
        if self._meta_worker:
            self._meta_worker.cancel()
        worker = _MetaWorker(dbpath, path)
        worker.signals.finished.connect(lambda result, p=path: self._on_meta_finished(p, result))
        self._meta_worker = worker
        main_thread.start(worker)

    def _on_meta_finished(self, path, result):
        self._meta_worker = None
        if path != self._loading_path:
            return
        self._pending_meta = result
        self._try_show()
