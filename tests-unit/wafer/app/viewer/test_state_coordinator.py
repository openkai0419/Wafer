from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from wafer.app.viewer.state_coordinator import (
    PathStateCoordinator,
    QueryStateCoordinator,
    UIStateCoordinator,
)
from wafer.core.state import StateStore


class _SearchService:
    def __init__(self, params=None):
        self._params = dict(params or {})

    def get(self, key, default=None):
        return self._params.get(key, default)

    def set_params(self, updates):
        self._params.update(updates)


def _make_window(**overrides):
    w = SimpleNamespace()
    w.window_state = SimpleNamespace(
        save_full_state=MagicMock(return_value={"geo": "G"}),
        restore_full_state=MagicMock(),
    )
    w.folder_view = SimpleNamespace(
        get_state=MagicMock(return_value=(["/a"], ["/a/b"])),
        get_selected_paths=MagicMock(return_value=["/a/b"]),
        set_state_async=MagicMock(),
    )
    w.database_name = "default"
    w.database_path = "/db"
    w.get_last_used_db_name = MagicMock(return_value="default")
    w.reload_database = MagicMock()
    w.search_row_widget = SimpleNamespace(
        get_bars=MagicMock(return_value=[{"filter": "text"}]),
        get_sort=MagicMock(return_value=("path", False)),
        set_sort=MagicMock(),
        apply_bars=MagicMock(),
        run_folder_worker=MagicMock(),
    )
    w.search_service = _SearchService({"include_subfolders": True, "include_contained_files": True, "auto_execute": True})
    w.sync_service_from_ui = MagicMock()
    w.search = MagicMock()
    for k, v in overrides.items():
        setattr(w, k, v)
    return w


class TestUIStateCoordinator:
    def test_capture_includes_window_and_components(self):
        w = _make_window()
        out = UIStateCoordinator(w).capture()
        assert out["window_state"] == {"geo": "G"}
        assert isinstance(out["component_states"], dict)

    def test_restore_skip_window_state(self):
        w = _make_window()
        UIStateCoordinator(w).restore({"window_state": {"geo": "X"}}, skip_window_state=True)
        w.window_state.restore_full_state.assert_not_called()

    def test_restore_calls_window_restore(self):
        w = _make_window()
        UIStateCoordinator(w).restore({"window_state": {"geo": "X"}})
        w.window_state.restore_full_state.assert_called_once_with({"geo": "X"})

    def test_restore_invalid_input_noop(self):
        w = _make_window()
        UIStateCoordinator(w).restore("not a dict")  # type: ignore[arg-type]
        w.window_state.restore_full_state.assert_not_called()


class TestPathStateCoordinator:
    def test_capture_returns_db_and_folders(self):
        w = _make_window()
        out = PathStateCoordinator(w).capture()
        assert out == {"database_name": "default", "expanded": ["/a"], "selected": ["/a/b"]}

    def test_restore_same_db_skips_reload(self):
        w = _make_window()
        PathStateCoordinator(w).restore({"database_name": "default", "expanded": ["/x"], "selected": ["/x/y"]})
        w.reload_database.assert_not_called()
        w.folder_view.set_state_async.assert_called_once()

    def test_restore_different_db_triggers_reload(self):
        w = _make_window()
        PathStateCoordinator(w).restore({"database_name": "other", "expanded": [], "selected": []})
        w.reload_database.assert_called_once()
        assert w.reload_database.call_args[0][0] == "other"

    def test_restore_invalid_calls_completion(self):
        w = _make_window()
        cb = MagicMock()
        PathStateCoordinator(w).restore("bad", on_complete=cb)  # type: ignore[arg-type]
        cb.assert_called_once()


class TestQueryStateCoordinator:
    def test_capture_persists_query_options(self):
        w = _make_window()
        w.search_service = _SearchService({"include_subfolders": False, "include_contained_files": False, "auto_execute": False})
        out = QueryStateCoordinator(w).capture()
        assert out["include_subfolders"] is False
        assert out["include_contained_files"] is False
        assert out["auto_execute"] is False
        assert out["bars"] == [{"filter": "text"}]
        assert out["sort_by"] == "path"
        assert out["ascending"] is False

    def test_restore_applies_params_in_single_batch(self, monkeypatch):
        from PySide6 import QtCore
        monkeypatch.setattr(QtCore.QTimer, "singleShot", lambda ms, fn: None)
        w = _make_window()
        spy = MagicMock(wraps=w.search_service.set_params)
        w.search_service.set_params = spy
        QueryStateCoordinator(w).restore({
            "bars": [],
            "sort_by": "name",
            "ascending": True,
            "include_subfolders": False,
            "include_contained_files": False,
            "auto_execute": False,
        })
        spy.assert_called_once_with({"include_subfolders": False, "include_contained_files": False, "auto_execute": False})
        assert w.search_service.get("auto_execute") is False
        assert w.search_service.get("include_subfolders") is False
        assert w.search_service.get("include_contained_files") is False
        w.search_row_widget.set_sort.assert_called_once_with("name", True)
        w.search_row_widget.apply_bars.assert_called_once_with([], mode="replace")
        w.sync_service_from_ui.assert_called_once()

    def test_restore_skips_set_params_when_keys_missing(self, monkeypatch):
        from PySide6 import QtCore
        monkeypatch.setattr(QtCore.QTimer, "singleShot", lambda ms, fn: None)
        w = _make_window()
        spy = MagicMock()
        w.search_service.set_params = spy
        QueryStateCoordinator(w).restore({"bars": [], "sort_by": "path", "ascending": False})
        spy.assert_not_called()

    def test_restore_invalid_input_noop(self):
        w = _make_window()
        QueryStateCoordinator(w).restore("nope")  # type: ignore[arg-type]
        w.sync_service_from_ui.assert_not_called()
