from __future__ import annotations

from ...core.commands.bridge import ActionKit
from ...core.commands.command.require import require
from ...core.platform.process import AppProcess
from ...core.workspace import (
    BarSpec,
    PathPreset,
    QueryPreset,
    UIPreset,
    WorkspaceStore,
)
from ...ui.dialogs import InputDialog
from ...utils.logs import AppLogger
from ...utils.notifier import Notifier


def _store() -> WorkspaceStore:
    return WorkspaceStore.instance()


def _ask_name(parent, title: str, default: str = "") -> str:
    name = InputDialog.get_text(
        "Name:",
        title=title,
        buttons=("Save", "Cancel"),
        parent=parent,
        default=default,
    )
    return (name or "").strip()


def _unique_name(prefix: str, existing: list[str]) -> str:
    used = set(existing)
    i = 1
    while True:
        candidate = f"{prefix} {i}"
        if candidate not in used:
            return candidate
        i += 1


# ---------- UI preset ----------
@require(w="MainWindow")
def ui_preset_save_current(ctx, w, name: str = "") -> str:
    name = (name or "").strip() or _unique_name("UI", [p.name for p in _store().list_ui_presets()])
    state = w.ui_coord.capture()
    preset = UIPreset(
        name=name,
        window_state=state.get("window_state", {}),
        component_states=state.get("component_states", {}),
    )
    _store().save_ui_preset(preset)
    Notifier.info(f"UI preset saved: {name}")
    AppLogger.info(f"ui_preset saved: {name} ({preset.preset_id})")
    return preset.preset_id


@require(w="MainWindow")
def ui_preset_apply(ctx, w, preset_id: str = ""):
    preset = _store().get_ui_preset(preset_id)
    if not preset:
        Notifier.warning("UI preset not found")
        return
    w.ui_coord.restore({"window_state": preset.window_state, "component_states": preset.component_states})
    Notifier.info(f"UI preset applied: {preset.name}")


@require(w="MainWindow")
def ui_preset_rename(ctx, w, preset_id: str = "", name: str = ""):
    preset = _store().get_ui_preset(preset_id)
    if not preset:
        return
    name = (name or "").strip() or _ask_name(w, "Rename UI Preset", default=preset.name)
    if not name or name == preset.name:
        return
    if not _store().rename_ui_preset(preset_id, name):
        Notifier.warning(f"Name already exists: {name}")
        return
    Notifier.info(f"Renamed: {name}")


def ui_preset_delete(ctx, preset_id: str = ""):
    if _store().delete_ui_preset(preset_id):
        Notifier.info("UI preset deleted")


def ui_preset_set_color(ctx, preset_id: str = "", color: str = ""):
    _store().set_ui_preset_color(preset_id, color)


# ---------- Path preset ----------
@require(w="MainWindow")
def path_preset_save_current(ctx, w, name: str = "") -> str:
    name = (name or "").strip() or _unique_name("Path", [p.name for p in _store().list_path_presets()])
    state = w.path_coord.capture()
    preset = PathPreset(
        name=name,
        database_name=state.get("database_name", ""),
        expanded=list(state.get("expanded") or []),
        selected=list(state.get("selected") or []),
    )
    _store().save_path_preset(preset)
    Notifier.info(f"Path preset saved: {name}")
    AppLogger.info(f"path_preset saved: {name} ({preset.preset_id})")
    return preset.preset_id


@require(w="MainWindow")
def path_preset_apply(ctx, w, preset_id: str = ""):
    preset = _store().get_path_preset(preset_id)
    if not preset:
        Notifier.warning("Path preset not found")
        return
    w.path_coord.restore(
        {
            "database_name": preset.database_name,
            "expanded": preset.expanded,
            "selected": preset.selected,
        },
        on_complete=w.on_folder_selected,
    )
    Notifier.info(f"Path preset applied: {preset.name}")


@require(w="MainWindow")
def path_preset_rename(ctx, w, preset_id: str = "", name: str = ""):
    preset = _store().get_path_preset(preset_id)
    if not preset:
        return
    name = (name or "").strip() or _ask_name(w, "Rename Path Preset", default=preset.name)
    if not name or name == preset.name:
        return
    if not _store().rename_path_preset(preset_id, name):
        Notifier.warning(f"Name already exists: {name}")
        return
    Notifier.info(f"Renamed: {name}")


def path_preset_delete(ctx, preset_id: str = ""):
    if _store().delete_path_preset(preset_id):
        Notifier.info("Path preset deleted")


# ---------- Query preset ----------
@require(w="MainWindow")
def query_preset_save_current(ctx, w, name: str = "", include_sort: bool = False) -> str:
    name = (name or "").strip() or _unique_name("Filter", [p.name for p in _store().list_query_presets()])
    state = w.query_coord.capture()
    preset = QueryPreset(
        name=name,
        bars=[BarSpec.from_dict(b) for b in (state.get("bars") or [])],
        include_sort=bool(include_sort),
        sort_by=state.get("sort_by", "path"),
        ascending=bool(state.get("ascending", False)),
    )
    _store().save_query_preset(preset)
    Notifier.info(f"Query preset saved: {name}")
    AppLogger.info(f"query_preset saved: {name} ({preset.preset_id})")
    return preset.preset_id


@require(w="MainWindow")
def query_preset_apply(ctx, w, preset_id: str = "", mode: str = "replace"):
    preset = _store().get_query_preset(preset_id)
    if not preset:
        Notifier.warning("Query preset not found")
        return
    bars = [b.to_dict() for b in preset.bars]
    w.search_row_widget.apply_bars(bars, mode=mode if mode in ("replace", "append") else "replace")
    if preset.include_sort:
        w.search_row_widget.set_sort(preset.sort_by, preset.ascending)
    w.sync_service_from_ui()
    Notifier.info(f"Query preset applied: {preset.name}")


@require(w="MainWindow")
def query_preset_rename(ctx, w, preset_id: str = "", name: str = ""):
    preset = _store().get_query_preset(preset_id)
    if not preset:
        return
    name = (name or "").strip() or _ask_name(w, "Rename Query Preset", default=preset.name)
    if not name or name == preset.name:
        return
    if not _store().rename_query_preset(preset_id, name):
        Notifier.warning(f"Name already exists: {name}")
        return
    Notifier.info(f"Renamed: {name}")


def query_preset_delete(ctx, preset_id: str = ""):
    if _store().delete_query_preset(preset_id):
        Notifier.info("Query preset deleted")


# ---------- Workspace popup / window ----------
@require(w="MainWindow")
def open_popup(ctx, w):
    existing = getattr(w, "_workspace_popup", None)
    if existing and existing.isVisible():
        existing.close()
        return
    from wafer.app.viewer.widgets.workspace_popup import WorkspacePopup

    popup = WorkspacePopup(ctx=ctx, parent=w)
    w._workspace_popup = popup
    btn = getattr(w, "_workspace_button", None)
    if btn:
        popup.show_below(btn)
    else:
        popup.show()


def new_window(ctx):
    AppProcess.new_main("--viewer")
    AppLogger.info("new_window: spawned new viewer")


class WorkspaceCommands(ActionKit.MenuBase):
    NAME = "Workspace"
    PRIORITY = 70

    @classmethod
    def commands(cls):
        return [
            ":Workspace",
            ActionKit.Command(path="ws.open_popup", display="Workspace...", func=open_popup),
            "-",
            ActionKit.Command(
                path="ui_preset.save_current",
                display="Save UI Preset",
                func=ui_preset_save_current,
                params=[ActionKit.Param(name="name", value="")],
            ),
            ActionKit.Command(
                path="ui_preset.apply",
                display="Apply UI Preset",
                func=ui_preset_apply,
                params=[ActionKit.Param(name="preset_id", value="")],
            ),
            ActionKit.Command(
                path="ui_preset.rename",
                display="Rename UI Preset",
                func=ui_preset_rename,
                params=[ActionKit.Param(name="preset_id", value=""), ActionKit.Param(name="name", value="")],
            ),
            ActionKit.Command(
                path="ui_preset.delete",
                display="Delete UI Preset",
                func=ui_preset_delete,
                params=[ActionKit.Param(name="preset_id", value="")],
            ),
            ActionKit.Command(
                path="ui_preset.set_color",
                display="Set UI Preset Color",
                func=ui_preset_set_color,
                params=[ActionKit.Param(name="preset_id", value=""), ActionKit.Param(name="color", value="")],
            ),
            "-",
            ActionKit.Command(
                path="path_preset.save_current",
                display="Save Path Preset",
                func=path_preset_save_current,
                params=[ActionKit.Param(name="name", value="")],
            ),
            ActionKit.Command(
                path="path_preset.apply",
                display="Apply Path Preset",
                func=path_preset_apply,
                params=[ActionKit.Param(name="preset_id", value="")],
            ),
            ActionKit.Command(
                path="path_preset.rename",
                display="Rename Path Preset",
                func=path_preset_rename,
                params=[ActionKit.Param(name="preset_id", value=""), ActionKit.Param(name="name", value="")],
            ),
            ActionKit.Command(
                path="path_preset.delete",
                display="Delete Path Preset",
                func=path_preset_delete,
                params=[ActionKit.Param(name="preset_id", value="")],
            ),
            "-",
            ActionKit.Command(
                path="query_preset.save_current",
                display="Save Query Preset",
                func=query_preset_save_current,
                params=[
                    ActionKit.Param(name="name", value=""),
                    ActionKit.Param(name="include_sort", value=False),
                ],
            ),
            ActionKit.Command(
                path="query_preset.apply",
                display="Apply Query Preset",
                func=query_preset_apply,
                params=[
                    ActionKit.Param(name="preset_id", value=""),
                    ActionKit.Param(name="mode", value="replace"),
                ],
            ),
            ActionKit.Command(
                path="query_preset.rename",
                display="Rename Query Preset",
                func=query_preset_rename,
                params=[ActionKit.Param(name="preset_id", value=""), ActionKit.Param(name="name", value="")],
            ),
            ActionKit.Command(
                path="query_preset.delete",
                display="Delete Query Preset",
                func=query_preset_delete,
                params=[ActionKit.Param(name="preset_id", value="")],
            ),
        ]
