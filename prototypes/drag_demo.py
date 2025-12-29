from __future__ import annotations
from pathlib import Path
from PySide6 import QtCore, QtGui
from .command.core import CommandMeta, register_command_defs


def accept_local_existing_files(event=None, **kwargs) -> bool:
    try:
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

def create_drag_commands():
    items = []
    
    move_counter = {"dropFiles": 0, "simpleFileDrop": 0}
    
    items.append({
        "path": "rectSelection",
        "meta": CommandMeta(
            id="rectSelection",
            display="Rectangle Selection",
            category="drag",
            target_widgets=["Widget A"],
            drag_callbacks={
                "start": lambda event=None, **kwargs: print(f"[RectSelection] Start at {event.pos() if event else 'unknown'}"),
                "move": lambda event=None, **kwargs: print(f"[RectSelection] Moving to {event.pos() if event else 'unknown'}"),
                "end": lambda event=None, **kwargs: print(f"[RectSelection] End at {event.pos() if event else 'unknown'}")
            }
        )
    })
    
    items.append({
        "path": "dragScroll",
        "meta": CommandMeta(
            id="dragScroll",
            display="Drag Scroll",
            category="drag",
            drag_callbacks={
                "start": lambda event=None, **kwargs: print(f"[DragScroll] Start at {event.pos() if event else 'unknown'}"),
                "move": lambda event=None, **kwargs: print(f"[DragScroll] Moving to {event.pos() if event else 'unknown'}"),
                "end": lambda event=None, **kwargs: print(f"[DragScroll] End at {event.pos() if event else 'unknown'}")
            }
        )
    })
    
    def drop_files_enter(event=None, widget=None, **kwargs):
        print(f"[dropFiles.enter] Called - widget={widget}, event={type(event).__name__ if event else None}")
        if widget and hasattr(widget, 'setText'):
            if event and hasattr(event, 'mimeData'):
                mime = event.mimeData()
                if mime.hasUrls():
                    count = len(mime.urls())
                    widget.setText(f"📥 ENTER\n{count} file(s) dragged in")
                else:
                    widget.setText(f"📥 ENTER\nNo file URLs")
            else:
                widget.setText(f"📥 ENTER")
    
    def drop_files_move(event=None, widget=None, **kwargs):
        if event and hasattr(event, 'pos'):
            print(f"[dropFiles.move] Called - pos=({event.pos().x()}, {event.pos().y()})")
        if widget and hasattr(widget, 'setText'):
            if event and hasattr(event, 'pos'):
                pos = event.pos()
                widget.setText(f"🖱️ MOVE\n({pos.x()}, {pos.y()})")
    
    def drop_files_leave(event=None, widget=None, **kwargs):
        print(f"[dropFiles.leave] Called")
        if widget and hasattr(widget, 'setText'):
            widget.setText(f"🚪 LEAVE\nFiles dragged out")
    
    def drop_files_drop(event=None, widget=None, **kwargs):
        print(f"[dropFiles.drop] Called - widget={widget}, event={type(event).__name__ if event else None}")
        if widget and hasattr(widget, 'setText'):
            if event and hasattr(event, 'mimeData'):
                mime = event.mimeData()
                if mime.hasUrls():
                    urls = [url.toLocalFile() for url in mime.urls()]
                    print(f"[dropFiles.drop] {len(urls)} files: {[Path(url).name for url in urls[:3]]}")
                    file_list = "\n".join([f"{i}. {Path(url).name}" for i, url in enumerate(urls[:5], 1)])
                    more_text = f"\n+{len(urls)-5} more" if len(urls) > 5 else ""
                    widget.setText(f"✅ DROP\n{len(urls)} file(s):\n{file_list}{more_text}")
                else:
                    widget.setText(f"❌ DROP\nNo URLs")
            else:
                widget.setText(f"❌ DROP\nNo event data")
    
    items.append({
        "path": "dropFiles",
        "meta": CommandMeta(
            id="dropFiles",
            display="Drop Files",
            category="drop",
            target_widgets=["Widget A"],
            drop_acceptor=accept_local_existing_files,
            drop_callbacks={
                "enter": drop_files_enter,
                "move": drop_files_move,
                "leave": drop_files_leave,
                "drop": drop_files_drop
            }
        )
    })
    
    def simple_file_drop_enter(event=None, widget=None, **kwargs):
        print(f"[simpleFileDrop.enter] Called")
        if widget and hasattr(widget, 'setText'):
            widget.setText(f"📥 File(s) entered")
    
    def simple_file_drop_move(event=None, widget=None, **kwargs):
        if event and hasattr(event, 'pos'):
            print(f"[simpleFileDrop.move] pos=({event.pos().x()}, {event.pos().y()})")
        if widget and hasattr(widget, 'setText'):
            if event and hasattr(event, 'pos'):
                pos = event.pos()
                widget.setText(f"🖱️ Moving\n({pos.x()}, {pos.y()})")
    
    def simple_file_drop_leave(event=None, widget=None, **kwargs):
        print(f"[simpleFileDrop.leave] Called")
        if widget and hasattr(widget, 'setText'):
            widget.setText(f"🚪 File(s) left")
    
    def simple_file_drop_drop(event=None, widget=None, **kwargs):
        print(f"[simpleFileDrop.drop] Called - widget={widget}")
        if widget and hasattr(widget, 'setText'):
            if event and hasattr(event, 'mimeData'):
                mime = event.mimeData()
                if mime.hasUrls():
                    urls = [url.toLocalFile() for url in mime.urls()]
                    print(f"[simpleFileDrop.drop] {len(urls)} files: {[Path(url).name for url in urls[:3]]}")
                    names = [Path(url).name for url in urls[:3]]
                    widget.setText(f"✅ Dropped {len(urls)} file(s)\n{', '.join(names)}")
    
    items.append({
        "path": "simpleFileDrop",
        "meta": CommandMeta(
            id="simpleFileDrop",
            display="Simple File Drop",
            category="drop",
            drop_acceptor=accept_local_existing_files,
            drop_callbacks={
                "enter": simple_file_drop_enter,
                "move": simple_file_drop_move,
                "leave": simple_file_drop_leave,
                "drop": simple_file_drop_drop
            }
        )
    })

    def simple_file_drop_ctrl_enter(event=None, widget=None, **kwargs):
        print(f"[simpleFileDropCtrl.enter] Called")
        if widget and hasattr(widget, 'setText'):
            widget.setText(f"📥 CTRL File(s) entered")

    def simple_file_drop_ctrl_move(event=None, widget=None, **kwargs):
        if event and hasattr(event, 'pos'):
            print(f"[simpleFileDropCtrl.move] pos=({event.pos().x()}, {event.pos().y()})")
        if widget and hasattr(widget, 'setText'):
            if event and hasattr(event, 'pos'):
                pos = event.pos()
                widget.setText(f"🖱️ CTRL Moving\n({pos.x()}, {pos.y()})")

    def simple_file_drop_ctrl_leave(event=None, widget=None, **kwargs):
        print(f"[simpleFileDropCtrl.leave] Called")
        if widget and hasattr(widget, 'setText'):
            widget.setText(f"🚪 CTRL File(s) left")

    def simple_file_drop_ctrl_drop(event=None, widget=None, **kwargs):
        print(f"[simpleFileDropCtrl.drop] Called - widget={widget}")
        if widget and hasattr(widget, 'setText'):
            if event and hasattr(event, 'mimeData'):
                mime = event.mimeData()
                if mime.hasUrls():
                    urls = [url.toLocalFile() for url in mime.urls()]
                    print(f"[simpleFileDropCtrl.drop] {len(urls)} files: {[Path(url).name for url in urls[:3]]}")
                    names = [Path(url).name for url in urls[:3]]
                    widget.setText(f"✅ CTRL Dropped {len(urls)} file(s)\n{', '.join(names)}")

    items.append({
        "path": "simpleFileDropCtrl",
        "meta": CommandMeta(
            id="simpleFileDropCtrl",
            display="Simple File Drop (Ctrl)",
            category="drop",
            drop_acceptor=accept_local_existing_files,
            drop_callbacks={
                "enter": simple_file_drop_ctrl_enter,
                "move": simple_file_drop_ctrl_move,
                "leave": simple_file_drop_ctrl_leave,
                "drop": simple_file_drop_ctrl_drop
            }
        )
    })
    
    def widget_drag_start(event=None, widget=None, **kwargs):
        widget_name = widget.binding_scope() if widget and hasattr(widget, 'binding_scope') else str(type(widget).__name__ if widget else 'None')
        pos = event.position().toPoint() if event and hasattr(event, 'position') else (event.pos() if event and hasattr(event, 'pos') else 'unknown')
        print(f"[WidgetDrag] Start on {widget_name} at {pos}")
    
    def widget_drag_move(event=None, widget=None, context=None, **kwargs):
        widget_name = widget.binding_scope() if widget and hasattr(widget, 'binding_scope') else str(type(widget).__name__ if widget else 'None')
        pos = event.position().toPoint() if event and hasattr(event, 'position') else (event.pos() if event and hasattr(event, 'pos') else 'unknown')
        print(f"[WidgetDrag] Moving on {widget_name} to {pos}")
    
    def widget_drag_end(event=None, widget=None, context=None, **kwargs):
        widget_name = widget.binding_scope() if widget and hasattr(widget, 'binding_scope') else str(type(widget).__name__ if widget else 'None')
        pos = event.position().toPoint() if event and hasattr(event, 'position') else (event.pos() if event and hasattr(event, 'pos') else 'unknown')
        print(f"[WidgetDrag] End on {widget_name} at {pos}")
    
    items.append({
        "path": "widgetDrag",
        "meta": CommandMeta(
            id="widgetDrag",
            display="Widget Drag",
            category="drag",
            target_widgets=["Drag Demo Widget"],
            drag_callbacks={
                "start": widget_drag_start,
                "move": widget_drag_move,
                "end": widget_drag_end
            }
        )
    })
    
    def file_path_drop(event=None, **kwargs):
        if event and hasattr(event, 'mimeData'):
            mime = event.mimeData()
            if mime.hasUrls():
                paths = [url.toLocalFile() for url in mime.urls()]
                for path in paths:
                    print(f"[FilePathDrop] {path}")
            else:
                print(f"[FilePathDrop] No file paths in drop")

    def file_path_move(event=None, **kwargs):
        if event and hasattr(event, 'pos'):
            print(f"[filePathDrop.move] pos=({event.pos().x()}, {event.pos().y()})")
        else:
            print(f"[filePathDrop.move] Called")
    
    items.append({
        "path": "filePathDrop",
        "meta": CommandMeta(
            id="filePathDrop",
            display="File Path Drop",
            category="drop",
            target_widgets=["Drag Demo Widget"],
            drop_acceptor=accept_local_existing_files,
            drop_callbacks={
                "move": file_path_move,
                "drop": file_path_drop
            }
        )
    })
    
    return items

register_command_defs(create_drag_commands())
