from datetime import datetime, timedelta

from PySide6 import QtCore

from ...utils.profiling import profiler
from ...utils.logs import AppLogger
from ...core.db.query import FileSearchEngine, SearchQuery
from ...core.qt.rate_limit import qt_debounce
from ...core.qt.thread import thread_pool, CancellableRunnable
from .viewer_settings import app_settings


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

_PERSIST_KEYS = {"query_mode", "keyword_mode", "sort_by", "ascending", "keyword_separator", "include_subfolders", "auto_execute"}


class _SearchWorker(CancellableRunnable):

    def __init__(self, dbpath, query):
        super().__init__()
        self.engine = FileSearchEngine(dbpath)
        self.query = query

    @profiler.profile
    def execute(self):
        return self.engine.search(self.query)


class SearchService(QtCore.QObject):
    search_started = QtCore.Signal()
    search_finished = QtCore.Signal(object, object, object)
    params_changed = QtCore.Signal(dict)

    def __init__(self, dbpath_getter, parent=None):
        super().__init__(parent)
        self._dbpath_getter = dbpath_getter
        self._params = self._load_defaults()
        self._keys = None
        self._directories = None
        self._current_worker = None
        self._last_query = None
        self._pending_query = None
        self._query_start_time = None
        self._timeout_threshold = timedelta(seconds=5)
        self._lock = QtCore.QMutex()

    def _load_defaults(self):
        params = {}
        for key, default in _DEFAULTS.items():
            if key in _PERSIST_KEYS:
                params[key] = app_settings.get(f'query/{key}', default)
            else:
                params[key] = default
        return params

    @property
    def params(self):
        return dict(self._params)

    def get(self, key, default=None):
        return self._params.get(key, default)

    def set_param(self, key, value):
        if self._params.get(key) == value:
            return
        self._params[key] = value
        if key in _PERSIST_KEYS:
            app_settings.set(f'query/{key}', value)
        self.params_changed.emit({key: value})

    def set_params(self, updates):
        changed = {}
        for key, value in updates.items():
            if self._params.get(key) != value:
                self._params[key] = value
                if key in _PERSIST_KEYS:
                    app_settings.set(f'query/{key}', value)
                changed[key] = value
        if changed:
            self.params_changed.emit(changed)

    def set_keys(self, keys):
        self._keys = keys

    def set_directories(self, directories):
        self._directories = directories

    def reset_state(self):
        self._last_query = None
        self._keys = None
        self._directories = None

    def build_query(self):
        return SearchQuery(
            keys=self._keys,
            keywords=self._params.get("keywords", ""),
            query_mode=self._params.get("query_mode", "GLOB"),
            keyword_mode=self._params.get("keyword_mode", "AND"),
            sort_by=self._params.get("sort_by", "path"),
            ascending=self._params.get("ascending", True),
            keyword_separator=self._params.get("keyword_separator", ","),
            include_subfolders=self._params.get("include_subfolders", True),
            directories=self._directories,
        )

    def execute_if_auto(self):
        if self._params.get('auto_execute', True):
            self.execute()

    @qt_debounce(150)
    @profiler.profile
    def execute(self, force=False):
        AppLogger.debug('[RUNNING] SearchService.execute')
        query = self.build_query()
        now = datetime.now()
        if not force:
            if self._current_worker and query == self._current_worker.query:
                return
            if self._last_query and query == self._last_query:
                return
        with QtCore.QMutexLocker(self._lock):
            if self._current_worker:
                elapsed = now - self._query_start_time if self._query_start_time else timedelta.max
                if elapsed < self._timeout_threshold:
                    self._current_worker.cancel()
                else:
                    AppLogger.warning('query is taking more than expected, continuing without cancel.')
                    self._pending_query = query
                    return
            self._pending_query = None
            self._start_worker(query)

    @profiler.profile
    def _start_worker(self, query):
        self.search_started.emit()
        dbpath = self._dbpath_getter()
        worker = _SearchWorker(dbpath, query)
        worker.signals.finished.connect(self._on_worker_finished)
        self._current_worker = worker
        self._query_start_time = datetime.now()
        thread_pool.submit(worker, 7)

    @QtCore.Slot(object)
    @profiler.profile
    def _on_worker_finished(self, result):
        if self._current_worker is None:
            return
        self._last_query = self._current_worker.query
        self._current_worker = None
        self._query_start_time = None
        paths, sources, aspects = result
        AppLogger.debug(f'search done: {len(paths)} results')
        self.search_finished.emit(paths, sources, aspects)
        with QtCore.QMutexLocker(self._lock):
            if self._pending_query:
                query = self._pending_query
                self._pending_query = None
                self._start_worker(query)
