from __future__ import annotations
from typing import List, Tuple, Union
from ...utils import CommandPayload

KeySpec = Union[str, int]
KeyChordSpec = Tuple[KeySpec, ...]

def default_key_bindings() -> List[Tuple[KeyChordSpec, CommandPayload]]:
    return [
        (("Shift", "F10"), CommandPayload("showContextMenuHere", {})),
        (("H",), CommandPayload("hello", {})),
        (("T",), CommandPayload("time", {})),
    ]
