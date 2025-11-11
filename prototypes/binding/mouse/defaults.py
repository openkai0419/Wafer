from __future__ import annotations
from typing import Dict
from .mouseeventmanager import MouseActionKey, MouseButton, ClickType
from ...utils import CommandPayload

def default_mouse_bindings() -> Dict[MouseActionKey, CommandPayload]:
    return {
        MouseActionKey(MouseButton.RIGHT, ClickType.SINGLE, ()): CommandPayload("showContextMenuHere", {}),
        MouseActionKey(MouseButton.LEFT, ClickType.SINGLE, ()): CommandPayload("hello", {})
    }
