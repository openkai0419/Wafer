from __future__ import annotations
from PySide6 import QtCore, QtGui
from .command.core import CommandMeta, register_command_defs

def create_drag_commands():
    items = []
    
    items.append({
        "path": "rectSelection.start",
        "meta": CommandMeta(
            id="rectSelection.start",
            display="Rectangle Selection Start",
            func=lambda event=None, **kwargs: print(f"[RectSelection] Start at {event.pos() if event else 'unknown'}")
        )
    })
    
    items.append({
        "path": "rectSelection.move",
        "meta": CommandMeta(
            id="rectSelection.move",
            display="Rectangle Selection Move",
            func=lambda event=None, **kwargs: print(f"[RectSelection] Moving to {event.pos() if event else 'unknown'}")
        )
    })
    
    items.append({
        "path": "rectSelection.end",
        "meta": CommandMeta(
            id="rectSelection.end",
            display="Rectangle Selection End",
            func=lambda event=None, **kwargs: print(f"[RectSelection] End at {event.pos() if event else 'unknown'}")
        )
    })
    
    items.append({
        "path": "dragScroll.start",
        "meta": CommandMeta(
            id="dragScroll.start",
            display="Drag Scroll Start",
            func=lambda event=None, **kwargs: print(f"[DragScroll] Start at {event.pos() if event else 'unknown'}")
        )
    })
    
    items.append({
        "path": "dragScroll.move",
        "meta": CommandMeta(
            id="dragScroll.move",
            display="Drag Scroll Move",
            func=lambda event=None, **kwargs: print(f"[DragScroll] Moving to {event.pos() if event else 'unknown'}")
        )
    })
    
    items.append({
        "path": "dragScroll.end",
        "meta": CommandMeta(
            id="dragScroll.end",
            display="Drag Scroll End",
            func=lambda event=None, **kwargs: print(f"[DragScroll] End at {event.pos() if event else 'unknown'}")
        )
    })
    
    items.append({
        "path": "dropFiles.enter",
        "meta": CommandMeta(
            id="dropFiles.enter",
            display="Drop Files Enter",
            func=lambda event=None, **kwargs: print(f"[DropFiles] Drag entered")
        )
    })
    
    items.append({
        "path": "dropFiles.move",
        "meta": CommandMeta(
            id="dropFiles.move",
            display="Drop Files Move",
            func=lambda event=None, **kwargs: print(f"[DropFiles] Drag move at {event.pos()}") if event and hasattr(event, 'pos') else None
        )
    })
    
    items.append({
        "path": "dropFiles.leave",
        "meta": CommandMeta(
            id="dropFiles.leave",
            display="Drop Files Leave",
            func=lambda event=None, **kwargs: print(f"[DropFiles] Drag left")
        )
    })
    
    def drop_files_drop(event=None, **kwargs):
        if event and hasattr(event, 'mimeData'):
            mime = event.mimeData()
            if mime.hasUrls():
                urls = [url.toLocalFile() for url in mime.urls()]
                print(f"[DropFiles] Dropped {len(urls)} files: {urls[:3]}")
            else:
                print(f"[DropFiles] Dropped (no URLs)")
        else:
            print(f"[DropFiles] Dropped at {event.pos() if event and hasattr(event, 'pos') else 'unknown'}")
    
    items.append({
        "path": "dropFiles.drop",
        "meta": CommandMeta(
            id="dropFiles.drop",
            display="Drop Files Drop",
            func=drop_files_drop
        )
    })
    
    def simple_file_drop(event=None, **kwargs):
        if event and hasattr(event, 'mimeData'):
            mime = event.mimeData()
            if mime.hasUrls():
                urls = [url.toLocalFile() for url in mime.urls()]
                print(f"[SimpleDrop] Dropped {len(urls)} files: {urls[:3]}")
    
    items.append({
        "path": "simpleFileDrop",
        "meta": CommandMeta(
            id="simpleFileDrop",
            display="Simple File Drop",
            func=simple_file_drop
        )
    })
    
    def widget_drag_start(event=None, widget=None, **kwargs):
        widget_name = widget.binding_scope() if widget and hasattr(widget, 'binding_scope') else str(type(widget).__name__ if widget else 'None')
        pos = event.position().toPoint() if event and hasattr(event, 'position') else (event.pos() if event and hasattr(event, 'pos') else 'unknown')
        print(f"[WidgetDrag] Start on {widget_name} at {pos}")
    
    items.append({
        "path": "widgetDrag.start",
        "meta": CommandMeta(
            id="widgetDrag.start",
            display="Widget Drag Start",
            func=widget_drag_start
        )
    })
    
    def widget_drag_move(event=None, widget=None, context=None, **kwargs):
        widget_name = widget.binding_scope() if widget and hasattr(widget, 'binding_scope') else str(type(widget).__name__ if widget else 'None')
        pos = event.position().toPoint() if event and hasattr(event, 'position') else (event.pos() if event and hasattr(event, 'pos') else 'unknown')
        print(f"[WidgetDrag] Moving on {widget_name} to {pos}")
    
    items.append({
        "path": "、.move",
        "meta": CommandMeta(
            id="widgetDrag.move",
            display="Widget Drag Move",
            func=widget_drag_move
        )
    })
    
    def widget_drag_end(event=None, widget=None, context=None, **kwargs):
        widget_name = widget.binding_scope() if widget and hasattr(widget, 'binding_scope') else str(type(widget).__name__ if widget else 'None')
        pos = event.position().toPoint() if event and hasattr(event, 'position') else (event.pos() if event and hasattr(event, 'pos') else 'unknown')
        print(f"[WidgetDrag] End on {widget_name} at {pos}")
    
    items.append({
        "path": "widgetDrag.end",
        "meta": CommandMeta(
            id="widgetDrag.end",
            display="Widget Drag End",
            func=widget_drag_end
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
    
    items.append({
        "path": "filePathDrop",
        "meta": CommandMeta(
            id="filePathDrop",
            display="File Path Drop",
            func=file_path_drop
        )
    })
    
    return items

register_command_defs(create_drag_commands())
