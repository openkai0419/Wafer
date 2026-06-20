from ...core.commands.bridge import ActionKit
from ...core.commands.binding.instance_registry import InstanceRegistry
from ...core.commands.command.require import require
from ...core.lang.manager import t
from ...ui.layout.manager import LayoutManager, MODE_EDIT
from ...utils.logs import AppLogger
from ...utils.notifier import Notifier


def _is_layout_edit():
    w = InstanceRegistry.instance().get_one("MainWindow")
    return w._layout_manager._mode == MODE_EDIT if w else False


def toggle_layout_mode(ctx):
    w = ctx.get_instance("MainWindow")
    if not w:
        return
    w._layout_manager.toggle_mode()


def _panel_name_choices() -> list[str]:
    w = InstanceRegistry.instance().get_one("MainWindow")
    mgr = getattr(w, "_layout_manager", None) if w else None
    return mgr.panel_names() if mgr else []


def _resolve_panel_name(name: str, mgr: LayoutManager) -> str | None:
    if not name:
        return None
    names = mgr.panel_names()
    if name in names:
        return name
    lowered = name.lower()
    for candidate in names:
        if candidate.lower() == lowered:
            return candidate
    return None


def _notify_solo_failed(name: str = ""):
    if name:
        Notifier.warning(t("Panel solo failed: {name}", name=name))
    else:
        Notifier.warning(t("Panel solo failed"))


@require(w="MainWindow")
def reset_panel_layout(ctx, *, w):
    w.reset_panel_layout_to_default()
    AppLogger.info(f"panel layout reset: slot={getattr(w, 'slot_id', '')}")


@require(w="MainWindow")
def reset_floating_position(ctx, *, w):
    count = w.reset_floating_positions()
    AppLogger.info(f"floating positions reset: count={count} slot={getattr(w, 'slot_id', '')}")


@require(w="MainWindow")
def solo_panel(ctx, name: str = "", *, w):
    mgr = getattr(w, "_layout_manager", None)
    if mgr is None:
        AppLogger.warning("Panel solo failed: LayoutManager is not available")
        _notify_solo_failed()
        return
    target = _resolve_panel_name(name, mgr)
    if target is None:
        AppLogger.warning(f"Panel solo failed: unknown panel '{name}'")
        _notify_solo_failed(name)
        return
    if not mgr.solo_panel(target):
        _notify_solo_failed(target)


@require(w="MainWindow")
def solo_current_panel(ctx, *, w):
    mgr = getattr(w, "_layout_manager", None)
    if mgr is None:
        AppLogger.warning("Panel solo failed: LayoutManager is not available")
        _notify_solo_failed()
        return
    target = mgr.panel_at_widget(getattr(ctx, "_widget", None))
    if target is None:
        AppLogger.warning("Panel solo failed: command context is not inside a panel")
        _notify_solo_failed()
        return
    if not mgr.solo_panel(target):
        _notify_solo_failed(target)


class PanelCommands(ActionKit.MenuBase):
    NAME = "Panels"
    PRIORITY = 60

    _CORE_PANELS = ["Toolbar", "Folder Tree", "Search", "Grid View", "Content Viewer", "Meta Viewer"]

    @classmethod
    def commands(cls):
        from ...plugin.panel.handler import panel_registry

        items: list = [
            ":Edit",
            ActionKit.Command(
                path="win.toggle_layout_mode",
                display="Edit Mode (might have visual issues)",
                func=toggle_layout_mode,
                checkable=True,
                checked_resolver=_is_layout_edit,
            ),
            ActionKit.Command(
                path="panel.reset_layout",
                display=t("Reset Panel Layout"),
                func=reset_panel_layout,
            ),
            ActionKit.Command(
                path="panel.reset_floating",
                display=t("Reset Floating Position"),
                func=reset_floating_position,
            ),
            "-",
            ":Solo",
            ActionKit.Command(
                path="panel.solo_current",
                display=t("Solo This Panel"),
                func=solo_current_panel,
            ),
            ActionKit.Command(
                path="panel.solo",
                display=t("Solo Panel..."),
                params=[ActionKit.Param(name="name", value=_panel_name_choices, description=t("Panel name"), required=True)],
                func=solo_panel,
            ),
            "-",
        ]
        items.append(":Core")
        for name in cls._CORE_PANELS:
            items.append(LayoutManager._command_id(name))
        items.append("-")

        builtins = []
        plugins = []
        for plugin_cls in panel_registry.list_all():
            name = plugin_cls.DISPLAY_NAME or plugin_cls.NAME
            cmd_id = LayoutManager._command_id(name)
            if getattr(plugin_cls, "SOURCE", "Plugin") == "Builtin":
                builtins.append(cmd_id)
            else:
                plugins.append(cmd_id)

        if builtins:
            items.append(":Builtin")
            items.extend(builtins)
            items.append("-")
        if plugins:
            items.append(":Plugin")
            items.extend(plugins)
            items.append("-")
        return items
