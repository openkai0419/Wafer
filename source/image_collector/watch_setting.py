from PySide6 import QtCore
import os
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from ..core.setting_db import SettingDB
import atexit


class SettingWatcher(QtCore.QObject):
    parentFoldersChanged = QtCore.Signal(list)
    ignoreFoldersChanged = QtCore.Signal(list)  # ← typo修正

    def __init__(self, db_path, parent=None):
        super().__init__(parent)
        self.db = SettingDB(db_path)
        self.db_path = self.db.db_name
        if os.path.exists(self.db_path):
            self.last_mtime = os.path.getmtime(self.db_path)
        else:
            self.last_mtime = None
        self.cached_parent_folders = set(self.db.get_all_parent_folders())
        self.cached_ignore_folders = set(self.db.get_all_ignore_folders())

        self._observer = Observer()
        self._handler = self._make_handler()

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
                    print(f"[SettingWatcher] ファイル変更検出中にエラー: {e}")

        return Handler()

    def _parent_folders_changed(self):
        current = set(self.db.get_all_parent_folders())
        if current != self.cached_parent_folders:
            print("[SettingWatcher] 差分検出：emit parentFoldersChanged")
            self.cached_parent_folders = current
            self.parentFoldersChanged.emit(list(current))

    def _ignore_folders_changed(self):
        current = set(self.db.get_all_ignore_folders())
        if current != self.cached_ignore_folders:
            print("[SettingWatcher] 差分検出：emit ignoreFoldersChanged")
            self.cached_ignore_folders = current
            self.ignoreFoldersChanged.emit(list(current))

    def _on_db_changed(self):
        self._parent_folders_changed()
        self._ignore_folders_changed()

    def start(self):
        dir_path = os.path.dirname(self.db_path) or "."
        self._observer.schedule(self._handler, path=dir_path, recursive=False)
        self._observer.start()
        atexit.register(self.stop)
        print("[SettingWatcher] 監視開始")

    def stop(self):
        self._observer.stop()
        self._observer.join()
