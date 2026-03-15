from datetime import datetime, timedelta

from PySide6 import QtCore

from ...utils.profiling import profiler
from ...utils.logs import AppLogger
from ...core.db.query import FileSearchEngine
from ...plugin.query.composer import SearchComposer
from ...core.qt.rate_limit import qt_debounce
from ...core.qt.dispatcher import Dispatcher, CancelToken
from ...core.qt.thread import utility_pool
from ...plugin.query.handler import sort_registry
from ...builtins.filters import TextFilter, DirectoryFilter
from ...builtins.sorts import NaturalPathSort


SORT_CHOICES = ["path", "name", "created", "modified", "collected", "size", "random"]

_DEFAULTS = {
    "keywords": "",
    "query_mode": "GLOB",
    "keyword_mode": "AND",
    "sort_by": "path",
    "ascending": True,
    "keyword_separator": ",",
    "include_subfolders": True,
    "auto_execute": True,
}


class SearchService(QtCore.QObject):
    search_started = QtCore.Signal()
    search_finished = QtCore.Signal(object, object, object)
    params_changed = QtCore.Signal(dict)

    def __init__(self, dbpath_getter, parent=None):
        super().__init__(parent)
        self._dbpath_getter = dbpath_getter
        self._dispatcher = Dispatcher(utility_pool)
        self._composer = SearchComposer()
        self._params = self._load_defaults()
        self._keys = None
        self._directories = None
        self._external_entries = None
        self._entries_builder = None
        self._current_cancel = None
        self._current_snapshot = None
        self._last_snapshot = None
        self._pending_snapshot = None
        self._query_start_time = None
        self._timeout_threshold = timedelta(seconds=5)
        self._lock = QtCore.QMutex()

    def _load_defaults(self):
        return dict(_DEFAULTS)

    @property
    def params(self):
        return dict(self._params)

    def get(self, key, default=None):
        return self._params.get(key, default)

    def set_param(self, key, value):
        if self._params.get(key) == value:
            return
        self._params[key] = value
        self.params_changed.emit({key: value})

    def set_params(self, updates):
        changed = {}
        for key, value in updates.items():
            if self._params.get(key) != value:
                self._params[key] = value
                changed[key] = value
        if changed:
            self.params_changed.emit(changed)

    def set_keys(self, keys):
        self._keys = keys

    def set_directories(self, directories):
        self._directories = directories

    def set_filter_entries(self, entries):
        self._external_entries = entries

    def set_entries_builder(self, builder):
        self._entries_builder = builder

    def reset_state(self):
        self._last_snapshot = None
        self._keys = None
        self._directories = None
        self._external_entries = None

    def _query_snapshot(self, entries=None):
        if entries is None:
            entries = self.build_filter_entries()
        entries_key = tuple(
            (cls.NAME, repr(sorted(params.items())), op)
            for cls, params, op in entries
        )
        return (
            self._params.get('sort_by', 'path'),
            self._params.get('ascending', True),
            entries_key,
        )

    @profiler.profile
    def build_filter_entries(self):
        if self._entries_builder is not None:
            return self._entries_builder()
        if self._external_entries is not None:
            return self._external_entries
        text_params = {
            'keys': self._keys,
            'keywords': self._params.get('keywords', ''),
            'query_mode': self._params.get('query_mode', 'GLOB'),
            'keyword_mode': self._params.get('keyword_mode', 'AND'),
            'keyword_separator': self._params.get('keyword_separator', ','),
        }
        entries = []
        entries.append((TextFilter, text_params, None))
        if self._directories:
            dir_params = {
                'directories': self._directories,
                'include_subfolders': self._params.get('include_subfolders', True),
            }
            entries.append((DirectoryFilter, dir_params, None))
        return entries

    @profiler.profile
    def resolve_sort(self):
        sort_name = self._params.get('sort_by', 'path')
        plugin = sort_registry.get(sort_name)
        return plugin or NaturalPathSort

    def execute_if_auto(self):
        if self._params.get('auto_execute', True):
            self.execute()

    @qt_debounce(150)
    @profiler.profile
    def execute(self, force=False):
        AppLogger.debug('[RUNNING] SearchService.execute')
        filter_entries = self.build_filter_entries()
        sort_plugin = self.resolve_sort()
        ascending = self._params.get('ascending', True)
        snapshot = self._query_snapshot(filter_entries)
        now = datetime.now()
        with QtCore.QMutexLocker(self._lock):
            if not force:
                if self._current_cancel and not self._current_cancel.is_cancelled() and snapshot == self._current_snapshot:
                    return
                if self._last_snapshot and snapshot == self._last_snapshot:
                    return
            if self._current_cancel and not self._current_cancel.is_cancelled():
                elapsed = now - self._query_start_time if self._query_start_time else timedelta.max
                if elapsed < self._timeout_threshold:
                    self._current_cancel.cancel()
                else:
                    AppLogger.warning('query is taking more than expected, continuing without cancel.')
                    self._pending_snapshot = snapshot
                    return
            self._pending_snapshot = None
            self._start_search(snapshot, filter_entries, sort_plugin, ascending)

    @profiler.profile
    def _start_search(self, snapshot, filter_entries, sort_plugin, ascending):
        self.search_started.emit()
        dbpath = self._dbpath_getter()
        cancel = CancelToken()
        self._current_cancel = cancel
        self._current_snapshot = snapshot
        self._query_start_time = datetime.now()

        def task():
            engine = FileSearchEngine(dbpath)
            result = self._composer.execute(engine, filter_entries, sort_plugin, ascending)
            if cancel.is_cancelled():
                return
            self._dispatcher.invoke(lambda: self._on_search_finished(cancel, snapshot, result))

        self._dispatcher.post(task, priority=7, cancel=cancel)

    @profiler.profile
    def _on_search_finished(self, cancel, snapshot, result):
        if cancel is not self._current_cancel:
            return
        self._last_snapshot = snapshot
        self._current_cancel = None
        self._current_snapshot = None
        self._query_start_time = None
        paths, sources, aspects = result
        AppLogger.debug(f'search done: {len(paths)} results')
        self.search_finished.emit(paths, sources, aspects)
        with QtCore.QMutexLocker(self._lock):
            if self._pending_snapshot:
                self._pending_snapshot = None
                self.execute(force=True)
