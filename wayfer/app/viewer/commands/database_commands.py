from ....core.actions.bridge import ActionKit
from ....utils.paths import list_setting_db_names
from ....utils.logs import AppLogger
from ....core.platform.process import AppProcess
from ....core.qt.dialog import ConfirmDialog, InputDialog

def _win(ctx):
    return ctx.get_instance("MainWindow")


def next_database(ctx):
    _cycle_database(ctx, 1)


def prev_database(ctx):
    _cycle_database(ctx, -1)


def _cycle_database(ctx, direction: int):
    w = _win(ctx)
    if not w:
        return
    names = list_setting_db_names()
    if not names or len(names) <= 1:
        return
    try:
        idx = names.index(w.database_name)
    except ValueError:
        idx = 0
    new_idx = (idx + direction) % len(names)
    w.reload_database(names[new_idx])


def set_database(ctx, name: str = ""):
    w = _win(ctx)
    if not w or not name:
        return
    if name not in list_setting_db_names():
        AppLogger.warning(f'[set_database] database not found: {name}')
        return
    w.reload_database(name)


def add_database(ctx):
    w = _win(ctx)
    if not w:
        return
    text = InputDialog.get_text(
        w.t.tr('Enter a name for the new table'),
        title=w.t.tr('Create New'),
        buttons=(w.t.tr('Create'), w.t.tr('Cancel')),
        parent=w,
    )
    if text is None:
        return
    text = text.strip()
    AppLogger.info(f'[add_database] {text}')
    if not text or text in list_setting_db_names():
        return
    AppProcess.new_main('--indexer', text)
    w.database_combo.addItem(text)
    w.database_combo.setCurrentText(text)
    w.reload_database(text)


def remove_database(ctx):
    w = _win(ctx)
    if not w or w.database_combo.count() <= 1:
        return
    ret = ConfirmDialog.ask(
        w.t.tr_format('Delete table? : {dbname}', dbname=w.database_name),
        title=w.t.tr('Delete'),
        buttons=(w.t.tr('Delete'), w.t.tr('Cancel')),
        parent=w,
    )
    if ret == w.t.tr('Delete'):
        w.setting_db.set_setting('deleteflag', True)
        w.database_combo.removeItem(w.database_name)
        w.reload_database(w.database_combo.currentText())


class DatabaseCommands(ActionKit.MenuBase):
    NAME = "Database"
    PRIORITY = 80

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
                params=[ActionKit.Param(name="name", value="")],
            ),
            ActionKit.Command(path="db.add_database", display="Add Database", func=add_database),
            ActionKit.Command(path="db.remove_database", display="Remove Database", func=remove_database),
        ]
