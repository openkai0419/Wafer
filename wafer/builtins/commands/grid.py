import os
from dataclasses import dataclass

from PySide6 import QtCore, QtGui

from ...core.commands.bridge import ActionKit
from ...core.commands.binding.instance_registry import InstanceRegistry
from ...core.lang.manager import t
from ...utils.logs import AppLogger
from ...utils.paths import normalize_path, containing_dir
from ...utils.formatting import dpix
from ...core.platform.dragparser import MimeDataParser
from ...core.platform.paste import drop_files_with_ui, get_saved_drop_operation
from ...core.qt.pixmap import PixmapFactory
from ...ui.dialogs import ConfirmDialog, DropTargetDialog

INTERNAL_MIME_TYPE = b"application/x-gridview-internal" + f"{os.getpid()}".encode()

ORIENTATION_CHOICES = ["Z(↘)", "S(↙)", "И(↘)", "N(↙)"]
_CMD_IDS = ["grid.orientation_z", "grid.orientation_reverse_z", "grid.orientation_n", "grid.orientation_reverse_n"]
_CMD_TO_CHOICE = dict(zip(_CMD_IDS, ORIENTATION_CHOICES))
_CHOICE_TO_CMD = dict(zip(ORIENTATION_CHOICES, _CMD_IDS))
_CHOICE_TO_INDEX = {c: i for i, c in enumerate(ORIENTATION_CHOICES)}

_INDEX_TO_ORI_CMD = {i: cmd for i, cmd in enumerate(_CMD_IDS)}


@dataclass(frozen=True, slots=True)
class GridDropTarget:
    directory: str
    kind: str
    index: int | None = None


def _grid():
    return InstanceRegistry.instance().get_one("GridView")


def _overlay_host():
    return InstanceRegistry.instance().get_one("GridOverlayHost")


def _overlay_badge_visible():
    host = _overlay_host()
    return host is not None and host.badge_visible()


def _cell_overlay_visible(name: str):
    host = _overlay_host()
    return host is not None and host.cell_overlay_visible(name)


def _get_layout_modes():
    from ...plugin.layout.handler import layout_registry

    layouts = layout_registry.list_all()
    if not layouts:
        return [], {}, {}, {}, {}
    labels = [cls.DISPLAY_NAME for cls in layouts]
    values = {cls.DISPLAY_NAME: cls.NAME for cls in layouts}
    cmds = {cls.DISPLAY_NAME: f"grid.layout_{cls.NAME}" for cls in layouts}
    cmd_to_label = {v: k for k, v in cmds.items()}
    value_to_cmd = {v: cmds[k] for k, v in values.items()}
    return labels, values, cmds, cmd_to_label, value_to_cmd


def _get_cycle_choices():
    labels, *_ = _get_layout_modes()
    return [f"{m} {o}" for m in labels for o in ORIENTATION_CHOICES]


def _orientation_checked(idx: int):
    g = _grid()
    return g is not None and getattr(g, "orientation", -1) == idx


def _layout_checked(name: str):
    g = _grid()
    return g is not None and getattr(g, "layout_mode", "") == name


def _scroll_anchor_checked(anchor: str):
    g = _grid()
    return g is not None and getattr(g, "scroll_anchor", "center") == anchor


def _scroll_follow_checked():
    g = _grid()
    return g is not None and getattr(g, "follow_selection_on_update", False)


def _autoscroll_checked():
    g = _grid()
    return g is not None and g.is_scrolling()


class GridViewCommands(ActionKit.MenuBase):
    NAME = "GridView"
    PRIORITY = 40

    @staticmethod
    def get_view(ctx):
        return ctx.get_instance("GridView")

    @staticmethod
    def get_items(ctx):
        items = ctx.get_instance("GridItemModel")
        return items or GridViewCommands.get_view(ctx).items

    @staticmethod
    def get_file_viewer(ctx):
        return ctx.get_instance("FileViewerController")

    @staticmethod
    def get_file_list_provider(ctx):
        return ctx.get_instance("FileListProvider")

    @staticmethod
    def _resolve_index(ctx, index: int | None) -> tuple[int, str] | None:
        if index is None:
            return None
        items = GridViewCommands.get_items(ctx)
        idx = int(index)
        path = items.path_at(idx)
        if not path:
            return None
        return idx, path

    @staticmethod
    def _show_index(ctx, index: int | None):
        resolved = GridViewCommands._resolve_index(ctx, index)
        if resolved is None:
            return
        _, path = resolved
        GridViewCommands.get_file_list_provider(ctx).on_file_set(path)

    @staticmethod
    def _scroll_to_index(ctx, index: int | None):
        resolved = GridViewCommands._resolve_index(ctx, index)
        if resolved is None:
            return
        idx, _ = resolved
        view = GridViewCommands.get_view(ctx)
        view.scroll_to_index(int(idx), animated=True)

    @staticmethod
    def click_select_at_pos(ctx):
        view = GridViewCommands.get_view(ctx)
        items = GridViewCommands.get_items(ctx)
        idx = view.index_at_pos(ctx.pos)
        if idx is None:
            return
        idx = int(idx)
        if not items.is_selected(idx) or items.selected_count() > 1:
            items.set_selected([idx], last=0)
        else:
            items.deselect(idx)

    @staticmethod
    def select_at_pos(ctx):
        view = GridViewCommands.get_view(ctx)
        items = GridViewCommands.get_items(ctx)
        idx = view.index_at_pos(ctx.pos)
        if idx is None:
            return
        items.set_selected([int(idx)], last=0)

    @staticmethod
    def toggle_at_pos(ctx):
        view = GridViewCommands.get_view(ctx)
        items = GridViewCommands.get_items(ctx)
        idx = view.index_at_pos(ctx.pos)
        if idx is None:
            return
        items.toggle_selection(int(idx))

    @staticmethod
    def range_select_at_pos(ctx):
        view = GridViewCommands.get_view(ctx)
        items = GridViewCommands.get_items(ctx)
        idx = view.index_at_pos(ctx.pos)
        if idx is None:
            return
        idx = int(idx)
        last = items.last_selected_index()
        if last is None:
            items.add_selection([idx], last=0)
            return
        if last < idx:
            items.add_selection(list(range(last, idx + 1)), last=-1)
        else:
            items.add_selection(list(range(idx, last + 1)), last=0)

    @staticmethod
    def show_at_pos(ctx):
        view = GridViewCommands.get_view(ctx)
        GridViewCommands.get_items(ctx)
        idx = view.index_at_pos(ctx.pos)
        if idx is None:
            return
        idx = int(idx)
        GridViewCommands._show_index(ctx, idx)

    @staticmethod
    def select_all(ctx):
        items = GridViewCommands.get_items(ctx)
        n = items.count()
        if n <= 0:
            items.clear_selection()
            return
        items.set_selected(list(range(n)), last=-1)

    @staticmethod
    def clear_selection(ctx):
        GridViewCommands.get_items(ctx).clear_selection()

    @staticmethod
    def _scroll_by_wheel(ctx, direction: int):
        view = GridViewCommands.get_view(ctx)
        scroll = getattr(view, "parent_scroll", None)
        if scroll is None or not hasattr(scroll, "_primary_bar"):
            return
        if hasattr(scroll, "stop_auto_scroll") and callable(scroll.stop_auto_scroll):
            scroll.stop_auto_scroll()
        bar = scroll._primary_bar()
        steps = int(ctx.get("wheel_steps") or 1)
        step = int(getattr(bar, "singleStep", lambda: 25)() or 25)
        multiplier = int(ctx.get("multiplier") or 4)
        delta = max(1, step * max(1, multiplier)) * max(1, steps)
        if hasattr(scroll, "_is_primary_reversed") and scroll._is_primary_reversed():
            direction = -direction
        bar.setValue(int(bar.value()) + int(direction) * int(delta))

    @staticmethod
    def wheel_scroll_up(ctx, multiplier: int = 4):
        ctx.put("multiplier", int(multiplier))
        GridViewCommands._scroll_by_wheel(ctx, -1)

    @staticmethod
    def wheel_scroll_down(ctx, multiplier: int = 4):
        ctx.put("multiplier", int(multiplier))
        GridViewCommands._scroll_by_wheel(ctx, 1)

    @staticmethod
    def _clamp(v: int, lo: int, hi: int) -> int:
        return max(int(lo), min(int(v), int(hi)))

    @staticmethod
    def set_scale(ctx, height: int):
        view = GridViewCommands.get_view(ctx)
        lo = getattr(view, "min_height", 1)
        hi = getattr(view, "max_height", max(int(lo), 1))
        h = GridViewCommands._clamp(int(height), int(lo), int(hi))
        if int(getattr(view, "base_height", 0)) == h:
            return
        view.base_height = h
        view.base_height_changed.emit()
        view._debounce_recalc_layout()

    @staticmethod
    def scale_up(ctx, ratio: float = 1.1):
        view = GridViewCommands.get_view(ctx)
        cur = int(getattr(view, "base_height", 0) or 0)
        if cur <= 0:
            return
        steps = int(ctx.get("wheel_steps") or 1)
        r = float(ratio) ** float(max(1, steps))
        GridViewCommands.set_scale(ctx, int(cur * r))

    @staticmethod
    def scale_down(ctx, ratio: float = 1.1):
        view = GridViewCommands.get_view(ctx)
        cur = int(getattr(view, "base_height", 0) or 0)
        if cur <= 0:
            return
        r = float(ratio)
        if r <= 0.0:
            return
        steps = int(ctx.get("wheel_steps") or 1)
        rr = float(r) ** float(max(1, steps))
        GridViewCommands.set_scale(ctx, int(cur / rr))

    @staticmethod
    def scale_reset(ctx):
        view = GridViewCommands.get_view(ctx)
        w = getattr(view, "screen_width", None)
        if w is None:
            return
        GridViewCommands.set_scale(ctx, int(int(w) / 10))

    @staticmethod
    def toggle_autoscroll(ctx, speed: int = 50, loop: bool = False, query_on_loop: bool = False):
        view = GridViewCommands.get_view(ctx)
        scroll = getattr(view, "parent_scroll", None)
        if scroll is None:
            return
        if scroll.is_scrolling():
            scroll.stop_auto_scroll()
        else:
            base_speed = int(speed)
            adjusted = view.get_adjusted_scroll_speed(base_speed) if hasattr(view, "get_adjusted_scroll_speed") else float(base_speed)
            scroll.start_auto_scroll(adjusted, base_speed, loop=bool(loop), query_on_loop=bool(query_on_loop))

    @staticmethod
    def autoscroll_speed_up(ctx, step: int = 10):
        view = GridViewCommands.get_view(ctx)
        scroll = getattr(view, "parent_scroll", None)
        if scroll is None or not scroll.is_scrolling():
            return
        new_base = scroll._autoscroll_base_speed + int(step)
        adjusted = view.get_adjusted_scroll_speed(new_base)
        scroll.start_auto_scroll(adjusted, new_base)

    @staticmethod
    def autoscroll_speed_down(ctx, step: int = 10):
        view = GridViewCommands.get_view(ctx)
        scroll = getattr(view, "parent_scroll", None)
        if scroll is None or not scroll.is_scrolling():
            return
        new_base = max(1, scroll._autoscroll_base_speed - int(step))
        adjusted = view.get_adjusted_scroll_speed(new_base)
        scroll.start_auto_scroll(adjusted, new_base)

    @staticmethod
    def toggle_overlay(ctx):
        host = _overlay_host()
        if host is None:
            return
        host.set_badge_visible(not host.badge_visible())

    @staticmethod
    def set_overlay_size(ctx, size: int = 8):
        host = _overlay_host()
        if host is None:
            return
        host.set_badge_radius(int(size))

    @staticmethod
    def toggle_cell_overlay(ctx, name: str = ""):
        host = _overlay_host()
        if host is None or not name:
            return
        host.set_cell_overlay_visible(name, not host.cell_overlay_visible(name))

    @staticmethod
    def move_to_next_row(ctx):
        view = GridViewCommands.get_view(ctx)
        view.scroll_to_next_row(animated=True)

    @staticmethod
    def move_to_prev_row(ctx):
        view = GridViewCommands.get_view(ctx)
        view.scroll_to_prev_row(animated=True)

    @staticmethod
    def set_scroll_anchor_top(ctx):
        GridViewCommands.get_view(ctx).set_scroll_anchor("top")

    @staticmethod
    def set_scroll_anchor_center(ctx):
        GridViewCommands.get_view(ctx).set_scroll_anchor("center")

    @staticmethod
    def toggle_scroll_follow_selection(ctx):
        view = GridViewCommands.get_view(ctx)
        view.set_follow_selection_on_update(not getattr(view, "follow_selection_on_update", False))

    @staticmethod
    def set_orientation_z(ctx):
        GridViewCommands.get_view(ctx).set_orientation(0)

    @staticmethod
    def set_orientation_reverse_z(ctx):
        GridViewCommands.get_view(ctx).set_orientation(1)

    @staticmethod
    def set_orientation_n(ctx):
        GridViewCommands.get_view(ctx).set_orientation(2)

    @staticmethod
    def set_orientation_reverse_n(ctx):
        GridViewCommands.get_view(ctx).set_orientation(3)

    @staticmethod
    def set_layout(ctx, mode):
        GridViewCommands.get_view(ctx).set_layout_mode(mode)

    @classmethod
    def _layout_commands(cls):
        from ...plugin.layout.handler import layout_registry

        cmds = []
        for layout_cls in layout_registry.list_all():
            name = layout_cls.NAME
            display = layout_cls.DISPLAY_NAME
            cmds.append(
                ActionKit.Command(
                    path=f"Layout/grid.layout_{name}",
                    display=display,
                    func=lambda ctx, m=name: cls.set_layout(ctx, m),
                    action_group="grid_layout_mode",
                    checked=lambda n=name: _layout_checked(n),
                )
            )
        return cmds

    @staticmethod
    def cycle_orientation(ctx, reverse=False, **kwargs):
        cycle_choices = _get_cycle_choices()
        enabled = [k for k in cycle_choices if kwargs.get(k, True)]
        if not enabled:
            return
        labels, values, _, cmd_to_label, _ = _get_layout_modes()
        view = GridViewCommands.get_view(ctx)
        cur_ori = getattr(view, "orientation", 0)
        cur_mode_name = getattr(view, "layout_mode", "")
        ori_label = ORIENTATION_CHOICES[cur_ori] if 0 <= cur_ori < len(ORIENTATION_CHOICES) else ORIENTATION_CHOICES[0]
        cur_mode_cmd = f"grid.layout_{cur_mode_name}"
        mode_label = cmd_to_label.get(cur_mode_cmd, labels[0] if labels else "")
        current_key = f"{mode_label} {ori_label}"
        step = -1 if reverse else 1
        try:
            idx = enabled.index(current_key)
            next_key = enabled[(idx + step) % len(enabled)]
        except (ValueError, IndexError):
            next_key = enabled[-1 if reverse else 0]
        next_mode, next_ori = next_key.rsplit(" ", 1)
        view.set_layout_mode(values[next_mode])
        view.set_orientation(_CHOICE_TO_INDEX[next_ori])

    @classmethod
    def commands(cls):
        return [
            ":GridView",
            "-",
            ":Selection",
            ActionKit.Command(path="grid.click_select_at_pos", display="Click Select", func=cls.click_select_at_pos),
            ActionKit.Command(path="grid.toggle_at_pos", display="Toggle Select", func=cls.toggle_at_pos),
            ActionKit.Command(path="grid.range_select_at_pos", display="Range Select", func=cls.range_select_at_pos),
            ActionKit.Command(path="grid.select_at_pos", display="Select", func=cls.select_at_pos, hidden=True),
            ActionKit.Command(path="grid.select_all", display="Select All", func=cls.select_all),
            ActionKit.Command(path="grid.clear_selection", display="Clear Selection", func=cls.clear_selection),
            "-",
            ":Viewer",
            ActionKit.Command(path="grid.show_at_pos", display="Show at Pos", func=cls.show_at_pos),
            "file.show_file",
            "-",
            ":Scroll",
            ActionKit.Command(path="grid.scroll_up", display="Scroll Up", func=cls.wheel_scroll_up, params=[ActionKit.Param(name="multiplier", value=1.5)]),
            ActionKit.Command(path="grid.scroll_down", display="Scroll Down", func=cls.wheel_scroll_down, params=[ActionKit.Param(name="multiplier", value=1.5)]),
            ActionKit.Command(path="grid.move_to_next_row", display="Next Row", func=cls.move_to_next_row),
            ActionKit.Command(path="grid.move_to_prev_row", display="Prev Row", func=cls.move_to_prev_row),
            "-",
            ":Settings",
            ActionKit.Command(
                path="grid.toggle_overlay",
                display="Show overlay badges",
                func=cls.toggle_overlay,
                checked=_overlay_badge_visible,
            ),
            ActionKit.Command(
                path="grid.set_overlay_size",
                display="Overlay badge size",
                func=cls.set_overlay_size,
                params=[ActionKit.Param(name="size", value=8, min_value=4, max_value=40)],
            ),
            ActionKit.Command(
                path="grid.toggle_cell_overlay",
                display="Toggle cell overlay",
                func=cls.toggle_cell_overlay,
                params=[ActionKit.Param(name="name", value="", required=True)],
            ),
            ActionKit.Command(
                path="grid.toggle_scroll_follow_selection",
                display="Scroll to selection on update",
                func=cls.toggle_scroll_follow_selection,
                checked=_scroll_follow_checked,
            ),
            "Scroll Anchor/:Scroll Anchor",
            ActionKit.Command(
                path="Scroll Anchor/grid.scroll_anchor_top",
                display="Top",
                func=cls.set_scroll_anchor_top,
                action_group="grid_scroll_anchor",
                checked=lambda: _scroll_anchor_checked("top"),
            ),
            ActionKit.Command(
                path="Scroll Anchor/grid.scroll_anchor_center",
                display="Center",
                func=cls.set_scroll_anchor_center,
                action_group="grid_scroll_anchor",
                checked=lambda: _scroll_anchor_checked("center"),
            ),
            "Layout/:Layout",
            *cls._layout_commands(),
            ActionKit.Command(
                path="Layout/grid.orientation_z",
                display="Z (↘)",
                func=cls.set_orientation_z,
                action_group="grid_orientation",
                checked=lambda: _orientation_checked(0),
            ),
            ActionKit.Command(
                path="Layout/grid.orientation_reverse_z",
                display="S (↙)",
                func=cls.set_orientation_reverse_z,
                action_group="grid_orientation",
                checked=lambda: _orientation_checked(1),
            ),
            ActionKit.Command(
                path="Layout/grid.orientation_n",
                display="И (↘)",
                func=cls.set_orientation_n,
                action_group="grid_orientation",
                checked=lambda: _orientation_checked(2),
            ),
            ActionKit.Command(
                path="Layout/grid.orientation_reverse_n",
                display="N (↙)",
                func=cls.set_orientation_reverse_n,
                action_group="grid_orientation",
                checked=lambda: _orientation_checked(3),
            ),
            ActionKit.Command(
                path="grid.cycle_orientation",
                display="Cycle Orientation",
                func=cls.cycle_orientation,
                params=[ActionKit.Param(name=k, value=True) for k in _get_cycle_choices()] + [ActionKit.Param(name="reverse", value=False)],
            ),
            "-",
            ":Scale",
            ActionKit.Command(path="grid.scale_up", display="Scale Up", func=cls.scale_up, params=[ActionKit.Param(name="ratio", value=1.1)]),
            ActionKit.Command(path="grid.scale_down", display="Scale Down", func=cls.scale_down, params=[ActionKit.Param(name="ratio", value=1.1)]),
            ActionKit.Command(path="grid.set_scale", display="Set Scale", func=cls.set_scale, params=[ActionKit.Param(name="height", value=500)]),
            ActionKit.Command(path="grid.scale_reset", display="Reset Scale", func=cls.scale_reset),
            "-",
            ActionKit.Command(
                path="grid.toggle_autoscroll",
                display="AutoScroll",
                func=cls.toggle_autoscroll,
                checked=_autoscroll_checked,
                params=[
                    ActionKit.Param(name="speed", value=50, min_value=1, max_value=500),
                    ActionKit.Param(name="loop", value=False),
                    ActionKit.Param(name="query_on_loop", value=False),
                ],
            ),
            ActionKit.Command(
                path="grid.autoscroll_speed_up", display="AutoScroll Speed Up", func=cls.autoscroll_speed_up, params=[ActionKit.Param(name="step", value=10, min_value=1, max_value=100)]
            ),
            ActionKit.Command(
                path="grid.autoscroll_speed_down", display="AutoScroll Speed Down", func=cls.autoscroll_speed_down, params=[ActionKit.Param(name="step", value=10, min_value=1, max_value=100)]
            ),
            "-",
        ]


class GridViewDragCommands(ActionKit.DragMenuBase):
    NAME = "GridView"

    @staticmethod
    def _noop(ctx):
        return

    @staticmethod
    def drag_files_start(ctx):
        view = GridViewCommands.get_view(ctx)
        items = GridViewCommands.get_items(ctx)
        pos = ctx.pos
        index = view.index_at_pos(pos)
        if index is None:
            return
        if not items.is_selected(int(index)):
            items.set_selected([int(index)], last=0)
        selected = items.selected_sources()
        urls = [QtCore.QUrl.fromLocalFile(str(p)) for p in selected if p]
        if not urls:
            return
        drag = QtGui.QDrag(view)
        mime = QtCore.QMimeData()
        mime.setUrls(urls)
        mime.setData(INTERNAL_MIME_TYPE.decode(), QtCore.QByteArray(b"1"))
        drag.setMimeData(mime)
        pixmap = view.grab_widget_pixmap(int(index)) if hasattr(view, "grab_widget_pixmap") else None
        if pixmap is not None:
            pixmap = QtGui.QPixmap(pixmap)
            pixmap = pixmap.scaled(QtCore.QSize(dpix(150), dpix(150)), QtCore.Qt.KeepAspectRatio, QtCore.Qt.FastTransformation)
            transparent = QtGui.QPixmap(pixmap.size())
            transparent.fill(QtCore.Qt.transparent)
            painter = QtGui.QPainter(transparent)
            painter.setOpacity(0.5)
            painter.drawPixmap(0, 0, pixmap)
            painter.end()
            pixmap = transparent
            if len(urls) > 1:
                pixmap = PixmapFactory.draw_centered_text_with_background(pixmap, f" {len(urls)}  ")
            drag.setPixmap(pixmap)
            drag.setHotSpot(pixmap.rect().topLeft())

        def _run_drag():
            from ...core.commands.binding.mouse.manager import MouseStateManager

            try:
                drag.exec(QtCore.Qt.CopyAction | QtCore.Qt.MoveAction)
            finally:
                MouseStateManager.instance().end_internal_drag(view)

        QtCore.QTimer.singleShot(0, _run_drag)

    @staticmethod
    def _rect_select_start(view, mode: str, pos):
        view._rect_select_mode = str(mode or "replace")
        view._rect_select_dragging = True
        scene_pos = view.to_scene_pos(pos) if hasattr(view, "to_scene_pos") else pos
        view._rect_select_start_pos = scene_pos
        view._rect_select_current_pos = scene_pos
        view.viewport().update()

    @staticmethod
    def _rect_select_move(view, pos):
        if not view._rect_select_dragging:
            return
        view._rect_select_current_pos = view.to_scene_pos(pos) if hasattr(view, "to_scene_pos") else pos
        view.viewport().update()

    @staticmethod
    def _rect_select_end(view, items):
        if not view._rect_select_dragging:
            return
        start = view._rect_select_start_pos
        cur = view._rect_select_current_pos
        view._rect_select_dragging = False
        view._rect_select_start_pos = None
        view._rect_select_current_pos = None
        if start is None or cur is None:
            view.viewport().update()
            return
        rect = QtCore.QRect(start, cur).normalized()
        selected_indices = view.rects.intersecting_indices(rect) if view.rects else []
        if selected_indices:
            if view._rect_select_mode == "remove":
                items.remove_selection(selected_indices)
            elif view._rect_select_mode == "add":
                items.add_selection(selected_indices, last=-1)
            else:
                items.set_selected(selected_indices, last=-1)
        view.viewport().update()

    @staticmethod
    def rect_select_move(ctx):
        GridViewDragCommands._rect_select_move(GridViewCommands.get_view(ctx), ctx.pos)

    @staticmethod
    def rect_select_end(ctx):
        GridViewDragCommands._rect_select_end(GridViewCommands.get_view(ctx), GridViewCommands.get_items(ctx))

    @classmethod
    def commands(cls):
        return [
            ActionKit.Command(
                path="grid.drag_files",
                display="Drag Files",
                category="drag",
                drag_callbacks={"start": cls.drag_files_start, "move": cls._noop, "end": cls._noop},
                target_widgets=["GridView"],
            ),
            ActionKit.Command(
                path="grid.rect_select_replace",
                display="Rect Select Replace",
                category="drag",
                drag_callbacks={
                    "start": lambda ctx: GridViewDragCommands._rect_select_start(GridViewCommands.get_view(ctx), "replace", ctx.pos),
                    "move": cls.rect_select_move,
                    "end": cls.rect_select_end,
                },
                target_widgets=["GridView"],
            ),
            ActionKit.Command(
                path="grid.rect_select_add",
                display="Rect Select Add",
                category="drag",
                drag_callbacks={
                    "start": lambda ctx: GridViewDragCommands._rect_select_start(GridViewCommands.get_view(ctx), "add", ctx.pos),
                    "move": cls.rect_select_move,
                    "end": cls.rect_select_end,
                },
                target_widgets=["GridView"],
            ),
            ActionKit.Command(
                path="grid.rect_select_remove",
                display="Rect Select Remove",
                category="drag",
                drag_callbacks={
                    "start": lambda ctx: GridViewDragCommands._rect_select_start(GridViewCommands.get_view(ctx), "remove", ctx.pos),
                    "move": cls.rect_select_move,
                    "end": cls.rect_select_end,
                },
                target_widgets=["GridView"],
            ),
        ]


class GridViewDropCommands(ActionKit.DragMenuBase):
    NAME = "GridView"

    @staticmethod
    def _directory_from_source(source: str | None) -> str | None:
        if not source:
            return None
        return containing_dir(source)

    @staticmethod
    def _apply_drop_action(ctx, op: str) -> None:
        event = ctx.get_event() if hasattr(ctx, "get_event") else None
        if event is None:
            return
        set_action = getattr(event, "setDropAction", None)
        if not callable(set_action):
            return
        if op == "ask":
            op = get_saved_drop_operation()
        if op == "move":
            set_action(QtCore.Qt.DropAction.MoveAction)
        elif op == "copy":
            set_action(QtCore.Qt.DropAction.CopyAction)
        elif op == "ignore":
            set_action(QtCore.Qt.DropAction.IgnoreAction)
        else:
            raise ValueError(f"Invalid op: {op}")

    @staticmethod
    def accept_external_drop(ctx) -> bool:
        event = ctx.get_event()
        if event is None:
            return False
        mime = event.mimeData() if hasattr(event, "mimeData") else None
        if mime is None:
            return False
        return MimeDataParser().can_accept(mime, deny_formats=(INTERNAL_MIME_TYPE.decode(),))

    @staticmethod
    def _extract_items(event):
        if event is None or not hasattr(event, "mimeData"):
            return []
        mime = event.mimeData()
        if mime is None:
            return []
        if mime.hasFormat(INTERNAL_MIME_TYPE.decode()):
            return []
        return MimeDataParser().parse(mime)

    @staticmethod
    def _drop_target_dir(ctx, view) -> str | None:
        source = ctx.get("source")
        return GridViewDropCommands._directory_from_source(str(source)) if source else None

    @staticmethod
    def _hover_index(ctx, view) -> int | None:
        idx = view.index_at_pos(ctx.pos)
        return int(idx) if idx is not None else None

    @staticmethod
    def _target_from_index(items, idx: int, kind: str) -> GridDropTarget | None:
        source = items.source_at(idx)
        if not source:
            AppLogger.warning(f"[grid.drop] missing source for {kind} index: {idx}")
            return None
        directory = GridViewDropCommands._directory_from_source(str(source))
        return GridDropTarget(directory, kind, idx) if directory else None

    @staticmethod
    def _drop_target_dir_from_hover(ctx, view, items) -> str | None:
        idx = GridViewDropCommands._hover_index(ctx, view)
        if idx is not None:
            target = GridViewDropCommands._target_from_index(items, idx, "hover")
            return target.directory if target else None
        return GridViewDropCommands._drop_target_dir(ctx, view)

    @staticmethod
    def _nearest_index(ctx, view) -> int | None:
        idx = view.nearest_index_at_pos(ctx.pos)
        return int(idx) if idx is not None else None

    @staticmethod
    def _resolve_grid_drop_target(ctx, view, items) -> GridDropTarget | None:
        idx = GridViewDropCommands._hover_index(ctx, view)
        if idx is not None:
            return GridViewDropCommands._target_from_index(items, idx, "hover")
        if not view.rects:
            return None
        idx = GridViewDropCommands._nearest_index(ctx, view)
        if idx is None:
            return None
        return GridViewDropCommands._target_from_index(items, idx, "nearest")

    @staticmethod
    def _normalize_existing_dirs(paths) -> list[str]:
        out = []
        seen = set()
        for path in paths or []:
            if not path:
                continue
            normalized = normalize_path(os.path.abspath(str(path)))
            if normalized in seen or not os.path.isdir(normalized):
                continue
            seen.add(normalized)
            out.append(normalized)
        return out

    @staticmethod
    def _folder_tree(ctx):
        return ctx.get_instance("FolderTree")

    @staticmethod
    def _folder_tree_selected_dirs(ctx) -> list[str]:
        tree = GridViewDropCommands._folder_tree(ctx)
        if tree is None:
            return []
        return GridViewDropCommands._normalize_existing_dirs(tree.get_selected_paths())

    @staticmethod
    def _folder_tree_current_dir(ctx) -> str | None:
        tree = GridViewDropCommands._folder_tree(ctx)
        if tree is None:
            return None
        dirs = GridViewDropCommands._normalize_existing_dirs([tree.current_path()])
        return dirs[0] if dirs else None

    @staticmethod
    def _resolve_folder_tree_drop_target(ctx, view) -> GridDropTarget | None:
        selected = GridViewDropCommands._folder_tree_selected_dirs(ctx)
        if not selected:
            ConfirmDialog.ask(
                t("Select a folder in FolderTree before dropping without a grid target."),
                title=t("Drop Target Required"),
                buttons=(t("OK"),),
                parent=view,
            )
            return None
        if len(selected) == 1:
            return GridDropTarget(selected[0], "folder_tree_single")
        chosen = DropTargetDialog.ask(
            selected,
            default=GridViewDropCommands._folder_tree_current_dir(ctx),
            message=t("Choose the FolderTree destination for this drop."),
            title=t("Choose Drop Target"),
            parent=view,
        )
        return GridDropTarget(chosen, "folder_tree_choice") if chosen else None

    @staticmethod
    def _resolve_drop_target(ctx, view, items) -> GridDropTarget | None:
        target = GridViewDropCommands._resolve_grid_drop_target(ctx, view, items)
        return target if target is not None else GridViewDropCommands._resolve_folder_tree_drop_target(ctx, view)

    @staticmethod
    def _confirm_message_for_target(target: GridDropTarget, op: str) -> str | None:
        if target.kind == "folder_tree_single":
            return t("Drop to the selected FolderTree folder?\n  {path}", path=target.directory)
        if target.kind == "folder_tree_choice" and op == "ask":
            return t("Drop to:\n  {path}", path=target.directory)
        return None

    @staticmethod
    def _preview_clear(view):
        view._drop_preview_rect = None
        view._drop_preview_title = None
        view._drop_preview_text = None
        view.viewport().update()

    @staticmethod
    def _preview_update(ctx, view, items, op: str):
        event = ctx.get_event()
        if event is None:
            GridViewDropCommands._preview_clear(view)
            return
        mime = event.mimeData()
        if mime is None or mime.hasFormat(INTERNAL_MIME_TYPE.decode()):
            GridViewDropCommands._preview_clear(view)
            return
        target = GridViewDropCommands._resolve_grid_drop_target(ctx, view, items)
        if target is None or target.index is None or not (0 <= target.index < len(view.rects)):
            GridViewDropCommands._preview_clear(view)
            return
        r = view.rects[target.index]
        if op == "ask":
            op = get_saved_drop_operation()
        view._drop_preview_rect = r
        view._drop_preview_title = t("Move to:") if op == "move" else t("Copy to:")
        view._drop_preview_text = target.directory
        view.viewport().update()

    @staticmethod
    def _enter(ctx, *, op: str, on_conflict: str = "rename"):
        GridViewDropCommands._apply_drop_action(ctx, op)
        GridViewDropCommands._preview_update(ctx, GridViewCommands.get_view(ctx), GridViewCommands.get_items(ctx), op)

    @staticmethod
    def _move(ctx, *, op: str, on_conflict: str = "rename"):
        GridViewDropCommands._apply_drop_action(ctx, op)
        GridViewDropCommands._preview_update(ctx, GridViewCommands.get_view(ctx), GridViewCommands.get_items(ctx), op)

    @staticmethod
    def _leave(ctx, *, op: str, on_conflict: str = "rename"):
        GridViewDropCommands._preview_clear(GridViewCommands.get_view(ctx))

    @staticmethod
    def _save(ctx, *, op: str, on_conflict: str = "rename"):
        event = ctx.get_event()
        if event is None:
            return
        view = None
        try:
            view = GridViewCommands.get_view(ctx)
            items = GridViewCommands.get_items(ctx)
            src_items = GridViewDropCommands._extract_items(event)
            if not src_items:
                return

            if op not in ("copy", "move", "ask"):
                raise ValueError(f"Invalid op: {op}")
            if on_conflict not in ("overwrite", "rename", "skip", "ask"):
                raise ValueError(f"Invalid on_conflict: {on_conflict}")

            target = GridViewDropCommands._resolve_drop_target(ctx, view, items)
            if target is None:
                return
            drop_files_with_ui(
                src_items,
                target.directory,
                op,
                overwrite_mode=on_conflict,
                parent=view,
                confirm_message=GridViewDropCommands._confirm_message_for_target(target, op),
            )
        finally:
            GridViewDropCommands._apply_drop_action(ctx, "ignore")
            if view is not None:
                GridViewDropCommands._preview_clear(view)

    @classmethod
    def commands(cls):
        return [
            ActionKit.Command(
                path="grid.drop_files_copy",
                display="Drop Files (Copy)",
                category="drop",
                params=[ActionKit.Param(name="on_conflict", value=("ask", "overwrite", "rename", "skip"))],
                drop_acceptor=cls.accept_external_drop,
                drop_callbacks={
                    "enter": lambda ctx, on_conflict="rename": GridViewDropCommands._enter(ctx, op="copy", on_conflict=on_conflict),
                    "move": lambda ctx, on_conflict="rename": GridViewDropCommands._move(ctx, op="copy", on_conflict=on_conflict),
                    "leave": lambda ctx, on_conflict="rename": GridViewDropCommands._leave(ctx, op="copy", on_conflict=on_conflict),
                    "drop": lambda ctx, on_conflict="rename": GridViewDropCommands._save(ctx, op="copy", on_conflict=on_conflict),
                },
                target_widgets=["GridView"],
            ),
            ActionKit.Command(
                path="grid.drop_files_move",
                display="Drop Files (Move)",
                category="drop",
                params=[ActionKit.Param(name="on_conflict", value=("ask", "overwrite", "rename", "skip"))],
                drop_acceptor=cls.accept_external_drop,
                drop_callbacks={
                    "enter": lambda ctx, on_conflict="rename": GridViewDropCommands._enter(ctx, op="move", on_conflict=on_conflict),
                    "move": lambda ctx, on_conflict="rename": GridViewDropCommands._move(ctx, op="move", on_conflict=on_conflict),
                    "leave": lambda ctx, on_conflict="rename": GridViewDropCommands._leave(ctx, op="move", on_conflict=on_conflict),
                    "drop": lambda ctx, on_conflict="rename": GridViewDropCommands._save(ctx, op="move", on_conflict=on_conflict),
                },
                target_widgets=["GridView"],
            ),
            ActionKit.Command(
                path="grid.drop_files_ask",
                display="Drop Files (Ask)",
                category="drop",
                params=[ActionKit.Param(name="on_conflict", value=("ask", "overwrite", "rename", "skip"))],
                drop_acceptor=cls.accept_external_drop,
                drop_callbacks={
                    "enter": lambda ctx, on_conflict="rename": GridViewDropCommands._enter(ctx, op="ask", on_conflict=on_conflict),
                    "move": lambda ctx, on_conflict="rename": GridViewDropCommands._move(ctx, op="ask", on_conflict=on_conflict),
                    "leave": lambda ctx, on_conflict="rename": GridViewDropCommands._leave(ctx, op="ask", on_conflict=on_conflict),
                    "drop": lambda ctx, on_conflict="rename": GridViewDropCommands._save(ctx, op="ask", on_conflict=on_conflict),
                },
                target_widgets=["GridView"],
            ),
        ]
