import py_compile

from wafer.core.profile import (
    QueryState,
    UIState,
    BookmarkEntry,
    BookmarkStore,
    ProfileEntry,
    ProfileStore,
)


def test_compile():
    py_compile.compile("wafer/builtins/commands/profile_commands.py")


class TestBookmarkCommands:
    def test_command_class_registers(self):
        from wafer.builtins.commands.profile_commands import BookmarkCommands

        BookmarkCommands.register()

    def test_bm_store_lazy_init(self):
        from wafer.builtins.commands.profile_commands import _bm_store

        store = _bm_store()
        assert isinstance(store, BookmarkStore)

    def test_bookmark_save_and_list_via_store(self, tmp_path):
        store = BookmarkStore(base_dir=str(tmp_path / "bm"))
        query = QueryState(database_name="cmd_test", search_params={"sort_by": "path"})
        entry = BookmarkEntry(name="TestMark", query=query)
        store.save_bookmark(entry)
        loaded = store.list_bookmarks()
        assert len(loaded) == 1
        assert loaded[0].name == "TestMark"
        assert loaded[0].query.database_name == "cmd_test"


class TestProfileCommands:
    def test_window_commands_include_session(self):
        from wafer.builtins.commands.window_commands import WindowCommands

        cmds = WindowCommands.commands()
        paths = [c.path for c in cmds if hasattr(c, "path")]
        assert "win.new_profile" in paths
        assert "win.new_window" in paths
        assert "win.open_profile" in paths
        assert "win.rename_profile" in paths
        assert "win.delete_profile" in paths
        assert "win.profile_color" not in paths

    def test_pf_store_lazy_init(self):
        from wafer.builtins.commands.profile_commands import _pf_store

        store = _pf_store()
        assert isinstance(store, ProfileStore)

    def test_session_create_and_list_via_store(self, tmp_path):
        store = ProfileStore(path=str(tmp_path / "profiles.json"))
        sid = store.create_profile("Test")
        sessions = store.list_profiles()
        assert len(sessions) == 1
        assert sessions[0].name == "Test"
        assert sessions[0].profile_id == sid

    def test_session_rename_via_store(self, tmp_path):
        store = ProfileStore(path=str(tmp_path / "profiles.json"))
        sid = store.create_profile("Old")
        assert store.rename_profile(sid, "New")
        assert store.get_profile(sid).name == "New"

    def test_session_delete_via_store(self, tmp_path):
        store = ProfileStore(path=str(tmp_path / "profiles.json"))
        sid = store.create_profile("ToDel")
        assert store.delete_profile(sid)
        assert store.get_profile(sid) is None

    def test_alive_detection_reads_store(self, tmp_path, monkeypatch):
        store = ProfileStore(path=str(tmp_path / "profiles.json"))
        store.save_profile(ProfileEntry(profile_id="s1"))
        store.set_active_profile_ids(["s1"])
        monkeypatch.setattr(ProfileStore, "_instance", store)
        from wafer.builtins.commands import profile_commands

        alive = profile_commands._get_alive_profile_ids()
        assert "s1" in alive

    def test_resolve_profile_by_pid(self, tmp_path):
        store = ProfileStore(path=str(tmp_path / "profiles.json"))
        pid = store.create_profile("Work")
        from wafer.builtins.commands.profile_commands import _resolve_profile

        entry = _resolve_profile(store, pid=pid)
        assert entry is not None
        assert entry.name == "Work"

    def test_resolve_profile_by_name(self, tmp_path):
        store = ProfileStore(path=str(tmp_path / "profiles.json"))
        store.create_profile("Work")
        from wafer.builtins.commands.profile_commands import _resolve_profile

        entry = _resolve_profile(store, profile="Work")
        assert entry is not None
        assert entry.name == "Work"

    def test_resolve_profile_empty_returns_none(self, tmp_path):
        store = ProfileStore(path=str(tmp_path / "profiles.json"))
        from wafer.builtins.commands.profile_commands import _resolve_profile

        assert _resolve_profile(store) is None

    def test_list_session_names(self, tmp_path):
        store = ProfileStore(path=str(tmp_path / "profiles.json"))
        store.create_profile("Alpha")
        store.create_profile("Beta")
        assert store.list_profile_names() == ["Alpha", "Beta"]

    def test_find_session_by_name(self, tmp_path):
        store = ProfileStore(path=str(tmp_path / "profiles.json"))
        sid = store.create_profile("Target")
        entry = store.find_profile_by_name("Target")
        assert entry is not None
        assert entry.profile_id == sid

    def test_find_session_by_name_not_found(self, tmp_path):
        store = ProfileStore(path=str(tmp_path / "profiles.json"))
        assert store.find_profile_by_name("Ghost") is None

    def test_rename_duplicate_rejected_via_store(self, tmp_path):
        store = ProfileStore(path=str(tmp_path / "profiles.json"))
        store.create_profile("Alpha")
        sid_b = store.create_profile("Beta")
        assert not store.rename_profile(sid_b, "Alpha")
        assert store.get_profile(sid_b).name == "Beta"

    def test_rename_to_own_name_succeeds_via_store(self, tmp_path):
        store = ProfileStore(path=str(tmp_path / "profiles.json"))
        sid = store.create_profile("Same")
        assert store.rename_profile(sid, "Same")

    def test_pf_store_returns_singleton(self, monkeypatch):
        from wafer.builtins.commands.profile_commands import _pf_store

        a = _pf_store()
        b = _pf_store()
        assert a is b

    def test_bm_store_returns_singleton(self, monkeypatch):
        from wafer.builtins.commands.profile_commands import _bm_store

        a = _bm_store()
        b = _bm_store()
        assert a is b

    def test_create_session_inherits_state_without_geometry(self, tmp_path):
        store = ProfileStore(path=str(tmp_path / "profiles.json"))
        sid = store.create_profile("Child")
        entry = store.get_profile(sid)
        parent_query = QueryState(
            database_name="parent.db",
            search_params={"keywords": "sunset", "sort_by": "modified"},
            folder_state={"expanded": ["/a"], "selected": "/a"},
        )
        parent_ui = UIState(
            window_state={"geometry": "base64geom==", "always_on_top": False},
            component_states={"grid": {"scroll_index": 42}},
        )
        entry.query_snapshot = parent_query
        entry.ui = UIState(
            window_state={},
            component_states=parent_ui.component_states,
        )
        store.save_profile(entry)

        loaded = store.get_profile(sid)
        assert loaded.query_snapshot.database_name == "parent.db"
        assert loaded.query_snapshot.search_params["keywords"] == "sunset"
        assert loaded.ui.window_state == {}
        assert loaded.ui.component_states["grid"]["scroll_index"] == 42
