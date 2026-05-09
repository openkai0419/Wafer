from __future__ import annotations

from typing import TYPE_CHECKING
from collections.abc import Callable

from PySide6 import QtCore

from ...core.state import StateStore
from ...utils.logs import AppLogger

if TYPE_CHECKING:
    from .mainwindow import MainWindow


class UIStateCoordinator:
    """Capture / restore the MainWindow's UI layout (window geometry + StateStore)."""

    def __init__(self, window: MainWindow):
        self._w = window

    def capture(self) -> dict:
        return {
            "window_state": self._w.window_state.save_full_state(),
            "component_states": StateStore.instance().save_all(),
        }

    def restore(self, ui: dict, skip_window_state: bool = False) -> None:
        if not isinstance(ui, dict):
            return
        ws = ui.get("window_state") or {}
        if ws and not skip_window_state:
            try:
                self._w.window_state.restore_full_state(ws)
            except Exception as e:
                AppLogger.warning(f"UIStateCoordinator.restore window_state failed: {e}", exc=e)
        cs = ui.get("component_states") or {}
        if cs:
            StateStore.instance().restore_all(cs)


class PathStateCoordinator:
    """Capture / restore the active database and folder tree selection."""

    def __init__(self, window: MainWindow):
        self._w = window

    def capture(self) -> dict:
        expanded, selected = self._w.folder_view.get_state()
        return {
            "database_name": self._w.database_name or "",
            "expanded": list(expanded),
            "selected": list(selected),
        }

    def restore(self, path: dict, on_complete: Callable[[], None] | None = None) -> None:
        if not isinstance(path, dict):
            if on_complete:
                on_complete()
            return
        db_name = path.get("database_name") or self._w.get_last_used_db_name()
        expanded = path.get("expanded") or []
        selected = path.get("selected") or []

        def apply_folders():
            if expanded or selected:
                self._w.folder_view.set_state_async(
                    (expanded, selected),
                    on_complete=on_complete,
                )
            elif on_complete:
                on_complete()

        if db_name and db_name != self._w.database_name:
            self._w.reload_database(db_name, on_complete=apply_folders)
        else:
            apply_folders()


class QueryStateCoordinator:
    """Capture / restore filter bars, sort order, and subfolder inclusion."""

    def __init__(self, window: MainWindow):
        self._w = window

    def capture(self) -> dict:
        bars = self._w.search_row_widget.get_bars()
        sort_by, ascending = self._w.search_row_widget.get_sort()
        return {
            "bars": bars,
            "sort_by": sort_by,
            "ascending": ascending,
            "include_subfolders": bool(self._w.search_service.get("include_subfolders", True)),
            "include_contained_files": bool(self._w.search_service.get("include_contained_files", True)),
            "auto_execute": bool(self._w.search_service.get("auto_execute", True)),
            "auto_execute_on_update": bool(self._w.search_service.get("auto_execute_on_update", True)),
        }

    def restore(self, query: dict) -> None:
        if not isinstance(query, dict):
            return
        bars = query.get("bars")
        sort_by = query.get("sort_by", "none")
        ascending = query.get("ascending", False)
        self._w.search_row_widget.set_sort(sort_by, ascending)
        if bars is not None:
            self._w.search_row_widget.apply_bars(bars, mode="replace")
        param_updates = {}
        if "include_subfolders" in query:
            param_updates["include_subfolders"] = bool(query["include_subfolders"])
        if "include_contained_files" in query:
            param_updates["include_contained_files"] = bool(query["include_contained_files"])
        if "auto_execute" in query:
            param_updates["auto_execute"] = bool(query["auto_execute"])
        if "auto_execute_on_update" in query:
            param_updates["auto_execute_on_update"] = bool(query["auto_execute_on_update"])
        if param_updates:
            self._w.search_service.set_params(param_updates)
        self._w.sync_service_from_ui()

        def _search_after_keys():
            self._w.search_row_widget.run_folder_worker(
                self._w.database_path,
                self._w.folder_view.get_selected_paths(),
                self._w.search_service.get("include_subfolders", True),
                self._w.search_service.get("include_contained_files", True),
                on_complete=lambda: self._w.search(force=True),
            )

        QtCore.QTimer.singleShot(0, _search_after_keys)
