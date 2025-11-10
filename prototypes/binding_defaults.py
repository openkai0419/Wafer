from __future__ import annotations
from typing import Dict
from .mouseeventmanager import MouseActionKey, MouseButton, ClickType
from .command.utils import to_payload_json

# 右クリック単押し(SINGLE)で context メニュー表示コマンドを呼ぶ初期バインド
# 共有モードとして空 args JSON を使用

def default_mouse_bindings() -> Dict[MouseActionKey, str]:
    return {
        MouseActionKey(MouseButton.RIGHT, ClickType.SINGLE, ()): to_payload_json({"id": "showContextMenuHere"}),
        MouseActionKey(MouseButton.LEFT, ClickType.SINGLE, ()): to_payload_json({"id": "hello"})
    }
