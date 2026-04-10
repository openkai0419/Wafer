from PySide6 import QtCore, QtWidgets

from ...core.commands.bridge import ActionKit
from ...core.commands.command.require import require
from ...ui.dialogs import InputDialog
from ...core.platform.process import AppProcess
from ...utils.logs import AppLogger
from ...utils.notifier import Notifier
from ...core.profile import BookmarkEntry, BookmarkStore, ProfileStore


def _bm_store():
    return BookmarkStore.instance()


def _pf_store():
    return ProfileStore.instance()


@require(w="MainWindow")
def save_bookmark(ctx, w, name: str = ""):
    if not name:
        name = InputDialog.get_text(
            "Bookmark name:",
            title="Save Bookmark",
            buttons=("Save", "Cancel"),
            parent=w,
        )
        if not name or not name.strip():
            return
        name = name.strip()
    query = w.capture_query_state()
    entry = BookmarkEntry(name=name, query=query)
    _bm_store().save_bookmark(entry)
    Notifier.info(f"Bookmark saved: {name}")
    AppLogger.info(f"Bookmark saved: {name} ({entry.bookmark_id})")


@require(w="MainWindow")
def restore_bookmark(ctx, w, bookmark_id: str = ""):
    if not bookmark_id:
        entries = _bm_store().list_bookmarks()
        if not entries:
            Notifier.warning("No bookmarks found")
            return
        names = [e.name or e.bookmark_id for e in entries]
        chosen, ok = QtWidgets.QInputDialog.getItem(w, "Restore Bookmark", "Select bookmark:", names, editable=False)
        if not ok:
            return
        idx = names.index(chosen)
        entry = entries[idx]
    else:
        entry = _bm_store().get_bookmark(bookmark_id)
        if entry is None:
            Notifier.warning(f"Bookmark not found: {bookmark_id}")
            return
    w.restore_query_state(entry.query)
    Notifier.info(f"Bookmark restored: {entry.name}")


@require(w="MainWindow")
def delete_bookmark(ctx, w, bookmark_id: str = ""):
    if not bookmark_id:
        entries = _bm_store().list_bookmarks()
        if not entries:
            Notifier.warning("No bookmarks found")
            return
        names = [e.name or e.bookmark_id for e in entries]
        chosen, ok = QtWidgets.QInputDialog.getItem(w, "Delete Bookmark", "Select bookmark:", names, editable=False)
        if not ok:
            return
        idx = names.index(chosen)
        entry = entries[idx]
        bookmark_id = entry.bookmark_id
    if _bm_store().delete_bookmark(bookmark_id):
        Notifier.info("Bookmark deleted")
        AppLogger.info(f"Bookmark deleted: {bookmark_id}")
    else:
        Notifier.warning(f"Bookmark not found: {bookmark_id}")


def list_bookmarks(ctx):
    entries = _bm_store().list_bookmarks()
    if not entries:
        Notifier.info("No bookmarks")
        return
    lines = [f"{e.name or '(unnamed)'}  [{e.bookmark_id}]" for e in entries]
    Notifier.info(f"{len(entries)} bookmark(s)")
    for line in lines:
        AppLogger.info(f"  Bookmark: {line}")


class BookmarkCommands(ActionKit.MenuBase):
    NAME = "Query"
    PRIORITY = 65

    @classmethod
    def commands(cls):
        return [
            ":Bookmark",
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


def _get_alive_profile_ids() -> list[str]:
    return _pf_store().get_active_profile_ids()


@require(w="MainWindow")
def show_profile_popup(ctx, w):
    existing = getattr(w, "_profile_popup", None)
    if existing and existing.isVisible():
        existing.close()
        return
    from wafer.app.viewer.widgets.profile_popup import ProfilePopup

    store = _pf_store()
    named = store.list_profiles()
    popup = ProfilePopup(parent=w)
    w._profile_popup = popup
    popup.populate(named, current_profile_id=w.profile_id)
    popup.profile_create.connect(lambda: create_profile(ctx))
    popup.profile_open.connect(lambda pid: open_profile(ctx, pid=pid))
    popup.profile_open_new_window.connect(lambda pid: open_profile_in_new_window(ctx, pid=pid))
    popup.profile_rename.connect(lambda pid: rename_profile(ctx, pid=pid))
    popup.profile_delete.connect(lambda pid: delete_profile(ctx, pid=pid))
    popup.profile_color_changed.connect(lambda pid, color: _apply_profile_color(w, pid, color))
    btn = getattr(w, "_profile_button", None)
    if btn:
        popup.show_below(btn)
    else:
        popup.show()


@require(w="MainWindow")
def create_profile(ctx, w):
    store = _pf_store()
    default_name = store.next_default_name()
    name = InputDialog.get_text(
        "Profile name:",
        title="New Profile",
        buttons=("Create", "Cancel"),
        parent=w,
        default=default_name,
    )
    if not name or not name.strip():
        return
    name = name.strip()
    pid = store.create_profile(name)
    if pid is None:
        Notifier.warning(f"Profile name already exists: {name}")
        return
    entry = store.get_profile(pid)
    entry.query_snapshot = w.capture_query_state()
    ui = w.capture_ui_state()
    ui.window_state = {}
    entry.ui = ui
    store.save_profile(entry)
    AppLogger.info(f"Profile created: {name} ({pid})")
    Notifier.info(f"Profile created: {name}")
    w.switch_profile(pid)


def new_window(ctx):
    store = _pf_store()
    profiles = store.list_profiles()
    if profiles:
        pid = profiles[0].profile_id
    else:
        pid = store.create_profile_with_unique_name(store.next_default_name())
    AppProcess.new_main("--viewer", "--profile", pid)
    AppLogger.info(f"new_window: profile={pid}")


def _resolve_profile(store, profile: str = "", pid: str = ""):
    if pid:
        return store.get_profile(pid)
    if profile:
        return store.find_profile_by_name(profile)
    return None


@require(w="MainWindow")
def open_profile(ctx, w, profile: str = "", pid: str = ""):
    store = _pf_store()
    entry = _resolve_profile(store, profile, pid)
    if not entry:
        return
    if entry.profile_id == w.profile_id:
        return
    w.switch_profile(entry.profile_id)


@require(w="MainWindow")
def open_profile_in_new_window(ctx, w, profile: str = "", pid: str = ""):
    store = _pf_store()
    entry = _resolve_profile(store, profile, pid)
    if not entry:
        return
    AppProcess.new_main("--viewer", "--profile", entry.profile_id)
    AppLogger.info(f"open_profile_in_new_window: {entry.profile_id}")


@require(w="MainWindow")
def rename_profile(ctx, w, profile: str = "", pid: str = ""):
    store = _pf_store()
    entry = _resolve_profile(store, profile, pid)
    if not entry:
        return
    name = InputDialog.get_text(
        "New name:",
        title="Rename Profile",
        buttons=("Rename", "Cancel"),
        parent=w,
        default=entry.name,
    )
    if not name or not name.strip():
        return
    name = name.strip()
    if name == entry.name:
        return
    if not store.rename_profile(entry.profile_id, name):
        Notifier.warning(f"Profile name already exists: {name}")
        return
    Notifier.info(f"Profile renamed: {name}")
    AppLogger.info(f"Profile renamed: {entry.profile_id} -> {name}")
    if w.profile_id == entry.profile_id:
        w._profile_entry.name = name
        w._update_title()


@require(w="MainWindow")
def delete_profile(ctx, w, profile: str = "", pid: str = ""):
    store = _pf_store()
    entry = _resolve_profile(store, profile, pid)
    if not entry:
        return
    result = QtWidgets.QMessageBox.question(
        w,
        "Delete Profile",
        f'Delete profile "{entry.name}"?',
        QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
    )
    if result != QtWidgets.QMessageBox.Yes:
        return
    is_own = entry.profile_id == w.profile_id
    if store.delete_profile(entry.profile_id):
        Notifier.info(f"Profile deleted: {entry.name}")
        AppLogger.info(f"Profile deleted: {entry.profile_id}")
        if is_own:
            w._profile_deleted = True
            w.close()
        else:
            node = getattr(w, "_node", None)
            if node:
                node.send("profile.close", entry.profile_id, dst="viewer")


def _apply_profile_color(w, pid, color):
    store = _pf_store()
    store.set_profile_color(pid, color)
    if w.profile_id == pid:
        w._profile_entry.color = color
        w._update_title()
    AppLogger.info(f"Profile color set: {pid} -> {color}")
