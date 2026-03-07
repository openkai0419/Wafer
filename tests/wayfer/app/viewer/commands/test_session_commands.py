import py_compile

from wayfer.app.viewer.session import (
    QueryState,
    BookmarkEntry,
    BookmarkStore,
)


def test_compile():
    py_compile.compile('wayfer/app/viewer/commands/session_commands.py')


class TestBookmarkCommands:

    def test_command_class_registers(self):
        from wayfer.app.viewer.commands.session_commands import BookmarkCommands
        BookmarkCommands.register()

    def test_bm_store_lazy_init(self):
        from wayfer.app.viewer.commands.session_commands import _bm_store
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
