from PySide6 import QtCore, QtGui, QtWidgets
from natsort import natsorted

from ....utils.formatting import dpix, format_aspect, format_size_detail, format_timestamp
from ....core.qt.rate_limit import qt_debounce, qt_throttle
from ....utils.profiling import profiler
from ....utils.logs import AppLogger
from ....core.db.query import FileSearchEngine
from ....plugin.viewer.handler import viewer_resolver
from ....plugin.viewer.base import WidgetViewerPlugin as _WidgetViewerPlugin
from ....core.qt.dispatcher import Dispatcher, CancelSlot
from ....core.qt.thread import utility_pool
from ....core.state import StateStore
from .meta_viewer import MetaListWidget
from .image_viewer import ImageDisplayWidget
from .file_model import FileViewModel
from ..grid.cachemanager import MemoryLimitedImageCache, fullsize_key
from ..viewer_settings import app_settings


_DEFAULT_WIDGET_NAME = '_default'


def _format_meta(engine, path):
    source, image, tags, meta_infos = engine.get_all_metadata(path)
    if source.get("status"):
        source.pop("status")
    if image.get("source"):
        image.pop("source")
    if image.get("aspect_ratio"):
        image["aspect_ratio"] = format_aspect(image.get("aspect_ratio"))
    source["size"] = format_size_detail(source.get("size"))
    source["modified"] = format_timestamp(source.get("modified"))
    source["created"] = format_timestamp(source.get("created"))
    source["collected"] = format_timestamp(source.get("collected"))
    meta_infos = {k: meta_infos[k] for k in natsorted(meta_infos)}
    tags = {k: tags[k] for k in natsorted(tags)}
    return [source, image, tags, meta_infos]


class FileViewerWidget(QtWidgets.QSplitter):

    def __init__(self, model: FileViewModel, parent=None):
        super().__init__(QtCore.Qt.Vertical, parent)
        self.model = model
        self.image_cache = MemoryLimitedImageCache(app_settings.get('window/cache_size', 500))
        self._dispatcher = Dispatcher(utility_pool)
        self._content_cancel = CancelSlot()
        self._meta_cancel = CancelSlot()
        self._pending_meta = None
        self._pending_content = None
        self._loading_path = None
        self._target_plugin: str | None = None
        self._widget_map: dict[str, QtWidgets.QWidget] = {}
        self._current_plugin_name: str = _DEFAULT_WIDGET_NAME
        self.setup_ui()
        self.model.pathChanged.connect(self._on_path_changed)

    @property
    def path(self) -> str | None:
        return self.model.path()

    def setup_ui(self):
        self._stack = QtWidgets.QStackedWidget(self)
        self._stack.setMinimumSize(dpix(200), dpix(200))

        self.image_viewer = ImageDisplayWidget()
        self.image_viewer.resized.connect(self.update_content)
        self._stack.addWidget(self.image_viewer)
        self._widget_map[_DEFAULT_WIDGET_NAME] = self.image_viewer

        for name, widget_cls in viewer_resolver.widget_classes().items():
            widget = widget_cls(self._stack)
            self._stack.addWidget(widget)
            self._widget_map[name] = widget

        self.addWidget(self._stack)

        self.meta_viewer = MetaListWidget()

        self.area = QtWidgets.QScrollArea(self)
        self.area.setWidgetResizable(True)
        self.area.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.area.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.area.setWidget(self.meta_viewer)
        self.addWidget(self.area)
        self.setSizes([10, 800])

        self._register_states()
        QtWidgets.QApplication.instance().aboutToQuit.connect(self.on_exit)

    def _switch_to(self, plugin_name: str):
        if plugin_name == self._current_plugin_name:
            return
        widget = self._widget_map.get(plugin_name)
        if widget is None:
            plugin_name = _DEFAULT_WIDGET_NAME
            widget = self.image_viewer
        self._stack.setCurrentWidget(widget)
        self._current_plugin_name = plugin_name

    def _register_states(self):
        store = StateStore.instance()
        store.register('file_viewer', self._save_state, self._restore_state)
        for name, widget in self._widget_map.items():
            if name == _DEFAULT_WIDGET_NAME:
                continue
            plugin = viewer_resolver.registry.instance(name)
            if plugin is None or not isinstance(plugin, _WidgetViewerPlugin):
                continue
            w = widget
            p = plugin
            store.register(f'viewer_plugin.{name}', lambda p=p, w=w: p.save_state(w), lambda s, p=p, w=w: p.restore_state(w, s))

    def _save_state(self):
        return {
            'fit_mode': 'contain' if self.image_viewer.is_contain_mode() else 'cover',
            'splitter_sizes': self.sizes(),
        }

    def _restore_state(self, state):
        if 'fit_mode' in state:
            self.image_viewer.set_contain_mode(state['fit_mode'] == 'contain')
        if 'splitter_sizes' in state:
            self.setSizes(state['splitter_sizes'])

    def on_exit(self):
        pass

    @qt_throttle(100, 200)
    def update_content(self):
        self._load_and_show_content(self.model.path())

    def _on_path_changed(self, path):
        if not path:
            return
        self._loading_path = path
        self._pending_meta = None
        self._pending_content = None
        self._target_plugin = None
        self._update_meta(path)

        plugin_cls = viewer_resolver.resolve(path)
        if plugin_cls is not None and issubclass(plugin_cls, _WidgetViewerPlugin):
            self._target_plugin = plugin_cls.NAME
            self._pending_content = (path, None)
            self._try_show()
        else:
            self._target_plugin = _DEFAULT_WIDGET_NAME
            self._load_and_show_content(path)

    def _try_show(self):
        if self._pending_content is None or self._pending_meta is None:
            return
        path, image = self._pending_content
        self._pending_content = None
        meta = self._pending_meta
        self._pending_meta = None

        target = self._target_plugin or _DEFAULT_WIDGET_NAME
        if image is not None:
            self.image_viewer.set_image(image, path)
        elif target != _DEFAULT_WIDGET_NAME:
            widget = self._widget_map[target]
            viewer_resolver.render(widget, path)
        self.meta_viewer.set_data(meta)
        self._switch_to(target)

    def _load_and_show_content(self, path):
        if not path:
            return
        key = fullsize_key(path)
        image = self.image_cache.get(key)
        if image is not None and not image.isNull():
            self._pending_content = (path, image)
            self._try_show()
            return
        cancel = self._content_cancel.renew()

        def task():
            image = viewer_resolver.load_content(path)
            if cancel.is_cancelled():
                return
            if image is None or image.isNull():
                return
            self.image_cache[fullsize_key(path)] = image
            self._dispatcher.invoke(lambda: self._on_content_ready(cancel, path, image))

        self._dispatcher.post(task, cancel=cancel)

    def _on_content_ready(self, cancel, path, image):
        if cancel.is_cancelled():
            return
        if path != self._loading_path:
            return
        self._pending_content = (path, image)
        self._try_show()

    def set_path(self, path: str | None):
        if not path:
            return
        self.model.set_path(path)

    def _update_meta(self, path):
        dbpath = self.model.dbpath
        if not dbpath:
            return
        cancel = self._meta_cancel.renew()

        def task():
            engine = FileSearchEngine(dbpath)
            result = _format_meta(engine, path)
            if cancel.is_cancelled():
                return
            self._dispatcher.invoke(lambda: self._on_meta_ready(cancel, path, result))

        self._dispatcher.post(task, cancel=cancel)

    def _on_meta_ready(self, cancel, path, result):
        if cancel.is_cancelled():
            return
        if path != self._loading_path:
            return
        self._pending_meta = result
        self._try_show()
