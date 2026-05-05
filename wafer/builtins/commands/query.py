from ...core.commands.bridge import ActionKit
from ...core.commands.binding.instance_registry import InstanceRegistry
from ...plugin.query.handler import sort_registry


GROUP_SORT = "qry_sort"
GROUP_ORDER = "qry_order"


def _sort_choices():
    return [s.NAME for s in sort_registry.list_all()]


def _sort_map():
    return {f"qry.sort_{k}": k for k in _sort_choices()}


_ORDER_MAP = {"qry.order_asc": True, "qry.order_desc": False}


def _search_row(ctx):
    w = ctx.get_instance("MainWindow")
    return w.search_row_widget if w else None


def _service(ctx):
    return ctx.get_instance("SearchService")


_GROUP_CONFIG = {
    GROUP_SORT: {"search_key": "sort_by", "map": _sort_map, "ui_method": "set_sort_by"},
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


def _make_order_func(ascending):
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


def search(ctx, force=False):
    svc = _service(ctx)
    if svc:
        svc.execute(force=force)


def toggle_include_subfolders(ctx):
    svc = _service(ctx)
    if not svc:
        return
    current = svc.get("include_subfolders", True)
    svc.set_param("include_subfolders", not current)
    svc.execute_if_auto()


def toggle_include_contained_files(ctx):
    svc = _service(ctx)
    if not svc:
        return
    current = svc.get("include_contained_files", True)
    svc.set_param("include_contained_files", not current)
    svc.execute_if_auto()


def toggle_auto_execute(ctx):
    svc = _service(ctx)
    if not svc:
        return
    current = svc.get("auto_execute", True)
    svc.set_param("auto_execute", not current)


def toggle_auto_execute_on_update(ctx):
    svc = _service(ctx)
    if not svc:
        return
    current = svc.get("auto_execute_on_update", True)
    svc.set_param("auto_execute_on_update", not current)


def _svc():
    return InstanceRegistry.instance().get_one("SearchService")


def _sort_resolver(key):
    return lambda: (_svc().get("sort_by") if _svc() else "none") == key


def _order_resolver(ascending):
    return lambda: (_svc().get("ascending") if _svc() else False) == ascending


_SORT_DISPLAY = {
    "none": "None",
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
                display="Auto Execute on Parameter Change",
                func=toggle_auto_execute,
                checkable=True,
                default_checked=True,
                checked_resolver=lambda: _svc().get("auto_execute", True) if _svc() else True,
            ),
            ActionKit.Command(
                path="qry.toggle_auto_execute_on_update",
                display="Auto Execute on Database Update",
                func=toggle_auto_execute_on_update,
                checkable=True,
                default_checked=True,
                checked_resolver=lambda: _svc().get("auto_execute_on_update", True) if _svc() else True,
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
                path="qry.toggle_include_contained_files",
                display="Include Contained/Virtual Files",
                func=toggle_include_contained_files,
                checkable=True,
                default_checked=True,
                checked_resolver=lambda: _svc().get("include_contained_files", True) if _svc() else True,
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
                    default_checked=(k == "none"),
                    action_group=GROUP_SORT,
                    checked_resolver=_sort_resolver(k),
                )
                for k in _sort_choices()
            ],
            "Sort Order/:Sort Order",
            ActionKit.Command(path="Sort Order/qry.order_asc", display="Ascending", func=_make_order_func(True), checkable=True, action_group=GROUP_ORDER, checked_resolver=_order_resolver(True)),
            ActionKit.Command(
                path="Sort Order/qry.order_desc",
                display="Descending",
                func=_make_order_func(False),
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
        ]
