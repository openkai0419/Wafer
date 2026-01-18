import os

from PySide6 import QtCore

from ...actions.bridge import Kit, Menu
from ...common.funcs import normalize_path
from ...qt.dialog import ConfirmDialog


def _ctx_tree(ctx):
    w = ctx.get("widget") if hasattr(ctx, "get") else None
    if w is not None and hasattr(w, "get_selected_paths"):
        return w
    t = ctx.get_instance("FolderTree") if hasattr(ctx, "get_instance") else None
    return t


def _ctx_path(ctx) -> str | None:
    p = ctx.get("path") if hasattr(ctx, "get") else None
    return str(p) if p else None


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
    path = _ctx_dir_path(ctx)
    if not path:
        return
    root = _ctx_root(tree)
    if root is None or not hasattr(root, "setting_db"):
        raise RuntimeError("root widget not found")
    if not hasattr(tree, "roots") or path not in tree.roots or not hasattr(tree, "remove_root"):
        return
    result = ConfirmDialog.ask(
        f"Are you sure to Remove this folder?  (This does not delete folders)\\  {path}",
        title="Confirm",
        buttons=("Remove", "Cancel"),
        parent=tree,
    )
    if result != "Remove":
        return
    tree.remove_root(path)
    root.setting_db.remove_parent_folder(path)


def ignore_folder(ctx):
    tree = _ctx_tree(ctx)
    if tree is None:
        return
    path = _ctx_dir_path(ctx)
    if not path:
        return
    root = _ctx_root(tree)
    if root is None or not hasattr(root, "setting_db"):
        raise RuntimeError("root widget not found")
    if hasattr(tree, "roots") and path in tree.roots:
        return
    result = ConfirmDialog.ask(
        f"Are you sure to Ingore this folder?  (This does not delete folders)\n  {path}",
        title="Confirm",
        buttons=("Ignore", "Cancel"),
        parent=tree,
    )
    if result != "Ignore":
        return
    p = normalize_path(str(path))
    if hasattr(tree, "add_excluded"):
        tree.add_excluded(p)
    root.setting_db.add_ignore_folder(p)


def reload_tree(ctx):
    tree = _ctx_tree(ctx)
    if tree is None:
        return
    if hasattr(tree, "reload_tree"):
        tree.reload_tree()


def show_context_menu(ctx):
    tree = _ctx_tree(ctx)
    if tree is None:
        return
    path = _ctx_dir_path(ctx)
    if not path:
        return
    if hasattr(tree, "folder_selected"):
        try:
            tree.folder_selected.emit()
        except Exception:
            pass
    items = [
        ":Path",
        "file.copy_path",
        "file.show_explorer",
        "-",
        "file.paste",
        "-",
    ]
    if hasattr(tree, "roots") and path in tree.roots:
        items.append(Kit.Command(path="inline.folder.remove_from_view", display="Remove from view", func=remove_from_view))
    else:
        items.extend([
            Kit.Command(path="inline.folder.ignore", display="Ignore this folder", func=ignore_folder),
        ])
    s = Menu.with_ctx(ctx)
    if s is None:
        return
    s.menu(items).exec()


class FolderTreeCommands(Kit.MenuBase):
    prefix = "FolderTree"

    commands = [
        ":FolderTree",
        Kit.Command(path="ft.menu", display="Context Menu", func=show_context_menu, hidden=True),
        "-",
        Kit.Command(path="ft.reload_tree", display="Reload Tree", func=reload_tree),
    ]
