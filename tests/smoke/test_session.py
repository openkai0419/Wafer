from wafer.core.session import (
    QueryState,
    UIState,
    SessionEntry,
    BookmarkEntry,
    SessionStore,
    BookmarkStore,
)


class TestSessionStoreBasicFlow:
    def test_create_save_load_delete(self, tmp_path):
        store = SessionStore(str(tmp_path / "sessions.json"))
        try:
            sid = store.create_session("smoke", "#4A90D9")
            assert sid

            entry = store.get_session(sid)
            assert entry.name == "smoke"
            assert entry.color == "#4A90D9"

            entry.ui = UIState(window_state={"geometry": "g"}, component_states={"grid": {"h": 200}})
            entry.query_snapshot = QueryState(database_name="test.db", search_params={"keywords": "a"})
            store.save_session(entry)

            loaded = store.get_session(sid)
            assert loaded is not None
            assert loaded.name == "smoke"
            assert loaded.ui.window_state["geometry"] == "g"
            assert loaded.query_snapshot.database_name == "test.db"

            store.delete_session(sid)
            assert store.get_session(sid) is None
        finally:
            SessionStore._instance = None

    def test_list_sessions(self, tmp_path):
        store = SessionStore(str(tmp_path / "sessions.json"))
        try:
            store.create_session("alpha", "")
            store.create_session("beta", "")
            sessions = store.list_sessions()
            names = {s.name for s in sessions}
            assert "alpha" in names
            assert "beta" in names
        finally:
            SessionStore._instance = None

    def test_unique_name(self, tmp_path):
        store = SessionStore(str(tmp_path / "sessions.json"))
        try:
            sid1 = store.create_session_with_unique_name("dup", "")
            sid2 = store.create_session_with_unique_name("dup", "")
            e1 = store.get_session(sid1)
            e2 = store.get_session(sid2)
            assert e1.name != e2.name
            assert sid1 != sid2
        finally:
            SessionStore._instance = None

    def test_find_by_name(self, tmp_path):
        store = SessionStore(str(tmp_path / "sessions.json"))
        try:
            store.create_session("findme", "#D94A4A")
            found = store.find_session_by_name("findme")
            assert found is not None
            assert found.color == "#D94A4A"
            assert store.find_session_by_name("nope") is None
        finally:
            SessionStore._instance = None

    def test_active_session_ids(self, tmp_path):
        store = SessionStore(str(tmp_path / "sessions.json"))
        try:
            sid1 = store.create_session("s1", "")
            sid2 = store.create_session("s2", "")
            store.set_active_session_ids([sid1, sid2])
            active = store.get_active_session_ids()
            assert sid1 in active
            assert sid2 in active
        finally:
            SessionStore._instance = None


class TestBookmarkStoreBasicFlow:
    def test_create_load_delete(self, tmp_path):
        store = BookmarkStore(str(tmp_path / "bookmarks"))
        try:
            entry = BookmarkEntry(name="bm1", query=QueryState(database_name="db1"))
            store.save_bookmark(entry)
            bid = entry.bookmark_id

            loaded = store.get_bookmark(bid)
            assert loaded is not None
            assert loaded.name == "bm1"
            assert loaded.query.database_name == "db1"

            store.delete_bookmark(bid)
            assert store.get_bookmark(bid) is None
        finally:
            BookmarkStore._instance = None

    def test_list_all(self, tmp_path):
        store = BookmarkStore(str(tmp_path / "bookmarks"))
        try:
            store.save_bookmark(BookmarkEntry(name="b1"))
            store.save_bookmark(BookmarkEntry(name="b2"))
            all_bm = store.list_bookmarks()
            names = {b.name for b in all_bm}
            assert "b1" in names
            assert "b2" in names
        finally:
            BookmarkStore._instance = None
