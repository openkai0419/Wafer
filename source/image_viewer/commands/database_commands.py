from ...actions.bridge import Kit
from ...common.funcs import get_setting_file_names
from ...common.profiling import logger


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
    if w:
        w.on_add_database()


def remove_database(ctx):
    w = _win(ctx)
    if w:
        w.on_remove_database()


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
