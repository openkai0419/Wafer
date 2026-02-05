from source.actions.bridge import Kit


def get_all_mouse_bindings():
    return {
        Kit.Mouse("RIGHT", "SINGLE", ()): Kit.Bind({
            "*": {"id": "showContextMenuHere", "args": {}}
        }),
        Kit.Mouse("LEFT", "SINGLE", ()): Kit.Bind({
            "*": {"id": "hello", "args": {}},
            "Widget A": {"id": "file.0", "args": {}},
            "Widget B": {"id": "file.1", "args": {}},
        }),
        Kit.Mouse("LEFT", "SINGLE", ("RIGHT",)): Kit.Bind({
            "*": {"id": "path.0", "args": {}},
            "Widget A": {"id": "echo", "args": {}},
            "Widget B": {"id": "count", "args": {}},
        }),
        Kit.Mouse("LEFT", "SINGLE", ("MIDDLE",)): Kit.Bind({
            "Widget A": {"id": "echo", "args": {"text": "echoe", "repeat": 7}},
            "Widget B": {"id": "count", "args": {"value": 3, "step": 8}},
        }),
        Kit.Mouse("X1", "SINGLE", ()): Kit.Bind({
            "*": {"id": "toggleVerbose", "args": {}}
        }),
        Kit.Mouse("X2", "SINGLE", ()): Kit.Bind({
            "*": {"id": "mode", "args": {"mode": "C"}}
        }),
        Kit.Mouse("LEFT", "DOUBLE", ()): Kit.Bind({
            "*": {"id": "hello", "args": {}}
        }),
        Kit.Mouse("RIGHT", "SINGLE", ("LEFT",)): Kit.Bind({
            "*": {"id": "showAllMenu", "args": {}}
        }),
        Kit.Mouse("MIDDLE", "SINGLE", ("LEFT",)): Kit.Bind({
            "*": {"id": "sortBySize", "args": {}}
        }),
        Kit.Mouse("MIDDLE", "SINGLE", ("RIGHT",)): Kit.Bind({
            "*": {"id": "sortByName", "args": {}}
        }),
        Kit.Mouse("MIDDLE", "SINGLE", ()): Kit.Bind({
            "*": {"id": "cycleSortOrder", "args": {}}
        }),
        Kit.Mouse("LEFT", "DRAG_START", ()): Kit.Bind({
            "Widget A": {"id": "rectSelection", "args": {}},
            "Drag Demo Widget": {"id": "widgetDrag", "args": {}},
        }),
        Kit.Mouse("RIGHT", "DRAG_START", ()): Kit.Bind({
            "Widget A": {"id": "dragScroll", "args": {}}
        }),
        Kit.Mouse("NONE", "DROP", ()): Kit.Bind({
            "Widget A": {"id": "dropFiles", "args": {}},
            "Widget B": {"id": "simpleFileDrop", "args": {}},
            "Drag Demo Widget": {"id": "filePathDrop", "args": {}},
        }),
    }

def get_all_key_bindings():
    return {
        Kit.Key("H"): Kit.Bind({
            "*": {"id": "hello", "args": {}}
        }),
        Kit.Key("T"): Kit.Bind({
            "*": {"id": "time", "args": {}}
        }),
        Kit.Key("Ctrl", "W"): Kit.Bind({
            "*": {"id": "bindings", "args": {}}
        }),
        Kit.Key("A"): Kit.Bind({
            "*": {"id": "showContextMenuHere", "args": {}}
        }),
        Kit.Key("E"): Kit.Bind({
            "*": {"id": "showContextMenuHere", "args": {}}
        }),
        Kit.Key("Control", "Z"): Kit.Bind({
            "*": {"id": "hello", "args": {}}
        }),
        Kit.Key("W"): Kit.Bind({
            "*": {"id": "file.0", "args": {}},
            "Widget A": {"id": "file.1", "args": {}},
            "Widget B": {"id": "file.2", "args": {}},
            "Widget C": {"id": "file.3", "args": {}},
        }),
    }
