from __future__ import annotations

from PySide6 import QtCore

from .runtime import KeyNameResolver, KeySpec
from .sequence import KeySequence

KeyChordSpec = tuple[KeySpec, ...] | list[KeySpec]
KeyCombo = tuple[int, ...]

_MODIFIER_MAP: tuple[tuple[QtCore.Qt.KeyboardModifier, int], ...] = (
    (QtCore.Qt.ControlModifier, int(QtCore.Qt.Key_Control)),
    (QtCore.Qt.ShiftModifier, int(QtCore.Qt.Key_Shift)),
    (QtCore.Qt.AltModifier, int(QtCore.Qt.Key_Alt)),
    (QtCore.Qt.MetaModifier, int(QtCore.Qt.Key_Meta)),
)


def modifier_keys_from_qt(mods) -> list[int]:
    return [key for flag, key in _MODIFIER_MAP if mods & flag]


class ComboParser:
    def __init__(self, resolver: KeyNameResolver, max_len: int = 2):
        self._resolver = resolver
        self._max_len = max_len

    def _validate(self, xs: list[int]) -> KeyCombo:
        if not xs or len(xs) > self._max_len:
            return tuple()
        if len(xs) == 2 and xs[0] == xs[1]:
            return tuple()
        return tuple(xs)

    def from_sequence(self, seq: KeySequence) -> KeyCombo:
        tokens: list[int] = []
        for key_name in seq.to_tuple():
            tokens.append(self._resolver.to_key_code(self._resolver.normalize_token(key_name)))
        xs = [t for t in tokens if t]
        return self._validate(xs)

    def from_string(self, s: str) -> KeyCombo:
        if not s:
            return tuple()
        head = s.split(",")[0].strip()
        if not head:
            return tuple()
        parts = [p.strip() for p in head.replace("&", "+").split("+") if p.strip()]
        tokens: list[int] = []
        for p in parts:
            tokens.append(self._resolver.to_key_code(self._resolver.normalize_token(p)))
        xs = [t for t in tokens if t]
        return self._validate(xs)

    def from_spec(self, spec: KeyChordSpec) -> KeyCombo:
        xs = [self._resolver.to_key_code(x) for x in spec]
        xs = [x for x in xs if x]
        return self._validate(xs)

    def from_sc_spec(self, spec: KeyChordSpec) -> KeyCombo:
        def to_sc_code(token: KeySpec) -> int:
            if isinstance(token, int):
                return int(token)
            t = str(token).strip().upper()
            if not t:
                return 0
            if t.startswith("SC"):
                t = t[2:]
            return int(t) if t.isdigit() else 0

        xs = [to_sc_code(x) for x in spec]
        xs = [x for x in xs if x]
        return self._validate(xs)
