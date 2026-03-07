from PySide6 import QtWidgets

from ....core.actions.bridge import ActionKit
from ....utils.logs import AppLogger
from ....utils.notifier import Notifier
from ..session import BookmarkEntry, BookmarkStore


_bookmark_store = None


def _bm_store():
    global _bookmark_store
    if _bookmark_store is None:
        _bookmark_store = BookmarkStore()
    return _bookmark_store


def _win(ctx):
    return ctx.get_instance("MainWindow")


def save_bookmark(ctx, name: str = ''):
    w = _win(ctx)
    if not w:
        return
    if not name:
        name, ok = QtWidgets.QInputDialog.getText(w, 'Save Bookmark', 'Bookmark name:')
        if not ok or not name.strip():
            return
        name = name.strip()
    query = w.capture_query_state()
    entry = BookmarkEntry(name=name, query=query)
    _bm_store().save_bookmark(entry)
    Notifier.info(f'Bookmark saved: {name}')
    AppLogger.info(f'Bookmark saved: {name} ({entry.bookmark_id})')


def restore_bookmark(ctx, bookmark_id: str = ''):
    w = _win(ctx)
    if not w:
        return
    if not bookmark_id:
        entries = _bm_store().list_bookmarks()
        if not entries:
            Notifier.warning('No bookmarks found')
            return
        names = [e.name or e.bookmark_id for e in entries]
        chosen, ok = QtWidgets.QInputDialog.getItem(w, 'Restore Bookmark', 'Select bookmark:', names, editable=False)
        if not ok:
            return
        idx = names.index(chosen)
        entry = entries[idx]
    else:
        entry = _bm_store().get_bookmark(bookmark_id)
        if entry is None:
            Notifier.warning(f'Bookmark not found: {bookmark_id}')
            return
    w.restore_query_state(entry.query)
    Notifier.info(f'Bookmark restored: {entry.name}')


def delete_bookmark(ctx, bookmark_id: str = ''):
    w = _win(ctx)
    if not bookmark_id:
        entries = _bm_store().list_bookmarks()
        if not entries:
            Notifier.warning('No bookmarks found')
            return
        names = [e.name or e.bookmark_id for e in entries]
        chosen, ok = QtWidgets.QInputDialog.getItem(w, 'Delete Bookmark', 'Select bookmark:', names, editable=False)
        if not ok:
            return
        idx = names.index(chosen)
        entry = entries[idx]
        bookmark_id = entry.bookmark_id
    if _bm_store().delete_bookmark(bookmark_id):
        Notifier.info(f'Bookmark deleted')
        AppLogger.info(f'Bookmark deleted: {bookmark_id}')
    else:
        Notifier.warning(f'Bookmark not found: {bookmark_id}')


def list_bookmarks(ctx):
    entries = _bm_store().list_bookmarks()
    if not entries:
        Notifier.info('No bookmarks')
        return
    lines = [f'{e.name or "(unnamed)"}  [{e.bookmark_id}]' for e in entries]
    Notifier.info(f'{len(entries)} bookmark(s)')
    for line in lines:
        AppLogger.info(f'  Bookmark: {line}')


class BookmarkCommands(ActionKit.MenuBase):
    NAME = "Bookmark"
    PRIORITY = 75

    @classmethod
    def commands(cls):
        return [
            ActionKit.Command(
                path="bm.save",
                display="Save Bookmark",
                func=save_bookmark,
                params=[ActionKit.Param(name="name", value="")],
            ),
            ActionKit.Command(
                path="bm.restore",
                display="Restore Bookmark",
                func=restore_bookmark,
                params=[ActionKit.Param(name="bookmark_id", value="")],
            ),
            ActionKit.Command(
                path="bm.delete",
                display="Delete Bookmark",
                func=delete_bookmark,
                params=[ActionKit.Param(name="bookmark_id", value="")],
            ),
            ActionKit.Command(
                path="bm.list",
                display="List Bookmarks",
                func=list_bookmarks,
            ),
        ]
