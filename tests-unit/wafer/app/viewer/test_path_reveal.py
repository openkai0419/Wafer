from unittest.mock import ANY, MagicMock

import pytest
from PySide6 import QtCore

from wafer.app.viewer import path_reveal
from wafer.app.viewer.path_reveal import PathRevealer, scroll_grid_to_path

FILE = "F:/p/sub/a.png"
FOLDER = "F:/p/sub"


class FakeGridView(QtCore.QObject):
    layout_ready = QtCore.Signal()

    def __init__(self):
        super().__init__()
        self.rects = [object()] * 10
        self.scroll_to_index = MagicMock()

    def layout_ready_receivers(self):
        return self.receivers(QtCore.SIGNAL("layout_ready()"))


class FakeWindow(QtCore.QObject):
    def __init__(self, roots=("F:/p",), selected=(), grid_paths=(FILE,)):
        super().__init__()
        self.folder_view = MagicMock()
        self.folder_view.get_selected_paths.return_value = list(selected)
        self.grid_view = FakeGridView()
        self.grid_items = MagicMock()
        paths = list(grid_paths)
        self.grid_items.index_of_path.side_effect = lambda p: paths.index(p) if p in paths else None
        self.file_list_provider = MagicMock()
        self._layout_manager = MagicMock()
        self.setting_db = MagicMock()
        self.setting_db.get_all_parent_folders.return_value = list(roots)


@pytest.fixture
def notifications(monkeypatch):
    shown = []
    monkeypatch.setattr(path_reveal.Notifier, "info", staticmethod(shown.append))
    return shown


def on_complete_of(window, call_index=-1):
    return window.folder_view.expand_and_select_paths.call_args_list[call_index].kwargs["on_complete"]


def test_show_viewer_sets_file_and_makes_panel_visible():
    window = FakeWindow()

    PathRevealer(window).reveal(FILE, select_folder=False, scroll_grid=False, show_viewer=True)

    window.file_list_provider.on_file_set.assert_called_once_with(FILE)
    window._layout_manager.ensure_panel_visible.assert_called_once_with("Content Viewer")
    window.folder_view.expand_and_select_paths.assert_not_called()
    window.grid_view.scroll_to_index.assert_not_called()


def test_select_folder_selects_parent():
    window = FakeWindow()

    PathRevealer(window).reveal(FILE, select_folder=True, scroll_grid=False, show_viewer=False)

    window.folder_view.expand_and_select_paths.assert_called_once_with([FOLDER], on_complete=ANY)


def test_scroll_waits_for_layout_after_folder_change(qtbot):
    window = FakeWindow(selected=["F:/p/other"])
    revealer = PathRevealer(window)

    revealer.reveal(FILE, select_folder=True, scroll_grid=True, show_viewer=True)
    on_complete_of(window)()
    QtCore.QCoreApplication.processEvents()

    window.grid_view.scroll_to_index.assert_not_called()
    window.file_list_provider.on_file_set.assert_not_called()

    window.grid_view.layout_ready.emit()
    qtbot.waitUntil(lambda: window.grid_view.scroll_to_index.called)

    window.grid_view.scroll_to_index.assert_called_once_with(0, animated=True)
    window.file_list_provider.on_file_set.assert_called_once_with(FILE)
    window._layout_manager.ensure_panel_visible.assert_called_once_with("Content Viewer")
    assert window.grid_view.layout_ready_receivers() == 0


def test_scroll_immediately_when_folder_already_selected():
    window = FakeWindow(selected=["f:\\p\\sub"])

    PathRevealer(window).reveal(FILE, select_folder=True, scroll_grid=True, show_viewer=False)

    window.folder_view.expand_and_select_paths.assert_not_called()
    window.grid_view.scroll_to_index.assert_called_once_with(0, animated=True)
    assert window.grid_view.layout_ready_receivers() == 0


def test_scroll_without_folder_selection_uses_current_grid():
    window = FakeWindow(grid_paths=("F:/p/x.png", FILE))

    PathRevealer(window).reveal(FILE, select_folder=False, scroll_grid=True, show_viewer=False)

    window.folder_view.expand_and_select_paths.assert_not_called()
    window.grid_view.scroll_to_index.assert_called_once_with(1, animated=True)


def test_outside_db_roots_only_shows_viewer(monkeypatch):
    window = FakeWindow(roots=["F:/elsewhere"])
    logged = []
    monkeypatch.setattr(path_reveal.AppLogger, "info", staticmethod(logged.append))

    PathRevealer(window).reveal(FILE, select_folder=True, scroll_grid=True, show_viewer=True)

    window.folder_view.expand_and_select_paths.assert_not_called()
    window.grid_view.scroll_to_index.assert_not_called()
    window.file_list_provider.on_file_set.assert_called_once_with(FILE)
    assert len(logged) == 1
    assert FILE in logged[0]


def test_without_setting_db_only_shows_viewer():
    window = FakeWindow()
    window.setting_db = None

    PathRevealer(window).reveal(FILE, select_folder=True, scroll_grid=True, show_viewer=True)

    window.folder_view.expand_and_select_paths.assert_not_called()
    window.grid_view.scroll_to_index.assert_not_called()
    window.file_list_provider.on_file_set.assert_called_once_with(FILE)


def test_next_reveal_cancels_the_pending_layout_wait(qtbot):
    window = FakeWindow(selected=["F:/p/other"], grid_paths=(FILE, "F:/p/b/c.png"))
    revealer = PathRevealer(window)

    revealer.reveal(FILE, select_folder=True, scroll_grid=True, show_viewer=False)
    on_complete_of(window)()
    revealer.reveal("F:/p/b/c.png", select_folder=True, scroll_grid=True, show_viewer=False)
    assert window.grid_view.layout_ready_receivers() == 0

    on_complete_of(window, 0)()
    assert window.grid_view.layout_ready_receivers() == 0

    on_complete_of(window, 1)()
    assert window.grid_view.layout_ready_receivers() == 1
    window.grid_view.layout_ready.emit()
    qtbot.waitUntil(lambda: window.grid_view.scroll_to_index.called)

    window.grid_view.scroll_to_index.assert_called_once_with(1, animated=True)
    assert window.grid_view.layout_ready_receivers() == 0


def test_reveal_cancels_a_deferred_scroll_already_triggered(qtbot):
    window = FakeWindow(selected=["F:/p/other"])
    revealer = PathRevealer(window)

    revealer.reveal(FILE, select_folder=True, scroll_grid=True, show_viewer=False)
    on_complete_of(window)()
    window.grid_view.layout_ready.emit()
    revealer.reveal(FILE, select_folder=False, scroll_grid=False, show_viewer=True)
    QtCore.QCoreApplication.processEvents()

    window.grid_view.scroll_to_index.assert_not_called()


def test_scroll_reports_a_file_missing_from_the_grid(qtbot, notifications):
    window = FakeWindow(selected=["F:/p/other"], grid_paths=())
    revealer = PathRevealer(window)

    revealer.reveal(FILE, select_folder=True, scroll_grid=True, show_viewer=False)
    on_complete_of(window)()
    window.grid_view.layout_ready.emit()
    qtbot.waitUntil(lambda: bool(notifications))

    window.grid_view.scroll_to_index.assert_not_called()
    assert notifications == ["File not found in view"]


def test_scroll_grid_to_path_reports_out_of_layout(notifications):
    view = FakeGridView()
    view.rects = []
    items = MagicMock()
    items.index_of_path.return_value = 3

    scroll_grid_to_path(items, view, FILE)

    view.scroll_to_index.assert_not_called()
    assert notifications == ["File out of visible area"]
