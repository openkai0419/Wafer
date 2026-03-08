import py_compile

from wafer.app.viewer.session import (
    QueryState,
    BookmarkEntry,
    BookmarkStore,
    SessionEntry,
    SessionStore,
)


def test_compile():
    py_compile.compile('wafer/app/viewer/commands/session_commands.py')


class TestBookmarkCommands:

    def test_command_class_registers(self):
        from wafer.app.viewer.commands.session_commands import BookmarkCommands
        BookmarkCommands.register()

    def test_bm_store_lazy_init(self):
        from wafer.app.viewer.commands.session_commands import _bm_store
        store = _bm_store()
        assert isinstance(store, BookmarkStore)

    def test_bookmark_save_and_list_via_store(self, tmp_path):
        store = BookmarkStore(base_dir=str(tmp_path / 'bm'))
        query = QueryState(database_name='cmd_test', search_params={'sort_by': 'path'})
        entry = BookmarkEntry(name='TestMark', query=query)
        store.save_bookmark(entry)
        loaded = store.list_bookmarks()
        assert len(loaded) == 1
        assert loaded[0].name == 'TestMark'
        assert loaded[0].query.database_name == 'cmd_test'


class TestSessionCommands:

    def test_window_commands_include_session(self):
        from wafer.app.viewer.commands.window_commands import WindowCommands
        cmds = WindowCommands.commands()
        paths = [c.path for c in cmds if hasattr(c, 'path')]
        assert 'win.new_window' in paths
        assert 'win.open_session' in paths
        assert 'win.rename_session' in paths
        assert 'win.delete_session' in paths

    def test_ss_store_lazy_init(self):
        from wafer.app.viewer.commands.session_commands import _ss_store
        store = _ss_store()
        assert isinstance(store, SessionStore)

    def test_session_create_and_list_via_store(self, tmp_path):
        store = SessionStore(path=str(tmp_path / 'sessions.json'))
        sid = store.create_session('Test')
        sessions = store.list_sessions()
        assert len(sessions) == 1
        assert sessions[0].name == 'Test'
        assert sessions[0].session_id == sid

    def test_session_rename_via_store(self, tmp_path):
        store = SessionStore(path=str(tmp_path / 'sessions.json'))
        sid = store.create_session('Old')
        assert store.rename_session(sid, 'New')
        assert store.get_session(sid).name == 'New'

    def test_session_delete_via_store(self, tmp_path):
        store = SessionStore(path=str(tmp_path / 'sessions.json'))
        sid = store.create_session('ToDel')
        assert store.delete_session(sid)
        assert store.get_session(sid) is None

    def test_alive_detection_reads_store(self, tmp_path, monkeypatch):
        store = SessionStore(path=str(tmp_path / 'sessions.json'))
        store.save_session(SessionEntry(session_id='s1'))
        store.set_active_session_ids(['s1'])
        from wafer.app.viewer.commands import session_commands
        monkeypatch.setattr(session_commands, '_session_store', store)
        alive = session_commands._get_alive_session_ids()
        assert 's1' in alive

    def test_resolve_session_by_sid(self, tmp_path):
        store = SessionStore(path=str(tmp_path / 'sessions.json'))
        sid = store.create_session('Work')
        from wafer.app.viewer.commands.session_commands import _resolve_session
        entry = _resolve_session(store, sid=sid)
        assert entry is not None
        assert entry.name == 'Work'

    def test_resolve_session_by_name(self, tmp_path):
        store = SessionStore(path=str(tmp_path / 'sessions.json'))
        store.create_session('Work')
        from wafer.app.viewer.commands.session_commands import _resolve_session
        entry = _resolve_session(store, session='Work')
        assert entry is not None
        assert entry.name == 'Work'

    def test_resolve_session_empty_returns_none(self, tmp_path):
        store = SessionStore(path=str(tmp_path / 'sessions.json'))
        from wafer.app.viewer.commands.session_commands import _resolve_session
        assert _resolve_session(store) is None

    def test_list_session_names(self, tmp_path):
        store = SessionStore(path=str(tmp_path / 'sessions.json'))
        store.create_session('Alpha')
        store.create_session('Beta')
        assert store.list_session_names() == ['Alpha', 'Beta']

    def test_find_session_by_name(self, tmp_path):
        store = SessionStore(path=str(tmp_path / 'sessions.json'))
        sid = store.create_session('Target')
        entry = store.find_session_by_name('Target')
        assert entry is not None
        assert entry.session_id == sid

    def test_find_session_by_name_not_found(self, tmp_path):
        store = SessionStore(path=str(tmp_path / 'sessions.json'))
        assert store.find_session_by_name('Ghost') is None
