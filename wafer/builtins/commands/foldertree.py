import os

from PySide6 import QtCore, QtWidgets

from ...core.commands.bridge import ActionKit, Menu
from ...core.lang.manager import t
from ...utils.paths import normalize_path
from ...utils.logs import AppLogger
from ...ui.dialogs import ConfirmDialog


def _ctx_tree(ctx):
    w = ctx.get("widget") if hasattr(ctx, "get") else None
    if w is not None and hasattr(w, "get_selected_paths"):
        return w
    t = ctx.get_instance("FolderTree") if hasattr(ctx, "get_instance") else None
    return t


def _ctx_path(ctx) -> str | None:
    p = ctx.get("path") if hasattr(ctx, "get") else None
    return str(p) if p else None


def _ctx_normalized_path(ctx) -> str | None:
    path = _ctx_path(ctx)
    if not path:
        return None
    return normalize_path(os.path.abspath(path))


def _ctx_dir_path(ctx) -> str | None:
    path = _ctx_path(ctx)
    if not path:
        return None
    info = QtCore.QFileInfo(str(path))
    if not info.exists():
        return None
    if info.isDir():
        return normalize_path(info.absoluteFilePath())
    if info.isFile():
        return normalize_path(info.absolutePath())
    p = normalize_path(str(path))
    a = os.path.abspath(p)
    return normalize_path(a) if os.path.isdir(a) else normalize_path(os.path.dirname(a))


def _ctx_root(tree):
    w = getattr(tree, "window", None)
    return w() if callable(w) else None


def remove_from_view(ctx):
    tree = _ctx_tree(ctx)
    if tree is None:
        return
    path = _ctx_normalized_path(ctx)
    if not path:
        return
    root = _ctx_root(tree)
    if root is None or not hasattr(root, "setting_db"):
        raise RuntimeError("root widget not found")
    if not hasattr(tree, "roots") or path not in tree.roots or not hasattr(tree, "remove_root"):
        return
    result = ConfirmDialog.ask(
        f"Are you sure to Remove this folder?  (This does not delete folders)\n  {path}",
        title="Confirm",
        buttons=("Remove", "Cancel"),
        parent=tree,
    )
    if result != "Remove":
        return
    tree.remove_root(path)
    root.setting_db.remove_parent_folder(path)


def _ctx_normalized_paths(ctx) -> list[str]:
    raw = ctx.get("paths") if hasattr(ctx, "get") else None
    if not raw:
        single = _ctx_normalized_path(ctx)
        return [single] if single else []
    return [normalize_path(os.path.abspath(str(p))) for p in raw if p]


def ignore_folder(ctx):
    tree = _ctx_tree(ctx)
    if tree is None:
        return
    paths = _ctx_normalized_paths(ctx)
    if not paths:
        return
    root = _ctx_root(tree)
    if root is None or not hasattr(root, "setting_db"):
        raise RuntimeError("root widget not found")
    roots = getattr(tree, "roots", set())
    targets = [p for p in dict.fromkeys(paths) if p not in roots]
    if not targets:
        return
    if len(targets) == 1:
        message = f"Are you sure to Ignore this folder?  (This does not delete folders)\n  {targets[0]}"
    else:
        listing = "\n  ".join(targets)
        message = f"Are you sure to Ignore these folders?  (This does not delete folders)\n  {listing}"
    result = ConfirmDialog.ask(
        message,
        title="Confirm",
        buttons=("Ignore", "Cancel"),
        parent=tree,
    )
    if result != "Ignore":
        return
    for p in targets:
        if hasattr(tree, "add_excluded"):
            tree.add_excluded(p)
        root.setting_db.add_ignore_folder(p)


def show_context_menu(ctx):
    tree = _ctx_tree(ctx)
    if tree is None:
        raise RuntimeError("FolderTree not found")
    path = _ctx_normalized_path(ctx)
    if not path:
        return
    exists = os.path.isdir(path)
    if hasattr(tree, "folder_selected"):
        try:
            tree.folder_selected.emit()
        except Exception as e:
            AppLogger.debug(f"folder_selected emit failed: {e}")
    items = []
    if exists:
        items.extend(
            [
                ":Path",
                "file.show_explorer",
                "file.shell_context_menu",
                "-",
                "file.copy_path",
                "-",
                "file.select_path",
                "-",
                "-",
                "file.cut",
                "file.copy",
                "file.delete",
                "-",
                "file.paste",
                "file.new_folder",
                "-",
            ]
        )
    else:
        items.extend(
            [
                "file.copy_path",
                "-",
            ]
        )
    if hasattr(tree, "roots") and path in tree.roots:
        items.append(ActionKit.Action(path="inline.folder.remove_from_view", display="Remove from view", func=remove_from_view))
    else:
        items.append(ActionKit.Action(path="inline.folder.ignore", display="Ignore this folder", func=ignore_folder))
    s = Menu.from_context(ctx)
    if s is None:
        return
    s.menu(items).exec()


def reload_tree(ctx):
    tree = _ctx_tree(ctx)
    if tree is None:
        return
    if hasattr(tree, "reload_tree"):
        tree.reload_tree()


def add_folder(ctx):
    w = ctx.get_instance("MainWindow")
    if not w:
        return
    folder_path = QtWidgets.QFileDialog.getExistingDirectory(w, t.tr("Select folder"))
    if folder_path:
        w.setting_db.add_parent_folder(folder_path)
        w.folder_view.add_root(folder_path)


def _navigate(ctx, method_name, trigger_search=True):
    tree = _ctx_tree(ctx)
    if tree is None:
        return
    method = getattr(tree, method_name, None)
    if not callable(method):
        return
    return method(trigger_search=bool(trigger_search))


def next_folder_dfs(ctx, trigger_search: bool = True):
    return _navigate(ctx, "navigate_next_dfs", trigger_search=trigger_search)


def prev_folder_dfs(ctx, trigger_search: bool = True):
    return _navigate(ctx, "navigate_prev_dfs", trigger_search=trigger_search)


def next_folder_visible(ctx, trigger_search: bool = True):
    return _navigate(ctx, "navigate_next_visible", trigger_search=trigger_search)


def prev_folder_visible(ctx, trigger_search: bool = True):
    return _navigate(ctx, "navigate_prev_visible", trigger_search=trigger_search)


def parent_folder(ctx, trigger_search: bool = True):
    return _navigate(ctx, "navigate_parent", trigger_search=trigger_search)


def child_folder(ctx, trigger_search: bool = True):
    return _navigate(ctx, "navigate_child", trigger_search=trigger_search)


class FolderTreeCommands(ActionKit.MenuBase):
    NAME = "FolderTree"
    PRIORITY = 30

    @classmethod
    def commands(cls):
        return [
            ":FolderTree",
            "-",
            ":Navigate (Filesystem DFS)",
            ActionKit.Command(
                path="ft.next_folder_dfs",
                display="Next Folder (DFS)",
                func=next_folder_dfs,
                params=[ActionKit.Param(name="trigger_search", value=True)],
            ),
            ActionKit.Command(
                path="ft.prev_folder_dfs",
                display="Prev Folder (DFS)",
                func=prev_folder_dfs,
                params=[ActionKit.Param(name="trigger_search", value=True)],
            ),
            "-",
            ":Navigate (Visible Tree)",
            ActionKit.Command(
                path="ft.next_folder_visible",
                display="Next Folder (Visible)",
                func=next_folder_visible,
                params=[ActionKit.Param(name="trigger_search", value=True)],
            ),
            ActionKit.Command(
                path="ft.prev_folder_visible",
                display="Prev Folder (Visible)",
                func=prev_folder_visible,
                params=[ActionKit.Param(name="trigger_search", value=True)],
            ),
            "-",
            ":Navigate (Hierarchy)",
            ActionKit.Command(
                path="ft.parent_folder",
                display="Parent Folder",
                func=parent_folder,
                params=[ActionKit.Param(name="trigger_search", value=True)],
            ),
            ActionKit.Command(
                path="ft.child_folder",
                display="Child Folder",
                func=child_folder,
                params=[ActionKit.Param(name="trigger_search", value=True)],
            ),
            "-",
            ActionKit.Command(path="ft.reload_tree", display="Reload Tree", func=reload_tree),
            "-",
            ActionKit.Command(path="ft.add_folder", display="Add Folder", func=add_folder),
        ]
