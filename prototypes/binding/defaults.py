from wafer.core.actions.bridge import ActionKit


def get_all_mouse_bindings():
    return {
        ActionKit.Mouse("RIGHT", "SINGLE", ()): ActionKit.ScopedPayloads({
            "*": {"id": "showContextMenuHere", "args": {}}
        }),
        ActionKit.Mouse("LEFT", "SINGLE", ()): ActionKit.ScopedPayloads({
            "*": {"id": "hello", "args": {}},
            "Widget A": {"id": "file.0", "args": {}},
            "Widget B": {"id": "file.1", "args": {}},
        }),
        ActionKit.Mouse("LEFT", "SINGLE", ("RIGHT",)): ActionKit.ScopedPayloads({
            "*": {"id": "path.0", "args": {}},
            "Widget A": {"id": "echo", "args": {}},
            "Widget B": {"id": "count", "args": {}},
        }),
        ActionKit.Mouse("LEFT", "SINGLE", ("MIDDLE",)): ActionKit.ScopedPayloads({
            "Widget A": {"id": "echo", "args": {"text": "echoe", "repeat": 7}},
            "Widget B": {"id": "count", "args": {"value": 3, "step": 8}},
        }),
        ActionKit.Mouse("X1", "SINGLE", ()): ActionKit.ScopedPayloads({
            "*": {"id": "toggleVerbose", "args": {}}
        }),
        ActionKit.Mouse("X2", "SINGLE", ()): ActionKit.ScopedPayloads({
            "*": {"id": "mode", "args": {"mode": "C"}}
        }),
        ActionKit.Mouse("LEFT", "DOUBLE", ()): ActionKit.ScopedPayloads({
            "*": {"id": "hello", "args": {}}
        }),
        ActionKit.Mouse("RIGHT", "SINGLE", ("LEFT",)): ActionKit.ScopedPayloads({
            "*": {"id": "showAllMenu", "args": {}}
        }),
        ActionKit.Mouse("MIDDLE", "SINGLE", ("LEFT",)): ActionKit.ScopedPayloads({
            "*": {"id": "sortBySize", "args": {}}
        }),
        ActionKit.Mouse("MIDDLE", "SINGLE", ("RIGHT",)): ActionKit.ScopedPayloads({
            "*": {"id": "sortByName", "args": {}}
        }),
        ActionKit.Mouse("MIDDLE", "SINGLE", ()): ActionKit.ScopedPayloads({
            "*": {"id": "cycleSortOrder", "args": {}}
        }),
        ActionKit.Mouse("LEFT", "DRAG_START", ()): ActionKit.ScopedPayloads({
            "Widget A": {"id": "rectSelection", "args": {}},
            "Drag Demo Widget": {"id": "widgetDrag", "args": {}},
        }),
        ActionKit.Mouse("RIGHT", "DRAG_START", ()): ActionKit.ScopedPayloads({
            "Widget A": {"id": "dragScroll", "args": {}}
        }),
        ActionKit.Mouse("NONE", "DROP", ()): ActionKit.ScopedPayloads({
            "Widget A": {"id": "dropFiles", "args": {}},
            "Widget B": {"id": "simpleFileDrop", "args": {}},
            "Drag Demo Widget": {"id": "filePathDrop", "args": {}},
        }),
    }

def get_all_key_bindings():
    return {
        ActionKit.Key("H"): ActionKit.ScopedPayloads({
            "*": {"id": "hello", "args": {}}
        }),
        ActionKit.Key("T"): ActionKit.ScopedPayloads({
            "*": {"id": "time", "args": {}}
        }),
        ActionKit.Key("Ctrl", "W"): ActionKit.ScopedPayloads({
            "*": {"id": "bindings", "args": {}}
        }),
        ActionKit.Key("A"): ActionKit.ScopedPayloads({
            "*": {"id": "showContextMenuHere", "args": {}}
        }),
        ActionKit.Key("E"): ActionKit.ScopedPayloads({
            "*": {"id": "showContextMenuHere", "args": {}}
        }),
        ActionKit.Key("Control", "Z"): ActionKit.ScopedPayloads({
            "*": {"id": "hello", "args": {}}
        }),
        ActionKit.Key("W"): ActionKit.ScopedPayloads({
            "*": {"id": "file.0", "args": {}},
            "Widget A": {"id": "file.1", "args": {}},
            "Widget B": {"id": "file.2", "args": {}},
            "Widget C": {"id": "file.3", "args": {}},
        }),
    }
