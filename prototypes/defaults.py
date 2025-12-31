from .actions.command.payload import ScopedPayloads

KeySpec = str | int
KeyChordSpec = tuple[KeySpec, ...]
MouseActionSpec = tuple[object, ...]

def get_all_mouse_bindings() -> dict[MouseActionSpec, ScopedPayloads]:
    return {
        ("RIGHT", "SINGLE", ()): ScopedPayloads({
            "*": {"id": "showContextMenuHere", "args": {}}
        }),
        ("LEFT", "SINGLE", ()): ScopedPayloads({
            "*": {"id": "hello", "args": {}},
            "Widget A": {"id": "file.0", "args": {}},
            "Widget B": {"id": "file.1", "args": {}},
        }),
        ("LEFT", "SINGLE", ("RIGHT",)): ScopedPayloads({
            "*": {"id": "path.0", "args": {}},
            "Widget A": {"id": "echo", "args": {}},
            "Widget B": {"id": "count", "args": {}},
        }),
        ("LEFT", "SINGLE", ("MIDDLE",)): ScopedPayloads({
            "Widget A": {"id": "echo", "args": {"text": "echoe", "repeat": 7}},
            "Widget B": {"id": "count", "args": {"value": 3, "step": 8}},
        }),
        ("X1", "SINGLE", ()): ScopedPayloads({
            "*": {"id": "toggleVerbose", "args": {}}
        }),
        ("X2", "SINGLE", ()): ScopedPayloads({
            "*": {"id": "mode", "args": {"mode": "C"}}
        }),
        ("LEFT", "DOUBLE", ()): ScopedPayloads({
            "*": {"id": "hello", "args": {}}
        }),
        ("RIGHT", "SINGLE", ("LEFT",)): ScopedPayloads({
            "*": {"id": "showAllMenu", "args": {}}
        }),
        ("MIDDLE", "SINGLE", ("LEFT",)): ScopedPayloads({
            "*": {"id": "sortBySize", "args": {}}
        }),
        ("MIDDLE", "SINGLE", ("RIGHT",)): ScopedPayloads({
            "*": {"id": "sortByName", "args": {}}
        }),
        ("MIDDLE", "SINGLE", ()): ScopedPayloads({
            "*": {"id": "cycleSortOrder", "args": {}}
        }),
        ("LEFT", "DRAG_START", ()): ScopedPayloads({
            "Widget A": {"id": "rectSelection", "args": {}},
            "Drag Demo Widget": {"id": "widgetDrag", "args": {}},
        }),
        ("RIGHT", "DRAG_START", ()): ScopedPayloads({
            "Widget A": {"id": "dragScroll", "args": {}}
        }),
        ("NONE", "DROP", ()): ScopedPayloads({
            "Widget A": {"id": "dropFiles", "args": {}},
            "Widget B": {"id": "simpleFileDrop", "args": {}},
            "Drag Demo Widget": {"id": "filePathDrop", "args": {}},
        }),
    }

def get_all_key_bindings() -> dict[KeyChordSpec, ScopedPayloads]:
    return {
        ("H",): ScopedPayloads({
            "*": {"id": "hello", "args": {}}
        }),
        ("T",): ScopedPayloads({
            "*": {"id": "time", "args": {}}
        }),
        ("Ctrl", "W"): ScopedPayloads({
            "*": {"id": "bindings", "args": {}}
        }),
        ("A",): ScopedPayloads({
            "*": {"id": "showContextMenuHere", "args": {}}
        }),
        ("E",): ScopedPayloads({
            "*": {"id": "showContextMenuHere", "args": {}}
        }),
        ("Control", "Z"): ScopedPayloads({
            "*": {"id": "hello", "args": {}}
        }),
        ("W",): ScopedPayloads({
            "*": {"id": "file.0", "args": {}},
            "Widget A": {"id": "file.1", "args": {}},
            "Widget B": {"id": "file.2", "args": {}},
            "Widget C": {"id": "file.3", "args": {}},
        }),
    }
