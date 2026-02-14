import os
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from ..common.profiling import logger
from ..common.signal import Signal


class SettingWatcher(FileSystemEventHandler):

    def __init__(self, setting_db):
        self.parentFoldersChanged = Signal()
        self.ignoreFoldersChanged = Signal()
        self.deleteFlagEmit = Signal()
        self._db = setting_db
        self._db_path = os.path.abspath(setting_db.db_name)
        self._last_mtime = os.path.getmtime(self._db_path) if os.path.exists(self._db_path) else None
        self._parent_cache = set(self._db.get_all_parent_folders())
        self._ignore_cache = set(self._db.get_all_ignore_folders())
        self._observer = Observer()

    def on_modified(self, event):
        if os.path.abspath(event.src_path) != self._db_path:
            return
        try:
            if not os.path.exists(self._db_path):
                return
            mtime = os.stat(self._db_path).st_mtime
            if self._last_mtime is not None and mtime == self._last_mtime:
                return
            self._last_mtime = mtime
            self._check_changes()
        except Exception as e:
            logger.warning(f'SettingWatcher error: {e}')

    def _check_changes(self):
        parents = set(self._db.get_all_parent_folders())
        if parents != self._parent_cache:
            self._parent_cache = parents
            self.parentFoldersChanged.emit(list(parents))
        ignores = set(self._db.get_all_ignore_folders())
        if ignores != self._ignore_cache:
            self._ignore_cache = ignores
            self.ignoreFoldersChanged.emit(list(ignores))
        if self._db.get_kv('deleteflag', False) == True:
            self.deleteFlagEmit.emit()

    def start(self):
        dir_path = os.path.dirname(self._db_path) or '.'
        self._observer.schedule(self, dir_path, recursive=False)
        self._observer.start()

    def stop(self):
        self._observer.stop()
        self._observer.join()
