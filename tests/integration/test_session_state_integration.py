from wafer.core.session import (
    QueryState,
    UIState,
    SessionEntry,
    BookmarkEntry,
    SessionStore,
    BookmarkStore,
)
from wafer.core.state import StateStore


class TestSessionAndStateStoreCombined:
    def test_session_stores_state_data(self, tmp_path):
        state_store = StateStore()
        grid_state = {"base_height": 200, "spacing": 4, "layout_mode": "justified", "scroll_index": 42}
        viewer_state = {"zoom": 1.5, "fit_mode": "width"}

        state_store.register("grid", lambda: dict(grid_state), lambda d: None)
        state_store.register("viewer", lambda: dict(viewer_state), lambda d: None)

        saved_states = state_store.save_all()

        session_store = SessionStore(str(tmp_path / "sessions.json"))
        sid = session_store.create_session("Test Session")
        entry = session_store.get_session(sid)
        entry.query_snapshot = QueryState(
            database_name="photos.db",
            search_params={"keywords": "sunset", "sort_by": "modified"},
            folder_state={"selected": "/photos"},
        )
        entry.ui = UIState(
            window_state={"geometry": "geo_encoded"},
            component_states=saved_states,
        )
        session_store.save_session(entry)

        loaded = session_store.get_session(sid)
        assert loaded.query_snapshot.database_name == "photos.db"
        assert loaded.query_snapshot.search_params["keywords"] == "sunset"
        assert loaded.ui.component_states["grid"]["base_height"] == 200
        assert loaded.ui.component_states["viewer"]["zoom"] == 1.5

    def test_session_restore_feeds_state_store(self, tmp_path):
        session_store = SessionStore(str(tmp_path / "sessions.json"))
        sid = session_store.create_session("Restore Test")
        entry = session_store.get_session(sid)

        states = {
            "grid": {"base_height": 300, "scroll_index": 10},
            "tree": {"expanded": ["/a", "/b"], "selected": "/a"},
        }
        entry.ui = UIState(component_states=states)
        session_store.save_session(entry)

        loaded = session_store.get_session(sid)

        state_store = StateStore()
        restored_grid = {}
        restored_tree = {}
        state_store.register("grid", lambda: {}, lambda d: restored_grid.update(d))
        state_store.register("tree", lambda: {}, lambda d: restored_tree.update(d))
        state_store.restore_all(loaded.ui.component_states)

        assert restored_grid["base_height"] == 300
        assert restored_grid["scroll_index"] == 10
        assert restored_tree["expanded"] == ["/a", "/b"]
        assert restored_tree["selected"] == "/a"

    def test_deferred_state_restore(self, tmp_path):
        session_store = SessionStore(str(tmp_path / "sessions.json"))
        sid = session_store.create_session("Deferred")
        entry = session_store.get_session(sid)
        entry.ui = UIState(component_states={
            "panel_a": {"width": 250},
            "panel_b": {"height": 100},
        })
        session_store.save_session(entry)

        loaded = session_store.get_session(sid)

        state_store = StateStore()
        state_store.restore_all(loaded.ui.component_states)

        restored_a = {}
        state_store.register("panel_a", lambda: {}, lambda d: restored_a.update(d))
        assert restored_a["width"] == 250

        restored_b = {}
        state_store.register("panel_b", lambda: {}, lambda d: restored_b.update(d))
        assert restored_b["height"] == 100


class TestSessionWithSearchParams:
    def test_full_search_params_roundtrip(self, tmp_path):
        store = SessionStore(str(tmp_path / "sessions.json"))
        sid = store.create_session("Full Search")

        full_params = {
            "keywords": "sunset,ocean",
            "query_mode": "GLOB",
            "keyword_mode": "AND",
            "sort_by": "created",
            "ascending": False,
            "keyword_separator": ",",
            "include_subfolders": True,
            "auto_execute": True,
        }
        entry = store.get_session(sid)
        entry.query_snapshot = QueryState(
            database_name="main.db",
            search_params=full_params,
            folder_state={"expanded": ["/photos", "/art"], "selected": "/photos"},
        )
        store.save_session(entry)

        loaded = store.get_session(sid)
        assert loaded.query_snapshot.search_params == full_params
        assert loaded.query_snapshot.database_name == "main.db"
        assert loaded.query_snapshot.folder_state["expanded"] == ["/photos", "/art"]

    def test_empty_search_params(self, tmp_path):
        store = SessionStore(str(tmp_path / "sessions.json"))
        sid = store.create_session("Empty Search")
        entry = store.get_session(sid)
        entry.query_snapshot = QueryState()
        store.save_session(entry)

        loaded = store.get_session(sid)
        assert loaded.query_snapshot.search_params == {}


class TestMultiSessionStateIsolation:
    def test_two_sessions_different_states(self, tmp_path):
        store = SessionStore(str(tmp_path / "sessions.json"))
        sid_a = store.create_session("Session A")
        sid_b = store.create_session("Session B")

        entry_a = store.get_session(sid_a)
        entry_a.query_snapshot = QueryState(
            database_name="db_a",
            search_params={"keywords": "alpha"},
        )
        entry_a.ui = UIState(component_states={
            "grid": {"base_height": 200, "scroll_index": 5},
        })
        store.save_session(entry_a)

        entry_b = store.get_session(sid_b)
        entry_b.query_snapshot = QueryState(
            database_name="db_b",
            search_params={"keywords": "beta"},
        )
        entry_b.ui = UIState(component_states={
            "grid": {"base_height": 300, "scroll_index": 99},
        })
        store.save_session(entry_b)

        loaded_a = store.get_session(sid_a)
        loaded_b = store.get_session(sid_b)

        assert loaded_a.query_snapshot.database_name == "db_a"
        assert loaded_b.query_snapshot.database_name == "db_b"
        assert loaded_a.ui.component_states["grid"]["base_height"] == 200
        assert loaded_b.ui.component_states["grid"]["base_height"] == 300

    def test_session_a_restore_does_not_affect_b(self, tmp_path):
        store = SessionStore(str(tmp_path / "sessions.json"))
        sid_a = store.create_session("A")
        sid_b = store.create_session("B")

        entry_a = store.get_session(sid_a)
        entry_a.ui = UIState(component_states={"ns": {"val": "from_a"}})
        store.save_session(entry_a)

        entry_b = store.get_session(sid_b)
        entry_b.ui = UIState(component_states={"ns": {"val": "from_b"}})
        store.save_session(entry_b)

        state_store = StateStore()
        captured = {}
        state_store.register("ns", lambda: {}, lambda d: captured.update(d))

        loaded_a = store.get_session(sid_a)
        state_store.restore_all(loaded_a.ui.component_states)
        assert captured["val"] == "from_a"

        loaded_b = store.get_session(sid_b)
        state_store.restore_all(loaded_b.ui.component_states)
        assert captured["val"] == "from_b"


class TestBookmarkWithSession:
    def test_bookmark_and_session_share_query_format(self, tmp_path):
        session_store = SessionStore(str(tmp_path / "sessions.json"))
        bm_store = BookmarkStore(str(tmp_path / "bookmarks"))

        query = QueryState(
            database_name="shared.db",
            search_params={"keywords": "forest", "sort_by": "name"},
        )

        sid = session_store.create_session("From Bookmark")
        entry = session_store.get_session(sid)
        entry.query_snapshot = query
        session_store.save_session(entry)

        bm = BookmarkEntry(bookmark_id="bm001", name="Forest", query=query)
        bm_store.save_bookmark(bm)

        loaded_session = session_store.get_session(sid)
        loaded_bm = bm_store.get_bookmark("bm001")

        assert loaded_session.query_snapshot.to_dict() == loaded_bm.query.to_dict()
