from typing import Set, Dict, List, Callable, Any, Tuple, Deque, Union
from collections import deque
from PySide6 import QtCore, QtGui
from source.common.errors import show_warning

KeySpec = Union[int, str]

class KeyPressState:
    def __init__(self):
        self.pressed: Set[int] = set()
        self.order: List[int] = []
        self.fired: Set[Tuple[int, ...]] = set()
        self.consumed: Dict[int, bool] = {}
    def add_pressed(self, key: int):
        k = int(key)
        if k in self.pressed:
            return
        self.pressed.add(k)
        self.order.append(k)
    def remove_pressed(self, key: int):
        k = int(key)
        self.pressed.discard(k)
        self.order = [x for x in self.order if x != k]

    def mark_fired(self, combo: Tuple[int, ...]):
        c = tuple(int(x) for x in combo)
        self.fired.add(c)
        for key in c:
            self.consumed[int(key)] = True

    def is_fired(self, combo: Tuple[int, ...]) -> bool:
        return tuple(combo) in self.fired
    def is_consumed(self, key: int) -> bool:
        return self.consumed.get(key, False)
    def unconsume(self, key: int):
        self.consumed.pop(key, None)
    def cleanup_fired(self):
        to_remove = [c for c in self.fired if any(int(k) not in self.pressed for k in c)]
        for c in to_remove:
            self.fired.remove(c)
        keys_to_remove = [k for k in self.consumed if k not in self.pressed]
        for k in keys_to_remove:
            self.consumed.pop(k, None)
    def reset(self):
        self.pressed.clear()
        self.order.clear()
        self.fired.clear()
        self.consumed.clear()

class RecentEventDeduper:
    def __init__(self, limit: int = 128):
        self._limit = int(limit) if limit and limit > 0 else 128
        self._queue: Deque[Tuple[Any, ...]] = deque()
        self._set: set[Tuple[Any, ...]] = set()
    def set_limit(self, n: int):
        self._limit = int(n) if n and n > 0 else self._limit
        self._shrink()
    def clear(self):
        self._queue.clear()
        self._set.clear()
    def add_and_check(self, stamp: Tuple[Any, ...]) -> bool:
        if stamp in self._set:
            return False
        self._queue.append(stamp)
        self._set.add(stamp)
        self._shrink()
        return True
    def _shrink(self):
        while len(self._queue) > self._limit:
            old = self._queue.popleft()
            self._set.discard(old)

class ScanCodeMapper:
    def __init__(self):
        self._map: Dict[int, Dict[int, int]] = {}
    def map(self, wid: int, sc: int, key: int) -> int:
        m = self._map.setdefault(int(wid), {})
        if sc not in m:
            m[sc] = int(key)
        return m.get(sc, int(key))
    def pop(self, wid: int, sc: int, default: int) -> int:
        m = self._map.get(int(wid)) or {}
        return int(m.pop(int(sc), int(default)))
    def clear(self, wid: int):
        self._map.pop(int(wid), None)

class KeyListenerRegistry:
    def __init__(self):
        self._press: Dict[int, List[Callable[..., None]]] = {}
        self._release: Dict[int, List[Callable[..., None]]] = {}
    def add_press(self, wid: int, cb: Callable[..., None]):
        lst = self._press.setdefault(int(wid), [])
        if cb not in lst:
            lst.append(cb)
    def add_release(self, wid: int, cb: Callable[..., None]):
        lst = self._release.setdefault(int(wid), [])
        if cb not in lst:
            lst.append(cb)
    def emit_press(self, wid: int, *args: Any):
        for cb in list(self._press.get(int(wid), []) or []):
            try:
                cb(*args)
            except Exception as e:
                show_warning(None, f"key press listener failed: {getattr(cb, '__name__', str(cb))}", exc=e)
    def emit_release(self, wid: int, *args: Any):
        for cb in list(self._release.get(int(wid), []) or []):
            try:
                cb(*args)
            except Exception as e:
                show_warning(None, f"key release listener failed: {getattr(cb, '__name__', str(cb))}", exc=e)
    def remove_all(self, wid: int):
        self._press.pop(int(wid), None)
        self._release.pop(int(wid), None)
    def ids(self) -> set[int]:
        return set(self._press.keys()) | set(self._release.keys())

class KeyNameResolver:
    def __init__(self):
        self._aliases = {
            'Ctrl': 'Control',
            'Win': 'Meta',
            'Cmd': 'Meta',
            'Enter': 'Return',
            'Esc': 'Escape',
            'Del': 'Delete',
            'Ins': 'Insert',
            'PgUp': 'PageUp',
            'PgDown': 'PageDown',
        }
        self._allowed_keys = set()
        for i in range(ord('A'), ord('Z') + 1):
            self._allowed_keys.add(getattr(QtCore.Qt.Key, f'Key_{chr(i)}'))
        for i in range(10):
            self._allowed_keys.add(getattr(QtCore.Qt.Key, f'Key_{i}'))
        for i in range(1, 25):
            k = getattr(QtCore.Qt.Key, f'Key_F{i}', None)
            if k is not None:
                self._allowed_keys.add(k)
        self._allowed_keys.update({
            QtCore.Qt.Key.Key_Shift,
            QtCore.Qt.Key.Key_Control,
            QtCore.Qt.Key.Key_Alt,
            QtCore.Qt.Key.Key_Meta,
        })
        self._allowed_keys.update({
            QtCore.Qt.Key.Key_Up,
            QtCore.Qt.Key.Key_Down,
            QtCore.Qt.Key.Key_Left,
            QtCore.Qt.Key.Key_Right,
            QtCore.Qt.Key.Key_Home,
            QtCore.Qt.Key.Key_End,
            QtCore.Qt.Key.Key_PageUp,
            QtCore.Qt.Key.Key_PageDown,
            QtCore.Qt.Key.Key_Insert,
            QtCore.Qt.Key.Key_Delete,
        })
        self._allowed_keys.update({
            QtCore.Qt.Key.Key_Space,
            QtCore.Qt.Key.Key_Tab,
            QtCore.Qt.Key.Key_Return,
            QtCore.Qt.Key.Key_Enter,
            QtCore.Qt.Key.Key_Backspace,
            QtCore.Qt.Key.Key_Escape,
        })
        symbol_keys = [
            'Minus', 'Equal', 'BracketLeft', 'BracketRight', 'Backslash',
            'Semicolon', 'Apostrophe', 'Comma', 'Period', 'Slash', 'Plus',
            'Asterisk', 'At', 'QuoteLeft', 'AsciiTilde', 'Underscore',
            'Ampersand', 'NumberSign', 'Dollar', 'Percent', 'AsciiCircum',
            'ParenLeft', 'ParenRight', 'BraceLeft', 'BraceRight', 'Bar',
            'Question', 'Exclam', 'Colon', 'Less', 'Greater'
        ]
        for sym in symbol_keys:
            k = getattr(QtCore.Qt.Key, f'Key_{sym}', None)
            if k is not None:
                self._allowed_keys.add(k)
        self._pretty_names = {
            'Control': 'Ctrl',
            'Meta': 'Win',
            'Return': 'Enter',
            'Escape': 'Esc',
            'Delete': 'Del',
            'Insert': 'Ins',
            'PageUp': 'PgUp',
            'PageDown': 'PgDown',
            'Space': 'Space',
        }
    def to_key_code(self, token: KeySpec) -> int:
        if isinstance(token, int):
            return token
        norm = self.normalize_token(str(token))
        return getattr(QtCore.Qt.Key, f'Key_{norm}', 0)
    def normalize_token(self, t: str) -> str:
        return self._aliases.get(t, t)
    def is_key_bindable(self, key: int) -> bool:
        return key in self._allowed_keys
    def key_name(self, key: int, pretty: bool = False) -> str:
        name = QtGui.QKeySequence(key).toString().replace('Ctrl+', 'Control').replace('Meta+', 'Meta')
        if '+' in name:
            name = name.split('+')[-1]
        if pretty and name in self._pretty_names:
            return self._pretty_names[name]
        return name
    def format_keys(self, keys: List[int], sep: str = '+', pretty: bool = False) -> str:
        return sep.join(self.key_name(k, pretty) for k in keys)
    def format_combo(self, combo: Tuple[int, ...], pretty: bool = False) -> str:
        return self.format_keys(list(combo), '+', pretty)
    def key_text_from_event(self, e: QtGui.QKeyEvent, pretty: bool = False) -> str:
        key = e.key()
        mods = e.modifiers()
        keys = []
        if mods & QtCore.Qt.KeyboardModifier.ControlModifier:
            keys.append(self.to_key_code('Control'))
        if mods & QtCore.Qt.KeyboardModifier.AltModifier:
            keys.append(self.to_key_code('Alt'))
        if mods & QtCore.Qt.KeyboardModifier.ShiftModifier:
            keys.append(self.to_key_code('Shift'))
        if mods & QtCore.Qt.KeyboardModifier.MetaModifier:
            keys.append(self.to_key_code('Meta'))
        keys.append(key)
        return self.format_keys(keys, '+', pretty)
