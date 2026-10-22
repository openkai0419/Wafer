from types import SimpleNamespace
from unittest.mock import ANY, MagicMock

import pytest
from PySide6 import QtCore

from wafer.app.viewer import path_reveal
from wafer.app.viewer.path_reveal import PathRevealer, scroll_grid_to_path
from wafer.core.db.path_scope import compile_ignore_patterns

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


class FakeFolderView:
    def __init__(self, roots, selected):
        self.model_ = SimpleNamespace(roots=list(roots), excluded=set(), ignore_pattern_re=None)
        self.selected = list(selected)
        self.expand_and_select_paths = MagicMock()

    def get_selected_paths(self):
        return list(self.selected)


class FakeWindow(QtCore.QObject):
    def __init__(self, roots=("F:/p",), selected=(), grid_paths=(FILE,), auto_search=True):
        super().__init__()
        self.folder_view = FakeFolderView(roots, selected)
        self.grid_view = FakeGridView()
        self.grid_items = MagicMock()
        paths = list(grid_paths)
        self.grid_items.index_of_path.side_effect = lambda p: paths.index(p) if p in paths else None
        self.file_list_provider = MagicMock()
        self._layout_manager = MagicMock()
        self.search_service = MagicMock()
        self.search_service.get.side_effect = lambda key, default=None: auto_search if key == "auto_execute" else default


@pytest.fixture
def notifications(monkeypatch):
    shown = []
    monkeypatch.setattr(path_reveal.Notifier, "info", staticmethod(shown.append))
    return shown


@pytest.fixture
def info_logs(monkeypatch):
    logged = []
    monkeypatch.setattr(path_reveal.AppLogger, "info", staticmethod(logged.append))
    return logged


def on_complete_of(window, call_index=-1):
    return window.folder_view.expand_and_select_paths.call_args_list[call_index].kwargs["on_complete"]


def apply_selection(window, selected=(FOLDER,), call_index=-1):
    window.folder_view.selected = list(selected)
    on_complete_of(window, call_index)()


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
    apply_selection(window)
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


def test_outside_db_roots_only_shows_viewer(info_logs):
    window = FakeWindow(roots=["F:/elsewhere"])

    PathRevealer(window).reveal(FILE, select_folder=True, scroll_grid=True, show_viewer=True)

    window.folder_view.expand_and_select_paths.assert_not_called()
    window.grid_view.scroll_to_index.assert_not_called()
    window.file_list_provider.on_file_set.assert_called_once_with(FILE)
    assert len(info_logs) == 1
    assert FILE in info_logs[0]


def test_before_folders_are_loaded_only_shows_viewer():
    window = FakeWindow()
    window.folder_view.model_.roots = None

    PathRevealer(window).reveal(FILE, select_folder=True, scroll_grid=True, show_viewer=True)

    window.folder_view.expand_and_select_paths.assert_not_called()
    window.grid_view.scroll_to_index.assert_not_called()
    window.file_list_provider.on_file_set.assert_called_once_with(FILE)


def test_ignored_folder_only_shows_viewer():
    window = FakeWindow()
    window.folder_view.model_.excluded = {FOLDER}

    PathRevealer(window).reveal(FILE, select_folder=True, scroll_grid=True, show_viewer=True)

    window.folder_view.expand_and_select_paths.assert_not_called()
    window.file_list_provider.on_file_set.assert_called_once_with(FILE)


def test_ignore_pattern_only_shows_viewer():
    window = FakeWindow()
    window.folder_view.model_.ignore_pattern_re = compile_ignore_patterns(["*/sub*"])

    PathRevealer(window).reveal(FILE, select_folder=True, scroll_grid=True, show_viewer=True)

    window.folder_view.expand_and_select_paths.assert_not_called()
    window.file_list_provider.on_file_set.assert_called_once_with(FILE)


def test_folder_that_never_gets_selected_still_shows_viewer(info_logs):
    window = FakeWindow(selected=["F:/p/other"])

    PathRevealer(window).reveal(FILE, select_folder=True, scroll_grid=False, show_viewer=True)
    apply_selection(window, selected=[])

    window.file_list_provider.on_file_set.assert_called_once_with(FILE)
    assert window.grid_view.layout_ready_receivers() == 0
    assert any(FOLDER in line for line in info_logs)


def test_auto_search_off_finishes_without_waiting_for_layout():
    window = FakeWindow(selected=["F:/p/other"], auto_search=False)

    PathRevealer(window).reveal(FILE, select_folder=True, scroll_grid=True, show_viewer=True)
    apply_selection(window)

    window.grid_view.scroll_to_index.assert_called_once_with(0, animated=True)
    window.file_list_provider.on_file_set.assert_called_once_with(FILE)
    assert window.grid_view.layout_ready_receivers() == 0


def test_search_with_unchanged_results_ends_the_wait(qtbot):
    from wafer.app.viewer.mainwindow import MainWindow

    window = FakeWindow(selected=["F:/p/other"])
    paths = [FILE]
    window._last_paths = paths
    window._folder_changed = True
    window.search_row_widget = MagicMock()
    window.grid_overlay_host = MagicMock()
    window.database_path = "test.db"

    PathRevealer(window).reveal(FILE, select_folder=True, scroll_grid=False, show_viewer=True)
    apply_selection(window)
    MainWindow._on_search_finished(window, list(paths), list(paths), [1.0])
    qtbot.waitUntil(lambda: window.file_list_provider.on_file_set.called)

    window.file_list_provider.on_file_set.assert_called_once_with(FILE)
    assert window.grid_view.layout_ready_receivers() == 0


def test_next_reveal_cancels_the_pending_layout_wait(qtbot):
    window = FakeWindow(selected=["F:/p/other"], grid_paths=(FILE, "F:/p/b/c.png"))
    revealer = PathRevealer(window)

    revealer.reveal(FILE, select_folder=True, scroll_grid=True, show_viewer=False)
    apply_selection(window)
    window.folder_view.selected = ["F:/p/other"]
    revealer.reveal("F:/p/b/c.png", select_folder=True, scroll_grid=True, show_viewer=False)
    assert window.grid_view.layout_ready_receivers() == 0

    apply_selection(window, call_index=0)
    assert window.grid_view.layout_ready_receivers() == 0

    apply_selection(window, selected=["F:/p/b"], call_index=1)
    assert window.grid_view.layout_ready_receivers() == 1
    window.grid_view.layout_ready.emit()
    qtbot.waitUntil(lambda: window.grid_view.scroll_to_index.called)

    window.grid_view.scroll_to_index.assert_called_once_with(1, animated=True)
    assert window.grid_view.layout_ready_receivers() == 0


def test_reveal_cancels_a_deferred_scroll_already_triggered(qtbot):
    window = FakeWindow(selected=["F:/p/other"])
    revealer = PathRevealer(window)

    revealer.reveal(FILE, select_folder=True, scroll_grid=True, show_viewer=False)
    apply_selection(window)
    window.grid_view.layout_ready.emit()
    revealer.reveal(FILE, select_folder=False, scroll_grid=False, show_viewer=True)
    QtCore.QCoreApplication.processEvents()

    window.grid_view.scroll_to_index.assert_not_called()


def test_scroll_reports_a_file_missing_from_the_grid(qtbot, notifications):
    window = FakeWindow(selected=["F:/p/other"], grid_paths=())
    revealer = PathRevealer(window)

    revealer.reveal(FILE, select_folder=True, scroll_grid=True, show_viewer=False)
    apply_selection(window)
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
