from __future__ import annotations

from PySide6 import QtCore, QtWidgets
from natsort import natsorted

from ....utils.formatting import format_aspect, format_size_detail, format_timestamp
from ....utils.profiling import profiler
from ....utils.logs import AppLogger
from ....core.db.query import FileSearchEngine
from ....plugin.viewer.handler import viewer_resolver
from ....plugin.viewer.base import WidgetViewerPlugin as _WidgetViewerPlugin
from ....core.qt.dispatcher import Dispatcher, CancelSlot
from ....core.qt.pixmap import PixmapFactory
from ....core.qt.thread import utility_pool
from ....core.state import StateStore
from ....core.commands.bridge import Command
from .file_model import FileViewModel
from .content_viewer import ContentViewerWidget, _DEFAULT_WIDGET_NAME
from .meta_panel import MetaViewerWidget
from ..grid.cachemanager import MemoryLimitedImageCache, fullsize_key
from ....core.setting.app_settings import app_settings


def _format_meta(engine, path):
    file_rec, tags, meta_infos = engine.get_all_metadata(path)
    file_rec.pop("path", None)
    if file_rec.get("aspect_ratio"):
        file_rec["aspect_ratio"] = format_aspect(file_rec["aspect_ratio"])
    standard = {}
    prefixed = {}
    for k, v in meta_infos.items():
        if '.' in k:
            prefixed[k] = v
        else:
            standard[k] = v
    for k in ('created', 'collected', 'modified', 'size'):
        raw = standard.get(k)
        if raw is not None:
            try:
                standard[k] = format_timestamp(float(raw)) if k != 'size' else format_size_detail(float(raw))
            except (ValueError, TypeError):
                pass
    _standard_order = ['name', 'path', 'file_hash', 'size', 'created', 'modified', 'collected']
    standard = {k: standard[k] for k in _standard_order if k in standard}
    tags = {k: tags[k] for k in natsorted(tags)}
    prefixed = {k: prefixed[k] for k in natsorted(prefixed)}
    collector_status = engine.get_collection_status(path)
    if collector_status:
        parts = []
        for name, status in sorted(collector_status):
            color = '#4caf50' if status == 'ok' else '#f44336'
            parts.append(f'<span style="color:{color}">\u25cf</span> {name}')
        file_rec['collected by'] = '&nbsp;&nbsp;'.join(parts)
    return [file_rec, standard, tags, prefixed]


class FileViewerController(QtCore.QObject):

    _DEFAULT_AUTOPLAY_INTERVAL = 3000

    def __init__(self, model: FileViewModel, content_viewer: ContentViewerWidget, meta_viewer: MetaViewerWidget, parent=None):
        super().__init__(parent)
        self.model = model
        self.content_viewer = content_viewer
        self.meta_viewer = meta_viewer
        self.image_cache = MemoryLimitedImageCache(app_settings.get('window/cache_size', 500))
        self._dispatcher = Dispatcher(utility_pool)
        self._content_cancel = CancelSlot()
        self._meta_cancel = CancelSlot()
        self._pending_meta = None
        self._pending_content = None
        self._loading_path = None
        self._target_plugin: str | None = None
        self._autoplay_active = False
        self._autoplay_interval = self._DEFAULT_AUTOPLAY_INTERVAL
        self._autoplay_loop = True
        self._autoplay_held = False
        self._autoplay_generation = 0
        self._autoplay_timer = QtCore.QTimer(self)
        self._autoplay_timer.setSingleShot(True)
        self._autoplay_timer.timeout.connect(self._on_autoplay_tick)
        self._register_states()
        self.model.pathChanged.connect(self._on_path_changed)

    @property
    def image_viewer(self):
        return self.content_viewer.image_viewer

    @property
    def path(self) -> str | None:
        return self.model.path()

    def _switch_to(self, plugin_name: str):
        old_name = self.content_viewer._current_plugin_name
        if old_name != _DEFAULT_WIDGET_NAME and old_name != plugin_name:
            self._unbind_autoplay(old_name)
        self.content_viewer.switch_to(plugin_name)

    def _register_states(self):
        store = StateStore.instance()
        store.register('file_viewer', self._save_state, self._restore_state)
        for name, plugin in viewer_resolver.viewer_plugins().items():
            if not isinstance(plugin, _WidgetViewerPlugin):
                continue
            p = plugin
            store.register(f'viewer_plugin.{name}', lambda p=p: p.save_state(), lambda s, p=p: p.restore_state(s))

    def _save_state(self):
        return {
            'fit_mode': 'contain' if self.image_viewer.is_contain_mode() else 'cover',
            'autoplay_interval': self._autoplay_interval,
            'autoplay_loop': self._autoplay_loop,
        }

    def _restore_state(self, state):
        if 'fit_mode' in state:
            self.image_viewer.set_contain_mode(state['fit_mode'] == 'contain')
        if 'autoplay_interval' in state:
            self._autoplay_interval = int(state['autoplay_interval'])
        if 'autoplay_loop' in state:
            self._autoplay_loop = bool(state['autoplay_loop'])
        Command.set_checked('fv.toggle_slideshow', False)

    def _on_path_changed(self, path):
        if not path:
            return
        self._loading_path = path
        self._pending_meta = None
        self._pending_content = None
        self._update_meta(path)
        self._load_content(path)

    def _load_content(self, path):
        plugin_cls = viewer_resolver.resolve(path)
        if plugin_cls is not None and issubclass(plugin_cls, _WidgetViewerPlugin):
            self._target_plugin = plugin_cls.NAME
            self._pending_content = (path, None)
            self._flush()
            return

        self._target_plugin = _DEFAULT_WIDGET_NAME
        key = fullsize_key(path)
        image = self.image_cache.get(key)
        if image is not None and not image.isNull():
            self._pending_content = (path, image)
            self._flush()
            return
        cancel = self._content_cancel.renew()

        def task():
            image = viewer_resolver.load_content(path)
            if cancel.is_cancelled():
                return
            if image is not None and not image.isNull():
                self.image_cache[fullsize_key(path)] = image
            else:
                image = None
            self._dispatcher.invoke(lambda: self._on_content_ready(cancel, path, image))

        self._dispatcher.post(task, cancel=cancel)

    def _on_content_ready(self, cancel, path, image):
        if cancel.is_cancelled():
            return
        if path != self._loading_path:
            return
        self._pending_content = (path, image)
        self._flush()

    def _flush(self):
        if self._pending_content is None or self._pending_meta is None:
            return
        path, image = self._pending_content
        self._pending_content = None
        meta = self._pending_meta
        self._pending_meta = None

        target = self._target_plugin or _DEFAULT_WIDGET_NAME
        self._switch_to(target)
        if image is not None:
            self.image_viewer.set_image(image, path)
        elif target != _DEFAULT_WIDGET_NAME:
            viewer_resolver.render(path)
        else:
            self.image_viewer.set_image(PixmapFactory.create_viewer_error_placeholder(), path)
        self.meta_viewer.set_data(meta)
        self._arm_autoplay()

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
        self._flush()

    def _arm_autoplay(self):
        if not self._autoplay_active:
            return
        self._autoplay_timer.stop()
        self._autoplay_held = False
        plugin = self._active_viewer_plugin()
        if plugin is not None:
            self._autoplay_generation += 1
            gen = self._autoplay_generation
            held = plugin.set_autoplay(lambda gen=gen: self._on_plugin_advance(gen))
            if held:
                self._autoplay_held = True
                return
        self._autoplay_timer.start(self._autoplay_interval)

    def _unbind_autoplay(self, plugin_name: str):
        if not self._autoplay_active:
            return
        plugin = viewer_resolver.registry.instance(plugin_name)
        if isinstance(plugin, _WidgetViewerPlugin):
            plugin.set_autoplay(None)
        self._autoplay_held = False

    def _on_plugin_advance(self, generation: int):
        if generation != self._autoplay_generation:
            return
        if not self._autoplay_active:
            return
        self._do_advance()

    def _on_autoplay_tick(self):
        if not self._autoplay_active:
            return
        self._do_advance()

    def _do_advance(self):
        self._autoplay_timer.stop()
        self._autoplay_generation += 1
        self.model.move_current_next(step=1, loop=self._autoplay_loop)

    def _active_viewer_plugin(self) -> _WidgetViewerPlugin | None:
        name = self.content_viewer._current_plugin_name
        if name == _DEFAULT_WIDGET_NAME:
            return None
        plugin = viewer_resolver.registry.instance(name)
        if isinstance(plugin, _WidgetViewerPlugin):
            return plugin
        return None

    def start_autoplay(self, interval_ms: int | None = None, loop: bool | None = None):
        if interval_ms is not None:
            self._autoplay_interval = max(500, int(interval_ms))
        if loop is not None:
            self._autoplay_loop = bool(loop)
        self._autoplay_active = True
        Command.set_checked('fv.toggle_slideshow', True)
        self._arm_autoplay()

    def stop_autoplay(self):
        self._autoplay_active = False
        self._autoplay_timer.stop()
        self._autoplay_generation += 1
        plugin = self._active_viewer_plugin()
        if plugin is not None:
            plugin.set_autoplay(None)
        self._autoplay_held = False
        Command.set_checked('fv.toggle_slideshow', False)

    def toggle_autoplay(self, interval_ms: int | None = None, loop: bool | None = None):
        if self._autoplay_active:
            self.stop_autoplay()
        else:
            self.start_autoplay(interval_ms=interval_ms, loop=loop)

    @property
    def autoplay_active(self) -> bool:
        return self._autoplay_active

    @property
    def autoplay_interval(self) -> int:
        return self._autoplay_interval
