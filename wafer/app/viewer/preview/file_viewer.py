from __future__ import annotations

from dataclasses import dataclass

from PySide6 import QtCore
from natsort import natsorted

from ....utils.formatting import format_aspect, format_size_detail, format_timestamp
from ....utils.paths import db_name_from_path
from ....core.db.query import FileSearchEngine
from ....core.files.render_target import RenderPlan
from ....plugin.viewer.handler import viewer_resolver
from ....plugin.viewer.base import MultiWidgetViewerPlugin as _MultiWidgetViewerPlugin, ViewerContext, WidgetViewerPlugin as _WidgetViewerPlugin
from ....core.qt.dispatcher import Dispatcher, CancelSlot
from ....core.qt.thread import utility_pool
from ....core.state import StateStore
from .file_model import FileViewModel
from .file_list_provider import FileListProvider
from .content_viewer import ContentViewerWidget
from .meta_panel import MetaViewerWidget
from ....core.color.theme import ThemeManager
from ....utils.logs import AppLogger
from ....utils.profiling import profiler

_STANDARD_SOURCE_KEYS = ("source", "size", "created", "modified", "collected", "file_hash")
_STANDARD_FILE_KEYS = ("name", "path", "aspect_ratio", "source_extension")


@dataclass(frozen=True)
class ViewerBatch:
    start_index: int
    plugin_name: str
    logical_path: str
    contexts: tuple[ViewerContext, ...]

    @property
    def count(self) -> int:
        return len(self.contexts)

    @property
    def end_index_exclusive(self) -> int:
        return self.start_index + self.count

    @property
    def paths(self) -> tuple[str, ...]:
        return tuple(context.path for context in self.contexts)

    @property
    def render_paths(self) -> tuple[str, ...]:
        return tuple(context.render_path for context in self.contexts)

    @property
    def first_render_path(self) -> str:
        return self.contexts[0].render_path if self.contexts else self.logical_path


def _format_meta(engine, path, dbpath):
    source_rec, file_rec, file_hash, tags_with_lock, meta_infos_with_lock = engine.get_all_metadata_with_locks(path)
    tags = {k: v for k, (v, _) in tags_with_lock.items()}
    tag_locks = {k: lk for k, (_, lk) in tags_with_lock.items()}
    meta_infos = {k: v for k, (v, _) in meta_infos_with_lock.items()}
    meta_locks = {k: lk for k, (_, lk) in meta_infos_with_lock.items()}
    if file_rec.get("aspect_ratio"):
        file_rec["aspect_ratio"] = format_aspect(file_rec["aspect_ratio"])
    if not file_rec.get("source_extension"):
        file_rec.pop("source_extension", None)
    file_section = {k: file_rec[k] for k in _STANDARD_FILE_KEYS if k in file_rec and file_rec[k] is not None}
    source_section: dict = {}
    for k in _STANDARD_SOURCE_KEYS:
        v = source_rec.get(k)
        if v is None:
            continue
        if k == "size":
            try:
                v = format_size_detail(float(v))
            except (ValueError, TypeError):
                pass
        elif k in ("created", "modified", "collected"):
            try:
                v = format_timestamp(float(v))
            except (ValueError, TypeError):
                pass
        source_section[k] = v
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
        else:
            meta_root[k] = v
            meta_root_locks[k] = meta_locks.get(k, False)
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
        source_section["collected by"] = "&nbsp;&nbsp;".join(parts)
    return {
        "source": source_section,
        "file": file_section,
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

    def __init__(self, model: FileViewModel, content_viewer: ContentViewerWidget, meta_viewer: MetaViewerWidget, file_list_provider: FileListProvider | None = None, parent=None):
        super().__init__(parent)
        self.model = model
        self.content_viewer = content_viewer
        self.meta_viewer = meta_viewer
        self.file_list_provider = file_list_provider
        self._dispatcher = Dispatcher(utility_pool)
        self._content_cancel = CancelSlot()
        self._meta_cancel = CancelSlot()
        self._pending_meta = None
        self._pending_content = None
        self._loading_path = None
        self._target_plugin: str | None = None
        self._target_contexts: tuple[ViewerContext, ...] = ()
        self._target_paths: tuple[str, ...] = ()
        self._target_render_path: str | None = None
        self._target_render_paths: tuple[str, ...] = ()
        self._autoplay_active = False
        self._autoplay_interval = self._DEFAULT_AUTOPLAY_INTERVAL
        self._autoplay_loop = True
        self._autoplay_held = False
        self._autoplay_generation = 0
        self._navigation_cache_key = None
        self._navigation_cache_starts: list[int] = []
        self._navigation_cache_batches: dict[int, ViewerBatch] = {}
        self._autoplay_timer = QtCore.QTimer(self)
        self._autoplay_timer.setSingleShot(True)
        self._autoplay_timer.timeout.connect(self._on_autoplay_tick)
        self._register_states()
        self._connect_viewer_settings()
        self.model.itemsChanged.connect(self.invalidate_navigation_cache)
        self.model.pathChanged.connect(self._on_path_changed)

    def viewer_plugin(self, name: str):
        return viewer_resolver.registry.instance(name)

    @property
    def path(self) -> str | None:
        return self.model.path()

    @property
    def source(self) -> str | None:
        return self.model.source()

    def current_viewer_contexts(self) -> tuple[ViewerContext, ...]:
        if self._target_contexts:
            return self._target_contexts
        path = self.model.path()
        if not path:
            return ()
        return (ViewerContext(path=path, source=self.model.source() or path, render_path=self._target_render_path or path),)

    def current_paths(self) -> tuple[str, ...]:
        return tuple(context.path for context in self.current_viewer_contexts())

    def current_sources(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(context.source for context in self.current_viewer_contexts() if context.source))

    def current_render_paths(self) -> tuple[str, ...]:
        return tuple(context.render_path for context in self.current_viewer_contexts())

    def _set_target_contexts(self, contexts):
        self._target_contexts = tuple(contexts or ())
        self._target_paths = tuple(context.path for context in self._target_contexts)
        self._target_render_paths = tuple(context.render_path for context in self._target_contexts)
        self._target_render_path = self._target_render_paths[0] if self._target_render_paths else None

    def _switch_to(self, plugin_name: str):
        old_name = self.content_viewer._current_plugin_name
        if old_name != plugin_name:
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

    def _connect_viewer_settings(self):
        for name, plugin in viewer_resolver.viewer_plugins().items():
            signal = getattr(plugin, "settingsChanged", None)
            if signal is not None and hasattr(signal, "connect"):
                signal.connect(lambda name=name: self._on_viewer_settings_changed(name))

    def _save_state(self):
        state = {
            "autoplay_interval": self._autoplay_interval,
            "autoplay_loop": self._autoplay_loop,
        }
        if self.file_list_provider is not None:
            state.update(self.file_list_provider.save_ui_state())
        return state

    def _restore_state(self, state):
        if "autoplay_interval" in state:
            self._autoplay_interval = int(state["autoplay_interval"])
        if "autoplay_loop" in state:
            self._autoplay_loop = bool(state["autoplay_loop"])
        if self.file_list_provider is not None:
            self.file_list_provider.restore_ui_state(state)

    @profiler.profile
    def _on_path_changed(self, path):
        if not path:
            self._content_cancel.renew()
            self._meta_cancel.renew()
            self._loading_path = None
            self._pending_meta = None
            self._pending_content = None
            self._set_target_contexts(())
            self.content_viewer.clear()
            self.meta_viewer.clear()
            return
        self._loading_path = path
        self._pending_meta = None
        self._pending_content = None
        self._update_meta(path)
        self._load_content(path)

    @profiler.profile
    def _load_content(self, path):
        cancel = self._content_cancel.renew()
        current_index = self.model.current_index()
        self._target_plugin = None
        self._set_target_contexts((ViewerContext(path=path, source=self.model.source() or path, render_path=path),))

        @profiler.profile
        def resolve_task():
            if cancel.is_cancelled():
                return
            batch = self._resolve_viewer_batch(current_index, cancel=cancel)
            if cancel.is_cancelled():
                return
            self._dispatcher.invoke(lambda: self._on_content_ready(cancel, batch))

        self._dispatcher.post(resolve_task, cancel=cancel)

    @profiler.profile
    def _on_content_ready(self, cancel, batch: ViewerBatch, content=None):
        if cancel.is_cancelled():
            return
        path = batch.logical_path
        if path != self._loading_path:
            return
        self._remember_navigation_batch(batch)
        self._target_plugin = batch.plugin_name
        self._set_target_contexts(batch.contexts)
        self._pending_content = (batch, content)
        self._flush()

    @profiler.profile
    def _flush(self):
        if self._pending_content is None or self._pending_meta is None:
            return
        batch, _ = self._pending_content
        self._pending_content = None
        meta = self._pending_meta
        self._pending_meta = None

        target = self._target_plugin or batch.plugin_name
        self._switch_to(target)
        if target:
            viewer_resolver.render(batch.contexts, plugin_name=target)
        self.meta_viewer.set_data(meta)
        self._arm_autoplay()

    def set_path(self, path: str | None):
        if not path:
            return
        self.model.set_path(path)

    def invalidate_navigation_cache(self):
        self._navigation_cache_key = None
        self._navigation_cache_starts = []
        self._navigation_cache_batches = {}

    def _on_viewer_settings_changed(self, _plugin_name: str | None = None):
        self.invalidate_navigation_cache()
        paths = self.current_paths()
        path = paths[0] if paths else self.model.path()
        if not path:
            return
        if path != self.model.path():
            self.model.set_path(path)
            return
        self._on_path_changed(path)

    @profiler.profile
    def _resolve_viewer_batch(self, index: int | None, cancel=None) -> ViewerBatch:
        path = self.model.path_at(index) or self.model.path()
        start = int(index) if index is not None else self.model.index_of_path(path)
        start = start if start is not None else 0
        if path is None:
            return ViewerBatch(start, "", "", ())
        first_plan = viewer_resolver.resolve_plan(path)
        plugin_name = self._plugin_name(first_plan)
        contexts: list[ViewerContext] = []
        display_count = self._display_count(plugin_name, start, cancel=cancel)
        for offset in range(display_count):
            if cancel is not None and cancel.is_cancelled():
                break
            item_path = self.model.path_at(start + offset)
            if item_path is None:
                break
            plan = viewer_resolver.resolve_plan(item_path)
            if not self._same_viewer(plugin_name, plan):
                break
            contexts.append(self._viewer_context(plan))
        if not contexts:
            contexts.append(self._viewer_context(first_plan))
        return ViewerBatch(start, plugin_name, first_plan.path, tuple(contexts))

    def _viewer_context(self, plan: RenderPlan) -> ViewerContext:
        return ViewerContext(
            path=plan.path,
            source=plan.source,
            render_path=plan.resolved_path,
        )

    def _display_count(self, plugin_name: str, index: int | None, cancel=None) -> int:
        if index is None:
            return 1
        try:
            plugin = viewer_resolver.registry.instance(plugin_name) if plugin_name else None
            count = plugin.display_count(int(index), self.model.paths) if isinstance(plugin, _MultiWidgetViewerPlugin) else 1
        except Exception as exc:
            AppLogger.warning("Viewer display count failed; falling back to single item", exc=exc)
            count = 1
        remaining = max(1, self.model.count() - int(index))
        return max(1, min(int(count), remaining))

    def _remember_navigation_batch(self, batch: ViewerBatch):
        count = self.model.count()
        start = batch.start_index
        if count <= 0 or start < 0 or start >= count:
            return
        self._ensure_navigation_cache()
        self._navigation_cache_batches[start] = batch
        if start not in self._navigation_cache_starts:
            self._navigation_cache_starts.append(start)
            self._navigation_cache_starts.sort()

    def _same_viewer(self, plugin_name: str, plan: RenderPlan) -> bool:
        return bool(plugin_name) and isinstance(plan.handler, _WidgetViewerPlugin) and plugin_name == plan.handler.NAME

    def _plugin_name(self, plan: RenderPlan) -> str:
        return plan.handler.NAME if isinstance(plan.handler, _WidgetViewerPlugin) else ""

    def _current_navigation_cache_key(self):
        plugin_name = self._target_plugin or self.content_viewer._current_plugin_name
        plugin = viewer_resolver.registry.instance(plugin_name) if plugin_name else None
        plugin_key = plugin.navigation_cache_key() if isinstance(plugin, _WidgetViewerPlugin) else None
        return (plugin_name, id(self.model.paths), self.model.count(), plugin_key)

    def _ensure_navigation_cache(self):
        key = self._current_navigation_cache_key()
        if key != self._navigation_cache_key:
            self._navigation_cache_key = key
            self._navigation_cache_starts = []
            self._navigation_cache_batches = {}

    def _navigation_batch_at(self, index: int) -> ViewerBatch:
        count = self.model.count()
        if count <= 0:
            return ViewerBatch(0, "", "", ())
        index = max(0, min(int(index), count - 1))
        self._ensure_navigation_cache()
        cached = self._navigation_cache_batches.get(index)
        if cached is not None:
            return cached
        batch = self._resolve_viewer_batch(index)
        self._remember_navigation_batch(batch)
        return batch

    def _ensure_navigation_cache_until(self, index: int):
        self._ensure_navigation_cache()
        count = self.model.count()
        if count <= 0:
            return
        index = max(0, min(int(index), count - 1))
        start = 0
        while start < count:
            batch = self._navigation_batch_at(start)
            if batch.start_index >= index or batch.end_index_exclusive > index:
                return
            next_start = batch.end_index_exclusive
            if next_start <= start or next_start >= count:
                return
            start = next_start

    def _ensure_navigation_cache_complete(self):
        count = self.model.count()
        if count <= 0:
            return
        self._ensure_navigation_cache_until(count - 1)

    def _active_batch_count(self, index: int) -> int:
        count = self.model.count()
        if index < 0 or index >= count:
            return 1
        return max(1, self._navigation_batch_at(index).count)

    def _ensure_current_initialized(self) -> bool:
        if self.model.count() <= 0:
            return False
        if self.model.current_index() is None:
            self.model.set_current_index(0)
        return self.model.current_index() is not None

    def _next_navigation_index(self, index: int, loop: bool) -> int:
        count = self.model.count()
        next_index = self._navigation_batch_at(index).end_index_exclusive
        if next_index < count:
            return next_index
        return 0 if loop else index

    def _last_navigation_start(self) -> int:
        count = self.model.count()
        if count <= 0:
            return 0
        return self._previous_navigation_start(count)

    @profiler.profile
    def _previous_navigation_start(self, index: int) -> int:
        count = self.model.count()
        if count <= 0:
            return 0
        index = max(0, min(int(index), count))
        if index <= 0:
            return 0
        previous_index = index - 1
        previous_path = self.model.path_at(previous_index)
        if previous_path is None:
            return 0
        previous_plan = viewer_resolver.resolve_plan(previous_path)
        plugin_name = self._plugin_name(previous_plan)
        span = self._display_count(plugin_name, previous_index)
        start = max(0, index - span)
        while start < previous_index:
            path = self.model.path_at(start)
            if path is None:
                break
            if self._same_viewer(plugin_name, viewer_resolver.resolve_plan(path)):
                break
            start += 1
        batch = self._navigation_batch_at(start)
        if batch.end_index_exclusive <= previous_index:
            batch = self._navigation_batch_at(previous_index)
        return batch.start_index

    def _prev_navigation_index(self, index: int, loop: bool) -> int:
        count = self.model.count()
        if count <= 0:
            return 0
        if index <= 0:
            return self._last_navigation_start() if loop else 0
        self._ensure_navigation_cache()
        previous_index = index - 1
        for start in reversed(self._navigation_cache_starts):
            cached = self._navigation_cache_batches.get(start)
            if start < index and cached is not None and cached.end_index_exclusive > previous_index:
                return start
        return self._previous_navigation_start(index)

    @profiler.profile
    def navigate_next(self, step: int = 1, loop: bool = False, origin: str = "command") -> str | None:
        if not self._ensure_current_initialized():
            return None
        index = self.model.current_index()
        if index is None:
            return None
        for _ in range(max(1, int(step))):
            next_index = self._next_navigation_index(index, bool(loop))
            if next_index == index:
                break
            index = next_index
        self.model.set_current_index(index)
        return self.model.path_at(index)

    @profiler.profile
    def navigate_prev(self, step: int = 1, loop: bool = False, origin: str = "command") -> str | None:
        if not self._ensure_current_initialized():
            return None
        index = self.model.current_index()
        if index is None:
            return None
        for _ in range(max(1, int(step))):
            prev_index = self._prev_navigation_index(index, bool(loop))
            if prev_index == index:
                break
            index = prev_index
        self.model.set_current_index(index)
        return self.model.path_at(index)

    def reload_meta(self):
        path = self.model.path()
        if path:
            self._fetch_meta(path, self._on_meta_reloaded)

    @profiler.profile
    def _on_meta_reloaded(self, cancel, path, result):
        if cancel.is_cancelled() or path != self.model.path():
            return
        self.meta_viewer.set_data(result)

    @profiler.profile
    def _update_meta(self, path):
        self._fetch_meta(path, self._on_meta_ready)

    @profiler.profile
    def _fetch_meta(self, path, callback):
        dbpath = self.model.dbpath
        if not dbpath:
            return
        cancel = self._meta_cancel.renew()

        @profiler.profile
        def task():
            engine = FileSearchEngine(dbpath)
            result = _format_meta(engine, path, dbpath)
            if cancel.is_cancelled():
                return
            self._dispatcher.invoke(lambda: callback(cancel, path, result))

        self._dispatcher.post(task, cancel=cancel)

    @profiler.profile
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
        self.navigate_next(step=1, loop=self._autoplay_loop, origin="slideshow")

    def _active_viewer_plugin(self) -> _WidgetViewerPlugin | None:
        name = self.content_viewer._current_plugin_name
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
