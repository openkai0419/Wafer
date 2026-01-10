import os

from PySide6 import QtGui, QtWidgets

from ...actions.bridge import Context, Kit, Menu
from ...common.funcs import normalize_path
from ...lang.manager import TranslatorMixin
from ...qt.dialog import ConfirmDialog


class ActionManager(TranslatorMixin):
    @staticmethod
    def get_directory_from_path(path):
        abs_path = os.path.abspath(path)
        return abs_path if os.path.isdir(abs_path) else os.path.dirname(abs_path)


class ContextMenuBuilder(ActionManager):
    def __init__(self, parent=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.parent = parent

    def build_menu(self, path):
        seed_ctx = Context.create_context(
            self.parent,
            "*",
            source="menu",
            extras={"path": path, "paths": self.get_selected_sources()},
        )
        return (
            Menu.session(self.parent, seed_ctx=seed_ctx)
            .use("File")
            .insert(
                "file.copy_path_list",
                [
                    Kit.Command(path="inline.copy_path", display="Copy FileName", func=ContextMenuBuilder._cmd_copy_path),
                    "-",
                    Kit.Command(path="inline.select_folder", display="Select Folder", func=ContextMenuBuilder._cmd_select_folder),
                ],
            )
            .build()
        )

    @staticmethod
    def _cmd_copy_path(ctx):
        get = getattr(ctx, "get", None)
        path = get("path") if callable(get) else None
        if not path:
            return
        QtGui.QGuiApplication.clipboard().setText(str(path))

    @staticmethod
    def _cmd_select_folder(ctx):
        get = getattr(ctx, "get", None)
        path = get("path") if callable(get) else None
        if not path:
            return
        w = get("widget") if callable(get) else None
        if w is None or not hasattr(w, "folder_view"):
            raise RuntimeError("folder_view not found")
        folder = ActionManager.get_directory_from_path(str(path))
        w.folder_view.expand_and_select_path(folder)

    def get_selected_sources(self):
        return self.parent.items.selected_sources()


class FolderContextMenuBuilder(ActionManager):
    def __init__(self, parent, root, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.root = root
        self.view = parent

    def build_menu(self, path):
        menu_items = [
            ":Path",
            "file.copy_path",
            "file.show_explorer",
            "-",
            "file.paste",
            "-",
        ]

        seed_ctx = Context.create_context(
            self.root,
            "*",
            source="menu",
            extras={"path": path},
        )
        if path in self.view.roots:
            spec = Menu.session(self.root, seed_ctx=seed_ctx).menu(menu_items).add(
                [
                    "-",
                    Kit.Command(path="inline.folder.remove_from_view", display="Remove from view", func=FolderContextMenuBuilder._cmd_remove_from_view),
                ]
            )
        else:
            spec = Menu.session(self.root, seed_ctx=seed_ctx).menu(menu_items).add(
                [
                    "-",
                    Kit.Command(path="inline.folder.ignore", display="Ignore this folder", func=FolderContextMenuBuilder._cmd_ignore_folder),
                ]
            )
        return spec.build()

    @staticmethod
    def _cmd_remove_from_view(ctx):
        get = getattr(ctx, "get", None)
        path = get("path") if callable(get) else None
        if not path:
            return
        root = get("widget") if callable(get) else None
        if root is None or not hasattr(root, "folder_view") or not hasattr(root, "setting_db"):
            raise RuntimeError("root widget not found")
        view = root.folder_view
        result = ConfirmDialog.ask(
            f"Are you sure to Remove this folder?  (This does not delete folders)\\  {path}",
            title="Confirm",
            buttons=("Remove", "Cancel"),
            parent=view,
        )
        if result != "Remove":
            return
        if hasattr(view, "roots") and path in view.roots and hasattr(view, "remove_root"):
            view.remove_root(path)
        root.setting_db.remove_parent_folder(path)

    @staticmethod
    def _cmd_ignore_folder(ctx):
        get = getattr(ctx, "get", None)
        path = get("path") if callable(get) else None
        if not path:
            return
        root = get("widget") if callable(get) else None
        if root is None or not hasattr(root, "folder_view") or not hasattr(root, "setting_db"):
            raise RuntimeError("root widget not found")
        view = root.folder_view
        result = ConfirmDialog.ask(
            f"Are you sure to Ingore this folder?  (This does not delete folders)\n  {path}",
            title="Confirm",
            buttons=("Ignore", "Cancel"),
            parent=view,
        )
        if result != "Ignore":
            return
        p = normalize_path(str(path))
        if hasattr(view, "add_excluded"):
            view.add_excluded(p)
        root.setting_db.add_ignore_folder(p)

    def remove(self, path):
        result = ConfirmDialog.ask(
            self.t.trf(
                "Are you sure to Remove this folder?  (This does not delete folders)\\  {path}",
                path=path,
            ),
            title=self.t.tr("Confirm"),
            buttons=(self.t.tr("Remove"), self.t.tr("Cancel")),
            parent=self.view,
        )
        if result == self.t.tr("Remove"):
            if path in self.view.roots:
                self.view.remove_root(path)
                self.root.setting_db.remove_parent_folder(path)

    def ignore(self, path):
        result = ConfirmDialog.ask(
            self.t.trf(
                "Are you sure to Ingore this folder?  (This does not delete folders)\n  {path}",
                path=path,
            ),
            title=self.t.tr("Confirm"),
            buttons=(self.t.tr("Ignore"), self.t.tr("Cancel")),
            parent=self.view,
        )
        if result == self.t.tr("Ignore"):
            path = normalize_path(path)
            self.view.add_excluded(path)
            self.root.setting_db.add_ignore_folder(path)
