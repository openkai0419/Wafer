from pathlib import Path
from wayfer.core.actions.bridge import ActionKit
from wayfer.utils.logs import AppLogger


def accept_local_existing_files(ctx) -> bool:
    event = ctx.get("event") if hasattr(ctx, "get") else None
    if event is None:
        return False
    md = getattr(event, "mimeData", None)
    if not callable(md):
        return False
    try:
        mime = md()
    except Exception as e:
        AppLogger.warning("event.mimeData() failed", exc=e)
        return False
    if not mime:
        return False
    has_urls = getattr(mime, "hasUrls", None)
    if not callable(has_urls) or not has_urls():
        return False
    urls_fn = getattr(mime, "urls", None)
    if not callable(urls_fn):
        return False
    try:
        urls = urls_fn()
    except Exception as e:
        AppLogger.warning("mime.urls() failed", exc=e)
        return False
    for url in urls or []:
        is_local = getattr(url, "isLocalFile", None)
        to_local = getattr(url, "toLocalFile", None)
        if callable(is_local) and is_local() and callable(to_local):
            try:
                p = Path(to_local())
            except Exception as e:
                AppLogger.warning("url.toLocalFile() failed", exc=e)
                continue
            if p.is_file():
                return True
    return False


def _rect_selection_start(ctx):
    print(f"[RectSelection] Start at {ctx.get('pos')}")


def _rect_selection_move(ctx):
    print(f"[RectSelection] Moving to {ctx.get('pos')}")


def _rect_selection_end(ctx):
    print(f"[RectSelection] End at {ctx.get('pos')}")


def _drag_scroll_start(ctx):
    print(f"[DragScroll] Start at {ctx.get('pos')}")


def _drag_scroll_move(ctx):
    print(f"[DragScroll] Moving to {ctx.get('pos')}")


def _drag_scroll_end(ctx):
    print(f"[DragScroll] End at {ctx.get('pos')}")


def _widget_drag_start(ctx):
    pos, widget = ctx.get_many(["pos", "widget"])
    widget_name = widget.binding_scope() if widget and hasattr(widget, "binding_scope") else str(type(widget).__name__ if widget else "None")
    print(f"[WidgetDrag] Start on {widget_name} at {pos}")


def _widget_drag_move(ctx):
    pos, widget = ctx.get_many(["pos", "widget"])
    widget_name = widget.binding_scope() if widget and hasattr(widget, "binding_scope") else str(type(widget).__name__ if widget else "None")
    print(f"[WidgetDrag] Moving on {widget_name} to {pos}")


def _widget_drag_end(ctx):
    pos, widget = ctx.get_many(["pos", "widget"])
    widget_name = widget.binding_scope() if widget and hasattr(widget, "binding_scope") else str(type(widget).__name__ if widget else "None")
    print(f"[WidgetDrag] End on {widget_name} at {pos}")


def _drop_files_enter(ctx):
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


def _drop_files_move(ctx):
    pos, widget = ctx.get_many(["pos", "widget"])
    if pos is not None and hasattr(pos, "x"):
        print(f"[dropFiles.move] Called - pos=({pos.x()}, {pos.y()})")
    if widget and hasattr(widget, "setText") and pos is not None and hasattr(pos, "x"):
        widget.setText(f"🖱️ MOVE\n({pos.x()}, {pos.y()})")


def _drop_files_leave(ctx):
    widget = ctx.get("widget")
    print("[dropFiles.leave] Called")
    if widget and hasattr(widget, "setText"):
        widget.setText("🚪 LEAVE\nFiles dragged out")


def _drop_files_drop(ctx):
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


def _simple_file_drop_enter(ctx):
    widget = ctx.get("widget")
    print("[simpleFileDrop.enter] Called")
    if widget and hasattr(widget, "setText"):
        widget.setText("📥 File(s) entered")


def _simple_file_drop_move(ctx):
    pos, widget = ctx.get_many(["pos", "widget"])
    if pos is not None and hasattr(pos, "x"):
        print(f"[simpleFileDrop.move] pos=({pos.x()}, {pos.y()})")
    if widget and hasattr(widget, "setText") and pos is not None and hasattr(pos, "x"):
        widget.setText(f"🖱️ Moving\n({pos.x()}, {pos.y()})")


def _simple_file_drop_leave(ctx):
    widget = ctx.get("widget")
    print("[simpleFileDrop.leave] Called")
    if widget and hasattr(widget, "setText"):
        widget.setText("🚪 File(s) left")


def _simple_file_drop_drop(ctx):
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


def _simple_file_drop_ctrl_enter(ctx):
    widget = ctx.get("widget")
    print("[simpleFileDropCtrl.enter] Called")
    if widget and hasattr(widget, "setText"):
        widget.setText("📥 CTRL File(s) entered")


def _simple_file_drop_ctrl_move(ctx):
    pos, widget = ctx.get_many(["pos", "widget"])
    if pos is not None and hasattr(pos, "x"):
        print(f"[simpleFileDropCtrl.move] pos=({pos.x()}, {pos.y()})")
    if widget and hasattr(widget, "setText") and pos is not None and hasattr(pos, "x"):
        widget.setText(f"🖱️ CTRL Moving\n({pos.x()}, {pos.y()})")


def _simple_file_drop_ctrl_leave(ctx):
    widget = ctx.get("widget")
    print("[simpleFileDropCtrl.leave] Called")
    if widget and hasattr(widget, "setText"):
        widget.setText("🚪 CTRL File(s) left")


def _simple_file_drop_ctrl_drop(ctx):
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


def _file_path_drop(ctx):
    event = ctx.get("event")
    if not (event and hasattr(event, "mimeData")):
        return
    mime = event.mimeData()
    if not mime.hasUrls():
        print("[FilePathDrop] No file paths in drop")
        return
    for url in mime.urls():
        print(f"[FilePathDrop] {url.toLocalFile()}")


def _file_path_move(ctx):
    pos = ctx.get("pos")
    if pos is not None and hasattr(pos, "x"):
        print(f"[filePathDrop.move] pos=({pos.x()}, {pos.y()})")
    else:
        print("[filePathDrop.move] Called")


class DragDemoDragCommands(ActionKit.DragMenuBase):
    commands = [
        ActionKit.Command(
            path="rectSelection",
            display="Rectangle Selection",
            category="drag",
            target_widgets=["Widget A"],
            drag_callbacks={
                "start": _rect_selection_start,
                "move": _rect_selection_move,
                "end": _rect_selection_end,
            },
        ),
        ActionKit.Command(
            path="dragScroll",
            display="Drag Scroll",
            category="drag",
            drag_callbacks={
                "start": _drag_scroll_start,
                "move": _drag_scroll_move,
                "end": _drag_scroll_end,
            },
        ),
        ActionKit.Command(
            path="widgetDrag",
            display="Widget Drag",
            category="drag",
            target_widgets=["Drag Demo Widget"],
            drag_callbacks={
                "start": _widget_drag_start,
                "move": _widget_drag_move,
                "end": _widget_drag_end,
            },
        ),
    ]


class DragDemoDropCommands(ActionKit.DragMenuBase):
    commands = [
        ActionKit.Command(
            path="dropFiles",
            display="Drop Files",
            category="drop",
            target_widgets=["Widget A"],
            drop_acceptor=accept_local_existing_files,
            drop_callbacks={
                "enter": _drop_files_enter,
                "move": _drop_files_move,
                "leave": _drop_files_leave,
                "drop": _drop_files_drop,
            },
        ),
        ActionKit.Command(
            path="simpleFileDrop",
            display="Simple File Drop",
            category="drop",
            drop_acceptor=accept_local_existing_files,
            drop_callbacks={
                "enter": _simple_file_drop_enter,
                "move": _simple_file_drop_move,
                "leave": _simple_file_drop_leave,
                "drop": _simple_file_drop_drop,
            },
        ),
        ActionKit.Command(
            path="simpleFileDropCtrl",
            display="Simple File Drop (Ctrl)",
            category="drop",
            drop_acceptor=accept_local_existing_files,
            drop_callbacks={
                "enter": _simple_file_drop_ctrl_enter,
                "move": _simple_file_drop_ctrl_move,
                "leave": _simple_file_drop_ctrl_leave,
                "drop": _simple_file_drop_ctrl_drop,
            },
        ),
        ActionKit.Command(
            path="filePathDrop",
            display="File Path Drop",
            category="drop",
            target_widgets=["Drag Demo Widget"],
            drop_acceptor=accept_local_existing_files,
            drop_callbacks={
                "move": _file_path_move,
                "drop": _file_path_drop,
            },
        ),
    ]


def get_menu_classes() -> list[type]:
    return [DragDemoDragCommands, DragDemoDropCommands]
