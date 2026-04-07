import pytest
from unittest.mock import MagicMock, patch
from wafer.app.viewer.preview.file_list_provider import FileListProvider, ListMode
from wafer.app.viewer.preview.file_model import FileViewModel
from wafer.app.viewer.grid.items import GridItemModel


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
        mock_search = MagicMock()
        mock_search.resolve_sort.return_value = None
        mock_search.get.return_value = True
        provider.set_search_service(mock_search)
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
