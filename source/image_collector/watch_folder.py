from PySide6 import QtWidgets, QtGui, QtCore
import os

from ..debounce import qt_debounce
from ..profiling import init_env
from .event_batcher import (
    EventBatcher,
    progress_callback,
    update_callback,
    filechange_callback,
    extensions,
)
from .folder_watcher_thread import FolderWatcherThread
from .db_worker import DBWorker

logger, profiler = init_env()




class WatchFolder:
    @profiler.profile
    def __init__(self, database):
        super().__init__()

        self.watcher_thread = None
        self.old_threads = []
        self.folders = None
        self.ignore_folders = None

        self.database = database
        self.database.set_progress_callback(progress_callback)
        self.database.set_update_callback(update_callback)

        self.db_thread = QtCore.QThread()
        self.db_worker = DBWorker(self.database)
        self.db_worker.moveToThread(self.db_thread)
        self.db_thread.start()
        self.event_batcher = EventBatcher(100)

        self.event_batcher.batched_deleted.connect(self.db_worker.remove_files)
        self.event_batcher.batched_changed.connect(self.db_worker.update_files)
        self.event_batcher.folder_changed.connect(filechange_callback)
        self.db_worker.finished.connect(self.event_batcher.on_db_finished)

        logger.debug("WatchFolder init end")

    @profiler.profile
    @qt_debounce(200)
    def rescan_all(self):
        if not self.folders:
            return
        self.db_worker.trigger_rescan.emit(self.folders)

    def set_ignore_folders(self, folders):
        self.ignore_folders = folders
        self.run_ignore_folders()

    @qt_debounce(200)
    def run_ignore_folders(self):
        if not self.ignore_folders:
            return
        self.db_worker.trigger_ignore.emit(self.ignore_folders)

    @profiler.profile
    def start(self, folders):
        if not folders:
            return
        if self.watcher_thread:
            self.watcher_thread.stop()
            self.old_threads.append(self.watcher_thread)

        self.watcher_thread = FolderWatcherThread(folders)
        self.watcher_thread.file_deleted.connect(self.event_batcher.add_deleted)
        self.watcher_thread.file_changed.connect(self.event_batcher.add_changed)
        self.watcher_thread.folder_changed.connect(self.event_batcher.path_changed)
        self.watcher_thread.start()

        self.folders = folders
        self.rescan_all()
        logger.debug("[FatchFOlder] ディレクトリ監視開始")
        self.delete_if_ended()

    def delete_if_ended(self):
        deleatings = []
        for thread in self.old_threads:
            if thread.isFinished():
                deleatings.append(thread)
        self.old_threads = [d for d in self.old_threads if not d in deleatings]


    def quit(self):
        logger.debug("Quitting TrayApp")
        if self.watcher_thread:
            self.watcher_thread.stop()
            #self.watcher_thread.wait()
        if self.db_thread:
            self.db_thread.quit()
            #self.db_thread.wait()
        with self.database as indexer:
            indexer.clean_unused()

