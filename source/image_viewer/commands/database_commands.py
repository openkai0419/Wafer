from ...actions.bridge import Kit
from ...common.funcs import get_setting_file_names
from ...common.profiling import logger
from ...os.process import Proc
from ...qt.dialog import ConfirmDialog, InputDialog


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
    names = get_setting_file_names()
    if not names or len(names) <= 1:
        return
    try:
        idx = names.index(w.dbname)
    except ValueError:
        idx = 0
    new_idx = (idx + direction) % len(names)
    w.reload_db(names[new_idx])


def set_database(ctx, name: str = ""):
    w = _win(ctx)
    if not w or not name:
        return
    if name not in get_setting_file_names():
        logger.warning(f'[set_database] database not found: {name}')
        return
    w.reload_db(name)


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
    logger.info(f'[add_database] {text}')
    if not text or text in get_setting_file_names():
        return
    Proc.new_main('--collector', text)
    w.dbcombo.addItem(text)
    w.dbcombo.setCurrentText(text)
    w.reload_db(text)


def remove_database(ctx):
    w = _win(ctx)
    if not w or w.dbcombo.count() <= 1:
        return
    ret = ConfirmDialog.ask(
        w.t.trf('Delete table? : {dbname}', dbname=w.dbname),
        title=w.t.tr('Delete'),
        buttons=(w.t.tr('Delete'), w.t.tr('Cancel')),
        parent=w,
    )
    if ret == w.t.tr('Delete'):
        w.setting_db.set_kv('deleteflag', True)
        w.dbcombo.removeItem(w.dbname)
        w.reload_db(w.dbcombo.currentText())


class DatabaseCommands(Kit.MenuBase):
    prefix = "Database"

    commands = [
        ":Database",
        Kit.Command(path="db.next_database", display="Next Database", func=next_database),
        Kit.Command(path="db.prev_database", display="Prev Database", func=prev_database),
        Kit.Command(
            path="db.set_database",
            display="Set Database",
            func=set_database,
            params=[Kit.Param(name="name", value="")],
        ),
        Kit.Command(path="db.add_database", display="Add Database", func=add_database),
        Kit.Command(path="db.remove_database", display="Remove Database", func=remove_database),
    ]
