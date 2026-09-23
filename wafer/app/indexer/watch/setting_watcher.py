import os
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from ....core.logs import AppLogger
from ....core.common.signal import Signal


class SettingWatcher(FileSystemEventHandler):
    def __init__(self, setting_db):
        self.parent_folders_changed = Signal()
        self.ignore_changed = Signal()
        self._db = setting_db
        self._db_path = os.path.abspath(setting_db.db_name)
        self._last_mtime = os.path.getmtime(self._db_path) if os.path.exists(self._db_path) else None
        parents, ignores, ignore_patterns = self._db.get_all_folder_settings()
        self._parent_cache = set(parents)
        self._ignore_cache = set(ignores)
        self._ignore_patterns_cache = set(ignore_patterns)
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
            AppLogger.warning(f"SettingWatcher error: {e}", exc=e)

    def _check_changes(self):
        parents, ignores_raw, ignore_patterns_raw = self._db.get_all_folder_settings()
        parents = set(parents)
        if parents != self._parent_cache:
            AppLogger.info(f"setting changed: parent folders ({len(parents)})")
            self._parent_cache = parents
            self.parent_folders_changed.emit(list(parents))
        ignores = set(ignores_raw)
        ignore_patterns = set(ignore_patterns_raw)
        if ignores != self._ignore_cache or ignore_patterns != self._ignore_patterns_cache:
            if ignores != self._ignore_cache:
                AppLogger.info(f"setting changed: ignore folders ({len(ignores)})")
                self._ignore_cache = ignores
            if ignore_patterns != self._ignore_patterns_cache:
                AppLogger.info(f"setting changed: ignore patterns ({len(ignore_patterns)})")
                self._ignore_patterns_cache = ignore_patterns
            self.ignore_changed.emit(list(ignores), list(ignore_patterns))

    def start(self):
        dir_path = os.path.dirname(self._db_path) or "."
        self._observer.schedule(self, dir_path, recursive=False)
        self._observer.start()

    def stop(self):
        try:
            self._observer.stop()
            self._observer.join(timeout=5.0)
        except Exception as e:
            AppLogger.debug(f"SettingWatcher observer stop: {e}")
