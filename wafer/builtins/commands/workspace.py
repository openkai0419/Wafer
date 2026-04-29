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
def ui_preset_apply(ctx, w, preset_id: str = "", restore_window_state: bool = True):
    preset = _store().get_ui_preset(preset_id)
    if not preset:
        Notifier.warning("UI preset not found")
        return
    w.ui_coord.restore(
        {"window_state": preset.window_state, "component_states": preset.component_states},
        skip_window_state=not bool(restore_window_state),
    )
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


@require(w="MainWindow")
def ui_preset_overwrite(ctx, w, preset_id: str = ""):
    preset = _store().get_ui_preset(preset_id)
    if not preset:
        Notifier.warning("UI preset not found")
        return
    state = w.ui_coord.capture()
    ok = _store().update_ui_preset(
        preset_id,
        state.get("window_state", {}),
        state.get("component_states", {}),
    )
    if ok:
        Notifier.info(f"UI preset overwritten: {preset.name}")
        AppLogger.info(f"ui_preset overwritten: {preset.name} ({preset_id})")


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


@require(w="MainWindow")
def path_preset_overwrite(ctx, w, preset_id: str = ""):
    preset = _store().get_path_preset(preset_id)
    if not preset:
        Notifier.warning("Path preset not found")
        return
    state = w.path_coord.capture()
    ok = _store().update_path_preset(
        preset_id,
        state.get("database_name", ""),
        list(state.get("expanded") or []),
        list(state.get("selected") or []),
    )
    if ok:
        Notifier.info(f"Path preset overwritten: {preset.name}")
        AppLogger.info(f"path_preset overwritten: {preset.name} ({preset_id})")


# ---------- Query preset ----------
@require(w="MainWindow")
def query_preset_save_current(ctx, w, name: str = "") -> str:
    name = (name or "").strip() or _unique_name("Filter", [p.name for p in _store().list_query_presets()])
    state = w.query_coord.capture()
    preset = QueryPreset(
        name=name,
        bars=[BarSpec.from_dict(b) for b in (state.get("bars") or [])],
        sort_by=state.get("sort_by", "path"),
        ascending=bool(state.get("ascending", False)),
    )
    _store().save_query_preset(preset)
    Notifier.info(f"Query preset saved: {name}")
    AppLogger.info(f"query_preset saved: {name} ({preset.preset_id})")
    return preset.preset_id


@require(w="MainWindow")
def query_preset_apply(ctx, w, preset_id: str = "", mode: str = "replace", restore_sort: bool = True):
    preset = _store().get_query_preset(preset_id)
    if not preset:
        Notifier.warning("Query preset not found")
        return
    bars = [b.to_dict() for b in preset.bars]
    w.search_row_widget.apply_bars(bars, mode=mode if mode in ("replace", "append") else "replace")
    if restore_sort:
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


@require(w="MainWindow")
def query_preset_overwrite(ctx, w, preset_id: str = ""):
    preset = _store().get_query_preset(preset_id)
    if not preset:
        Notifier.warning("Query preset not found")
        return
    state = w.query_coord.capture()
    ok = _store().update_query_preset(
        preset_id,
        [BarSpec.from_dict(b) for b in (state.get("bars") or [])],
        state.get("sort_by", "path"),
        bool(state.get("ascending", False)),
    )
    if ok:
        Notifier.info(f"Query preset overwritten: {preset.name}")
        AppLogger.info(f"query_preset overwritten: {preset.name} ({preset_id})")


@require(w="MainWindow")
def restore_slot(ctx, w, slot_id: str = ""):
    slot = _store().get_slot(slot_id)
    if not slot:
        Notifier.warning("Workspace slot not found")
        return
    if slot_id != getattr(w, "slot_id", ""):
        w._save_slot()
    w._restore_from_slot(slot)
    Notifier.info("Workspace restored")


@require(w="MainWindow")
def rename_slot(ctx, w, slot_id: str = "", name: str = ""):
    store = _store()
    slot = store.get_slot(slot_id)
    if not slot:
        Notifier.warning("Workspace slot not found")
        return
    new_name = str(name or "").strip()
    if not new_name:
        new_name = _ask_name(w, "Rename Workspace Slot", default=slot.name)
    if not new_name or new_name == slot.name:
        return
    if store.rename_slot(slot_id, new_name):
        Notifier.info(f"Workspace slot renamed: {new_name}")
        AppLogger.info(f"workspace slot renamed: {new_name} ({slot_id})")


@require(w="MainWindow")
def delete_slot(ctx, w, slot_id: str = ""):
    store = _store()
    if not store.get_slot(slot_id):
        Notifier.warning("Workspace slot not found")
        return
    if store.forget_slot_snapshot(slot_id):
        Notifier.info("Workspace slot removed from Recent")
        AppLogger.info(f"workspace slot snapshot removed: {slot_id}")


@require(tb="WorkspaceToolbarWidget")
def show_ui_popup(ctx, tb):
    tb.show_ui_popup()


@require(tb="WorkspaceToolbarWidget")
def show_path_popup(ctx, tb):
    tb.show_path_popup()


@require(tb="WorkspaceToolbarWidget")
def show_filter_popup(ctx, tb):
    tb.show_filter_popup()


@require(tb="WorkspaceToolbarWidget")
def show_recent_popup(ctx, tb):
    tb.show_recent_popup()


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
            ActionKit.Command(
                path="ws.show_ui_popup",
                display="UI",
                func=show_ui_popup,
            ),
            ActionKit.Command(
                path="ws.show_path_popup",
                display="Path",
                func=show_path_popup,
            ),
            ActionKit.Command(
                path="ws.show_filter_popup",
                display="Filter",
                func=show_filter_popup,
            ),
            ActionKit.Command(
                path="ws.show_recent_popup",
                display="Recent",
                func=show_recent_popup,
            ),
            ActionKit.Command(
                path="ws.restore_slot",
                display="Restore Workspace Slot",
                func=restore_slot,
                hidden=True,
                params=[ActionKit.Param(name="slot_id", value="")],
            ),
            ActionKit.Command(
                path="ws.rename_slot",
                display="Rename Workspace Slot",
                func=rename_slot,
                hidden=True,
                params=[ActionKit.Param(name="slot_id", value=""), ActionKit.Param(name="name", value="")],
            ),
            ActionKit.Command(
                path="ws.delete_slot",
                display="Delete Workspace Slot",
                func=delete_slot,
                hidden=True,
                params=[ActionKit.Param(name="slot_id", value="")],
            ),
            "-",
            ":UI",
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
                params=[ActionKit.Param(name="preset_id", value=""), ActionKit.Param(name="restore_window_state", value=True)],
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
                path="ui_preset.overwrite",
                display="Overwrite UI Preset",
                func=ui_preset_overwrite,
                params=[ActionKit.Param(name="preset_id", value="")],
            ),
            "-",
            ":Path",
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
            ActionKit.Command(
                path="path_preset.overwrite",
                display="Overwrite Path Preset",
                func=path_preset_overwrite,
                params=[ActionKit.Param(name="preset_id", value="")],
            ),
            "-",
            ":Query",
            ActionKit.Command(
                path="query_preset.save_current",
                display="Save Query Preset",
                func=query_preset_save_current,
                params=[ActionKit.Param(name="name", value="")],
            ),
            ActionKit.Command(
                path="query_preset.apply",
                display="Apply Query Preset",
                func=query_preset_apply,
                params=[
                    ActionKit.Param(name="preset_id", value=""),
                    ActionKit.Param(name="mode", value="replace"),
                    ActionKit.Param(name="restore_sort", value=True),
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
            ActionKit.Command(
                path="query_preset.overwrite",
                display="Overwrite Query Preset",
                func=query_preset_overwrite,
                params=[ActionKit.Param(name="preset_id", value="")],
            ),
        ]
