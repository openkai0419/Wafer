import json
import os
import pytest

from wayfer.app.viewer.session import (
    QueryState,
    UIState,
    BookmarkEntry,
    SessionEntry,
    SessionStore,
    BookmarkStore,
)


@pytest.fixture
def tmp_store(tmp_path):
    return SessionStore(path=str(tmp_path / 'sessions.json'))


@pytest.fixture
def tmp_bm_store(tmp_path):
    return BookmarkStore(base_dir=str(tmp_path / 'bookmark'))


class TestQueryState:

    def test_defaults(self):
        q = QueryState()
        assert q.database_name == ''
        assert q.search_params == {}
        assert q.folder_state == {}

    def test_roundtrip(self):
        q = QueryState(
            database_name='mydb',
            search_params={'sort_by': 'name', 'ascending': False},
            folder_state={'expanded': ['/a', '/b'], 'selected': ['/a']},
        )
        restored = QueryState.from_dict(q.to_dict())
        assert restored == q

    def test_from_dict_ignores_unknown_keys(self):
        q = QueryState.from_dict({'database_name': 'x', 'unknown_field': 123})
        assert q.database_name == 'x'

    def test_from_dict_handles_non_dict(self):
        assert QueryState.from_dict(None) == QueryState()

    def test_json_serializable(self):
        q = QueryState(database_name='test', search_params={'k': 'v'})
        text = json.dumps(q.to_dict())
        assert QueryState.from_dict(json.loads(text)) == q


class TestUIState:

    def test_defaults(self):
        u = UIState()
        assert u.window_geometry == ''
        assert u.splitter_sizes == []
        assert u.scroll_index is None
        assert u.grid_settings == {}

    def test_roundtrip(self):
        u = UIState(
            window_geometry='abc123==',
            splitter_sizes=[100, 500, 200],
            scroll_index=42,
            grid_settings={'zoom': 150, 'orientation': 1, 'layout_mode': 'masonry'},
        )
        restored = UIState.from_dict(u.to_dict())
        assert restored == u

    def test_from_dict_handles_non_dict(self):
        assert UIState.from_dict(None) == UIState()


class TestBookmarkEntry:

    def test_defaults(self):
        b = BookmarkEntry()
        assert len(b.bookmark_id) == 12
        assert b.name == ''
        assert isinstance(b.query, QueryState)

    def test_roundtrip(self):
        query = QueryState(database_name='db2', search_params={'sort_by': 'size'})
        b = BookmarkEntry(bookmark_id='bm001', name='Favorites', query=query)
        restored = BookmarkEntry.from_dict(b.to_dict())
        assert restored.bookmark_id == 'bm001'
        assert restored.name == 'Favorites'
        assert restored.query.database_name == 'db2'
        assert restored.query.search_params == {'sort_by': 'size'}

    def test_from_dict_handles_non_dict(self):
        b = BookmarkEntry.from_dict("invalid")
        assert isinstance(b, BookmarkEntry)


class TestSessionEntry:

    def test_defaults(self):
        e = SessionEntry()
        assert len(e.session_id) == 12
        assert e.name == ''
        assert isinstance(e.ui, UIState)
        assert e.bookmark_id == ''
        assert e.query_snapshot is None

    def test_roundtrip_with_snapshot(self):
        ui = UIState(splitter_sizes=[10, 80, 10], scroll_index=5)
        qs = QueryState(database_name='db1', search_params={'sort_by': 'name'})
        e = SessionEntry(session_id='s1', name='Work', ui=ui, query_snapshot=qs)
        restored = SessionEntry.from_dict(e.to_dict())
        assert restored.session_id == 's1'
        assert restored.name == 'Work'
        assert restored.ui.splitter_sizes == [10, 80, 10]
        assert restored.query_snapshot.database_name == 'db1'

    def test_roundtrip_with_bookmark_ref(self):
        e = SessionEntry(session_id='s2', bookmark_id='bm001')
        restored = SessionEntry.from_dict(e.to_dict())
        assert restored.bookmark_id == 'bm001'
        assert restored.query_snapshot is None

    def test_roundtrip_without_snapshot(self):
        e = SessionEntry(session_id='s3', name='NoQuery')
        d = e.to_dict()
        assert 'query_snapshot' not in d
        restored = SessionEntry.from_dict(d)
        assert restored.query_snapshot is None

    def test_from_dict_handles_non_dict(self):
        assert isinstance(SessionEntry.from_dict("invalid"), SessionEntry)


class TestSessionStoreSession:

    def test_empty_store(self, tmp_store):
        assert tmp_store.list_sessions() == []
        assert tmp_store.get_session('nonexistent') is None

    def test_save_and_get(self, tmp_store):
        ui = UIState(scroll_index=5)
        qs = QueryState(database_name='mydb')
        entry = SessionEntry(session_id='s1', name='Main', ui=ui, query_snapshot=qs)
        tmp_store.save_session(entry)

        loaded = tmp_store.get_session('s1')
        assert loaded is not None
        assert loaded.name == 'Main'
        assert loaded.ui.scroll_index == 5
        assert loaded.query_snapshot.database_name == 'mydb'

    def test_save_updates_timestamp(self, tmp_store):
        entry = SessionEntry(session_id='s1', name='A', updated_at='old')
        tmp_store.save_session(entry)
        loaded = tmp_store.get_session('s1')
        assert loaded.updated_at != 'old'

    def test_list_sessions(self, tmp_store):
        tmp_store.save_session(SessionEntry(session_id='a', name='First'))
        tmp_store.save_session(SessionEntry(session_id='b', name='Second'))
        sessions = tmp_store.list_sessions()
        assert len(sessions) == 2
        names = {s.name for s in sessions}
        assert names == {'First', 'Second'}

    def test_delete_session(self, tmp_store):
        tmp_store.save_session(SessionEntry(session_id='del1', name='ToDelete'))
        assert tmp_store.delete_session('del1')
        assert tmp_store.get_session('del1') is None
        assert not tmp_store.delete_session('del1')

    def test_delete_removes_from_active(self, tmp_store):
        tmp_store.save_session(SessionEntry(session_id='x'))
        tmp_store.set_active_session_ids(['x', 'y'])
        tmp_store.delete_session('x')
        assert 'x' not in tmp_store.get_active_session_ids()

    def test_overwrite_session(self, tmp_store):
        entry = SessionEntry(session_id='s1', name='Old')
        tmp_store.save_session(entry)
        entry.name = 'New'
        entry.ui.splitter_sizes = [1, 2, 3]
        tmp_store.save_session(entry)

        loaded = tmp_store.get_session('s1')
        assert loaded.name == 'New'
        assert loaded.ui.splitter_sizes == [1, 2, 3]
        assert len(tmp_store.list_sessions()) == 1


class TestSessionStoreActiveIds:

    def test_default_empty(self, tmp_store):
        assert tmp_store.get_active_session_ids() == []

    def test_set_and_get(self, tmp_store):
        tmp_store.set_active_session_ids(['a', 'b', 'c'])
        assert tmp_store.get_active_session_ids() == ['a', 'b', 'c']

    def test_replace(self, tmp_store):
        tmp_store.set_active_session_ids(['a'])
        tmp_store.set_active_session_ids(['b', 'c'])
        assert tmp_store.get_active_session_ids() == ['b', 'c']


class TestSessionStoreRestoreIds:

    def test_default_empty(self, tmp_store):
        assert tmp_store.get_restore_session_ids() == []

    def test_set_and_get(self, tmp_store):
        tmp_store.save_session(SessionEntry(session_id='anon-1'))
        tmp_store.save_session(SessionEntry(session_id='Work'))
        tmp_store.set_restore_session_ids(['anon-1', 'Work'])
        assert tmp_store.get_restore_session_ids() == ['anon-1', 'Work']

    def test_replace(self, tmp_store):
        tmp_store.save_session(SessionEntry(session_id='a'))
        tmp_store.save_session(SessionEntry(session_id='b'))
        tmp_store.save_session(SessionEntry(session_id='c'))
        tmp_store.set_restore_session_ids(['a'])
        tmp_store.set_restore_session_ids(['b', 'c'])
        assert tmp_store.get_restore_session_ids() == ['b', 'c']

    def test_independent_from_active(self, tmp_store):
        tmp_store.save_session(SessionEntry(session_id='x'))
        tmp_store.save_session(SessionEntry(session_id='y'))
        tmp_store.set_active_session_ids(['x'])
        tmp_store.set_restore_session_ids(['y'])
        assert tmp_store.get_active_session_ids() == ['x']
        assert tmp_store.get_restore_session_ids() == ['y']

    def test_filters_missing_sessions(self, tmp_store):
        tmp_store.save_session(SessionEntry(session_id='anon-1'))
        tmp_store.set_restore_session_ids(['anon-1', 'deleted'])
        assert tmp_store.get_restore_session_ids() == ['anon-1']

    def test_all_missing_returns_empty(self, tmp_store):
        tmp_store.set_restore_session_ids(['gone-1', 'gone-2'])
        assert tmp_store.get_restore_session_ids() == []


class TestSessionStoreAllocateAnonId:

    def test_first_anon(self, tmp_store):
        assert tmp_store.allocate_anon_id() == 'anon-1'

    def test_fills_gap(self, tmp_store):
        tmp_store.save_session(SessionEntry(session_id='anon-1'))
        tmp_store.save_session(SessionEntry(session_id='anon-3'))
        assert tmp_store.allocate_anon_id() == 'anon-2'

    def test_next_after_all_used(self, tmp_store):
        tmp_store.save_session(SessionEntry(session_id='anon-1'))
        tmp_store.save_session(SessionEntry(session_id='anon-2'))
        assert tmp_store.allocate_anon_id() == 'anon-3'

    def test_considers_active_ids(self, tmp_store):
        tmp_store.set_active_session_ids(['anon-1'])
        assert tmp_store.allocate_anon_id() == 'anon-2'

    def test_ignores_named_sessions(self, tmp_store):
        tmp_store.save_session(SessionEntry(session_id='Work'))
        assert tmp_store.allocate_anon_id() == 'anon-1'


class TestSessionStoreFileIntegrity:

    def test_corrupted_file_returns_defaults(self, tmp_path):
        path = str(tmp_path / 'sessions.json')
        with open(path, 'w') as f:
            f.write('not valid json')
        store = SessionStore(path=path)
        assert store.list_sessions() == []

    def test_file_created_on_first_save(self, tmp_path):
        path = str(tmp_path / 'new' / 'sessions.json')
        store = SessionStore(path=path)
        store.save_session(SessionEntry(session_id='first'))
        assert os.path.exists(path)


class TestBookmarkStore:

    def test_empty(self, tmp_bm_store):
        assert tmp_bm_store.list_bookmarks() == []
        assert tmp_bm_store.get_bookmark('x') is None

    def test_save_and_get(self, tmp_bm_store):
        query = QueryState(database_name='bm_db', search_params={'sort_by': 'path'})
        bm = BookmarkEntry(bookmark_id='b1', name='MyMark', query=query)
        tmp_bm_store.save_bookmark(bm)

        loaded = tmp_bm_store.get_bookmark('b1')
        assert loaded is not None
        assert loaded.name == 'MyMark'
        assert loaded.query.database_name == 'bm_db'

    def test_list_bookmarks(self, tmp_bm_store):
        tmp_bm_store.save_bookmark(BookmarkEntry(bookmark_id='b1', name='A'))
        tmp_bm_store.save_bookmark(BookmarkEntry(bookmark_id='b2', name='B'))
        result = tmp_bm_store.list_bookmarks()
        assert len(result) == 2
        names = {e.name for e in result}
        assert names == {'A', 'B'}

    def test_delete_bookmark(self, tmp_bm_store):
        tmp_bm_store.save_bookmark(BookmarkEntry(bookmark_id='bd', name='Del'))
        assert tmp_bm_store.delete_bookmark('bd')
        assert tmp_bm_store.get_bookmark('bd') is None
        assert not tmp_bm_store.delete_bookmark('bd')

    def test_overwrite(self, tmp_bm_store):
        bm = BookmarkEntry(bookmark_id='b1', name='Old')
        tmp_bm_store.save_bookmark(bm)
        bm.name = 'New'
        bm.query.database_name = 'updated'
        tmp_bm_store.save_bookmark(bm)
        loaded = tmp_bm_store.get_bookmark('b1')
        assert loaded.name == 'New'
        assert loaded.query.database_name == 'updated'
        assert len(tmp_bm_store.list_bookmarks()) == 1

    def test_individual_files(self, tmp_bm_store):
        tmp_bm_store.save_bookmark(BookmarkEntry(bookmark_id='x1', name='First'))
        tmp_bm_store.save_bookmark(BookmarkEntry(bookmark_id='x2', name='Second'))
        from pathlib import Path
        base = Path(tmp_bm_store._base)
        files = list(base.glob('*.json'))
        assert len(files) == 2
        assert {f.stem for f in files} == {'x1', 'x2'}

    def test_dir_created_on_first_save(self, tmp_path):
        d = str(tmp_path / 'deep' / 'bookmark')
        store = BookmarkStore(base_dir=d)
        store.save_bookmark(BookmarkEntry(bookmark_id='first'))
        assert os.path.isdir(d)
