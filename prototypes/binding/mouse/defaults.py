from __future__ import annotations
from typing import Dict
from .mouseeventmanager import MouseActionKey, MouseButton, ClickType
from ...utils import to_payload_json

def default_mouse_bindings() -> Dict[MouseActionKey, str]:
    return {
        MouseActionKey(MouseButton.RIGHT, ClickType.SINGLE, ()): to_payload_json({"id": "showContextMenuHere"}),
        MouseActionKey(MouseButton.LEFT, ClickType.SINGLE, ()): to_payload_json({"id": "hello"})
    }
