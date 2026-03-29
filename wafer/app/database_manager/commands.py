from ...core.commands.bridge import ActionKit


def _resolve_node(ctx):
    w = ctx.get_instance("MainWindow")
    if w:
        return w, getattr(w, '_node', None)
    tray = ctx.get_instance("Tray")
    if tray:
        return None, getattr(tray, '_node', None)
    return None, None


def open_database_manager(ctx):
    parent, node = _resolve_node(ctx)
    from .window import DatabaseManagerDialog
    DatabaseManagerDialog.open(parent=parent, node=node)


class DatabaseManagerCommands(ActionKit.MenuBase):
    NAME = "Setting"
    PRIORITY = 85

    @classmethod
    def commands(cls):
        return [
            ":Database",
            ActionKit.Command(
                path="setting.database_manager",
                display="Database Manager",
                func=open_database_manager,
            ),
        ]
