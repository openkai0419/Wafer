# server_watch.py
import os
from PySide6 import QtWidgets, QtGui, QtCore
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from ..core.folder_db import FolderDB

class DBUpdateHandler(FileSystemEventHandler):
    def __init__(self, db: FolderDB):
        super().__init__()
        self.db = db
        self.dbname = self.db.db_name
        self.last_mtime = os.path.getmtime(self.dbname)

    def on_modified(self, event):
        if event.src_path != os.path.abspath(self.dbname):
            return
        mtime = os.path.getmtime(self.dbname)
        if mtime == self.last_mtime:
            return
        self.last_mtime = mtime
        self._process_change()

    def _process_change(self):
        # 最新状態を返す（例：ログ、レスポンスなど）
        current_list = self.db.get_all_parent_folders()
        print(f"[SERVER] {current_list}")


class SettingWatcher(QtCore.QObject):
    foldersChanged = QtCore.Signal(list)  # 最新のフォルダリストを送信

    def __init__(self, db_path, parent=None):
        super().__init__(parent)
        self.db = FolderDB(db_path)
        self.db_path = self.db.db_name
        self.last_mtime = os.path.getmtime(self.db_path)
        self.cached_folders = set(self.db.get_all_parent_folders())

        self._observer = Observer()
        self._handler = self._make_handler()

    def _make_handler(self):
        watcher = self

        class Handler(FileSystemEventHandler):
            def on_modified(self, event):
                if os.path.abspath(event.src_path) != os.path.abspath(watcher.db_path):
                    return
                mtime = os.path.getmtime(watcher.db_path)
                if mtime == watcher.last_mtime:
                    return
                watcher.last_mtime = mtime
                watcher._on_db_changed()

        return Handler()

    def _on_db_changed(self):
        current = set(self.db.get_all_parent_folders())
        if current != self.cached_folders:
            print("[SettingWatcher] 差分検出：emit foldersChanged")
            self.cached_folders = current
            self.foldersChanged.emit(list(current))

    def start(self):
        dir_path = os.path.dirname(self.db_path) or "."
        self._observer.schedule(self._handler, path=dir_path, recursive=False)
        self._observer.start()
        print("[SettingWatcher] 監視開始")

    def stop(self):
        self._observer.stop()
        self._observer.join()