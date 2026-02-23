from ...actions.bridge import Kit, Command
from ...actions.command.state import ActionGroupStateManager
from ..search import SORT_CHOICES


GROUP_SORT = "qry_sort"
GROUP_MODE = "qry_mode"
GROUP_KEYWORD = "qry_keyword"
GROUP_ORDER = "qry_order"

_SORT_MAP = {f"qry.sort_{k}": k for k in SORT_CHOICES}
_MODE_MAP = {"qry.mode_glob": "GLOB", "qry.mode_like": "LIKE"}
_KEYWORD_MAP = {"qry.keyword_and": "AND", "qry.keyword_or": "OR"}
_ORDER_MAP = {"qry.order_asc": True, "qry.order_desc": False}


def _search_row(ctx):
    w = ctx.get_instance("MainWindow")
    return w.search_row_widget if w else None


def _service(ctx):
    return ctx.get_instance("SearchService")


_GROUP_CONFIG = {
    GROUP_SORT:    {"search_key": "sort_by",      "map": _SORT_MAP,    "ui_method": "set_sort_by"},
    GROUP_MODE:    {"search_key": "query_mode",   "map": _MODE_MAP,    "ui_method": "set_query_mode"},
    GROUP_KEYWORD: {"search_key": "keyword_mode", "map": _KEYWORD_MAP, "ui_method": "set_keyword_mode"},
    GROUP_ORDER:   {"search_key": "ascending",    "map": _ORDER_MAP,   "ui_method": "set_ascending"},
}


def _set_and_update(ctx, group, cmd_id, search_key, value):
    svc = _service(ctx)
    if svc:
        svc.set_param(search_key, value)
    ActionGroupStateManager().set_current(group, cmd_id, save=False)
    row = _search_row(ctx)
    if row:
        getattr(row, _GROUP_CONFIG[group]["ui_method"])(value)
    if svc:
        svc.try_execute()


def _make_sort_func(key):
    cmd_id = f"qry.sort_{key}"
    def func(ctx):
        _set_and_update(ctx, GROUP_SORT, cmd_id, "sort_by", key)
    return func


def _make_mode_func(cmd_id, mode):
    def func(ctx):
        _set_and_update(ctx, GROUP_MODE, cmd_id, "query_mode", mode)
    return func


def _make_keyword_func(cmd_id, mode):
    def func(ctx):
        _set_and_update(ctx, GROUP_KEYWORD, cmd_id, "keyword_mode", mode)
    return func


def _make_order_func(cmd_id, ascending):
    def func(ctx):
        _set_and_update(ctx, GROUP_ORDER, cmd_id, "ascending", ascending)
    return func


def _cycle_group(ctx, group):
    sm = ActionGroupStateManager()
    new_cmd = sm.cycle(group)
    if not new_cmd:
        return
    cfg = _GROUP_CONFIG[group]
    value = cfg["map"].get(new_cmd)
    if value is None:
        return
    svc = _service(ctx)
    if svc:
        svc.set_param(cfg["search_key"], value)
    row = _search_row(ctx)
    if row:
        getattr(row, cfg["ui_method"])(value)
    if svc:
        svc.try_execute()


def cycle_sort(ctx, reverse=False, **kwargs):
    enabled = [k for k in SORT_CHOICES if kwargs.get(k, True)]
    if not enabled:
        return
    sm = ActionGroupStateManager()
    current = sm.get_current(GROUP_SORT)
    current_key = _SORT_MAP.get(current)
    step = -1 if reverse else 1
    try:
        idx = enabled.index(current_key)
        next_key = enabled[(idx + step) % len(enabled)]
    except (ValueError, IndexError):
        next_key = enabled[-1 if reverse else 0]
    cmd_id = f"qry.sort_{next_key}"
    sm.set_current(GROUP_SORT, cmd_id)
    svc = _service(ctx)
    if svc:
        svc.set_param("sort_by", next_key)
    row = _search_row(ctx)
    if row:
        row.set_sort_by(next_key)
    if svc:
        svc.try_execute()


def cycle_order(ctx):
    _cycle_group(ctx, GROUP_ORDER)


def cycle_mode(ctx):
    _cycle_group(ctx, GROUP_MODE)


def cycle_keyword(ctx):
    _cycle_group(ctx, GROUP_KEYWORD)


def search(ctx, force=False):
    svc = _service(ctx)
    if svc:
        svc.execute(force=force)


def set_search_text(ctx, text: str = ""):
    row = _search_row(ctx)
    if row:
        row.set_search_text(text)


def set_splittext(ctx, text: str = ","):
    row = _search_row(ctx)
    if not row:
        return
    row.set_splittext(text)


def toggle_include_subfolders(ctx):
    svc = _service(ctx)
    if not svc:
        return
    current = svc.get('include_subfolders', True)
    svc.set_param('include_subfolders', not current)
    Command.set_checked("qry.toggle_include_subfolders", not current)
    svc.try_execute()


def toggle_auto_execute(ctx):
    svc = _service(ctx)
    if not svc:
        return
    current = svc.get('auto_execute', True)
    svc.set_param('auto_execute', not current)
    Command.set_checked("qry.toggle_auto_execute", not current)


def sync_groups_from_args(args):
    sm = ActionGroupStateManager()
    sort_by = args.get('sort_by', 'path')
    sort_cmd = f"qry.sort_{sort_by}"
    if sort_cmd in _SORT_MAP:
        sm.set_current(GROUP_SORT, sort_cmd, save=False)
    query_mode = args.get('query_mode', 'GLOB')
    for cmd_id, mode in _MODE_MAP.items():
        if mode == query_mode:
            sm.set_current(GROUP_MODE, cmd_id, save=False)
            break
    keyword_mode = args.get('keyword_mode', 'AND')
    for cmd_id, mode in _KEYWORD_MAP.items():
        if mode == keyword_mode:
            sm.set_current(GROUP_KEYWORD, cmd_id, save=False)
            break
    ascending = args.get('ascending', True)
    for cmd_id, asc in _ORDER_MAP.items():
        if asc == ascending:
            sm.set_current(GROUP_ORDER, cmd_id, save=False)
            break


_SORT_DISPLAY = {
    "path": "Path", "name": "Name", "created": "Created",
    "modified": "Modified", "collected": "Collected", "size": "Size", "random": "Random",
}

class QueryCommands(Kit.MenuBase):
    prefix = "Query"

    commands = [
        ":Query",
        Kit.Command(
            path="qry.search",
            display="Search",
            func=search,
            params=[Kit.Param(name="force", value=True)],
        ),
        Kit.Command(path="qry.toggle_auto_execute", display="Auto Execute on Change", func=toggle_auto_execute, checkable=True, default_checked=True),
        "-",
        ":Search Options",
        Kit.Command(path="qry.toggle_include_subfolders", display="Include Subfolders", func=toggle_include_subfolders, checkable=True, default_checked=True),
        Kit.Command(
            path="qry.set_search_text",
            display="Set Search Text to",
            func=set_search_text,
            params=[Kit.Param(name="text", value="")],
        ),
        "-",
        ":Sort",
        "Sort By/:Sort By",
        *[Kit.Command(
            path=f"Sort By/qry.sort_{k}", display=_SORT_DISPLAY[k],
            func=_make_sort_func(k), checkable=True,
            default_checked=(k == "path"), action_group=GROUP_SORT,
        ) for k in SORT_CHOICES],
        "Sort Order/:Sort Order",
        Kit.Command(path="Sort Order/qry.order_asc", display="Ascending", func=_make_order_func("qry.order_asc", True), checkable=True, action_group=GROUP_ORDER),
        Kit.Command(path="Sort Order/qry.order_desc", display="Descending", func=_make_order_func("qry.order_desc", False), checkable=True, default_checked=True, action_group=GROUP_ORDER),
        Kit.Command(
            path="qry.cycle_sort", display="Cycle Sort By", func=cycle_sort,
            params=[Kit.Param(name=k, value=True) for k in SORT_CHOICES] + [Kit.Param(name="reverse", value=False)],
        ),
        Kit.Command(path="qry.cycle_order", display="Toggle Sort Order", func=cycle_order),
        "-",
        ":Text",
        "Text Mode/:Text Mode",
        Kit.Command(path="Text Mode/qry.mode_glob", display="GLOB", func=_make_mode_func("qry.mode_glob", "GLOB"), checkable=True, default_checked=True, action_group=GROUP_MODE),
        Kit.Command(path="Text Mode/qry.mode_like", display="LIKE", func=_make_mode_func("qry.mode_like", "LIKE"), checkable=True, action_group=GROUP_MODE),
        "Join Mode/:Join Mode",
        Kit.Command(path="Join Mode/qry.keyword_and", display="AND", func=_make_keyword_func("qry.keyword_and", "AND"), checkable=True, default_checked=True, action_group=GROUP_KEYWORD),
        Kit.Command(path="Join Mode/qry.keyword_or", display="OR", func=_make_keyword_func("qry.keyword_or", "OR"), checkable=True, action_group=GROUP_KEYWORD),
        Kit.Command(path="qry.cycle_mode", display="Toggle Query Mode", func=cycle_mode),
        Kit.Command(path="qry.cycle_keyword", display="Toggle Join Mode", func=cycle_keyword),
        Kit.Command(
            path="qry.set_splittext",
            display="Set Split Text to",
            func=set_splittext,
            params=[Kit.Param(name="text", value=",")],
        ),
    ]
