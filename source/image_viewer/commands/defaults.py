from source.actions.bridge import Kit


def default_mouse_bindings():
    return {
        Kit.Mouse("RIGHT", "SINGLE"): Kit.Bind({
            "*": {"id": "allmenu", "args": {}},
            "FolderTree": {"id": "showfoldertreemenu", "args": {}},
        }),
        Kit.Mouse("LEFT", "SINGLE"): Kit.Bind({
            "JustifiedView": {"id": "jv.click_select_at_pos", "args": {}},
        }),
        Kit.Mouse("LEFT", "SINGLE", modifiers=("CTRL",)): Kit.Bind({
            "JustifiedView": {"id": "jv.toggle_at_pos", "args": {}},
        }),
        Kit.Mouse("LEFT", "SINGLE", modifiers=("SHIFT",)): Kit.Bind({
            "JustifiedView": {"id": "jv.range_select_at_pos", "args": {}},
        }),
        Kit.Mouse("LEFT", "DRAG_START", modifiers=("SHIFT",)): Kit.Bind({
            "JustifiedView": {"id": "jv.rect_select_replace", "args": {}},
        }),
        Kit.Mouse("LEFT", "DRAG_START", modifiers=("ALT",)): Kit.Bind({
            "JustifiedView": {"id": "jv.rect_select_add", "args": {}},
        }),
        Kit.Mouse("LEFT", "DRAG_START", modifiers=("CTRL",)): Kit.Bind({
            "JustifiedView": {"id": "jv.rect_select_remove", "args": {}},
        }),
        Kit.Mouse("X1", "SINGLE"): Kit.Bind({
            "GraphicsView": {"id": "fv.prev_file", "args": {}},
        }),
        Kit.Mouse("X2", "SINGLE"): Kit.Bind({
            "GraphicsView": {"id": "fv.next_file", "args": {}},
        }),
        Kit.Mouse("NONE", "WHEEL_UP"): Kit.Bind({
            "GraphicsView": {"id": "gv.zoom_in", "args": {}},
            "JustifiedView": {"id": "jv.scroll_up", "args": {"multiplier": 4}},
        }),
        Kit.Mouse("NONE", "WHEEL_DOWN"): Kit.Bind({
            "GraphicsView": {"id": "gv.zoom_out", "args": {}},
            "JustifiedView": {"id": "jv.scroll_down", "args": {"multiplier": 4}},
        }),
        Kit.Mouse("NONE", "WHEEL_UP", modifiers=("CTRL",)): Kit.Bind({
            "JustifiedView": {"id": "jv.scale_up", "args": {"ratio": 1.1}},
        }),
        Kit.Mouse("NONE", "WHEEL_DOWN", modifiers=("CTRL",)): Kit.Bind({
            "JustifiedView": {"id": "jv.scale_down", "args": {"ratio": 1.1}},
        }),
        Kit.Mouse("LEFT", "DOUBLE"): Kit.Bind({
            "JustifiedView": {"id": "jv.show_at_pos", "args": {}},
            "GraphicsView": {"id": "gv.toggle_fit_mode", "args": {}},
        }),
        Kit.Mouse("LEFT", "DRAG_START"): Kit.Bind({
            "JustifiedView": {"id": "jv.drag_files", "args": {}},
            "GraphicsView": {"id": "gv.pan", "args": {}},
        }),
        Kit.Mouse("NONE", "DROP"): Kit.Bind({
            "JustifiedView": {"id": "jv.drop_files_move", "args": {"on_conflict": "ask"}},
        }),
        Kit.Mouse("NONE", "DROP", modifiers=("SHIFT",)): Kit.Bind({
            "JustifiedView": {"id": "jv.drop_files_copy", "args": {"on_conflict": "ask"}},
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
