from PySide6 import QtCore
from ..profiling import init_env

logger, profiler = init_env()

class DBWorker(QtCore.QObject):
    finished = QtCore.Signal()
    trigger_ignore = QtCore.Signal(object)
    trigger_rescan = QtCore.Signal(object)

    def __init__(self, database, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.trigger_ignore.connect(self.set_ignore)
        self.trigger_rescan.connect(self.rescan_all)
        self.database = database

    @QtCore.Slot(list)
    def update_files(self, paths):
        with self.database as indexer:
            indexer.update_by_file_list(paths)
        self.finished.emit()

    @QtCore.Slot(list)
    def remove_files(self, paths):
        with self.database as indexer:
            indexer.remove_by_file_list(paths)
        self.finished.emit()

    @QtCore.Slot(list)
    def rescan_all(self, root_paths):
        logger.debug(f"スキャン開始: {root_paths}")
        with self.database as indexer:
            indexer.update_index(root_paths)

    @QtCore.Slot(list)
    def set_ignore(self, paths):
        logger.debug(f"無視対象を追加: {paths}")
        with self.database as indexer:
            indexer.set_exclude_paths(paths, run=True)

