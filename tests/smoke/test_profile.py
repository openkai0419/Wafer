from wafer.core.profile import (
    QueryState,
    UIState,
    ProfileEntry,
    BookmarkEntry,
    ProfileStore,
    BookmarkStore,
)


class TestProfileStoreBasicFlow:
    def test_create_save_load_delete(self, tmp_path):
        store = ProfileStore(str(tmp_path / "profiles.json"))
        try:
            sid = store.create_profile("smoke", "#4A90D9")
            assert sid

            entry = store.get_profile(sid)
            assert entry.name == "smoke"
            assert entry.color == "#4A90D9"

            entry.ui = UIState(window_state={"geometry": "g"}, component_states={"grid": {"h": 200}})
            entry.query_snapshot = QueryState(database_name="test.db", search_params={"keywords": "a"})
            store.save_profile(entry)

            loaded = store.get_profile(sid)
            assert loaded is not None
            assert loaded.name == "smoke"
            assert loaded.ui.window_state["geometry"] == "g"
            assert loaded.query_snapshot.database_name == "test.db"

            store.delete_profile(sid)
            assert store.get_profile(sid) is None
        finally:
            ProfileStore._instance = None

    def test_list_sessions(self, tmp_path):
        store = ProfileStore(str(tmp_path / "profiles.json"))
        try:
            store.create_profile("alpha", "")
            store.create_profile("beta", "")
            sessions = store.list_profiles()
            names = {s.name for s in sessions}
            assert "alpha" in names
            assert "beta" in names
        finally:
            ProfileStore._instance = None

    def test_unique_name(self, tmp_path):
        store = ProfileStore(str(tmp_path / "profiles.json"))
        try:
            sid1 = store.create_profile_with_unique_name("dup", "")
            sid2 = store.create_profile_with_unique_name("dup", "")
            e1 = store.get_profile(sid1)
            e2 = store.get_profile(sid2)
            assert e1.name != e2.name
            assert sid1 != sid2
        finally:
            ProfileStore._instance = None

    def test_find_by_name(self, tmp_path):
        store = ProfileStore(str(tmp_path / "profiles.json"))
        try:
            store.create_profile("findme", "#D94A4A")
            found = store.find_profile_by_name("findme")
            assert found is not None
            assert found.color == "#D94A4A"
            assert store.find_profile_by_name("nope") is None
        finally:
            ProfileStore._instance = None

    def test_active_session_ids(self, tmp_path):
        store = ProfileStore(str(tmp_path / "profiles.json"))
        try:
            sid1 = store.create_profile("s1", "")
            sid2 = store.create_profile("s2", "")
            store.set_active_profile_ids([sid1, sid2])
            active = store.get_active_profile_ids()
            assert sid1 in active
            assert sid2 in active
        finally:
            ProfileStore._instance = None


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
