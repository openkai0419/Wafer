from __future__ import annotations
from pathlib import Path
from .command.core import CommandMeta
from .command.context import CommandContext
from .command.menu import RegistryBackedMenu


def accept_local_existing_files(ctx: CommandContext) -> bool:
    try:
        event = ctx.get("event")
        if event is None or not hasattr(event, "mimeData"):
            return False
        mime = event.mimeData()
        if not mime or not mime.hasUrls():
            return False
        for url in mime.urls():
            if hasattr(url, "isLocalFile") and url.isLocalFile():
                p = Path(url.toLocalFile())
                if p.is_file():
                    return True
        return False
    except Exception:
        return False


class DragDemoDragCommands(RegistryBackedMenu):
    def _rect_selection_start(self, ctx: CommandContext):
        print(f"[RectSelection] Start at {ctx.get('pos')}")

    def _rect_selection_move(self, ctx: CommandContext):
        print(f"[RectSelection] Moving to {ctx.get('pos')}")

    def _rect_selection_end(self, ctx: CommandContext):
        print(f"[RectSelection] End at {ctx.get('pos')}")

    def _drag_scroll_start(self, ctx: CommandContext):
        print(f"[DragScroll] Start at {ctx.get('pos')}")

    def _drag_scroll_move(self, ctx: CommandContext):
        print(f"[DragScroll] Moving to {ctx.get('pos')}")

    def _drag_scroll_end(self, ctx: CommandContext):
        print(f"[DragScroll] End at {ctx.get('pos')}")

    def _widget_drag_start(self, ctx: CommandContext):
        pos, widget = ctx.get_many(["pos", "widget"])
        widget_name = widget.binding_scope() if widget and hasattr(widget, "binding_scope") else str(type(widget).__name__ if widget else "None")
        print(f"[WidgetDrag] Start on {widget_name} at {pos}")

    def _widget_drag_move(self, ctx: CommandContext):
        pos, widget = ctx.get_many(["pos", "widget"])
        widget_name = widget.binding_scope() if widget and hasattr(widget, "binding_scope") else str(type(widget).__name__ if widget else "None")
        print(f"[WidgetDrag] Moving on {widget_name} to {pos}")

    def _widget_drag_end(self, ctx: CommandContext):
        pos, widget = ctx.get_many(["pos", "widget"])
        widget_name = widget.binding_scope() if widget and hasattr(widget, "binding_scope") else str(type(widget).__name__ if widget else "None")
        print(f"[WidgetDrag] End on {widget_name} at {pos}")

    def create_definitions(self):
        return [
            {
                "path": "rectSelection",
                "meta": CommandMeta(
                    display="Rectangle Selection",
                    category="drag",
                    target_widgets=["Widget A"],
                    drag_callbacks={
                        "start": self._rect_selection_start,
                        "move": self._rect_selection_move,
                        "end": self._rect_selection_end,
                    },
                ),
            },
            {
                "path": "dragScroll",
                "meta": CommandMeta(
                    display="Drag Scroll",
                    category="drag",
                    drag_callbacks={
                        "start": self._drag_scroll_start,
                        "move": self._drag_scroll_move,
                        "end": self._drag_scroll_end,
                    },
                ),
            },
            {
                "path": "widgetDrag",
                "meta": CommandMeta(
                    display="Widget Drag",
                    category="drag",
                    target_widgets=["Drag Demo Widget"],
                    drag_callbacks={
                        "start": self._widget_drag_start,
                        "move": self._widget_drag_move,
                        "end": self._widget_drag_end,
                    },
                ),
            },
        ]

class DragDemoDropCommands(RegistryBackedMenu):
    def _drop_files_enter(self, ctx: CommandContext):
        event, widget = ctx.get_many(["event", "widget"])
        print(f"[dropFiles.enter] Called - widget={widget}, event={type(event).__name__ if event else None}")
        if widget and hasattr(widget, "setText"):
            if event and hasattr(event, "mimeData"):
                mime = event.mimeData()
                if mime.hasUrls():
                    widget.setText(f"📥 ENTER\n{len(mime.urls())} file(s) dragged in")
                else:
                    widget.setText("📥 ENTER\nNo file URLs")
            else:
                widget.setText("📥 ENTER")

    def _drop_files_move(self, ctx: CommandContext):
        pos, widget = ctx.get_many(["pos", "widget"])
        if pos is not None and hasattr(pos, "x"):
            print(f"[dropFiles.move] Called - pos=({pos.x()}, {pos.y()})")
        if widget and hasattr(widget, "setText") and pos is not None and hasattr(pos, "x"):
            widget.setText(f"🖱️ MOVE\n({pos.x()}, {pos.y()})")

    def _drop_files_leave(self, ctx: CommandContext):
        widget = ctx.get("widget")
        print("[dropFiles.leave] Called")
        if widget and hasattr(widget, "setText"):
            widget.setText("🚪 LEAVE\nFiles dragged out")

    def _drop_files_drop(self, ctx: CommandContext):
        event, widget = ctx.get_many(["event", "widget"])
        print(f"[dropFiles.drop] Called - widget={widget}, event={type(event).__name__ if event else None}")
        if not (widget and hasattr(widget, "setText")):
            return
        if not (event and hasattr(event, "mimeData")):
            widget.setText("❌ DROP\nNo event data")
            return
        mime = event.mimeData()
        if not mime.hasUrls():
            widget.setText("❌ DROP\nNo URLs")
            return
        urls = [url.toLocalFile() for url in mime.urls()]
        print(f"[dropFiles.drop] {len(urls)} files: {[Path(url).name for url in urls[:3]]}")
        file_list = "\n".join([f"{i}. {Path(url).name}" for i, url in enumerate(urls[:5], 1)])
        more_text = f"\n+{len(urls)-5} more" if len(urls) > 5 else ""
        widget.setText(f"✅ DROP\n{len(urls)} file(s):\n{file_list}{more_text}")

    def _simple_file_drop_enter(self, ctx: CommandContext):
        widget = ctx.get("widget")
        print("[simpleFileDrop.enter] Called")
        if widget and hasattr(widget, "setText"):
            widget.setText("📥 File(s) entered")

    def _simple_file_drop_move(self, ctx: CommandContext):
        pos, widget = ctx.get_many(["pos", "widget"])
        if pos is not None and hasattr(pos, "x"):
            print(f"[simpleFileDrop.move] pos=({pos.x()}, {pos.y()})")
        if widget and hasattr(widget, "setText") and pos is not None and hasattr(pos, "x"):
            widget.setText(f"🖱️ Moving\n({pos.x()}, {pos.y()})")

    def _simple_file_drop_leave(self, ctx: CommandContext):
        widget = ctx.get("widget")
        print("[simpleFileDrop.leave] Called")
        if widget and hasattr(widget, "setText"):
            widget.setText("🚪 File(s) left")

    def _simple_file_drop_drop(self, ctx: CommandContext):
        event, widget = ctx.get_many(["event", "widget"])
        print(f"[simpleFileDrop.drop] Called - widget={widget}")
        if not (widget and hasattr(widget, "setText")):
            return
        if not (event and hasattr(event, "mimeData")):
            return
        mime = event.mimeData()
        if not mime.hasUrls():
            return
        urls = [url.toLocalFile() for url in mime.urls()]
        print(f"[simpleFileDrop.drop] {len(urls)} files: {[Path(url).name for url in urls[:3]]}")
        widget.setText(f"✅ Dropped {len(urls)} file(s)\n{', '.join([Path(url).name for url in urls[:3]])}")

    def _simple_file_drop_ctrl_enter(self, ctx: CommandContext):
        widget = ctx.get("widget")
        print("[simpleFileDropCtrl.enter] Called")
        if widget and hasattr(widget, "setText"):
            widget.setText("📥 CTRL File(s) entered")

    def _simple_file_drop_ctrl_move(self, ctx: CommandContext):
        pos, widget = ctx.get_many(["pos", "widget"])
        if pos is not None and hasattr(pos, "x"):
            print(f"[simpleFileDropCtrl.move] pos=({pos.x()}, {pos.y()})")
        if widget and hasattr(widget, "setText") and pos is not None and hasattr(pos, "x"):
            widget.setText(f"🖱️ CTRL Moving\n({pos.x()}, {pos.y()})")

    def _simple_file_drop_ctrl_leave(self, ctx: CommandContext):
        widget = ctx.get("widget")
        print("[simpleFileDropCtrl.leave] Called")
        if widget and hasattr(widget, "setText"):
            widget.setText("🚪 CTRL File(s) left")

    def _simple_file_drop_ctrl_drop(self, ctx: CommandContext):
        event, widget = ctx.get_many(["event", "widget"])
        print(f"[simpleFileDropCtrl.drop] Called - widget={widget}")
        if not (widget and hasattr(widget, "setText")):
            return
        if not (event and hasattr(event, "mimeData")):
            return
        mime = event.mimeData()
        if not mime.hasUrls():
            return
        urls = [url.toLocalFile() for url in mime.urls()]
        print(f"[simpleFileDropCtrl.drop] {len(urls)} files: {[Path(url).name for url in urls[:3]]}")
        widget.setText(f"✅ CTRL Dropped {len(urls)} file(s)\n{', '.join([Path(url).name for url in urls[:3]])}")

    def _widget_drag_start(self, ctx: CommandContext):
        pos, widget = ctx.get_many(["pos", "widget"])
        widget_name = widget.binding_scope() if widget and hasattr(widget, "binding_scope") else str(type(widget).__name__ if widget else "None")
        print(f"[WidgetDrag] Start on {widget_name} at {pos}")

    def _widget_drag_move(self, ctx: CommandContext):
        pos, widget = ctx.get_many(["pos", "widget"])
        widget_name = widget.binding_scope() if widget and hasattr(widget, "binding_scope") else str(type(widget).__name__ if widget else "None")
        print(f"[WidgetDrag] Moving on {widget_name} to {pos}")

    def _widget_drag_end(self, ctx: CommandContext):
        pos, widget = ctx.get_many(["pos", "widget"])
        widget_name = widget.binding_scope() if widget and hasattr(widget, "binding_scope") else str(type(widget).__name__ if widget else "None")
        print(f"[WidgetDrag] End on {widget_name} at {pos}")

    def _file_path_drop(self, ctx: CommandContext):
        event = ctx.get("event")
        if not (event and hasattr(event, "mimeData")):
            return
        mime = event.mimeData()
        if not mime.hasUrls():
            print("[FilePathDrop] No file paths in drop")
            return
        for url in mime.urls():
            print(f"[FilePathDrop] {url.toLocalFile()}")

    def _file_path_move(self, ctx: CommandContext):
        pos = ctx.get("pos")
        if pos is not None and hasattr(pos, "x"):
            print(f"[filePathDrop.move] pos=({pos.x()}, {pos.y()})")
        else:
            print("[filePathDrop.move] Called")

    def create_definitions(self):
        return [
            {
                "path": "dropFiles",
                "meta": CommandMeta(
                    display="Drop Files",
                    category="drop",
                    target_widgets=["Widget A"],
                    drop_acceptor=accept_local_existing_files,
                    drop_callbacks={
                        "enter": self._drop_files_enter,
                        "move": self._drop_files_move,
                        "leave": self._drop_files_leave,
                        "drop": self._drop_files_drop,
                    },
                ),
            },
            {
                "path": "simpleFileDrop",
                "meta": CommandMeta(
                    display="Simple File Drop",
                    category="drop",
                    drop_acceptor=accept_local_existing_files,
                    drop_callbacks={
                        "enter": self._simple_file_drop_enter,
                        "move": self._simple_file_drop_move,
                        "leave": self._simple_file_drop_leave,
                        "drop": self._simple_file_drop_drop,
                    },
                ),
            },
            {
                "path": "simpleFileDropCtrl",
                "meta": CommandMeta(
                    display="Simple File Drop (Ctrl)",
                    category="drop",
                    drop_acceptor=accept_local_existing_files,
                    drop_callbacks={
                        "enter": self._simple_file_drop_ctrl_enter,
                        "move": self._simple_file_drop_ctrl_move,
                        "leave": self._simple_file_drop_ctrl_leave,
                        "drop": self._simple_file_drop_ctrl_drop,
                    },
                ),
            },
            {
                "path": "filePathDrop",
                "meta": CommandMeta(
                    display="File Path Drop",
                    category="drop",
                    target_widgets=["Drag Demo Widget"],
                    drop_acceptor=accept_local_existing_files,
                    drop_callbacks={
                        "move": self._file_path_move,
                        "drop": self._file_path_drop,
                    },
                ),
            },
        ]
