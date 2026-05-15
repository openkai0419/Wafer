import pytest
from unittest.mock import MagicMock, patch
from wafer.app.viewer.preview.file_list_provider import FileListProvider, ListMode
from wafer.app.viewer.preview.file_model import FileViewModel
from wafer.app.viewer.grid.items import GridItemModel
from wafer.builtins.filters import SourceChildrenFilter
from wafer.utils.virtual_paths import build_virtual_path, register_owner_extension


@pytest.fixture
def file_model():
    return FileViewModel()


@pytest.fixture
def grid_items():
    return GridItemModel()


@pytest.fixture
def provider(file_model, grid_items):
    return FileListProvider(file_model, grid_items)


class TestListMode:
    def test_default_mode_is_sync(self, provider):
        assert provider.mode == ListMode.SYNC

    def test_set_mode(self, provider):
        provider.set_mode(ListMode.FIX)
        assert provider.mode == ListMode.FIX
        provider.set_mode(ListMode.DIR)
        assert provider.mode == ListMode.DIR
        provider.set_mode(ListMode.SYNC)
        assert provider.mode == ListMode.SYNC


class TestContainedFilesListOption:
    def test_default_is_disabled(self, provider):
        assert provider.open_contained_files_as_list is False

    def test_set_open_contained_files_as_list(self, provider):
        provider.set_open_contained_files_as_list(True)
        assert provider.open_contained_files_as_list is True
        provider.set_open_contained_files_as_list(False)
        assert provider.open_contained_files_as_list is False

    def test_save_restore_ui_state(self, provider):
        provider.set_mode(ListMode.DIR)
        provider.set_open_contained_files_as_list(True)

        state = provider.save_ui_state()
        provider.restore_ui_state({"list_mode": "fv.list_fix", "open_contained_files_as_list": False})

        assert state == {"list_mode": "dir", "open_contained_files_as_list": True}
        assert provider.mode == ListMode.FIX
        assert provider.open_contained_files_as_list is False

    @patch.object(FileListProvider, "_query_contained_files")
    def test_container_path_triggers_contained_query_when_enabled(self, mock_query, provider, file_model):
        register_owner_extension(".zip")
        file_model._dbpath_getter = lambda: ":memory:"
        provider.set_open_contained_files_as_list(True)

        provider.on_file_set("C:/data/temp.zip")

        mock_query.assert_called_once_with("C:/data/temp.zip", "C:/data/temp.zip")

    @patch.object(FileListProvider, "_query_contained_files")
    def test_virtual_child_triggers_sibling_query_when_enabled(self, mock_query, provider, file_model):
        register_owner_extension(".zip")
        file_model._dbpath_getter = lambda: ":memory:"
        child = build_virtual_path("C:/data/temp.zip", "a.png")
        provider.set_open_contained_files_as_list(True)

        provider.on_file_set(child)

        mock_query.assert_called_once_with("C:/data/temp.zip", child)

    @patch.object(FileListProvider, "_query_contained_files")
    def test_option_off_uses_current_list_mode(self, mock_query, provider, file_model):
        register_owner_extension(".zip")
        file_model._dbpath_getter = lambda: ":memory:"

        provider.on_file_set("C:/data/temp.zip")

        mock_query.assert_not_called()
        assert file_model.path() == "C:/data/temp.zip"

    def test_non_owner_extension_skips_contained_query(self, provider, file_model):
        file_model._dbpath_getter = lambda: ":memory:"
        provider.set_open_contained_files_as_list(True)

        provider.on_file_set("C:/data/plain.png")

        assert file_model.path() == "C:/data/plain.png"

    def test_on_contained_ready_sets_first_child_for_container(self, provider, file_model):
        register_owner_extension(".zip")
        archive = "C:/data/temp.zip"
        child_a = build_virtual_path(archive, "a.png")
        child_b = build_virtual_path(archive, "b.png")
        from wafer.core.qt.dispatcher import CancelToken

        cancel = CancelToken()
        provider._dir_cancel = cancel
        provider._on_contained_ready(([child_a, child_b], [archive, archive], [1.0, 1.0]), cancel, archive)

        assert file_model.paths == [child_a, child_b]
        assert file_model.path() == child_a
        assert file_model.current_index() == 0

    def test_on_contained_ready_keeps_requested_child(self, provider, file_model):
        register_owner_extension(".zip")
        archive = "C:/data/temp.zip"
        child_a = build_virtual_path(archive, "a.png")
        child_b = build_virtual_path(archive, "b.png")
        from wafer.core.qt.dispatcher import CancelToken

        cancel = CancelToken()
        provider._dir_cancel = cancel
        provider._on_contained_ready(([child_a, child_b], [archive, archive], [1.0, 1.0]), cancel, child_b)

        assert file_model.path() == child_b
        assert file_model.current_index() == 1

    def test_empty_contained_result_falls_back_to_mode(self, provider, file_model):
        from wafer.core.qt.dispatcher import CancelToken

        cancel = CancelToken()
        provider._dir_cancel = cancel
        provider._on_contained_ready(([], [], []), cancel, "C:/data/temp.zip")

        assert file_model.path() == "C:/data/temp.zip"

    def test_query_contained_files_uses_source_children_filter(self, provider, file_model):
        file_model._dbpath_getter = lambda: ":memory:"
        captured = {}

        def fake_post(task, *args, **kwargs):
            captured["task"] = task

        with patch.object(provider._composer, "execute") as mock_exec, patch.object(provider._dispatcher, "post", side_effect=fake_post):
            mock_exec.return_value = ([], [], [])
            provider._query_contained_files("C:/data/temp.zip", "C:/data/temp.zip")
            captured["task"]()
            args, _ = mock_exec.call_args
            assert args[1][0][0] is SourceChildrenFilter
            assert args[1][0][1] == {"source": "C:/data/temp.zip"}


class TestSyncMode:
    def test_on_search_results_updates_file_model(self, provider, file_model):
        provider.set_mode(ListMode.SYNC)
        provider.on_search_results(["a", "b", "c"], ["s1", "s2", "s3"])
        assert file_model.count() == 3
        assert file_model.paths == ["a", "b", "c"]
        assert file_model.sources == ["s1", "s2", "s3"]

    def test_on_file_set_calls_set_path(self, provider, file_model):
        provider.set_mode(ListMode.SYNC)
        file_model.set_items(["a", "b", "c"], ["s1", "s2", "s3"])
        provider.on_file_set("b")
        assert file_model.path() == "b"
        assert file_model.current_index() == 1

    def test_set_mode_sync_recovers_from_stale_directory_list(self, provider, file_model, grid_items):
        grid_items.set_items(["g0", "g1", "g2"], ["s0", "s1", "s2"], [1.0, 1.0, 1.0])
        provider.set_mode(ListMode.DIR)
        file_model.set_items(["d0", "d1", "g1", "d2"], ["sd0", "sd1", "sg1", "sd2"])
        file_model.set_path("g1")

        provider.set_mode(ListMode.SYNC)

        assert file_model.paths == ["g0", "g1", "g2"]
        assert file_model.sources == ["s0", "s1", "s2"]
        assert file_model.path() == "g1"
        assert file_model.current_index() == 1

    def test_set_mode_sync_refreshes_current_grid_even_when_already_sync(self, provider, file_model, grid_items):
        provider.set_mode(ListMode.SYNC)
        grid_items.set_items(["g0", "g1"], ["s0", "s1"], [1.0, 1.0])
        file_model.set_items(["old0", "g1", "old1"], ["so0", "stale", "so1"])
        file_model.set_path("g1")

        provider.set_mode(ListMode.SYNC)

        assert file_model.paths == ["g0", "g1"]
        assert file_model.sources == ["s0", "s1"]
        assert file_model.path() == "g1"
        assert file_model.current_index() == 1

    def test_on_file_set_sync_keeps_standalone_path_when_not_in_grid(self, provider, file_model, grid_items):
        file_model.set_items(["a", "b", "c"], ["s1", "s2", "s3"])
        grid_items.set_items(["x", "y"], ["sx", "sy"], [1.0, 1.0])

        provider.on_file_set("b")

        assert file_model.paths == ["a", "b", "c"]
        assert file_model.path() == "b"
        assert file_model.current_index() == 1


class TestFixMode:
    def test_on_search_results_ignored(self, provider, file_model, grid_items):
        grid_items.set_items(["x", "y"], ["sx", "sy"], [1.0, 1.0])
        provider.set_mode(ListMode.FIX)
        file_model.set_items(["x", "y"], ["sx", "sy"])
        provider.on_search_results(["a", "b", "c"], ["s1", "s2", "s3"])
        assert file_model.paths == ["x", "y"]

    def test_on_file_set_captures_grid_list(self, provider, file_model, grid_items):
        grid_items.set_items(["a", "b", "c"], ["s1", "s2", "s3"], [1.0, 1.0, 1.0])
        provider.set_mode(ListMode.FIX)
        provider.on_file_set("b")
        assert file_model.paths == ["a", "b", "c"]
        assert file_model.sources == ["s1", "s2", "s3"]
        assert file_model.path() == "b"
        assert file_model.current_index() == 1

    def test_fix_mode_preserves_list_on_search(self, provider, file_model, grid_items):
        grid_items.set_items(["a", "b"], ["s1", "s2"], [1.0, 1.0])
        provider.set_mode(ListMode.FIX)
        provider.on_file_set("a")
        assert file_model.paths == ["a", "b"]
        provider.on_search_results(["x", "y", "z"], ["sx", "sy", "sz"])
        assert file_model.paths == ["a", "b"]

    def test_fix_mode_recaptures_on_new_set(self, provider, file_model, grid_items):
        grid_items.set_items(["a", "b"], ["s1", "s2"], [1.0, 1.0])
        provider.set_mode(ListMode.FIX)
        provider.on_file_set("a")
        assert file_model.paths == ["a", "b"]
        grid_items.set_items(["x", "y", "z"], ["sx", "sy", "sz"], [1.0, 1.0, 1.0])
        provider.on_file_set("y")
        assert file_model.paths == ["x", "y", "z"]
        assert file_model.path() == "y"


class TestDirMode:
    def test_on_search_results_ignored(self, provider, file_model):
        provider.set_mode(ListMode.DIR)
        file_model.set_items(["x"], ["sx"])
        provider.on_search_results(["a", "b"], ["s1", "s2"])
        assert file_model.paths == ["x"]

    def test_on_file_set_sets_path_immediately(self, provider, file_model):
        provider.set_mode(ListMode.DIR)
        file_model._dbpath_getter = lambda: ":memory:"
        provider.on_file_set("/dir/test.jpg")
        assert file_model.path() == "/dir/test.jpg"

    @patch.object(FileListProvider, "_query_directory")
    def test_on_file_set_triggers_directory_query(self, mock_query, provider, file_model):
        provider.set_mode(ListMode.DIR)
        provider.on_file_set("/dir/test.jpg")
        mock_query.assert_called_once_with("/dir/test.jpg")

    def test_cancel_pending_on_mode_change(self, provider):
        from wafer.core.qt.dispatcher import CancelToken

        token = CancelToken()
        provider._dir_cancel = token
        provider.set_mode(ListMode.SYNC)
        assert token.is_cancelled()

    def test_on_dir_ready_updates_file_model(self, provider, file_model):
        from wafer.core.qt.dispatcher import CancelToken

        provider.set_mode(ListMode.DIR)
        file_model.set_items([], [])
        file_model.set_path("/dir/b.jpg")
        cancel = CancelToken()
        provider._dir_cancel = cancel
        result = (["/dir/a.jpg", "/dir/b.jpg", "/dir/c.jpg"], ["s1", "s2", "s3"], [1.0, 1.0, 1.0])
        provider._on_dir_ready(result, cancel)
        assert file_model.paths == ["/dir/a.jpg", "/dir/b.jpg", "/dir/c.jpg"]
        assert file_model.path() == "/dir/b.jpg"
        assert file_model.current_index() == 1

    def test_on_dir_ready_ignores_cancelled(self, provider, file_model):
        from wafer.core.qt.dispatcher import CancelToken

        provider.set_mode(ListMode.DIR)
        file_model.set_items(["old"], ["s_old"])
        cancel = CancelToken()
        cancel.cancel()
        result = (["/dir/a.jpg", "/dir/b.jpg"], ["s1", "s2"], [1.0, 1.0])
        provider._on_dir_ready(result, cancel)
        assert file_model.paths == ["old"]

    def test_query_directory_uses_path_sort_ascending(self, provider, file_model):
        from wafer.builtins.sorts import NaturalPathSort

        provider.set_mode(ListMode.DIR)
        file_model._dbpath_getter = lambda: ":memory:"
        captured = {}

        def fake_post(task, *args, **kwargs):
            captured["task"] = task

        with patch.object(provider._composer, "execute") as mock_exec, patch.object(provider._dispatcher, "post", side_effect=fake_post):
            mock_exec.return_value = ([], [], [])
            provider._query_directory("/dir/test.jpg")
            captured["task"]()
            args, _ = mock_exec.call_args
            assert args[2] is NaturalPathSort
            assert args[3] is True
