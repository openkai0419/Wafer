from __future__ import annotations
from typing import List, Tuple, Union, Dict
from .binding.mouse.mouseeventmanager import MouseActionKey, MouseButton, ClickType
from .utils import CommandPayload

KeySpec = Union[str, int]
KeyChordSpec = Tuple[KeySpec, ...]

def default_mouse_bindings() -> Dict[MouseActionKey, CommandPayload]:
    return {
        MouseActionKey(MouseButton.RIGHT, ClickType.SINGLE, ()): CommandPayload("showContextMenuHere", {}),
        MouseActionKey(MouseButton.LEFT, ClickType.SINGLE, ()): CommandPayload("hello", {}),
    }

def default_key_bindings() -> List[Tuple[KeyChordSpec, CommandPayload]]:
    return [
        (("Shift", "F10"), CommandPayload("showContextMenuHere", {})),
        (("H",), CommandPayload("hello", {})),
        (("T",), CommandPayload("time", {})),
    ]

def get_all_mouse_bindings() -> Dict[MouseActionKey, Dict[str, CommandPayload]]:
    return {
        MouseActionKey(MouseButton.RIGHT, ClickType.SINGLE, ()): {
            "*": CommandPayload("showContextMenuHere", {})
        },
        MouseActionKey(MouseButton.LEFT, ClickType.SINGLE, ()): {
            "*": CommandPayload("hello", {}),
            "Widget A": CommandPayload("file.0", {}),
            "Widget B": CommandPayload("file.1", {}),
        },
        MouseActionKey(MouseButton.LEFT, ClickType.SINGLE, (MouseButton.RIGHT,)): {
            "*": CommandPayload("path.0", {}),
            "Widget A": CommandPayload("echo", {}),
            "Widget B": CommandPayload("count", {}),
        },
        MouseActionKey(MouseButton.LEFT, ClickType.SINGLE, (MouseButton.MIDDLE,)): {
            "Widget A": CommandPayload("echo", {"text": "echoe", "repeat": 7}),
            "Widget B": CommandPayload("count", {"value": 3, "step": 8}),
        },
        MouseActionKey(MouseButton.X1, ClickType.SINGLE, ()): {
            "*": CommandPayload("toggleVerbose", {})
        },
        MouseActionKey(MouseButton.X2, ClickType.SINGLE, ()): {
            "*": CommandPayload("mode", {"mode": "C"})
        },
        MouseActionKey(MouseButton.LEFT, ClickType.DOUBLE, ()): {
            "*": CommandPayload("hello", {})
        },
        MouseActionKey(MouseButton.RIGHT, ClickType.SINGLE, (MouseButton.LEFT,)): {
            "*": CommandPayload("showAllMenu", {})
        },
        MouseActionKey(MouseButton.MIDDLE, ClickType.SINGLE, (MouseButton.LEFT,)): {
            "*": CommandPayload("sortBySize", {})
        },
        MouseActionKey(MouseButton.MIDDLE, ClickType.SINGLE, (MouseButton.RIGHT,)): {
            "*": CommandPayload("sortByName", {})
        },
        MouseActionKey(MouseButton.MIDDLE, ClickType.SINGLE, ()): {
            "*": CommandPayload("cycleSortOrder", {})
        },
        MouseActionKey(MouseButton.LEFT, ClickType.DRAG_START, ()): {
            "Widget A": CommandPayload("rectSelection", {}),
            "Drag Demo Widget": CommandPayload("widgetDrag", {}),
        },
        MouseActionKey(MouseButton.RIGHT, ClickType.DRAG_START, ()): {
            "Widget A": CommandPayload("dragScroll", {})
        },
        MouseActionKey(MouseButton.NONE, ClickType.DRAG_ENTER, ()): {
            "Widget A": CommandPayload("dropFiles", {})
        },
        MouseActionKey(MouseButton.NONE, ClickType.DROP, ()): {
            "Widget B": CommandPayload("simpleFileDrop", {}),
            "Drag Demo Widget": CommandPayload("filePathDrop", {}),
        },
    }

def get_all_key_bindings() -> Dict[KeyChordSpec, Dict[str, CommandPayload]]:
    return {
        ("H",): {
            "*": CommandPayload("hello", {})
        },
        ("T",): {
            "*": CommandPayload("time", {})
        },
        ("Ctrl", "W"): {
            "*": CommandPayload("bindings", {})
        },
        ("A",): {
            "*": CommandPayload("showContextMenuHere", {})
        },
        ("E",): {
            "*": CommandPayload("showContextMenuHere", {})
        },
        ("Control", "Z"): {
            "*": CommandPayload("hello", {})
        },
        ("W",): {
            "*": CommandPayload("file.0", {}),
            "Widget A": CommandPayload("file.1", {}),
            "Widget B": CommandPayload("file.2", {}),
            "Widget C": CommandPayload("file.3", {}),
        },
    }

def load_bindings_from_code():
    from .binding.mouse.store import MouseBindingStore
    from .binding.key.store import KeyBindingStore
    from .binding.key.sequence import KeySequence
    
    mouse_store = MouseBindingStore()
    mouse_store.set_all(get_all_mouse_bindings())
    
    key_store = KeyBindingStore()
    key_bindings = {}
    for spec, scopes in get_all_key_bindings().items():
        key_bindings[KeySequence(spec)] = scopes
    key_store.set_all(key_bindings)
