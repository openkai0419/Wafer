import os
from pathlib import Path

from PySide6 import QtCore, QtGui

from ...actions.bridge import Kit
from ...common.funcs import uipx
from ...os.dragparser import MimeDataParser
from ...os.save import drop_files_with_ui
from ...qt.pixmap import PixmapFactory


INTERNAL_MIME_FLAG = b"application/x-jvscroll-internal" + f"{os.getpid()}".encode()


class JustifiedViewCommands(Kit.MenuBase):
    prefix = "JustifiedView"

    @staticmethod
    def get_view(ctx):
        return ctx.get_instance("JustifiedView")

    @staticmethod
    def get_items(ctx):
        items = ctx.get_instance("ViewerItems")
        return items or JustifiedViewCommands.get_view(ctx).items

    @staticmethod
    def get_shower(ctx):
        return ctx.get_instance("ViewerWidget")

    @staticmethod
    def _resolve_index(ctx, index: int | None) -> tuple[int, str] | None:
        if index is None:
            return None
        items = JustifiedViewCommands.get_items(ctx)
        idx = int(index)
        path = items.path_at(idx)
        if not path:
            return None
        return idx, path

    @staticmethod
    def _show_index(ctx, index: int | None):
        resolved = JustifiedViewCommands._resolve_index(ctx, index)
        if resolved is None:
            return
        _, path = resolved
        JustifiedViewCommands.get_shower(ctx).set_path(path)

    @staticmethod
    def _scroll_to_index(ctx, index: int | None):
        resolved = JustifiedViewCommands._resolve_index(ctx, index)
        if resolved is None:
            return
        idx, _ = resolved
        view = JustifiedViewCommands.get_view(ctx)
        view.reinstall_scroll_index(int(idx), animated=True)

    @staticmethod
    def click_select_at_pos(ctx):
        view = JustifiedViewCommands.get_view(ctx)
        items = JustifiedViewCommands.get_items(ctx)
        idx = view.index_at_pos(ctx.pos)
        if idx is None:
            return
        idx = int(idx)
        if not items.is_selected(idx):
            items.set_selected([idx], last=0)
        elif items.selected_count() > 1:
            items.set_selected([idx], last=0)
        else:
            items.deselect(idx)

    @staticmethod
    def select_at_pos(ctx):
        view = JustifiedViewCommands.get_view(ctx)
        items = JustifiedViewCommands.get_items(ctx)
        idx = view.index_at_pos(ctx.pos)
        if idx is None:
            return
        items.set_selected([int(idx)], last=0)

    @staticmethod
    def toggle_at_pos(ctx):
        view = JustifiedViewCommands.get_view(ctx)
        items = JustifiedViewCommands.get_items(ctx)
        idx = view.index_at_pos(ctx.pos)
        if idx is None:
            return
        items.toggle_selection(int(idx))

    @staticmethod
    def range_select_at_pos(ctx):
        view = JustifiedViewCommands.get_view(ctx)
        items = JustifiedViewCommands.get_items(ctx)
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
        view = JustifiedViewCommands.get_view(ctx)
        items = JustifiedViewCommands.get_items(ctx)
        idx = view.index_at_pos(ctx.pos)
        if idx is None:
            return
        idx = int(idx)
        JustifiedViewCommands._show_index(ctx, idx)

    @staticmethod
    def show_selected(ctx):
        items = JustifiedViewCommands.get_items(ctx)
        JustifiedViewCommands._show_index(ctx, items.last_selected_index())

    @staticmethod
    def select_all(ctx):
        items = JustifiedViewCommands.get_items(ctx)
        n = items.count()
        if n <= 0:
            items.clear_selection()
            return
        items.set_selected(list(range(n)), last=-1)

    @staticmethod
    def clear_selection(ctx):
        JustifiedViewCommands.get_items(ctx).clear_selection()

    @staticmethod
    def _scroll_by_wheel(ctx, direction: int):
        view = JustifiedViewCommands.get_view(ctx)
        scroll = getattr(view, "parent_scroll", None)
        if scroll is None or not hasattr(scroll, "verticalScrollBar"):
            return
        if hasattr(scroll, "stop_auto_scroll") and callable(getattr(scroll, "stop_auto_scroll")):
            try:
                scroll.stop_auto_scroll()
            except Exception:
                pass
        bar = scroll.verticalScrollBar()
        steps = int(ctx.get("wheel_steps") or 1)
        step = int(getattr(bar, "singleStep", lambda: 25)() or 25)
        multiplier = int(ctx.get("multiplier") or 4)
        delta = max(1, step * max(1, multiplier)) * max(1, steps)
        bar.setValue(int(bar.value()) + int(direction) * int(delta))

    @staticmethod
    def wheel_scroll_up(ctx, multiplier: int = 4):
        ctx.put("multiplier", int(multiplier))
        JustifiedViewCommands._scroll_by_wheel(ctx, -1)

    @staticmethod
    def wheel_scroll_down(ctx, multiplier: int = 4):
        ctx.put("multiplier", int(multiplier))
        JustifiedViewCommands._scroll_by_wheel(ctx, 1)

    @staticmethod
    def _clamp(v: int, lo: int, hi: int) -> int:
        return max(int(lo), min(int(v), int(hi)))

    @staticmethod
    def set_scale(ctx, height: int):
        view = JustifiedViewCommands.get_view(ctx)
        lo = getattr(view, "min_height", 1)
        hi = getattr(view, "max_height", max(int(lo), 1))
        h = JustifiedViewCommands._clamp(int(height), int(lo), int(hi))
        if int(getattr(view, "base_height", 0)) == h:
            return
        view.base_height = h
        view.base_height_changed.emit()
        view._debounce_recalc_layout()

    @staticmethod
    def scale_up(ctx, ratio: float = 1.1):
        view = JustifiedViewCommands.get_view(ctx)
        cur = int(getattr(view, "base_height", 0) or 0)
        if cur <= 0:
            return
        steps = int(ctx.get("wheel_steps") or 1)
        r = float(ratio) ** float(max(1, steps))
        JustifiedViewCommands.set_scale(ctx, int(cur * r))

    @staticmethod
    def scale_down(ctx, ratio: float = 1.1):
        view = JustifiedViewCommands.get_view(ctx)
        cur = int(getattr(view, "base_height", 0) or 0)
        if cur <= 0:
            return
        r = float(ratio)
        if r <= 0.0:
            return
        steps = int(ctx.get("wheel_steps") or 1)
        rr = float(r) ** float(max(1, steps))
        JustifiedViewCommands.set_scale(ctx, int(cur / rr))

    @staticmethod
    def scale_reset(ctx):
        view = JustifiedViewCommands.get_view(ctx)
        w = getattr(view, "screen_width", None)
        if w is None:
            return
        JustifiedViewCommands.set_scale(ctx, int(int(w) / 10))

    @staticmethod
    def move_to_next_row(ctx):
        view = JustifiedViewCommands.get_view(ctx)
        view.scroll_to_next_row(animated=True)

    @staticmethod
    def move_to_prev_row(ctx):
        view = JustifiedViewCommands.get_view(ctx)
        view.scroll_to_prev_row(animated=True)

    commands = [
        ":JustifiedView",
        "-",
        ":Selection",
        Kit.Command(path="jv.click_select_at_pos", display="Click Select", func=click_select_at_pos),
        Kit.Command(path="jv.toggle_at_pos", display="Toggle Select", func=toggle_at_pos),
        Kit.Command(path="jv.range_select_at_pos", display="Range Select", func=range_select_at_pos),
        Kit.Command(path="jv.select_at_pos", display="Select", func=select_at_pos, hidden=True),
        Kit.Command(path="jv.select_all", display="Select All", func=select_all),
        Kit.Command(path="jv.clear_selection", display="Clear Selection", func=clear_selection),
        "-",
        ":Viewer",
        Kit.Command(path="jv.show_at_pos", display="Show at Pos", func=show_at_pos),
        Kit.Command(path="jv.show_selected", display="Show Selected", func=show_selected),
        "-",
        ":Scroll",
        Kit.Command(path="jv.scroll_up", display="Scroll Up", func=wheel_scroll_up, params=[Kit.Param(name="multiplier", value=4)]),
        Kit.Command(path="jv.scroll_down", display="Scroll Down", func=wheel_scroll_down, params=[Kit.Param(name="multiplier", value=4)]),
        Kit.Command(path="jv.move_to_next_row", display="Next Row", func=move_to_next_row),
        Kit.Command(path="jv.move_to_prev_row", display="Prev Row", func=move_to_prev_row),
        "-",
        ":Scale",
        Kit.Command(path="jv.scale_up", display="Scale Up", func=scale_up, params=[Kit.Param(name="ratio", value=1.1)]),
        Kit.Command(path="jv.scale_down", display="Scale Down", func=scale_down, params=[Kit.Param(name="ratio", value=1.1)]),
        Kit.Command(path="jv.set_scale", display="Set Scale", func=set_scale, params=[Kit.Param(name="height", value=500)]),
        Kit.Command(path="jv.scale_reset", display="Reset Scale", func=scale_reset),
        "-",
    ]


class JustifiedViewDragCommands(Kit.DragMenuBase):
    prefix = "JustifiedView"

    @staticmethod
    def _noop(ctx):
        return

    @staticmethod
    def drag_files_start(ctx):
        view = JustifiedViewCommands.get_view(ctx)
        items = JustifiedViewCommands.get_items(ctx)
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
        mime.setData(INTERNAL_MIME_FLAG.decode(), QtCore.QByteArray(b"1"))
        drag.setMimeData(mime)
        w = view.widgets.get(int(index))
        if w is not None:
            pixmap = QtGui.QPixmap(w.grab())
            pixmap = pixmap.scaled(QtCore.QSize(uipx(150), uipx(150)), QtCore.Qt.KeepAspectRatio, QtCore.Qt.FastTransformation)
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
            from ...actions.binding.mouse.mouseeventmanager import MouseStateManager

            try:
                drag.exec(QtCore.Qt.CopyAction | QtCore.Qt.MoveAction)
            finally:
                MouseStateManager.instance().end_internal_drag(view)

        QtCore.QTimer.singleShot(0, _run_drag)

    @staticmethod
    def _rect_select_start(view, mode: str, pos):
        view._rect_select_mode = str(mode or "replace")
        view._rect_select_dragging = True
        view._rect_select_start_pos = pos
        view._rect_select_current_pos = pos
        view.update()

    @staticmethod
    def _rect_select_move(view, pos):
        if not view._rect_select_dragging:
            return
        view._rect_select_current_pos = pos
        view.update()

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
            view.update()
            return
        rect = QtCore.QRect(start, cur).normalized()
        selected_indices = [i for i, r in enumerate(view.rects) if rect.intersects(r)]
        if selected_indices:
            if view._rect_select_mode == "remove":
                items.remove_selection(selected_indices)
            elif view._rect_select_mode == "add":
                items.add_selection(selected_indices, last=-1)
            else:
                items.set_selected(selected_indices, last=-1)
        view.update()

    @staticmethod
    def rect_select_move(ctx):
        JustifiedViewDragCommands._rect_select_move(JustifiedViewCommands.get_view(ctx), ctx.pos)

    @staticmethod
    def rect_select_end(ctx):
        JustifiedViewDragCommands._rect_select_end(JustifiedViewCommands.get_view(ctx), JustifiedViewCommands.get_items(ctx))
    commands = [
        Kit.Command(
            path="jv.drag_files",
            display="Drag Files",
            category="drag",
            drag_callbacks={"start": drag_files_start, "move": _noop, "end": _noop},
            target_widgets=["JustifiedView"],
        ),
        Kit.Command(
            path="jv.rect_select_replace",
            display="Rect Select Replace",
            category="drag",
            drag_callbacks={
                "start": lambda ctx: JustifiedViewDragCommands._rect_select_start(JustifiedViewCommands.get_view(ctx), "replace", ctx.pos),
                "move": rect_select_move,
                "end": rect_select_end,
            },
            target_widgets=["JustifiedView"],
        ),
        Kit.Command(
            path="jv.rect_select_add",
            display="Rect Select Add",
            category="drag",
            drag_callbacks={
                "start": lambda ctx: JustifiedViewDragCommands._rect_select_start(JustifiedViewCommands.get_view(ctx), "add", ctx.pos),
                "move": rect_select_move,
                "end": rect_select_end,
            },
            target_widgets=["JustifiedView"],
        ),
        Kit.Command(
            path="jv.rect_select_remove",
            display="Rect Select Remove",
            category="drag",
            drag_callbacks={
                "start": lambda ctx: JustifiedViewDragCommands._rect_select_start(JustifiedViewCommands.get_view(ctx), "remove", ctx.pos),
                "move": rect_select_move,
                "end": rect_select_end,
            },
            target_widgets=["JustifiedView"],
        ),
    ]


class JustifiedViewDropCommands(Kit.DragMenuBase):
    prefix = "JustifiedView"

    @staticmethod
    def _apply_drop_action(ctx, op: str) -> None:
        event = ctx.get_event() if hasattr(ctx, "get_event") else None
        if event is None:
            return
        set_action = getattr(event, "setDropAction", None)
        if not callable(set_action):
            return
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
        return MimeDataParser().can_accept(mime, deny_formats=(INTERNAL_MIME_FLAG.decode(),))

    @staticmethod
    def _extract_items(event):
        if event is None or not hasattr(event, "mimeData"):
            return []
        mime = event.mimeData()
        if mime is None:
            return []
        if mime.hasFormat(INTERNAL_MIME_FLAG.decode()):
            return []
        return MimeDataParser().parse(mime)

    @staticmethod
    def _drop_target_dir(ctx, view) -> str | None:
        p = ctx.get("path")
        if p:
            a = os.path.abspath(str(p))
            return a if os.path.isdir(a) else os.path.dirname(a)
        r = getattr(view, "root", None)
        if r:
            rr = os.path.abspath(str(r))
            return rr if os.path.isdir(rr) else None
        return None

    @staticmethod
    def _hover_index(ctx, view) -> int | None:
        idx = view.index_at_pos(ctx.pos)
        return int(idx) if idx is not None else None

    @staticmethod
    def _drop_target_dir_from_hover(ctx, view, items) -> str | None:
        idx = JustifiedViewDropCommands._hover_index(ctx, view)
        if idx is not None:
            p = items.path_at(idx)
            if p:
                return os.path.dirname(os.path.abspath(str(p)))
        return JustifiedViewDropCommands._drop_target_dir(ctx, view)

    @staticmethod
    def _preview_clear(view):
        view._drop_preview_rect = None
        view._drop_preview_title = None
        view._drop_preview_text = None
        view.update()

    @staticmethod
    def _preview_update(ctx, view, items, op: str):
        event = ctx.get_event()
        if event is None:
            JustifiedViewDropCommands._preview_clear(view)
            return
        mime = event.mimeData()
        if mime is None or mime.hasFormat(INTERNAL_MIME_FLAG.decode()):
            JustifiedViewDropCommands._preview_clear(view)
            return
        idx = JustifiedViewDropCommands._hover_index(ctx, view)
        if idx is None:
            JustifiedViewDropCommands._preview_clear(view)
            return
        if not (0 <= idx < len(view.rects)):
            JustifiedViewDropCommands._preview_clear(view)
            return
        dst_dir = JustifiedViewDropCommands._drop_target_dir_from_hover(ctx, view, items)
        if not dst_dir:
            JustifiedViewDropCommands._preview_clear(view)
            return
        r = view.rects[idx]
        view._drop_preview_rect = r
        view._drop_preview_title = "Move to:" if op == "move" else "Copy to:"
        view._drop_preview_text = dst_dir
        view.update()

    @staticmethod
    def _enter(ctx, *, op: str, on_conflict: str = "rename"):
        JustifiedViewDropCommands._preview_update(ctx, JustifiedViewCommands.get_view(ctx), JustifiedViewCommands.get_items(ctx), op)

    @staticmethod
    def _move(ctx, *, op: str, on_conflict: str = "rename"):
        JustifiedViewDropCommands._preview_update(ctx, JustifiedViewCommands.get_view(ctx), JustifiedViewCommands.get_items(ctx), op)

    @staticmethod
    def _leave(ctx, *, op: str, on_conflict: str = "rename"):
        JustifiedViewDropCommands._preview_clear(JustifiedViewCommands.get_view(ctx))

    @staticmethod
    def _save(ctx, *, op: str, on_conflict: str = "rename"):
        event = ctx.get_event()
        if event is None:
            return
        view = JustifiedViewCommands.get_view(ctx)
        items = JustifiedViewCommands.get_items(ctx)
        dst_dir = JustifiedViewDropCommands._drop_target_dir_from_hover(ctx, view, items)
        if not dst_dir:
            return
        src_items = JustifiedViewDropCommands._extract_items(event)
        if not src_items:
            return

        if op not in ("copy", "move"):
            raise ValueError(f"Invalid op: {op}")
        if on_conflict not in ("overwrite", "rename", "skip", "ask"):
            raise ValueError(f"Invalid on_conflict: {on_conflict}")

        drop_files_with_ui(src_items, dst_dir, op, overwrite_mode=on_conflict, parent=view)
        JustifiedViewDropCommands._preview_clear(view)

    commands = [
        Kit.Command(
            path="jv.drop_files_copy",
            display="Drop Files (Copy)",
            category="drop",
            params=[Kit.Param(name="on_conflict", value=("ask", "overwrite", "rename", "skip"))],
            drop_acceptor=accept_external_drop,
            drop_callbacks={
                "enter": lambda ctx, on_conflict="rename": JustifiedViewDropCommands._enter(ctx, op="copy", on_conflict=on_conflict),
                "move": lambda ctx, on_conflict="rename": JustifiedViewDropCommands._move(ctx, op="copy", on_conflict=on_conflict),
                "leave": lambda ctx, on_conflict="rename": JustifiedViewDropCommands._leave(ctx, op="copy", on_conflict=on_conflict),
                "drop": lambda ctx, on_conflict="rename": JustifiedViewDropCommands._save(ctx, op="copy", on_conflict=on_conflict),
            },
            target_widgets=["JustifiedView"],
        ),
        Kit.Command(
            path="jv.drop_files_move",
            display="Drop Files (Move)",
            category="drop",
            params=[Kit.Param(name="on_conflict", value=("ask", "overwrite", "rename", "skip"))],
            drop_acceptor=accept_external_drop,
            drop_callbacks={
                "enter": lambda ctx, on_conflict="rename": JustifiedViewDropCommands._enter(ctx, op="move", on_conflict=on_conflict),
                "move": lambda ctx, on_conflict="rename": JustifiedViewDropCommands._move(ctx, op="move", on_conflict=on_conflict),
                "leave": lambda ctx, on_conflict="rename": JustifiedViewDropCommands._leave(ctx, op="move", on_conflict=on_conflict),
                "drop": lambda ctx, on_conflict="rename": JustifiedViewDropCommands._save(ctx, op="move", on_conflict=on_conflict),
            },
            target_widgets=["JustifiedView"],
        ),
    ]
