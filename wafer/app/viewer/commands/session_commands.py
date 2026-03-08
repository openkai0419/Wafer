from PySide6 import QtCore, QtGui, QtWidgets

from ....core.actions.bridge import ActionKit
from ....core.actions.command.require import require
from ....core.qt.dialog import InputDialog
from ....core.platform.process import AppProcess
from ....utils.logs import AppLogger
from ....utils.notifier import Notifier
from ..session import BookmarkEntry, BookmarkStore, SessionStore


_bookmark_store = None
_session_store = None


def _bm_store():
    global _bookmark_store
    if _bookmark_store is None:
        _bookmark_store = BookmarkStore()
    return _bookmark_store


def _ss_store():
    global _session_store
    if _session_store is None:
        _session_store = SessionStore()
    return _session_store


@require(w="MainWindow")
def save_bookmark(ctx, w, name: str = ''):
    if not name:
        name = InputDialog.get_text(
            'Bookmark name:',
            title='Save Bookmark',
            buttons=('Save', 'Cancel'),
            parent=w,
        )
        if not name or not name.strip():
            return
        name = name.strip()
    query = w.capture_query_state()
    entry = BookmarkEntry(name=name, query=query)
    _bm_store().save_bookmark(entry)
    Notifier.info(f'Bookmark saved: {name}')
    AppLogger.info(f'Bookmark saved: {name} ({entry.bookmark_id})')


@require(w="MainWindow")
def restore_bookmark(ctx, w, bookmark_id: str = ''):
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


@require(w="MainWindow")
def delete_bookmark(ctx, w, bookmark_id: str = ''):
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
                params=[ActionKit.Param(name="bookmark_id", value=lambda: [e.name or e.bookmark_id for e in _bm_store().list_bookmarks()])],
            ),
            ActionKit.Command(
                path="bm.delete",
                display="Delete Bookmark",
                func=delete_bookmark,
                params=[ActionKit.Param(name="bookmark_id", value=lambda: [e.name or e.bookmark_id for e in _bm_store().list_bookmarks()])],
            ),
            ActionKit.Command(
                path="bm.list",
                display="List Bookmarks",
                func=list_bookmarks,
            ),
        ]


def _get_alive_session_ids() -> list[str]:
    return _ss_store().get_active_session_ids()


@require(w="MainWindow")
def show_session_popup(ctx, w):
    existing = getattr(w, '_session_popup', None)
    if existing and existing.isVisible():
        existing.close()
        return
    from ..widgets.session_popup import SessionPopup
    store = _ss_store()
    named = store.list_sessions()
    alive = _get_alive_session_ids()
    popup = SessionPopup(parent=w)
    w._session_popup = popup
    popup.populate(named, alive, current_session_id=w.session_id)
    popup.session_create.connect(lambda: create_session(ctx))
    popup.session_open.connect(lambda sid: open_session(ctx, sid=sid))
    popup.session_rename.connect(lambda sid: rename_session(ctx, sid=sid))
    popup.session_delete.connect(lambda sid: delete_session(ctx, sid=sid))
    popup.session_color.connect(lambda sid: color_session(ctx, sid=sid, popup=popup))
    btn = getattr(w, '_session_button', None)
    if btn:
        popup.show_below(btn)
    else:
        popup.show()


@require(w="MainWindow")
def create_session(ctx, w):
    from ..widgets.session_popup import ColorPalette
    store = _ss_store()
    default_name = store.next_default_name()
    name = InputDialog.get_text(
        'Session name:',
        title='New Window',
        buttons=('Create', 'Cancel'),
        parent=w,
        default=default_name,
    )
    if not name or not name.strip():
        return
    name = name.strip()
    sid = store.create_session(name)
    AppLogger.info(f'Session created: {name} ({sid})')
    Notifier.info(f'Session created: {name}')
    AppProcess.new_main('--viewer', '--session', sid)


def _resolve_session(store, session: str = '', sid: str = ''):
    if sid:
        return store.get_session(sid)
    if session:
        return store.find_session_by_name(session)
    return None


@require(w="MainWindow")
def open_session(ctx, w, session: str = '', sid: str = ''):
    store = _ss_store()
    entry = _resolve_session(store, session, sid)
    if not entry:
        return
    if entry.session_id == w.session_id:
        return
    if not store.claim_session(entry.session_id):
        node = getattr(w, '_node', None)
        if node:
            node.send('session.focus', entry.session_id, dst='viewer')
    else:
        AppProcess.new_main('--viewer', '--session', entry.session_id)
        Notifier.info(f'Session opened')
    AppLogger.info(f'open_session: {entry.session_id}')


@require(w="MainWindow")
def rename_session(ctx, w, session: str = '', sid: str = ''):
    store = _ss_store()
    entry = _resolve_session(store, session, sid)
    if not entry:
        return
    name = InputDialog.get_text(
        'New name:',
        title='Rename Session',
        buttons=('Rename', 'Cancel'),
        parent=w,
        default=entry.name,
    )
    if not name or not name.strip():
        return
    name = name.strip()
    if store.rename_session(entry.session_id, name):
        Notifier.info(f'Session renamed: {name}')
        AppLogger.info(f'Session renamed: {entry.session_id} -> {name}')
        if w.session_id == entry.session_id:
            w._session_entry.name = name
            w._update_title()


@require(w="MainWindow")
def delete_session(ctx, w, session: str = '', sid: str = ''):
    store = _ss_store()
    entry = _resolve_session(store, session, sid)
    if not entry:
        return
    result = QtWidgets.QMessageBox.question(
        w, 'Delete Session',
        f'Delete session "{entry.name}"?',
        QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
    )
    if result != QtWidgets.QMessageBox.Yes:
        return
    if store.delete_session(entry.session_id):
        Notifier.info(f'Session deleted: {entry.name}')
        AppLogger.info(f'Session deleted: {entry.session_id}')


@require(w="MainWindow")
def color_session(ctx, w, session: str = '', sid: str = '', popup=None):
    store = _ss_store()
    entry = _resolve_session(store, session, sid)
    if not entry:
        return
    from ..widgets.session_popup import ColorPalette
    palette = ColorPalette(current=entry.color, parent=w)
    palette.setWindowFlags(QtCore.Qt.Popup | QtCore.Qt.FramelessWindowHint)
    palette.setAttribute(QtCore.Qt.WA_TranslucentBackground)
    palette.setStyleSheet("background: #2b2b2b; border: 1px solid #555; border-radius: 4px;")

    _sid = entry.session_id

    def _apply(color):
        palette.close()
        if popup:
            popup.close()
        store.set_session_color(_sid, color)
        if w.session_id == _sid:
            w._session_entry.color = color
            w._update_title()
        AppLogger.info(f'Session color set: {_sid} -> {color}')

    palette.color_selected.connect(_apply)
    palette.move(QtGui.QCursor.pos())
    palette.show()
