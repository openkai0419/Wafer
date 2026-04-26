from ...core.commands.bridge import ActionKit
from ...core.commands.binding.instance_registry import InstanceRegistry
from ...plugin.query.handler import sort_registry


GROUP_SORT = "qry_sort"
GROUP_MODE = "qry_mode"
GROUP_KEYWORD = "qry_keyword"
GROUP_ORDER = "qry_order"


def _sort_choices():
    return [s.NAME for s in sort_registry.list_all()]


def _sort_map():
    return {f"qry.sort_{k}": k for k in _sort_choices()}


_MODE_MAP = {"qry.mode_glob": "GLOB", "qry.mode_like": "LIKE"}
_KEYWORD_MAP = {"qry.keyword_and": "AND", "qry.keyword_or": "OR"}
_ORDER_MAP = {"qry.order_asc": True, "qry.order_desc": False}


def _search_row(ctx):
    w = ctx.get_instance("MainWindow")
    return w.search_row_widget if w else None


def _service(ctx):
    return ctx.get_instance("SearchService")


_GROUP_CONFIG = {
    GROUP_SORT: {"search_key": "sort_by", "map": _sort_map, "ui_method": "set_sort_by"},
    GROUP_MODE: {"search_key": "query_mode", "map": _MODE_MAP, "ui_method": "set_query_mode"},
    GROUP_KEYWORD: {"search_key": "keyword_mode", "map": _KEYWORD_MAP, "ui_method": "set_keyword_mode"},
    GROUP_ORDER: {"search_key": "ascending", "map": _ORDER_MAP, "ui_method": "set_ascending"},
}


def _set_and_update(ctx, group, search_key, value):
    svc = _service(ctx)
    if svc:
        svc.set_param(search_key, value)
    row = _search_row(ctx)
    if row:
        getattr(row, _GROUP_CONFIG[group]["ui_method"])(value)
    if svc:
        svc.execute_if_auto()


def _make_sort_func(key):
    def func(ctx):
        _set_and_update(ctx, GROUP_SORT, "sort_by", key)

    return func


def _make_mode_func(_cmd_id, mode):
    def func(ctx):
        _set_and_update(ctx, GROUP_MODE, "query_mode", mode)

    return func


def _make_keyword_func(_cmd_id, mode):
    def func(ctx):
        _set_and_update(ctx, GROUP_KEYWORD, "keyword_mode", mode)

    return func


def _make_order_func(_cmd_id, ascending):
    def func(ctx):
        _set_and_update(ctx, GROUP_ORDER, "ascending", ascending)

    return func


def _cycle_group(ctx, group):
    cfg = _GROUP_CONFIG[group]
    m = cfg["map"]() if callable(cfg["map"]) else cfg["map"]
    members = list(m.keys())
    if not members:
        return
    svc = _service(ctx)
    current_value = svc.get(cfg["search_key"]) if svc else None
    current_cmd = next((cid for cid, val in m.items() if val == current_value), None)
    try:
        idx = members.index(current_cmd) if current_cmd else -1
    except ValueError:
        idx = -1
    next_cmd = members[(idx + 1) % len(members)]
    next_value = m[next_cmd]
    _set_and_update(ctx, group, cfg["search_key"], next_value)


def cycle_sort(ctx, reverse=False, **kwargs):
    choices = _sort_choices()
    enabled = [k for k in choices if kwargs.get(k, True)]
    if not enabled:
        return
    svc = _service(ctx)
    current_key = svc.get("sort_by") if svc else None
    step = -1 if reverse else 1
    try:
        idx = enabled.index(current_key)
        next_key = enabled[(idx + step) % len(enabled)]
    except (ValueError, IndexError):
        next_key = enabled[-1 if reverse else 0]
    _set_and_update(ctx, GROUP_SORT, "sort_by", next_key)


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


def set_keyword_delimiter(ctx, text: str = ","):
    row = _search_row(ctx)
    if not row:
        return
    row.set_keyword_delimiter(text)


def toggle_include_subfolders(ctx):
    svc = _service(ctx)
    if not svc:
        return
    current = svc.get("include_subfolders", True)
    svc.set_param("include_subfolders", not current)
    svc.execute_if_auto()


def toggle_auto_execute(ctx):
    svc = _service(ctx)
    if not svc:
        return
    current = svc.get("auto_execute", True)
    svc.set_param("auto_execute", not current)


def _svc():
    return InstanceRegistry.instance().get_one("SearchService")


def _sort_resolver(key):
    return lambda: (_svc().get("sort_by") if _svc() else "path") == key


def _mode_resolver(mode):
    return lambda: (_svc().get("query_mode") if _svc() else "GLOB") == mode


def _keyword_resolver(mode):
    return lambda: (_svc().get("keyword_mode") if _svc() else "AND") == mode


def _order_resolver(ascending):
    return lambda: (_svc().get("ascending") if _svc() else False) == ascending


_SORT_DISPLAY = {
    "path": "Path",
    "name": "Name",
    "created": "Created",
    "modified": "Modified",
    "collected": "Collected",
    "size": "Size",
    "random": "Random",
}


class QueryCommands(ActionKit.MenuBase):
    NAME = "Query"
    PRIORITY = 20

    @classmethod
    def commands(cls):
        return [
            ":Query",
            ActionKit.Command(
                path="qry.search",
                display="Search",
                func=search,
                params=[ActionKit.Param(name="force", value=True)],
            ),
            ActionKit.Command(
                path="qry.toggle_auto_execute",
                display="Auto Execute on Change",
                func=toggle_auto_execute,
                checkable=True,
                default_checked=True,
                checked_resolver=lambda: _svc().get("auto_execute", True) if _svc() else True,
            ),
            "-",
            ":Search Options",
            ActionKit.Command(
                path="qry.toggle_include_subfolders",
                display="Include Subfolders",
                func=toggle_include_subfolders,
                checkable=True,
                default_checked=True,
                checked_resolver=lambda: _svc().get("include_subfolders", True) if _svc() else True,
            ),
            ActionKit.Command(
                path="qry.set_search_text",
                display="Set Search Text to",
                func=set_search_text,
                params=[ActionKit.Param(name="text", value="")],
            ),
            "-",
            ":Sort",
            "Sort By/:Sort By",
            *[
                ActionKit.Command(
                    path=f"Sort By/qry.sort_{k}",
                    display=_SORT_DISPLAY[k],
                    func=_make_sort_func(k),
                    checkable=True,
                    default_checked=(k == "path"),
                    action_group=GROUP_SORT,
                    checked_resolver=_sort_resolver(k),
                )
                for k in _sort_choices()
            ],
            "Sort Order/:Sort Order",
            ActionKit.Command(
                path="Sort Order/qry.order_asc", display="Ascending", func=_make_order_func("qry.order_asc", True), checkable=True, action_group=GROUP_ORDER, checked_resolver=_order_resolver(True)
            ),
            ActionKit.Command(
                path="Sort Order/qry.order_desc",
                display="Descending",
                func=_make_order_func("qry.order_desc", False),
                checkable=True,
                default_checked=True,
                action_group=GROUP_ORDER,
                checked_resolver=_order_resolver(False),
            ),
            ActionKit.Command(
                path="qry.cycle_sort",
                display="Cycle Sort By",
                func=cycle_sort,
                params=[ActionKit.Param(name=k, value=True) for k in _sort_choices()] + [ActionKit.Param(name="reverse", value=False)],
            ),
            ActionKit.Command(path="qry.cycle_order", display="Toggle Sort Order", func=cycle_order),
            "-",
            ":Text",
            "Text Mode/:Text Mode",
            ActionKit.Command(
                path="Text Mode/qry.mode_glob",
                display="GLOB",
                func=_make_mode_func("qry.mode_glob", "GLOB"),
                checkable=True,
                default_checked=True,
                action_group=GROUP_MODE,
                checked_resolver=_mode_resolver("GLOB"),
            ),
            ActionKit.Command(
                path="Text Mode/qry.mode_like", display="LIKE", func=_make_mode_func("qry.mode_like", "LIKE"), checkable=True, action_group=GROUP_MODE, checked_resolver=_mode_resolver("LIKE")
            ),
            "Join Mode/:Join Mode",
            ActionKit.Command(
                path="Join Mode/qry.keyword_and",
                display="AND",
                func=_make_keyword_func("qry.keyword_and", "AND"),
                checkable=True,
                default_checked=True,
                action_group=GROUP_KEYWORD,
                checked_resolver=_keyword_resolver("AND"),
            ),
            ActionKit.Command(
                path="Join Mode/qry.keyword_or", display="OR", func=_make_keyword_func("qry.keyword_or", "OR"), checkable=True, action_group=GROUP_KEYWORD, checked_resolver=_keyword_resolver("OR")
            ),
            ActionKit.Command(path="qry.cycle_mode", display="Toggle Query Mode", func=cycle_mode),
            ActionKit.Command(path="qry.cycle_keyword", display="Toggle Join Mode", func=cycle_keyword),
            ActionKit.Command(
                path="qry.set_keyword_delimiter",
                display="Set Keyword Delimiter to",
                func=set_keyword_delimiter,
                params=[ActionKit.Param(name="text", value=",")],
            ),
        ]
