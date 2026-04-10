import json
import os
import pytest

from wafer.core.profile import (
    QueryState,
    UIState,
    BookmarkEntry,
    ProfileEntry,
    ProfileStore,
    BookmarkStore,
    PROFILE_COLORS,
)
from wafer.constants import DEFAULT_PROFILE_NAME


@pytest.fixture
def tmp_store(tmp_path):
    return ProfileStore(path=str(tmp_path / "profiles.json"))


@pytest.fixture
def tmp_bm_store(tmp_path):
    return BookmarkStore(base_dir=str(tmp_path / "bookmark"))


class TestQueryState:
    def test_defaults(self):
        q = QueryState()
        assert q.database_name == ""
        assert q.search_params == {}
        assert q.folder_state == {}

    def test_roundtrip(self):
        q = QueryState(
            database_name="mydb",
            search_params={"sort_by": "name", "ascending": False},
            folder_state={"expanded": ["/a", "/b"], "selected": ["/a"]},
        )
        restored = QueryState.from_dict(q.to_dict())
        assert restored == q

    def test_from_dict_ignores_unknown_keys(self):
        q = QueryState.from_dict({"database_name": "x", "unknown_field": 123})
        assert q.database_name == "x"

    def test_from_dict_handles_non_dict(self):
        assert QueryState.from_dict(None) == QueryState()

    def test_json_serializable(self):
        q = QueryState(database_name="test", search_params={"k": "v"})
        text = json.dumps(q.to_dict())
        assert QueryState.from_dict(json.loads(text)) == q


class TestUIState:
    def test_defaults(self):
        u = UIState()
        assert u.window_state == {}
        assert u.component_states == {}

    def test_roundtrip(self):
        u = UIState(
            window_state={"geometry": "abc123==", "always_on_top": False},
            component_states={
                "main_splitter": {"sizes": [100, 500, 200]},
                "grid": {"zoom": 150, "orientation": 1, "layout_mode": "masonry"},
            },
        )
        restored = UIState.from_dict(u.to_dict())
        assert restored == u

    def test_from_dict_handles_non_dict(self):
        assert UIState.from_dict(None) == UIState()


class TestBookmarkEntry:
    def test_defaults(self):
        b = BookmarkEntry()
        assert len(b.bookmark_id) == 12
        assert b.name == ""
        assert isinstance(b.query, QueryState)

    def test_roundtrip(self):
        query = QueryState(database_name="db2", search_params={"sort_by": "size"})
        b = BookmarkEntry(bookmark_id="bm001", name="Favorites", query=query)
        restored = BookmarkEntry.from_dict(b.to_dict())
        assert restored.bookmark_id == "bm001"
        assert restored.name == "Favorites"
        assert restored.query.database_name == "db2"
        assert restored.query.search_params == {"sort_by": "size"}

    def test_from_dict_handles_non_dict(self):
        b = BookmarkEntry.from_dict("invalid")
        assert isinstance(b, BookmarkEntry)


class TestProfileEntry:
    def test_defaults(self):
        e = ProfileEntry()
        assert len(e.profile_id) == 12
        assert e.name == ""
        assert e.color == ""
        assert isinstance(e.ui, UIState)
        assert e.bookmark_id == ""
        assert e.query_snapshot is None

    def test_roundtrip_with_snapshot(self):
        ui = UIState(component_states={"main_splitter": {"sizes": [10, 80, 10]}, "grid": {"scroll_index": 5}})
        qs = QueryState(database_name="db1", search_params={"sort_by": "name"})
        e = ProfileEntry(profile_id="s1", name="Work", color="#4A90D9", ui=ui, query_snapshot=qs)
        restored = ProfileEntry.from_dict(e.to_dict())
        assert restored.profile_id == "s1"
        assert restored.name == "Work"
        assert restored.color == "#4A90D9"
        assert restored.ui.component_states["main_splitter"]["sizes"] == [10, 80, 10]
        assert restored.query_snapshot.database_name == "db1"

    def test_roundtrip_with_bookmark_ref(self):
        e = ProfileEntry(profile_id="s2", bookmark_id="bm001")
        restored = ProfileEntry.from_dict(e.to_dict())
        assert restored.bookmark_id == "bm001"
        assert restored.query_snapshot is None

    def test_roundtrip_without_snapshot(self):
        e = ProfileEntry(profile_id="s3", name="NoQuery")
        d = e.to_dict()
        assert "query_snapshot" not in d
        restored = ProfileEntry.from_dict(d)
        assert restored.query_snapshot is None

    def test_from_dict_handles_non_dict(self):
        assert isinstance(ProfileEntry.from_dict("invalid"), ProfileEntry)

    def test_from_dict_ignores_legacy_anonymous_field(self):
        restored = ProfileEntry.from_dict({"session_id": "old", "anonymous": True})
        assert restored.profile_id == "old"


class TestProfileStoreSession:
    def test_empty_store(self, tmp_store):
        assert tmp_store.list_profiles() == []
        assert tmp_store.get_profile("nonexistent") is None

    def test_save_and_get(self, tmp_store):
        ui = UIState(component_states={"grid": {"scroll_index": 5}})
        qs = QueryState(database_name="mydb")
        entry = ProfileEntry(profile_id="s1", name="Main", ui=ui, query_snapshot=qs)
        tmp_store.save_profile(entry)

        loaded = tmp_store.get_profile("s1")
        assert loaded is not None
        assert loaded.name == "Main"
        assert loaded.ui.component_states["grid"]["scroll_index"] == 5
        assert loaded.query_snapshot.database_name == "mydb"

    def test_save_updates_timestamp(self, tmp_store):
        entry = ProfileEntry(profile_id="s1", name="A", updated_at="old")
        tmp_store.save_profile(entry)
        loaded = tmp_store.get_profile("s1")
        assert loaded.updated_at != "old"

    def test_list_sessions(self, tmp_store):
        tmp_store.save_profile(ProfileEntry(profile_id="a", name="First"))
        tmp_store.save_profile(ProfileEntry(profile_id="b", name="Second"))
        sessions = tmp_store.list_profiles()
        assert len(sessions) == 2
        names = {s.name for s in sessions}
        assert names == {"First", "Second"}

    def test_delete_session(self, tmp_store):
        tmp_store.save_profile(ProfileEntry(profile_id="del1", name="ToDelete"))
        assert tmp_store.delete_profile("del1")
        assert tmp_store.get_profile("del1") is None
        assert not tmp_store.delete_profile("del1")

    def test_delete_removes_from_active(self, tmp_store):
        tmp_store.save_profile(ProfileEntry(profile_id="x"))
        tmp_store.set_active_profile_ids(["x", "y"])
        tmp_store.delete_profile("x")
        assert "x" not in tmp_store.get_active_profile_ids()

    def test_delete_removes_from_restore(self, tmp_store):
        tmp_store.save_profile(ProfileEntry(profile_id="r1"))
        tmp_store.save_profile(ProfileEntry(profile_id="r2"))
        tmp_store.set_restore_profile_ids(["r1", "r2"])
        tmp_store.delete_profile("r1")
        assert tmp_store.get_restore_profile_ids() == ["r2"]

    def test_overwrite_session(self, tmp_store):
        entry = ProfileEntry(profile_id="s1", name="Old")
        tmp_store.save_profile(entry)
        entry.name = "New"
        entry.ui.component_states = {"main_splitter": {"sizes": [1, 2, 3]}}
        tmp_store.save_profile(entry)

        loaded = tmp_store.get_profile("s1")
        assert loaded.name == "New"
        assert loaded.ui.component_states["main_splitter"]["sizes"] == [1, 2, 3]
        assert len(tmp_store.list_profiles()) == 1


class TestProfileStoreActiveIds:
    def test_default_empty(self, tmp_store):
        assert tmp_store.get_active_profile_ids() == []

    def test_set_and_get(self, tmp_store):
        tmp_store.set_active_profile_ids(["a", "b", "c"])
        assert tmp_store.get_active_profile_ids() == ["a", "b", "c"]

    def test_replace(self, tmp_store):
        tmp_store.set_active_profile_ids(["a"])
        tmp_store.set_active_profile_ids(["b", "c"])
        assert tmp_store.get_active_profile_ids() == ["b", "c"]


class TestProfileStoreRestoreIds:
    def test_default_empty(self, tmp_store):
        assert tmp_store.get_restore_profile_ids() == []

    def test_set_and_get(self, tmp_store):
        tmp_store.save_profile(ProfileEntry(profile_id="s1", name="S1"))
        tmp_store.save_profile(ProfileEntry(profile_id="Work", name="Work"))
        tmp_store.set_restore_profile_ids(["s1", "Work"])
        assert tmp_store.get_restore_profile_ids() == ["s1", "Work"]

    def test_replace(self, tmp_store):
        tmp_store.save_profile(ProfileEntry(profile_id="a"))
        tmp_store.save_profile(ProfileEntry(profile_id="b"))
        tmp_store.save_profile(ProfileEntry(profile_id="c"))
        tmp_store.set_restore_profile_ids(["a"])
        tmp_store.set_restore_profile_ids(["b", "c"])
        assert tmp_store.get_restore_profile_ids() == ["b", "c"]

    def test_independent_from_active(self, tmp_store):
        tmp_store.save_profile(ProfileEntry(profile_id="x"))
        tmp_store.save_profile(ProfileEntry(profile_id="y"))
        tmp_store.set_active_profile_ids(["x"])
        tmp_store.set_restore_profile_ids(["y"])
        assert tmp_store.get_active_profile_ids() == ["x"]
        assert tmp_store.get_restore_profile_ids() == ["y"]

    def test_filters_missing_sessions(self, tmp_store):
        tmp_store.save_profile(ProfileEntry(profile_id="s1", name="S1"))
        tmp_store.set_restore_profile_ids(["s1", "deleted"])
        assert tmp_store.get_restore_profile_ids() == ["s1"]

    def test_all_missing_returns_empty(self, tmp_store):
        tmp_store.set_restore_profile_ids(["gone-1", "gone-2"])
        assert tmp_store.get_restore_profile_ids() == []


class TestNextDefaultName:
    def test_first_default(self, tmp_store):
        assert tmp_store.next_default_name() == f"{DEFAULT_PROFILE_NAME}1"

    def test_second_default(self, tmp_store):
        tmp_store.create_profile(f"{DEFAULT_PROFILE_NAME}1")
        assert tmp_store.next_default_name() == f"{DEFAULT_PROFILE_NAME}2"

    def test_fills_gap(self, tmp_store):
        tmp_store.create_profile(f"{DEFAULT_PROFILE_NAME}1")
        tmp_store.create_profile(f"{DEFAULT_PROFILE_NAME}2")
        tmp_store.create_profile(f"{DEFAULT_PROFILE_NAME}4")
        assert tmp_store.next_default_name() == f"{DEFAULT_PROFILE_NAME}3"

    def test_next_after_all_used(self, tmp_store):
        tmp_store.create_profile(f"{DEFAULT_PROFILE_NAME}1")
        tmp_store.create_profile(f"{DEFAULT_PROFILE_NAME}2")
        tmp_store.create_profile(f"{DEFAULT_PROFILE_NAME}3")
        assert tmp_store.next_default_name() == f"{DEFAULT_PROFILE_NAME}4"


class TestFindInactiveProfile:
    def test_empty_store_returns_none(self, tmp_store):
        assert tmp_store.find_inactive_profile_id() is None

    def test_all_active_returns_none(self, tmp_store):
        tmp_store.save_profile(ProfileEntry(profile_id="s1", name="A"))
        tmp_store.set_active_profile_ids(["s1"])
        assert tmp_store.find_inactive_profile_id() is None

    def test_returns_inactive(self, tmp_store):
        tmp_store.save_profile(ProfileEntry(profile_id="s1", name="A"))
        tmp_store.save_profile(ProfileEntry(profile_id="s2", name="B"))
        tmp_store.set_active_profile_ids(["s1"])
        assert tmp_store.find_inactive_profile_id() == "s2"

    def test_none_active_returns_first(self, tmp_store):
        tmp_store.save_profile(ProfileEntry(profile_id="s1", name="A"))
        assert tmp_store.find_inactive_profile_id() == "s1"


class TestProfileStoreFileIntegrity:
    def test_corrupted_file_returns_defaults(self, tmp_path):
        path = str(tmp_path / "profiles.json")
        with open(path, "w") as f:
            f.write("not valid json")
        store = ProfileStore(path=path)
        assert store.list_profiles() == []

    def test_file_created_on_first_save(self, tmp_path):
        path = str(tmp_path / "new" / "profiles.json")
        store = ProfileStore(path=path)
        store.save_profile(ProfileEntry(profile_id="first", name="First"))
        assert os.path.exists(path)


class TestBookmarkStore:
    def test_empty(self, tmp_bm_store):
        assert tmp_bm_store.list_bookmarks() == []
        assert tmp_bm_store.get_bookmark("x") is None

    def test_save_and_get(self, tmp_bm_store):
        query = QueryState(database_name="bm_db", search_params={"sort_by": "path"})
        bm = BookmarkEntry(bookmark_id="b1", name="MyMark", query=query)
        tmp_bm_store.save_bookmark(bm)

        loaded = tmp_bm_store.get_bookmark("b1")
        assert loaded is not None
        assert loaded.name == "MyMark"
        assert loaded.query.database_name == "bm_db"

    def test_list_bookmarks(self, tmp_bm_store):
        tmp_bm_store.save_bookmark(BookmarkEntry(bookmark_id="b1", name="A"))
        tmp_bm_store.save_bookmark(BookmarkEntry(bookmark_id="b2", name="B"))
        result = tmp_bm_store.list_bookmarks()
        assert len(result) == 2
        names = {e.name for e in result}
        assert names == {"A", "B"}

    def test_delete_bookmark(self, tmp_bm_store):
        tmp_bm_store.save_bookmark(BookmarkEntry(bookmark_id="bd", name="Del"))
        assert tmp_bm_store.delete_bookmark("bd")
        assert tmp_bm_store.get_bookmark("bd") is None
        assert not tmp_bm_store.delete_bookmark("bd")

    def test_overwrite(self, tmp_bm_store):
        bm = BookmarkEntry(bookmark_id="b1", name="Old")
        tmp_bm_store.save_bookmark(bm)
        bm.name = "New"
        bm.query.database_name = "updated"
        tmp_bm_store.save_bookmark(bm)
        loaded = tmp_bm_store.get_bookmark("b1")
        assert loaded.name == "New"
        assert loaded.query.database_name == "updated"
        assert len(tmp_bm_store.list_bookmarks()) == 1

    def test_individual_files(self, tmp_bm_store):
        tmp_bm_store.save_bookmark(BookmarkEntry(bookmark_id="x1", name="First"))
        tmp_bm_store.save_bookmark(BookmarkEntry(bookmark_id="x2", name="Second"))
        from pathlib import Path

        base = Path(tmp_bm_store._base)
        files = list(base.glob("*.json"))
        assert len(files) == 2
        assert {f.stem for f in files} == {"x1", "x2"}

    def test_dir_created_on_first_save(self, tmp_path):
        d = str(tmp_path / "deep" / "bookmark")
        store = BookmarkStore(base_dir=d)
        store.save_bookmark(BookmarkEntry(bookmark_id="first"))
        assert os.path.isdir(d)

    def test_entry_path_rejects_traversal(self, tmp_bm_store):
        with pytest.raises(ValueError):
            tmp_bm_store._entry_path("../../etc/passwd")

    def test_entry_path_rejects_empty(self, tmp_bm_store):
        with pytest.raises(ValueError):
            tmp_bm_store._entry_path("")

    def test_entry_path_accepts_valid_hex(self, tmp_bm_store):
        p = tmp_bm_store._entry_path("abc123def456")
        assert p.name == "abc123def456.json"


class TestCreateProfile:
    def test_creates_with_name(self, tmp_store):
        sid = tmp_store.create_profile("Work")
        entry = tmp_store.get_profile(sid)
        assert entry is not None
        assert entry.name == "Work"

    def test_returns_unique_ids(self, tmp_store):
        sid1 = tmp_store.create_profile("A")
        sid2 = tmp_store.create_profile("B")
        assert sid1 != sid2

    def test_appears_in_list_sessions(self, tmp_store):
        tmp_store.create_profile("Visible")
        assert any(e.name == "Visible" for e in tmp_store.list_profiles())

    def test_create_with_color(self, tmp_store):
        sid = tmp_store.create_profile("WithColor", color="#1ABC9C")
        entry = tmp_store.get_profile(sid)
        assert entry.color == "#1ABC9C"

    def test_duplicate_name_returns_none(self, tmp_store):
        tmp_store.create_profile("Dup")
        assert tmp_store.create_profile("Dup") is None

    def test_duplicate_name_does_not_add_session(self, tmp_store):
        tmp_store.create_profile("Only")
        tmp_store.create_profile("Only")
        assert len(tmp_store.list_profiles()) == 1

    def test_different_names_allowed(self, tmp_store):
        assert tmp_store.create_profile("Alpha") is not None
        assert tmp_store.create_profile("Beta") is not None
        assert len(tmp_store.list_profiles()) == 2


class TestRenameProfile:
    def test_rename(self, tmp_store):
        sid = tmp_store.create_profile("Old")
        assert tmp_store.rename_profile(sid, "New")
        assert tmp_store.get_profile(sid).name == "New"

    def test_rename_updates_timestamp(self, tmp_store):
        sid = tmp_store.create_profile("X")
        old_ts = tmp_store.get_profile(sid).updated_at
        import time

        time.sleep(0.01)
        tmp_store.rename_profile(sid, "Y")
        assert tmp_store.get_profile(sid).updated_at >= old_ts

    def test_rename_nonexistent_returns_false(self, tmp_store):
        assert tmp_store.rename_profile("no-such-id", "Name") is False

    def test_rename_duplicate_returns_false(self, tmp_store):
        tmp_store.create_profile("Taken")
        sid = tmp_store.create_profile("Mine")
        assert tmp_store.rename_profile(sid, "Taken") is False
        assert tmp_store.get_profile(sid).name == "Mine"

    def test_rename_to_own_name_succeeds(self, tmp_store):
        sid = tmp_store.create_profile("Same")
        assert tmp_store.rename_profile(sid, "Same") is True


class TestProfileColors:
    def test_session_colors_defined(self):
        assert len(PROFILE_COLORS) >= 4
        for c in PROFILE_COLORS:
            assert c.startswith("#")

    def test_color_roundtrip(self):
        e = ProfileEntry(profile_id="c1", color="#D94A4A")
        restored = ProfileEntry.from_dict(e.to_dict())
        assert restored.color == "#D94A4A"

    def test_color_empty_by_default(self):
        e = ProfileEntry()
        assert e.color == ""

    def test_from_dict_missing_color_defaults_empty(self):
        restored = ProfileEntry.from_dict({"session_id": "old"})
        assert restored.color == ""


class TestSetProfileColor:
    def test_set_color(self, tmp_store):
        sid = tmp_store.create_profile("Colored")
        assert tmp_store.set_profile_color(sid, "#4A90D9")
        assert tmp_store.get_profile(sid).color == "#4A90D9"

    def test_clear_color(self, tmp_store):
        sid = tmp_store.create_profile("Cls", color="#D94A4A")
        assert tmp_store.set_profile_color(sid, "")
        assert tmp_store.get_profile(sid).color == ""

    def test_nonexistent_returns_false(self, tmp_store):
        assert tmp_store.set_profile_color("no-such", "#000") is False


class TestHasProfileName:
    def test_empty_store(self, tmp_store):
        assert tmp_store.has_profile_name("any") is False

    def test_existing_name(self, tmp_store):
        tmp_store.create_profile("Exists")
        assert tmp_store.has_profile_name("Exists") is True

    def test_missing_name(self, tmp_store):
        tmp_store.create_profile("Other")
        assert tmp_store.has_profile_name("Missing") is False


class TestFindProfileByName:
    def test_empty_store(self, tmp_store):
        assert tmp_store.find_profile_by_name("any") is None

    def test_found(self, tmp_store):
        sid = tmp_store.create_profile("Target")
        found = tmp_store.find_profile_by_name("Target")
        assert found is not None
        assert found.profile_id == sid

    def test_not_found(self, tmp_store):
        tmp_store.create_profile("Other")
        assert tmp_store.find_profile_by_name("Missing") is None


class TestCreateProfileWithUniqueName:
    def test_no_conflict(self, tmp_store):
        sid = tmp_store.create_profile_with_unique_name("Fresh")
        entry = tmp_store.get_profile(sid)
        assert entry.name == "Fresh"

    def test_conflict_appends_suffix(self, tmp_store):
        tmp_store.create_profile("Dup")
        sid = tmp_store.create_profile_with_unique_name("Dup")
        entry = tmp_store.get_profile(sid)
        assert entry.name == "Dup (1)"

    def test_conflict_increments_suffix(self, tmp_store):
        tmp_store.create_profile("Dup")
        tmp_store.create_profile_with_unique_name("Dup")
        sid = tmp_store.create_profile_with_unique_name("Dup")
        entry = tmp_store.get_profile(sid)
        assert entry.name == "Dup (2)"

    def test_with_color(self, tmp_store):
        sid = tmp_store.create_profile_with_unique_name("Colored", color="#FF0000")
        assert tmp_store.get_profile(sid).color == "#FF0000"

    def test_empty_base_name_uses_default(self, tmp_store):
        sid = tmp_store.create_profile_with_unique_name()
        entry = tmp_store.get_profile(sid)
        assert entry.name == f"{DEFAULT_PROFILE_NAME}1"

    def test_empty_base_name_conflict_appends_suffix(self, tmp_store):
        default = f"{DEFAULT_PROFILE_NAME}1"
        tmp_store.create_profile(default)
        sid = tmp_store.create_profile_with_unique_name()
        entry = tmp_store.get_profile(sid)
        assert entry.name == f"{default} (1)"


class TestAcquireOrCreate:
    def test_with_existing_session_id(self, tmp_store):
        tmp_store.save_profile(ProfileEntry(profile_id="s1", name="Existing"))
        sid, entry = tmp_store.acquire_or_create(profile_id="s1")
        assert sid == "s1"
        assert entry.name == "Existing"
        assert "s1" in tmp_store.get_active_profile_ids()

    def test_claims_inactive_when_no_id(self, tmp_store):
        tmp_store.save_profile(ProfileEntry(profile_id="s1", name="A"))
        sid, entry = tmp_store.acquire_or_create()
        assert sid == "s1"
        assert "s1" in tmp_store.get_active_profile_ids()

    def test_creates_new_when_all_active(self, tmp_store):
        tmp_store.save_profile(ProfileEntry(profile_id="s1", name="A"))
        tmp_store.set_active_profile_ids(["s1"])
        sid, entry = tmp_store.acquire_or_create()
        assert sid != "s1"
        assert entry.name == f"{DEFAULT_PROFILE_NAME}1"
        assert sid in tmp_store.get_active_profile_ids()

    def test_creates_default_name_on_empty_store(self, tmp_store):
        sid, entry = tmp_store.acquire_or_create()
        assert entry.name == DEFAULT_PROFILE_NAME
        assert sid in tmp_store.get_active_profile_ids()
        assert tmp_store.get_profile(sid) is not None

    def test_does_not_double_claim(self, tmp_store):
        tmp_store.save_profile(ProfileEntry(profile_id="s1", name="A"))
        tmp_store.set_active_profile_ids(["s1"])
        tmp_store.acquire_or_create(profile_id="s1")
        active = tmp_store.get_active_profile_ids()
        assert active.count("s1") == 1

    def test_single_file_operation(self, tmp_store):
        sid, entry = tmp_store.acquire_or_create()
        loaded = tmp_store.get_profile(sid)
        assert loaded is not None
        assert loaded.name == entry.name

    def test_many_collisions(self, tmp_store):
        tmp_store.create_profile("X")
        for i in range(1, 6):
            tmp_store.create_profile(f"X ({i})")
        sid = tmp_store.create_profile_with_unique_name("X")
        assert tmp_store.get_profile(sid).name == "X (6)"


class TestProfileStoreInstance:
    def test_singleton(self):
        old = ProfileStore._instance
        try:
            ProfileStore._instance = None
            a = ProfileStore.instance()
            b = ProfileStore.instance()
            assert a is b
        finally:
            ProfileStore._instance = old

    def test_separate_from_constructor(self):
        old = ProfileStore._instance
        try:
            ProfileStore._instance = None
            inst = ProfileStore.instance()
            fresh = ProfileStore()
            assert fresh is not inst
        finally:
            ProfileStore._instance = old


class TestBookmarkStoreInstance:
    def test_singleton(self):
        old = BookmarkStore._instance
        try:
            BookmarkStore._instance = None
            a = BookmarkStore.instance()
            b = BookmarkStore.instance()
            assert a is b
        finally:
            BookmarkStore._instance = old
