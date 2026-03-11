from wafer.app.viewer.session import (
    QueryState, UIState, SessionEntry, BookmarkEntry,
    SessionStore, BookmarkStore,
)


class TestQueryStateRoundtrip:

    def test_empty_state(self):
        qs = QueryState()
        restored = QueryState.from_dict(qs.to_dict())
        assert restored.database_name == ''
        assert restored.search_params == {}
        assert restored.folder_state == {}

    def test_full_state(self):
        qs = QueryState(
            database_name='test.db',
            search_params={
                'keywords': 'sunset,mountain',
                'sort_by': 'modified',
                'ascending': False,
                'query_mode': 'GLOB',
                'keyword_mode': 'AND',
                'keyword_separator': ',',
                'include_subfolders': True,
                'auto_execute': True,
            },
            folder_state={'expanded': ['/photos', '/art'], 'selected': '/photos'},
        )
        restored = QueryState.from_dict(qs.to_dict())
        assert restored.database_name == 'test.db'
        assert restored.search_params['keywords'] == 'sunset,mountain'
        assert restored.search_params['sort_by'] == 'modified'
        assert restored.search_params['ascending'] is False
        assert restored.search_params['keyword_mode'] == 'AND'
        assert restored.folder_state['expanded'] == ['/photos', '/art']

    def test_nested_dict_values(self):
        qs = QueryState(
            search_params={'nested': {'a': 1, 'b': [2, 3]}},
        )
        restored = QueryState.from_dict(qs.to_dict())
        assert restored.search_params['nested'] == {'a': 1, 'b': [2, 3]}


class TestUIStateRoundtrip:

    def test_empty_state(self):
        ui = UIState()
        restored = UIState.from_dict(ui.to_dict())
        assert restored.window_geometry == ''
        assert restored.splitter_sizes == []
        assert restored.scroll_index is None
        assert restored.grid_settings == {}

    def test_full_state(self):
        ui = UIState(
            window_geometry='base64geometry==',
            splitter_sizes=[300, 700],
            scroll_index=42,
            grid_settings={'base_height': 200, 'spacing': 4, 'layout_mode': 'justified'},
        )
        restored = UIState.from_dict(ui.to_dict())
        assert restored.window_geometry == 'base64geometry=='
        assert restored.splitter_sizes == [300, 700]
        assert restored.scroll_index == 42
        assert restored.grid_settings['base_height'] == 200
        assert restored.grid_settings['layout_mode'] == 'justified'


class TestSessionEntryRoundtrip:

    def test_minimal_entry(self):
        entry = SessionEntry(session_id='abc123', name='Test Session')
        restored = SessionEntry.from_dict(entry.to_dict())
        assert restored.session_id == 'abc123'
        assert restored.name == 'Test Session'
        assert restored.query_snapshot is None

    def test_full_entry_with_query_snapshot(self):
        qs = QueryState(
            database_name='main.db',
            search_params={'keywords': 'test', 'sort_by': 'name'},
            folder_state={'selected': '/images'},
        )
        ui = UIState(
            window_geometry='geom',
            splitter_sizes=[250, 750],
            scroll_index=10,
            grid_settings={'base_height': 180},
        )
        entry = SessionEntry(
            session_id='sess001',
            name='My Session',
            color='#4A90D9',
            ui=ui,
            bookmark_id='bm001',
            query_snapshot=qs,
        )
        d = entry.to_dict()
        restored = SessionEntry.from_dict(d)
        assert restored.session_id == 'sess001'
        assert restored.name == 'My Session'
        assert restored.color == '#4A90D9'
        assert restored.bookmark_id == 'bm001'
        assert restored.ui.splitter_sizes == [250, 750]
        assert restored.ui.scroll_index == 10
        assert restored.query_snapshot is not None
        assert restored.query_snapshot.database_name == 'main.db'
        assert restored.query_snapshot.search_params['keywords'] == 'test'

    def test_entry_without_query_snapshot_key(self):
        d = {
            'session_id': 'x',
            'name': 'test',
            'ui': {},
        }
        restored = SessionEntry.from_dict(d)
        assert restored.query_snapshot is None

    def test_invalid_data_returns_default(self):
        restored = SessionEntry.from_dict("not a dict")
        assert restored.name == ''


class TestBookmarkRoundtrip:

    def test_bookmark_entry(self):
        qs = QueryState(
            database_name='db1',
            search_params={'keywords': 'landscape', 'sort_by': 'created'},
        )
        bm = BookmarkEntry(
            bookmark_id='bm123',
            name='Landscapes',
            query=qs,
        )
        d = bm.to_dict()
        restored = BookmarkEntry.from_dict(d)
        assert restored.bookmark_id == 'bm123'
        assert restored.name == 'Landscapes'
        assert restored.query.database_name == 'db1'
        assert restored.query.search_params['keywords'] == 'landscape'


class TestSessionStoreRoundtrip:

    def test_create_save_and_load(self, tmp_path):
        store = SessionStore(str(tmp_path / 'sessions.json'))
        sid = store.create_session('Session A', '#4A90D9')
        assert sid is not None

        entry = store.get_session(sid)
        assert entry.name == 'Session A'
        assert entry.color == '#4A90D9'

        qs = QueryState(
            database_name='test.db',
            search_params={'keywords': 'sunset', 'sort_by': 'modified'},
        )
        entry.query_snapshot = qs
        entry.ui = UIState(splitter_sizes=[300, 700], scroll_index=5)
        store.save_session(entry)

        loaded = store.get_session(sid)
        assert loaded.query_snapshot is not None
        assert loaded.query_snapshot.database_name == 'test.db'
        assert loaded.query_snapshot.search_params['keywords'] == 'sunset'
        assert loaded.ui.splitter_sizes == [300, 700]
        assert loaded.ui.scroll_index == 5

    def test_multiple_sessions_isolation(self, tmp_path):
        store = SessionStore(str(tmp_path / 'sessions.json'))
        sid_a = store.create_session('Session A')
        sid_b = store.create_session('Session B')
        assert sid_a != sid_b

        entry_a = store.get_session(sid_a)
        entry_a.query_snapshot = QueryState(search_params={'keywords': 'alpha'})
        store.save_session(entry_a)

        entry_b = store.get_session(sid_b)
        entry_b.query_snapshot = QueryState(search_params={'keywords': 'beta'})
        store.save_session(entry_b)

        a = store.get_session(sid_a)
        b = store.get_session(sid_b)
        assert a.query_snapshot.search_params['keywords'] == 'alpha'
        assert b.query_snapshot.search_params['keywords'] == 'beta'

    def test_session_with_all_search_params(self, tmp_path):
        store = SessionStore(str(tmp_path / 'sessions.json'))
        sid = store.create_session('Full Params')

        full_params = {
            'keywords': 'sunset,ocean',
            'query_mode': 'GLOB',
            'keyword_mode': 'AND',
            'sort_by': 'created',
            'ascending': False,
            'keyword_separator': ',',
            'include_subfolders': False,
            'auto_execute': True,
        }
        entry = store.get_session(sid)
        entry.query_snapshot = QueryState(
            database_name='full_test.db',
            search_params=full_params,
            folder_state={'expanded': ['/a', '/b'], 'selected': '/a'},
        )
        entry.ui = UIState(
            window_geometry='geo_data',
            splitter_sizes=[200, 400, 400],
            scroll_index=99,
            grid_settings={'base_height': 250, 'spacing': 8},
        )
        store.save_session(entry)

        restored = store.get_session(sid)
        assert restored.query_snapshot.search_params == full_params
        assert restored.query_snapshot.folder_state['expanded'] == ['/a', '/b']
        assert restored.ui.grid_settings['base_height'] == 250

    def test_delete_session_removes_data(self, tmp_path):
        store = SessionStore(str(tmp_path / 'sessions.json'))
        sid = store.create_session('Temporary')
        assert store.get_session(sid) is not None

        store.delete_session(sid)
        assert store.get_session(sid) is None

    def test_active_session_tracking(self, tmp_path):
        store = SessionStore(str(tmp_path / 'sessions.json'))
        sid = store.create_session('Active Test')

        assert store.claim_session(sid) is True
        assert sid in store.get_active_session_ids()

        assert store.claim_session(sid) is False

    def test_restore_session_ids(self, tmp_path):
        store = SessionStore(str(tmp_path / 'sessions.json'))
        sid1 = store.create_session('S1')
        sid2 = store.create_session('S2')

        store.set_restore_session_ids([sid1, sid2])
        restored = store.get_restore_session_ids()
        assert sid1 in restored
        assert sid2 in restored

    def test_find_inactive_session(self, tmp_path):
        store = SessionStore(str(tmp_path / 'sessions.json'))
        sid = store.create_session('Inactive')
        assert store.find_inactive_session_id() == sid

        store.claim_session(sid)
        assert store.find_inactive_session_id() is None

    def test_session_rename(self, tmp_path):
        store = SessionStore(str(tmp_path / 'sessions.json'))
        sid = store.create_session('Original')
        assert store.rename_session(sid, 'Renamed') is True
        assert store.get_session(sid).name == 'Renamed'

    def test_duplicate_name_rejected(self, tmp_path):
        store = SessionStore(str(tmp_path / 'sessions.json'))
        store.create_session('Taken')
        assert store.create_session('Taken') is None


class TestBookmarkStoreRoundtrip:

    def test_save_and_load_bookmark(self, tmp_path):
        bm_store = BookmarkStore(str(tmp_path / 'bookmarks'))
        qs = QueryState(
            database_name='test.db',
            search_params={'keywords': 'forest', 'sort_by': 'name'},
        )
        bm = BookmarkEntry(bookmark_id='bm001', name='Forest Search', query=qs)
        bm_store.save_bookmark(bm)

        loaded = bm_store.get_bookmark('bm001')
        assert loaded is not None
        assert loaded.name == 'Forest Search'
        assert loaded.query.search_params['keywords'] == 'forest'

    def test_list_bookmarks(self, tmp_path):
        bm_store = BookmarkStore(str(tmp_path / 'bookmarks'))
        for i in range(3):
            bm = BookmarkEntry(
                bookmark_id=f'bm{i:03d}',
                name=f'Bookmark {i}',
                query=QueryState(search_params={'idx': str(i)}),
            )
            bm_store.save_bookmark(bm)

        bookmarks = bm_store.list_bookmarks()
        assert len(bookmarks) == 3
        names = {b.name for b in bookmarks}
        assert names == {'Bookmark 0', 'Bookmark 1', 'Bookmark 2'}

    def test_delete_bookmark(self, tmp_path):
        bm_store = BookmarkStore(str(tmp_path / 'bookmarks'))
        bm = BookmarkEntry(bookmark_id='del001', name='ToDelete', query=QueryState())
        bm_store.save_bookmark(bm)
        assert bm_store.get_bookmark('del001') is not None

        assert bm_store.delete_bookmark('del001') is True
        assert bm_store.get_bookmark('del001') is None
        assert bm_store.delete_bookmark('del001') is False

    def test_bookmark_query_state_preserved(self, tmp_path):
        bm_store = BookmarkStore(str(tmp_path / 'bookmarks'))
        params = {
            'keywords': 'test,query',
            'sort_by': 'modified',
            'ascending': False,
            'keyword_mode': 'OR',
        }
        qs = QueryState(
            database_name='bm_db',
            search_params=params,
            folder_state={'selected': '/root'},
        )
        bm = BookmarkEntry(bookmark_id='preserve01', name='Preserved', query=qs)
        bm_store.save_bookmark(bm)

        loaded = bm_store.get_bookmark('preserve01')
        assert loaded.query.database_name == 'bm_db'
        assert loaded.query.search_params == params
        assert loaded.query.folder_state['selected'] == '/root'
