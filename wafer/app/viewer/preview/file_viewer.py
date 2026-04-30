from __future__ import annotations

from PySide6 import QtCore
from natsort import natsorted

from ....utils.formatting import format_aspect, format_size_detail, format_timestamp
from ....utils.paths import db_name_from_path
from ....core.db.query import FileSearchEngine
from ....core.files.render_target import RenderTarget, TARGET_WIDGET
from ....plugin.viewer.handler import viewer_resolver
from ....plugin.viewer.base import WidgetViewerPlugin as _WidgetViewerPlugin
from ....core.qt.dispatcher import Dispatcher, CancelSlot
from ....core.qt.pixmap import PixmapFactory
from ....core.qt.thread import utility_pool
from ....core.state import StateStore
from .file_model import FileViewModel
from .content_viewer import ContentViewerWidget, _DEFAULT_WIDGET_NAME
from .meta_panel import MetaViewerWidget
from ..grid.cachemanager import MemoryLimitedImageCache, fullsize_key
from ....core.app_settings import app_settings
from ....core.color.theme import ThemeManager

_STANDARD_META_KEYS = ("name", "path", "size", "created", "modified", "collected", "file_hash")


def _format_meta(engine, path, dbpath):
    file_rec, file_hash, tags_with_lock, meta_infos_with_lock = engine.get_all_metadata_with_locks(path)
    tags = {k: v for k, (v, _) in tags_with_lock.items()}
    tag_locks = {k: lk for k, (_, lk) in tags_with_lock.items()}
    meta_infos = {k: v for k, (v, _) in meta_infos_with_lock.items()}
    meta_locks = {k: lk for k, (_, lk) in meta_infos_with_lock.items()}
    file_rec.pop("path", None)
    if file_rec.get("aspect_ratio"):
        file_rec["aspect_ratio"] = format_aspect(file_rec["aspect_ratio"])
    standard = {}
    meta_prefixed: dict[str, dict] = {}
    meta_prefixed_locks: dict[str, dict] = {}
    meta_root: dict[str, str] = {}
    meta_root_locks: dict[str, bool] = {}
    tag_prefixed: dict[str, dict] = {}
    tag_prefixed_locks: dict[str, dict] = {}
    tag_root: dict[str, str] = {}
    tag_root_locks: dict[str, bool] = {}
    for k, v in meta_infos.items():
        dot = k.find(".")
        if dot > 0:
            prefix = k[:dot]
            short = k[dot + 1 :]
            meta_prefixed.setdefault(prefix, {})[short] = v
            meta_prefixed_locks.setdefault(prefix, {})[short] = meta_locks.get(k, False)
        elif k in _STANDARD_META_KEYS:
            standard[k] = v
        else:
            meta_root[k] = v
            meta_root_locks[k] = meta_locks.get(k, False)
    if file_hash and "file_hash" not in standard:
        standard["file_hash"] = file_hash
    for k, v in tags.items():
        dot = k.find(".")
        if dot > 0:
            prefix = k[:dot]
            short = k[dot + 1 :]
            tag_prefixed.setdefault(prefix, {})[short] = v
            tag_prefixed_locks.setdefault(prefix, {})[short] = tag_locks.get(k, False)
        else:
            tag_root[k] = v
            tag_root_locks[k] = tag_locks.get(k, False)
    for k in ("created", "collected", "modified", "size"):
        raw = standard.get(k)
        if raw is not None:
            try:
                standard[k] = format_timestamp(float(raw)) if k != "size" else format_size_detail(float(raw))
            except (ValueError, TypeError):
                pass
    standard = {k: standard[k] for k in _STANDARD_META_KEYS if k in standard}
    tag_root = {k: tag_root[k] for k in natsorted(tag_root)}
    meta_root = {k: meta_root[k] for k in natsorted(meta_root)}
    for prefix in meta_prefixed:
        d = meta_prefixed[prefix]
        meta_prefixed[prefix] = {k: d[k] for k in natsorted(d)}
    for prefix in tag_prefixed:
        d = tag_prefixed[prefix]
        tag_prefixed[prefix] = {k: d[k] for k in natsorted(d)}
    collector_status = engine.get_collection_status(path)
    if collector_status:
        palette = ThemeManager.instance().palette
        parts = []
        for name, status in sorted(collector_status):
            color = palette.success if status == "ok" else palette.error
            parts.append(f'<span style="color:{color}">\u25cf</span> {name}')
        file_rec["collected by"] = "&nbsp;&nbsp;".join(parts)
    return {
        "source": file_rec,
        "file": standard,
        "tag": tag_root,
        "meta": meta_root,
        "meta_locks": meta_root_locks,
        "tag_prefixed": tag_prefixed,
        "tag_prefixed_locks": tag_prefixed_locks,
        "prefixed": meta_prefixed,
        "prefixed_locks": meta_prefixed_locks,
        "_path": path,
        "_file_hash": file_hash,
        "_tag_locks": tag_root_locks,
        "_db_name": db_name_from_path(dbpath),
    }


class FileViewerController(QtCore.QObject):
    _DEFAULT_AUTOPLAY_INTERVAL = 3000

    def __init__(self, model: FileViewModel, content_viewer: ContentViewerWidget, meta_viewer: MetaViewerWidget, parent=None):
        super().__init__(parent)
        self.model = model
        self.content_viewer = content_viewer
        self.meta_viewer = meta_viewer
        self.image_cache = MemoryLimitedImageCache(app_settings.get("window/cache_size", 500))
        self._dispatcher = Dispatcher(utility_pool)
        self._content_cancel = CancelSlot()
        self._meta_cancel = CancelSlot()
        self._pending_meta = None
        self._pending_content = None
        self._loading_path = None
        self._target_plugin: str | None = None
        self._target_render_path: str | None = None
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

    @property
    def source(self) -> str | None:
        return self.model.source()

    def _switch_to(self, plugin_name: str):
        old_name = self.content_viewer._current_plugin_name
        if old_name != _DEFAULT_WIDGET_NAME and old_name != plugin_name:
            self._unbind_autoplay(old_name)
        self.content_viewer.switch_to(plugin_name)

    def _register_states(self):
        store = StateStore.instance()
        store.register("file_viewer", self._save_state, self._restore_state)
        for name, plugin in viewer_resolver.viewer_plugins().items():
            if not isinstance(plugin, _WidgetViewerPlugin):
                continue
            p = plugin
            store.register(f"viewer_plugin.{name}", lambda p=p: p.save_ui_state(), lambda s, p=p: p.restore_ui_state(s))

    def _save_state(self):
        return {
            "fit_mode": "contain" if self.image_viewer.is_contain_mode() else "cover",
            "autoplay_interval": self._autoplay_interval,
            "autoplay_loop": self._autoplay_loop,
        }

    def _restore_state(self, state):
        if "fit_mode" in state:
            self.image_viewer.set_contain_mode(state["fit_mode"] == "contain")
        if "autoplay_interval" in state:
            self._autoplay_interval = int(state["autoplay_interval"])
        if "autoplay_loop" in state:
            self._autoplay_loop = bool(state["autoplay_loop"])

    def _on_path_changed(self, path):
        if not path:
            self._content_cancel.renew()
            self._meta_cancel.renew()
            self._loading_path = None
            self._pending_meta = None
            self._pending_content = None
            self._target_render_path = None
            self.content_viewer.clear()
            self.meta_viewer.clear()
            return
        self._loading_path = path
        self._pending_meta = None
        self._pending_content = None
        self._update_meta(path)
        self._load_content(path)

    def _load_content(self, path):
        cancel = self._content_cancel.renew()
        self._target_plugin = _DEFAULT_WIDGET_NAME
        self._target_render_path = path

        def resolve_task():
            if cancel.is_cancelled():
                return
            target = viewer_resolver.resolve_target(path)
            if cancel.is_cancelled():
                return
            if target.kind == TARGET_WIDGET and target.plugin_name:
                self._dispatcher.invoke(lambda: self._on_resolve_widget(cancel, target))
                return
            key = fullsize_key(path)
            image = self.image_cache.get(key)
            if image is not None and not image.isNull():
                self._dispatcher.invoke(lambda: self._on_resolve_cached(cancel, target, image))
                return
            image = viewer_resolver.load_content(target.render_path)
            if cancel.is_cancelled():
                return
            if image is not None and not image.isNull():
                self.image_cache[fullsize_key(path)] = image
            else:
                image = None
            self._dispatcher.invoke(lambda: self._on_content_ready(cancel, target, image))

        self._dispatcher.post(resolve_task, cancel=cancel)

    def _on_resolve_widget(self, cancel, target: RenderTarget):
        path = target.logical_path
        if cancel.is_cancelled() or path != self._loading_path:
            return
        self._target_plugin = target.plugin_name
        self._target_render_path = target.render_path
        self._pending_content = (path, None)
        self._flush()

    def _on_resolve_cached(self, cancel, target: RenderTarget, image):
        path = target.logical_path
        if cancel.is_cancelled() or path != self._loading_path:
            return
        self._target_plugin = _DEFAULT_WIDGET_NAME
        self._target_render_path = target.render_path
        self._pending_content = (path, image)
        self._flush()

    def _on_content_ready(self, cancel, target: RenderTarget, image):
        if cancel.is_cancelled():
            return
        path = target.logical_path
        if path != self._loading_path:
            return
        self._target_render_path = target.render_path
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
            viewer_resolver.render(self._target_render_path or path)
        else:
            self.image_viewer.set_image(PixmapFactory.create_viewer_error_placeholder(), path)
        self.meta_viewer.set_data(meta)
        self._arm_autoplay()

    def set_path(self, path: str | None):
        if not path:
            return
        self.model.set_path(path)

    def reload_meta(self):
        path = self.model.path()
        if path:
            self._fetch_meta(path, self._on_meta_reloaded)

    def _on_meta_reloaded(self, cancel, path, result):
        if cancel.is_cancelled() or path != self.model.path():
            return
        self.meta_viewer.set_data(result)

    def _update_meta(self, path):
        self._fetch_meta(path, self._on_meta_ready)

    def _fetch_meta(self, path, callback):
        dbpath = self.model.dbpath
        if not dbpath:
            return
        cancel = self._meta_cancel.renew()

        def task():
            engine = FileSearchEngine(dbpath)
            result = _format_meta(engine, path, dbpath)
            if cancel.is_cancelled():
                return
            self._dispatcher.invoke(lambda: callback(cancel, path, result))

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
        self._arm_autoplay()

    def stop_autoplay(self):
        self._autoplay_active = False
        self._autoplay_timer.stop()
        self._autoplay_generation += 1
        plugin = self._active_viewer_plugin()
        if plugin is not None:
            plugin.set_autoplay(None)
        self._autoplay_held = False

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
