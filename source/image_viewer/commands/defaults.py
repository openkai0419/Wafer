from source.actions.bridge import Kit


def default_mouse_bindings():
    return {
        Kit.Mouse("RIGHT", "SINGLE"): Kit.Bind({
            "*": {"id": "allmenu", "args": {}}
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
