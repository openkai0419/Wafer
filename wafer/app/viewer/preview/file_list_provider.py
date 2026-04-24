from __future__ import annotations

from enum import Enum
from pathlib import Path

from PySide6 import QtCore

from ....core.db.query import FileSearchEngine
from ....core.qt.dispatcher import Dispatcher, CancelToken
from ....core.qt.thread import utility_pool
from ....plugin.query.composer import SearchComposer
from ....builtins.filters import DirectoryFilter
from ....builtins.sorts import NaturalPathSort
from .file_model import FileViewModel
from ..grid.items import GridItemModel


class ListMode(Enum):
    SYNC = "sync"
    FIX = "fix"
    DIR = "dir"


class FileListProvider(QtCore.QObject):
    def __init__(
        self,
        file_model: FileViewModel,
        grid_items: GridItemModel,
        parent=None,
    ):
        super().__init__(parent)
        self._file_model = file_model
        self._grid_items = grid_items
        self._mode = ListMode.SYNC
        self._composer = SearchComposer()
        self._dispatcher = Dispatcher(utility_pool)
        self._dir_cancel: CancelToken | None = None

    @property
    def mode(self) -> ListMode:
        return self._mode

    def set_mode(self, mode: ListMode):
        self._cancel_pending()
        self._mode = mode

    def on_search_results(self, paths: list[str], sources: list[str]):
        if self._mode == ListMode.SYNC:
            self._file_model.set_items(paths, sources)

    def on_file_set(self, path: str):
        match self._mode:
            case ListMode.SYNC:
                self._file_model.set_path(path)
            case ListMode.FIX:
                self._file_model.set_items(
                    list(self._grid_items.paths),
                    list(self._grid_items.sources),
                )
                self._file_model.set_path(path)
            case ListMode.DIR:
                self._file_model.set_path(path)
                self._query_directory(path)

    def _query_directory(self, path: str):
        self._cancel_pending()
        directory = str(Path(path).parent)
        sort_plugin = NaturalPathSort
        ascending = True
        dbpath = self._file_model.dbpath
        if not dbpath:
            return
        cancel = CancelToken()
        self._dir_cancel = cancel

        def task():
            engine = FileSearchEngine(dbpath)
            entries = [
                (
                    DirectoryFilter,
                    {
                        "directories": [directory],
                        "include_subfolders": False,
                    },
                    None,
                )
            ]
            result = self._composer.execute(engine, entries, sort_plugin, ascending)
            if not cancel.is_cancelled():
                self._dispatcher.invoke(lambda r=result: self._on_dir_ready(r, cancel))

        self._dispatcher.post(task, cancel=cancel)

    def _on_dir_ready(self, result, cancel):
        if cancel.is_cancelled():
            return
        paths, sources, _ = result
        self._file_model.set_items(paths, sources)

    def _cancel_pending(self):
        if self._dir_cancel and not self._dir_cancel.is_cancelled():
            self._dir_cancel.cancel()
        self._dir_cancel = None
