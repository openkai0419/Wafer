from ...core.commands.bridge import ActionKit
from ...core.commands.command.require import require
from ...core.lang.manager import t
from ...utils.paths import list_setting_db_names
from ...utils.logs import AppLogger
from ...core.platform.process import AppProcess
from ...ui.dialogs import ConfirmDialog, InputDialog


@require(w="MainWindow")
def next_database(ctx, w):
    _cycle_database(w, 1)


@require(w="MainWindow")
def prev_database(ctx, w):
    _cycle_database(w, -1)


def _cycle_database(w, direction: int):
    names = list_setting_db_names()
    if not names or len(names) <= 1:
        return
    try:
        idx = names.index(w.database_name)
    except ValueError:
        idx = 0
    new_idx = (idx + direction) % len(names)
    w.reload_database(names[new_idx])


@require(w="MainWindow")
def set_database(ctx, w, name: str = ""):
    if not name:
        return
    if name not in list_setting_db_names():
        AppLogger.warning(f"[set_database] database not found: {name}")
        return
    w.reload_database(name)


@require(w="MainWindow")
def add_database(ctx, w):
    text = InputDialog.get_text(
        t.tr("Enter a name for the new table"),
        title=t.tr("Create New"),
        buttons=(t.tr("Create"), t.tr("Cancel")),
        parent=w,
    )
    if text is None:
        return
    text = text.strip()
    AppLogger.info(f"[add_database] {text}")
    if not text or text in list_setting_db_names():
        return
    AppProcess.new_main("--indexer", text)
    w.database_combo.addItem(text)
    w.database_combo.setCurrentText(text)
    w.reload_database(text)


@require(w="MainWindow")
def remove_database(ctx, w):
    if w.database_combo.count() <= 1:
        return
    ret = ConfirmDialog.ask(
        t.tr_format("Delete table? : {dbname}", dbname=w.database_name),
        title=t.tr("Delete"),
        buttons=(t.tr("Delete"), t.tr("Cancel")),
        parent=w,
    )
    if ret == t.tr("Delete"):
        db_name = w.database_name
        w._node.send_reliable("db.delete", db_name, dst="indexer", db=db_name)
        w.database_combo.removeItem(db_name)
        w.reload_database(w.database_combo.currentText())


class DatabaseCommands(ActionKit.MenuBase):
    NAME = "Database"
    PRIORITY = 60

    @classmethod
    def commands(cls):
        return [
            ":Database",
            ActionKit.Command(path="db.next_database", display="Next Database", func=next_database),
            ActionKit.Command(path="db.prev_database", display="Prev Database", func=prev_database),
            ActionKit.Command(
                path="db.set_database",
                display="Set Database",
                func=set_database,
                params=[ActionKit.Param(name="name", value=list_setting_db_names, required=True)],
            ),
            ActionKit.Command(path="db.add_database", display="Add Database", func=add_database),
            ActionKit.Command(path="db.remove_database", display="Remove Database", func=remove_database),
        ]
