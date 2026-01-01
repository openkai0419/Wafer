from .actions.facade import Classes

ScopedPayloads = Classes.BindPayloads

KeySpec = str | int
KeyChordSpec = tuple[KeySpec, ...]
MouseActionSpec = tuple[object, ...]

def get_all_mouse_bindings() -> dict[MouseActionSpec, ScopedPayloads]:
    return {
        ("RIGHT", "SINGLE", ()): Classes.BindPayloads({
            "*": {"id": "showContextMenuHere", "args": {}}
        }),
        ("LEFT", "SINGLE", ()): Classes.BindPayloads({
            "*": {"id": "hello", "args": {}},
            "Widget A": {"id": "file.0", "args": {}},
            "Widget B": {"id": "file.1", "args": {}},
        }),
        ("LEFT", "SINGLE", ("RIGHT",)): Classes.BindPayloads({
            "*": {"id": "path.0", "args": {}},
            "Widget A": {"id": "echo", "args": {}},
            "Widget B": {"id": "count", "args": {}},
        }),
        ("LEFT", "SINGLE", ("MIDDLE",)): Classes.BindPayloads({
            "Widget A": {"id": "echo", "args": {"text": "echoe", "repeat": 7}},
            "Widget B": {"id": "count", "args": {"value": 3, "step": 8}},
        }),
        ("X1", "SINGLE", ()): Classes.BindPayloads({
            "*": {"id": "toggleVerbose", "args": {}}
        }),
        ("X2", "SINGLE", ()): Classes.BindPayloads({
            "*": {"id": "mode", "args": {"mode": "C"}}
        }),
        ("LEFT", "DOUBLE", ()): Classes.BindPayloads({
            "*": {"id": "hello", "args": {}}
        }),
        ("RIGHT", "SINGLE", ("LEFT",)): Classes.BindPayloads({
            "*": {"id": "showAllMenu", "args": {}}
        }),
        ("MIDDLE", "SINGLE", ("LEFT",)): Classes.BindPayloads({
            "*": {"id": "sortBySize", "args": {}}
        }),
        ("MIDDLE", "SINGLE", ("RIGHT",)): Classes.BindPayloads({
            "*": {"id": "sortByName", "args": {}}
        }),
        ("MIDDLE", "SINGLE", ()): Classes.BindPayloads({
            "*": {"id": "cycleSortOrder", "args": {}}
        }),
        ("LEFT", "DRAG_START", ()): Classes.BindPayloads({
            "Widget A": {"id": "rectSelection", "args": {}},
            "Drag Demo Widget": {"id": "widgetDrag", "args": {}},
        }),
        ("RIGHT", "DRAG_START", ()): Classes.BindPayloads({
            "Widget A": {"id": "dragScroll", "args": {}}
        }),
        ("NONE", "DROP", ()): Classes.BindPayloads({
            "Widget A": {"id": "dropFiles", "args": {}},
            "Widget B": {"id": "simpleFileDrop", "args": {}},
            "Drag Demo Widget": {"id": "filePathDrop", "args": {}},
        }),
    }

def get_all_key_bindings() -> dict[KeyChordSpec, ScopedPayloads]:
    return {
        ("H",): Classes.BindPayloads({
            "*": {"id": "hello", "args": {}}
        }),
        ("T",): Classes.BindPayloads({
            "*": {"id": "time", "args": {}}
        }),
        ("Ctrl", "W"): Classes.BindPayloads({
            "*": {"id": "bindings", "args": {}}
        }),
        ("A",): Classes.BindPayloads({
            "*": {"id": "showContextMenuHere", "args": {}}
        }),
        ("E",): Classes.BindPayloads({
            "*": {"id": "showContextMenuHere", "args": {}}
        }),
        ("Control", "Z"): Classes.BindPayloads({
            "*": {"id": "hello", "args": {}}
        }),
        ("W",): Classes.BindPayloads({
            "*": {"id": "file.0", "args": {}},
            "Widget A": {"id": "file.1", "args": {}},
            "Widget B": {"id": "file.2", "args": {}},
            "Widget C": {"id": "file.3", "args": {}},
        }),
    }
