from __future__ import annotations

from enum import Enum
from pathlib import Path

from PySide6 import QtCore

from ....core.db.query import FileSearchEngine
from ....core.qt.dispatcher import Dispatcher, CancelToken
from ....core.qt.thread import utility_pool
from ....plugin.query.composer import SearchComposer
from ....builtins.filters import DirectoryFilter, SourceChildrenFilter
from ....builtins.sorts import NaturalPathSort
from ....utils.virtual_paths import is_virtual_path, owner_extensions, source_path
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
        self._open_contained_files_as_list = False

    @property
    def mode(self) -> ListMode:
        return self._mode

    @property
    def open_contained_files_as_list(self) -> bool:
        return self._open_contained_files_as_list

    def _sync_from_grid(self):
        self._file_model.set_items(self._grid_items.paths, self._grid_items.sources)

    def set_mode(self, mode: ListMode):
        self._cancel_pending()
        self._mode = mode
        if mode == ListMode.SYNC:
            self._sync_from_grid()

    def set_open_contained_files_as_list(self, enabled: bool):
        enabled = bool(enabled)
        if self._open_contained_files_as_list == enabled:
            return
        self._open_contained_files_as_list = enabled
        if not enabled:
            self._cancel_pending()

    def save_ui_state(self) -> dict:
        return {
            "list_mode": self._mode.value,
            "open_contained_files_as_list": self._open_contained_files_as_list,
        }

    def restore_ui_state(self, state: dict) -> None:
        mode = self._mode_from_state(state.get("list_mode"))
        if mode is not None:
            self.set_mode(mode)
        if "open_contained_files_as_list" in state:
            self.set_open_contained_files_as_list(bool(state["open_contained_files_as_list"]))

    def _mode_from_state(self, value) -> ListMode | None:
        if isinstance(value, ListMode):
            return value
        if isinstance(value, str):
            value = value.removeprefix("fv.list_")
            try:
                return ListMode(value)
            except ValueError:
                return None
        return None

    def on_search_results(self, paths: list[str], sources: list[str]):
        if self._mode == ListMode.SYNC:
            self._file_model.set_items(paths, sources)

    def on_file_set(self, path: str):
        if self._open_contained_files_as_list and self._query_contained_files_if_available(path):
            return
        self._set_file_by_mode(path)

    def _set_file_by_mode(self, path: str):
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

    def _contained_source(self, path: str) -> str | None:
        if is_virtual_path(path):
            return source_path(path)
        suffix = Path(path).suffix.lower()
        return path if suffix in owner_extensions() else None

    def _query_contained_files_if_available(self, path: str) -> bool:
        source = self._contained_source(path)
        if not source or not self._file_model.dbpath:
            return False
        self._query_contained_files(source, path)
        return True

    def _query_contained_files(self, source: str, requested_path: str):
        self._cancel_pending()
        sort_plugin = NaturalPathSort
        ascending = True
        dbpath = self._file_model.dbpath
        if not dbpath:
            return
        cancel = CancelToken()
        self._dir_cancel = cancel

        def task():
            engine = FileSearchEngine(dbpath)
            entries = [(SourceChildrenFilter, {"source": source}, None)]
            result = self._composer.execute(engine, entries, sort_plugin, ascending)
            if not cancel.is_cancelled():
                self._dispatcher.invoke(lambda r=result: self._on_contained_ready(r, cancel, requested_path))

        self._dispatcher.post(task, cancel=cancel)

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
        if self._dir_cancel is cancel:
            self._dir_cancel = None
        paths, sources, _ = result
        self._file_model.set_items(paths, sources)

    def _on_contained_ready(self, result, cancel, requested_path: str):
        if cancel.is_cancelled():
            return
        if self._dir_cancel is cancel:
            self._dir_cancel = None
        paths, sources, _ = result
        if not paths:
            self._set_file_by_mode(requested_path)
            return
        self._file_model.set_items(paths, sources)
        self._file_model.set_path(requested_path if requested_path in paths else paths[0])

    def _cancel_pending(self):
        if self._dir_cancel and not self._dir_cancel.is_cancelled():
            self._dir_cancel.cancel()
        self._dir_cancel = None
