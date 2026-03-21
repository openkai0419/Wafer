import json
import os
import pytest

from wafer.app.viewer.session import (
    QueryState,
    UIState,
    BookmarkEntry,
    SessionEntry,
    SessionStore,
    BookmarkStore,
    SESSION_COLORS,
)
from wafer.constants import DEFAULT_SESSION_NAME


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
        assert u.window_state == {}
        assert u.component_states == {}

    def test_roundtrip(self):
        u = UIState(
            window_state={'geometry': 'abc123==', 'always_on_top': False},
            component_states={
                'main_splitter': {'sizes': [100, 500, 200]},
                'grid': {'zoom': 150, 'orientation': 1, 'layout_mode': 'masonry'},
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
        assert e.color == ''
        assert isinstance(e.ui, UIState)
        assert e.bookmark_id == ''
        assert e.query_snapshot is None

    def test_roundtrip_with_snapshot(self):
        ui = UIState(component_states={'main_splitter': {'sizes': [10, 80, 10]}, 'grid': {'scroll_index': 5}})
        qs = QueryState(database_name='db1', search_params={'sort_by': 'name'})
        e = SessionEntry(session_id='s1', name='Work', color='#4A90D9', ui=ui, query_snapshot=qs)
        restored = SessionEntry.from_dict(e.to_dict())
        assert restored.session_id == 's1'
        assert restored.name == 'Work'
        assert restored.color == '#4A90D9'
        assert restored.ui.component_states['main_splitter']['sizes'] == [10, 80, 10]
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

    def test_from_dict_ignores_legacy_anonymous_field(self):
        restored = SessionEntry.from_dict({'session_id': 'old', 'anonymous': True})
        assert restored.session_id == 'old'


class TestSessionStoreSession:

    def test_empty_store(self, tmp_store):
        assert tmp_store.list_sessions() == []
        assert tmp_store.get_session('nonexistent') is None

    def test_save_and_get(self, tmp_store):
        ui = UIState(component_states={'grid': {'scroll_index': 5}})
        qs = QueryState(database_name='mydb')
        entry = SessionEntry(session_id='s1', name='Main', ui=ui, query_snapshot=qs)
        tmp_store.save_session(entry)

        loaded = tmp_store.get_session('s1')
        assert loaded is not None
        assert loaded.name == 'Main'
        assert loaded.ui.component_states['grid']['scroll_index'] == 5
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

    def test_delete_removes_from_restore(self, tmp_store):
        tmp_store.save_session(SessionEntry(session_id='r1'))
        tmp_store.save_session(SessionEntry(session_id='r2'))
        tmp_store.set_restore_session_ids(['r1', 'r2'])
        tmp_store.delete_session('r1')
        assert tmp_store.get_restore_session_ids() == ['r2']

    def test_overwrite_session(self, tmp_store):
        entry = SessionEntry(session_id='s1', name='Old')
        tmp_store.save_session(entry)
        entry.name = 'New'
        entry.ui.component_states = {'main_splitter': {'sizes': [1, 2, 3]}}
        tmp_store.save_session(entry)

        loaded = tmp_store.get_session('s1')
        assert loaded.name == 'New'
        assert loaded.ui.component_states['main_splitter']['sizes'] == [1, 2, 3]
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
        tmp_store.save_session(SessionEntry(session_id='s1', name='S1'))
        tmp_store.save_session(SessionEntry(session_id='Work', name='Work'))
        tmp_store.set_restore_session_ids(['s1', 'Work'])
        assert tmp_store.get_restore_session_ids() == ['s1', 'Work']

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
        tmp_store.save_session(SessionEntry(session_id='s1', name='S1'))
        tmp_store.set_restore_session_ids(['s1', 'deleted'])
        assert tmp_store.get_restore_session_ids() == ['s1']

    def test_all_missing_returns_empty(self, tmp_store):
        tmp_store.set_restore_session_ids(['gone-1', 'gone-2'])
        assert tmp_store.get_restore_session_ids() == []


class TestNextDefaultName:

    def test_first_default(self, tmp_store):
        assert tmp_store.next_default_name() == f'{DEFAULT_SESSION_NAME}1'

    def test_second_default(self, tmp_store):
        tmp_store.create_session(f'{DEFAULT_SESSION_NAME}1')
        assert tmp_store.next_default_name() == f'{DEFAULT_SESSION_NAME}2'

    def test_fills_gap(self, tmp_store):
        tmp_store.create_session(f'{DEFAULT_SESSION_NAME}1')
        tmp_store.create_session(f'{DEFAULT_SESSION_NAME}2')
        tmp_store.create_session(f'{DEFAULT_SESSION_NAME}4')
        assert tmp_store.next_default_name() == f'{DEFAULT_SESSION_NAME}3'

    def test_next_after_all_used(self, tmp_store):
        tmp_store.create_session(f'{DEFAULT_SESSION_NAME}1')
        tmp_store.create_session(f'{DEFAULT_SESSION_NAME}2')
        tmp_store.create_session(f'{DEFAULT_SESSION_NAME}3')
        assert tmp_store.next_default_name() == f'{DEFAULT_SESSION_NAME}4'


class TestFindInactiveSession:

    def test_empty_store_returns_none(self, tmp_store):
        assert tmp_store.find_inactive_session_id() is None

    def test_all_active_returns_none(self, tmp_store):
        tmp_store.save_session(SessionEntry(session_id='s1', name='A'))
        tmp_store.set_active_session_ids(['s1'])
        assert tmp_store.find_inactive_session_id() is None

    def test_returns_inactive(self, tmp_store):
        tmp_store.save_session(SessionEntry(session_id='s1', name='A'))
        tmp_store.save_session(SessionEntry(session_id='s2', name='B'))
        tmp_store.set_active_session_ids(['s1'])
        assert tmp_store.find_inactive_session_id() == 's2'

    def test_none_active_returns_first(self, tmp_store):
        tmp_store.save_session(SessionEntry(session_id='s1', name='A'))
        assert tmp_store.find_inactive_session_id() == 's1'


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
        store.save_session(SessionEntry(session_id='first', name='First'))
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

    def test_entry_path_rejects_traversal(self, tmp_bm_store):
        with pytest.raises(ValueError):
            tmp_bm_store._entry_path('../../etc/passwd')

    def test_entry_path_rejects_empty(self, tmp_bm_store):
        with pytest.raises(ValueError):
            tmp_bm_store._entry_path('')

    def test_entry_path_accepts_valid_hex(self, tmp_bm_store):
        p = tmp_bm_store._entry_path('abc123def456')
        assert p.name == 'abc123def456.json'


class TestCreateSession:

    def test_creates_with_name(self, tmp_store):
        sid = tmp_store.create_session('Work')
        entry = tmp_store.get_session(sid)
        assert entry is not None
        assert entry.name == 'Work'

    def test_returns_unique_ids(self, tmp_store):
        sid1 = tmp_store.create_session('A')
        sid2 = tmp_store.create_session('B')
        assert sid1 != sid2

    def test_appears_in_list_sessions(self, tmp_store):
        tmp_store.create_session('Visible')
        assert any(e.name == 'Visible' for e in tmp_store.list_sessions())

    def test_create_with_color(self, tmp_store):
        sid = tmp_store.create_session('WithColor', color='#1ABC9C')
        entry = tmp_store.get_session(sid)
        assert entry.color == '#1ABC9C'

    def test_duplicate_name_returns_none(self, tmp_store):
        tmp_store.create_session('Dup')
        assert tmp_store.create_session('Dup') is None

    def test_duplicate_name_does_not_add_session(self, tmp_store):
        tmp_store.create_session('Only')
        tmp_store.create_session('Only')
        assert len(tmp_store.list_sessions()) == 1

    def test_different_names_allowed(self, tmp_store):
        assert tmp_store.create_session('Alpha') is not None
        assert tmp_store.create_session('Beta') is not None
        assert len(tmp_store.list_sessions()) == 2


class TestRenameSession:

    def test_rename(self, tmp_store):
        sid = tmp_store.create_session('Old')
        assert tmp_store.rename_session(sid, 'New')
        assert tmp_store.get_session(sid).name == 'New'

    def test_rename_updates_timestamp(self, tmp_store):
        sid = tmp_store.create_session('X')
        old_ts = tmp_store.get_session(sid).updated_at
        import time; time.sleep(0.01)
        tmp_store.rename_session(sid, 'Y')
        assert tmp_store.get_session(sid).updated_at >= old_ts

    def test_rename_nonexistent_returns_false(self, tmp_store):
        assert tmp_store.rename_session('no-such-id', 'Name') is False

    def test_rename_duplicate_returns_false(self, tmp_store):
        tmp_store.create_session('Taken')
        sid = tmp_store.create_session('Mine')
        assert tmp_store.rename_session(sid, 'Taken') is False
        assert tmp_store.get_session(sid).name == 'Mine'

    def test_rename_to_own_name_succeeds(self, tmp_store):
        sid = tmp_store.create_session('Same')
        assert tmp_store.rename_session(sid, 'Same') is True


class TestSessionColors:

    def test_session_colors_defined(self):
        assert len(SESSION_COLORS) >= 4
        for c in SESSION_COLORS:
            assert c.startswith('#')

    def test_color_roundtrip(self):
        e = SessionEntry(session_id='c1', color='#D94A4A')
        restored = SessionEntry.from_dict(e.to_dict())
        assert restored.color == '#D94A4A'

    def test_color_empty_by_default(self):
        e = SessionEntry()
        assert e.color == ''

    def test_from_dict_missing_color_defaults_empty(self):
        restored = SessionEntry.from_dict({'session_id': 'old'})
        assert restored.color == ''


class TestSetSessionColor:

    def test_set_color(self, tmp_store):
        sid = tmp_store.create_session('Colored')
        assert tmp_store.set_session_color(sid, '#4A90D9')
        assert tmp_store.get_session(sid).color == '#4A90D9'

    def test_clear_color(self, tmp_store):
        sid = tmp_store.create_session('Cls', color='#D94A4A')
        assert tmp_store.set_session_color(sid, '')
        assert tmp_store.get_session(sid).color == ''

    def test_nonexistent_returns_false(self, tmp_store):
        assert tmp_store.set_session_color('no-such', '#000') is False


class TestClaimSession:

    def test_claim_new_returns_true(self, tmp_store):
        assert tmp_store.claim_session('s1') is True
        assert 's1' in tmp_store.get_active_session_ids()

    def test_claim_already_active_returns_false(self, tmp_store):
        tmp_store.set_active_session_ids(['s1'])
        assert tmp_store.claim_session('s1') is False

    def test_claim_twice_returns_false_second_time(self, tmp_store):
        assert tmp_store.claim_session('s1') is True
        assert tmp_store.claim_session('s1') is False

    def test_claim_different_ids(self, tmp_store):
        assert tmp_store.claim_session('s1') is True
        assert tmp_store.claim_session('s2') is True
        active = tmp_store.get_active_session_ids()
        assert 's1' in active
        assert 's2' in active


class TestHasSessionName:

    def test_empty_store(self, tmp_store):
        assert tmp_store.has_session_name('any') is False

    def test_existing_name(self, tmp_store):
        tmp_store.create_session('Exists')
        assert tmp_store.has_session_name('Exists') is True

    def test_missing_name(self, tmp_store):
        tmp_store.create_session('Other')
        assert tmp_store.has_session_name('Missing') is False


class TestFindSessionByName:

    def test_empty_store(self, tmp_store):
        assert tmp_store.find_session_by_name('any') is None

    def test_found(self, tmp_store):
        sid = tmp_store.create_session('Target')
        found = tmp_store.find_session_by_name('Target')
        assert found is not None
        assert found.session_id == sid

    def test_not_found(self, tmp_store):
        tmp_store.create_session('Other')
        assert tmp_store.find_session_by_name('Missing') is None


class TestCreateSessionWithUniqueName:

    def test_no_conflict(self, tmp_store):
        sid = tmp_store.create_session_with_unique_name('Fresh')
        entry = tmp_store.get_session(sid)
        assert entry.name == 'Fresh'

    def test_conflict_appends_suffix(self, tmp_store):
        tmp_store.create_session('Dup')
        sid = tmp_store.create_session_with_unique_name('Dup')
        entry = tmp_store.get_session(sid)
        assert entry.name == 'Dup (1)'

    def test_conflict_increments_suffix(self, tmp_store):
        tmp_store.create_session('Dup')
        tmp_store.create_session_with_unique_name('Dup')
        sid = tmp_store.create_session_with_unique_name('Dup')
        entry = tmp_store.get_session(sid)
        assert entry.name == 'Dup (2)'

    def test_with_color(self, tmp_store):
        sid = tmp_store.create_session_with_unique_name('Colored', color='#FF0000')
        assert tmp_store.get_session(sid).color == '#FF0000'

    def test_empty_base_name_uses_default(self, tmp_store):
        sid = tmp_store.create_session_with_unique_name()
        entry = tmp_store.get_session(sid)
        assert entry.name == f'{DEFAULT_SESSION_NAME}1'


class TestAcquireOrCreate:

    def test_with_existing_session_id(self, tmp_store):
        tmp_store.save_session(SessionEntry(session_id='s1', name='Existing'))
        sid, entry = tmp_store.acquire_or_create(session_id='s1')
        assert sid == 's1'
        assert entry.name == 'Existing'
        assert 's1' in tmp_store.get_active_session_ids()

    def test_claims_inactive_when_no_id(self, tmp_store):
        tmp_store.save_session(SessionEntry(session_id='s1', name='A'))
        sid, entry = tmp_store.acquire_or_create()
        assert sid == 's1'
        assert 's1' in tmp_store.get_active_session_ids()

    def test_creates_new_when_all_active(self, tmp_store):
        tmp_store.save_session(SessionEntry(session_id='s1', name='A'))
        tmp_store.set_active_session_ids(['s1'])
        sid, entry = tmp_store.acquire_or_create()
        assert sid != 's1'
        assert entry.name == f'{DEFAULT_SESSION_NAME}1'
        assert sid in tmp_store.get_active_session_ids()

    def test_creates_default_name_on_empty_store(self, tmp_store):
        sid, entry = tmp_store.acquire_or_create()
        assert entry.name == DEFAULT_SESSION_NAME
        assert sid in tmp_store.get_active_session_ids()
        assert tmp_store.get_session(sid) is not None

    def test_does_not_double_claim(self, tmp_store):
        tmp_store.save_session(SessionEntry(session_id='s1', name='A'))
        tmp_store.set_active_session_ids(['s1'])
        tmp_store.acquire_or_create(session_id='s1')
        active = tmp_store.get_active_session_ids()
        assert active.count('s1') == 1

    def test_single_file_operation(self, tmp_store):
        sid, entry = tmp_store.acquire_or_create()
        loaded = tmp_store.get_session(sid)
        assert loaded is not None
        assert loaded.name == entry.name

    def test_many_collisions(self, tmp_store):
        tmp_store.create_session('X')
        for i in range(1, 6):
            tmp_store.create_session(f'X ({i})')
        sid = tmp_store.create_session_with_unique_name('X')
        assert tmp_store.get_session(sid).name == 'X (6)'


class TestSessionStoreInstance:

    def test_singleton(self):
        old = SessionStore._instance
        try:
            SessionStore._instance = None
            a = SessionStore.instance()
            b = SessionStore.instance()
            assert a is b
        finally:
            SessionStore._instance = old

    def test_separate_from_constructor(self):
        old = SessionStore._instance
        try:
            SessionStore._instance = None
            inst = SessionStore.instance()
            fresh = SessionStore()
            assert fresh is not inst
        finally:
            SessionStore._instance = old


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
