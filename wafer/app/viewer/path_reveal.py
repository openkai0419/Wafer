import os
from dataclasses import dataclass
from functools import partial

from PySide6 import QtCore

from ...core.common.paths import normalize_path
from ...core.db.path_scope import comparable_path, is_under
from ...core.logs import AppLogger
from ...qt.common.notifier import Notifier


def scroll_grid_to_path(items, view, path: str) -> None:
    index = items.index_of_path(path)
    if index is None:
        AppLogger.info(f"[grid] file not found in view: {path}")
        Notifier.info("File not found in view")
        return
    if index >= len(view.rects):
        AppLogger.info(f"[grid] file out of visible area: {path}")
        Notifier.info("File out of visible area")
        return
    view.scroll_to_index(index, animated=True)


@dataclass(frozen=True, eq=False)
class PendingReveal:
    path: str
    scroll_grid: bool
    show_viewer: bool


class PathRevealer(QtCore.QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.pending: PendingReveal | None = None
        self.waiting_for_layout = False

    def reveal(self, path: str, *, select_folder: bool, scroll_grid: bool, show_viewer: bool) -> None:
        self.cancel_pending()
        if (select_folder or scroll_grid) and not self.is_in_database_folders(path):
            AppLogger.info(f"[open_path] outside the database folders, showing in the viewer only: {path}")
            select_folder = scroll_grid = False
        folder = normalize_path(os.path.dirname(path))
        if select_folder and not self.is_only_selected_folder(folder):
            pending = PendingReveal(path, scroll_grid, show_viewer)
            self.pending = pending
            self.window.folder_view.expand_and_select_paths([folder], on_complete=partial(self.wait_for_layout, pending))
            return
        self.finish(path, scroll_grid=scroll_grid, show_viewer=show_viewer)

    def is_in_database_folders(self, path: str) -> bool:
        setting_db = self.window.setting_db
        return setting_db is not None and any(is_under(path, root) for root in setting_db.get_all_parent_folders())

    def is_only_selected_folder(self, folder: str) -> bool:
        selected = self.window.folder_view.get_selected_paths()
        return [comparable_path(p) for p in selected] == [comparable_path(folder)]

    def wait_for_layout(self, pending: PendingReveal) -> None:
        if pending is not self.pending:
            return
        self.window.grid_view.layout_ready.connect(self.on_layout_ready)
        self.waiting_for_layout = True

    def on_layout_ready(self) -> None:
        self.stop_waiting_for_layout()
        QtCore.QTimer.singleShot(0, self, partial(self.finish_pending, self.pending))

    def finish_pending(self, pending: PendingReveal | None) -> None:
        if pending is None or pending is not self.pending:
            return
        self.pending = None
        self.finish(pending.path, scroll_grid=pending.scroll_grid, show_viewer=pending.show_viewer)

    def cancel_pending(self) -> None:
        self.pending = None
        self.stop_waiting_for_layout()

    def stop_waiting_for_layout(self) -> None:
        if not self.waiting_for_layout:
            return
        self.window.grid_view.layout_ready.disconnect(self.on_layout_ready)
        self.waiting_for_layout = False

    def finish(self, path: str, *, scroll_grid: bool, show_viewer: bool) -> None:
        window = self.window
        if scroll_grid:
            scroll_grid_to_path(window.grid_items, window.grid_view, path)
        if show_viewer:
            window.file_list_provider.on_file_set(path)
            window._layout_manager.ensure_panel_visible("Content Viewer")
