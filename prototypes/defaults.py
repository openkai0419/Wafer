from source.actions.facade import Kit

ScopedPayloads = Kit.Payloads

KeySpec = str | int
KeyChordSpec = tuple[KeySpec, ...]
MouseActionSpec = tuple[object, ...]

def get_all_mouse_bindings() -> dict[MouseActionSpec, ScopedPayloads]:
    return {
        ("RIGHT", "SINGLE", ()): Kit.Payloads({
            "*": {"id": "showContextMenuHere", "args": {}}
        }),
        ("LEFT", "SINGLE", ()): Kit.Payloads({
            "*": {"id": "hello", "args": {}},
            "Widget A": {"id": "file.0", "args": {}},
            "Widget B": {"id": "file.1", "args": {}},
        }),
        ("LEFT", "SINGLE", ("RIGHT",)): Kit.Payloads({
            "*": {"id": "path.0", "args": {}},
            "Widget A": {"id": "echo", "args": {}},
            "Widget B": {"id": "count", "args": {}},
        }),
        ("LEFT", "SINGLE", ("MIDDLE",)): Kit.Payloads({
            "Widget A": {"id": "echo", "args": {"text": "echoe", "repeat": 7}},
            "Widget B": {"id": "count", "args": {"value": 3, "step": 8}},
        }),
        ("X1", "SINGLE", ()): Kit.Payloads({
            "*": {"id": "toggleVerbose", "args": {}}
        }),
        ("X2", "SINGLE", ()): Kit.Payloads({
            "*": {"id": "mode", "args": {"mode": "C"}}
        }),
        ("LEFT", "DOUBLE", ()): Kit.Payloads({
            "*": {"id": "hello", "args": {}}
        }),
        ("RIGHT", "SINGLE", ("LEFT",)): Kit.Payloads({
            "*": {"id": "showAllMenu", "args": {}}
        }),
        ("MIDDLE", "SINGLE", ("LEFT",)): Kit.Payloads({
            "*": {"id": "sortBySize", "args": {}}
        }),
        ("MIDDLE", "SINGLE", ("RIGHT",)): Kit.Payloads({
            "*": {"id": "sortByName", "args": {}}
        }),
        ("MIDDLE", "SINGLE", ()): Kit.Payloads({
            "*": {"id": "cycleSortOrder", "args": {}}
        }),
        ("LEFT", "DRAG_START", ()): Kit.Payloads({
            "Widget A": {"id": "rectSelection", "args": {}},
            "Drag Demo Widget": {"id": "widgetDrag", "args": {}},
        }),
        ("RIGHT", "DRAG_START", ()): Kit.Payloads({
            "Widget A": {"id": "dragScroll", "args": {}}
        }),
        ("NONE", "DROP", ()): Kit.Payloads({
            "Widget A": {"id": "dropFiles", "args": {}},
            "Widget B": {"id": "simpleFileDrop", "args": {}},
            "Drag Demo Widget": {"id": "filePathDrop", "args": {}},
        }),
    }

def get_all_key_bindings() -> dict[KeyChordSpec, ScopedPayloads]:
    return {
        ("H",): Kit.Payloads({
            "*": {"id": "hello", "args": {}}
        }),
        ("T",): Kit.Payloads({
            "*": {"id": "time", "args": {}}
        }),
        ("Ctrl", "W"): Kit.Payloads({
            "*": {"id": "bindings", "args": {}}
        }),
        ("A",): Kit.Payloads({
            "*": {"id": "showContextMenuHere", "args": {}}
        }),
        ("E",): Kit.Payloads({
            "*": {"id": "showContextMenuHere", "args": {}}
        }),
        ("Control", "Z"): Kit.Payloads({
            "*": {"id": "hello", "args": {}}
        }),
        ("W",): Kit.Payloads({
            "*": {"id": "file.0", "args": {}},
            "Widget A": {"id": "file.1", "args": {}},
            "Widget B": {"id": "file.2", "args": {}},
            "Widget C": {"id": "file.3", "args": {}},
        }),
    }
