from enum import Enum, auto

from PySide6 import QtCore


class ClickType(Enum):
    SINGLE = auto()
    DOUBLE = auto()
    WHEEL_UP = auto()
    WHEEL_DOWN = auto()
    DRAG_START = auto()
    DROP = auto()

    @staticmethod
    def from_any(v):
        if isinstance(v, ClickType):
            return v
        if isinstance(v, str):
            s = v.strip().upper().replace("-", "_").replace(" ", "_")
            aliases = {
                "WHEELUP": "WHEEL_UP",
                "WHEELDOWN": "WHEEL_DOWN",
                "DRAGSTART": "DRAG_START",
            }
            s = aliases.get(s, s)
            try:
                return ClickType[s]
            except KeyError as e:
                raise ValueError(f"invalid ClickType: {v}") from e
        raise TypeError("ClickType must be ClickType or str")


class MouseButton(Enum):
    LEFT = QtCore.Qt.LeftButton
    RIGHT = QtCore.Qt.RightButton
    MIDDLE = QtCore.Qt.MiddleButton
    X1 = QtCore.Qt.XButton1
    X2 = QtCore.Qt.XButton2
    NONE = 0

    @staticmethod
    def from_any(v):
        if isinstance(v, MouseButton):
            return v
        if isinstance(v, str):
            s = v.strip().upper().replace("-", "_").replace(" ", "_")
            aliases = {
                "LMB": "LEFT",
                "RMB": "RIGHT",
                "MMB": "MIDDLE",
                "MB1": "X1",
                "MB2": "X2",
                "XBUTTON1": "X1",
                "XBUTTON2": "X2",
            }
            s = aliases.get(s, s)
            try:
                return MouseButton[s]
            except KeyError as e:
                raise ValueError(f"invalid MouseButton: {v}") from e
        raise TypeError("MouseButton must be MouseButton or str")


class ModifierKey(Enum):
    CTRL = auto()
    SHIFT = auto()
    ALT = auto()
    META = auto()

    @staticmethod
    def from_any(v):
        if isinstance(v, ModifierKey):
            return v
        if isinstance(v, str):
            s = v.strip().upper().replace("-", "_").replace(" ", "_")
            aliases = {
                "CONTROL": "CTRL",
                "CMD": "META",
                "COMMAND": "META",
                "WIN": "META",
                "WINDOWS": "META",
                "SUPER": "META",
                "OPTION": "ALT",
            }
            s = aliases.get(s, s)
            try:
                return ModifierKey[s]
            except KeyError as e:
                raise ValueError(f"invalid ModifierKey: {v}") from e
        raise TypeError("ModifierKey must be ModifierKey or str")


class MouseActionKey:
    def __init__(self, button, click_type=None, held_buttons=(), modifiers=()):
        if click_type is None:
            raise TypeError("MouseActionKey requires click_type")
        if held_buttons == {} or held_buttons is None:
            held_buttons = ()
        if modifiers == {} or modifiers is None:
            modifiers = ()
        self.button = MouseButton.from_any(button)
        self.click_type = ClickType.from_any(click_type)
        self.held_buttons = frozenset(MouseButton.from_any(b) for b in (held_buttons or ()))
        self.modifiers = frozenset(ModifierKey.from_any(m) for m in (modifiers or ()))

    def __hash__(self):
        return hash((self.button, self.click_type, self.held_buttons, self.modifiers))

    def __eq__(self, other):
        if not isinstance(other, MouseActionKey):
            return NotImplemented
        return self.button == other.button and self.click_type == other.click_type and (self.held_buttons == other.held_buttons) and (self.modifiers == other.modifiers)

    def __repr__(self):
        held = '+'.join((btn.name for btn in sorted(self.held_buttons, key=lambda b: b.name)))
        mods = '+'.join((m.name for m in sorted(self.modifiers, key=lambda m: m.name)))
        prefix = '+'.join([p for p in (mods, held) if p])
        return f"{'+'.join([prefix, self.button.name])} {self.click_type.name}" if prefix else f'{self.button.name} {self.click_type.name}'

    def to_dict(self):
        return {
            "button": self.button.name,
            "click": self.click_type.name,
            "held": [b.name for b in sorted(self.held_buttons, key=lambda x: x.name)],
            "modifiers": [m.name for m in sorted(self.modifiers, key=lambda x: x.name)],
        }

    @classmethod
    def from_dict(cls, d):
        if not isinstance(d, dict):
            raise TypeError("MouseActionKey dict required")
        btn = MouseButton.from_any(d.get("button"))
        clk = ClickType.from_any(d.get("click"))
        held = tuple(MouseButton.from_any(x) for x in (d.get("held") or ()))
        mods = tuple(ModifierKey.from_any(x) for x in (d.get("modifiers") or ()))
        return cls(btn, clk, held, mods)
