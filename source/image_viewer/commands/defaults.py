from source.actions.bridge import Kit


def default_mouse_bindings():
    return {
        Kit.Mouse("RIGHT", "SINGLE"): Kit.Bind({
            "*": {"id": "allmenu", "args": {}},
        }),
        Kit.Mouse("NONE", "WHEEL_UP"): Kit.Bind({
            "GraphicsView": {"id": "gv.zoom_in", "args": {}},
        }),
        Kit.Mouse("NONE", "WHEEL_DOWN"): Kit.Bind({
            "GraphicsView": {"id": "gv.zoom_out", "args": {}},
        }),
        Kit.Mouse("LEFT", "DOUBLE"): Kit.Bind({
            "GraphicsView": {"id": "gv.toggle_fit_mode", "args": {}},
        }),
        Kit.Mouse("LEFT", "DRAG_START"): Kit.Bind({
            "GraphicsView": {"id": "gv.pan", "args": {}},
        }),
    }

def default_key_bindings():
    return {
        Kit.Key("H"): Kit.Bind({
            "*": {"id": "mousebind", "args": {}}
        }),
        Kit.Key("W"): Kit.Bind({
            "*": {"id": "keybind", "args": {}},
        }),
    }
