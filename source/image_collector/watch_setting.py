import os
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from ..common.profiling import logger, profiler
from ..common.signal import Signal

class SettingWatcher:

    @profiler.profile
    def __init__(self, setting_db):
        self.parentFoldersChanged = Signal()
        self.ignoreFoldersChanged = Signal()
        self.deleteFlagEmit = Signal()
        self.db = setting_db
        self.db_path = self.db.db_name
        if os.path.exists(self.db_path):
            self.last_mtime = os.path.getmtime(self.db_path)
        else:
            self.last_mtime = None
        self.cached_parent_folders = set(self.db.get_all_parent_folders())
        self.cached_ignore_folders = set(self.db.get_all_ignore_folders())
        self._observer = Observer()
        self._handler = self._make_handler()

    @profiler.profile
    def _make_handler(self):
        watcher = self

        class Handler(FileSystemEventHandler):

            def on_modified(self, event):
                if os.path.abspath(event.src_path) != os.path.abspath(watcher.db_path):
                    return
                try:
                    if not os.path.exists(watcher.db_path):
                        return
                    stat = os.stat(watcher.db_path)
                    if watcher.last_mtime is not None and stat.st_mtime == watcher.last_mtime:
                        return
                    watcher.last_mtime = stat.st_mtime
                    watcher._on_db_changed()
                except Exception as e:
                    logger.warning(f'[SettingWatcher] error while watching file: {e}')
        return Handler()

    @profiler.profile
    def _parent_folders_changed(self):
        current = set(self.db.get_all_parent_folders())
        if current != self.cached_parent_folders:
            logger.info('[SettingWatcher] parent folder diff detected, emit signal')
            self.cached_parent_folders = current
            self.parentFoldersChanged.emit(list(current))

    @profiler.profile
    def _ignore_folders_changed(self):
        current = set(self.db.get_all_ignore_folders())
        if current != self.cached_ignore_folders:
            logger.info('[SettingWatcher] ignore folder diff detected, emit signal')
            self.cached_ignore_folders = current
            self.ignoreFoldersChanged.emit(list(current))

    @profiler.profile
    def _delete_flag_changed(self):
        current = self.db.get_kv('deleteflag', False)
        if current == True:
            logger.info('[SettingWatcher] delefe flag enabled')
            self.deleteFlagEmit.emit()

    @profiler.profile
    def _on_db_changed(self):
        self._parent_folders_changed()
        self._ignore_folders_changed()
        self._delete_flag_changed()

    @profiler.profile
    def start(self):
        dir_path = os.path.dirname(self.db_path) or '.'
        self._observer.schedule(self._handler, path=dir_path, recursive=False)
        self._observer.start()
        logger.info('[SettingWatcher] start watching setting file')

    def stop(self):
        self._observer.stop()
        self._observer.join()
