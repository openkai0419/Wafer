from typing import Dict, List, Tuple, Union, Optional
from ...command.payload import CommandPayload
from .runtime import KeyNameResolver, KeySpec
from .sequence import KeySequence

KeyChordSpec = Union[Tuple[KeySpec, ...], List[KeySpec]]
KeyCombo = Tuple[int, ...]

class ComboParser:
    def __init__(self, resolver: KeyNameResolver, max_len: int = 2):
        self._resolver = resolver
        self._max_len = max_len
    
    def _validate(self, xs: List[int]) -> KeyCombo:
        if not xs or len(xs) > self._max_len:
            return tuple()
        if len(xs) == 2 and xs[0] == xs[1]:
            return tuple()
        return tuple(xs)
    
    def from_sequence(self, seq: KeySequence) -> KeyCombo:
        tokens: List[int] = []
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
        tokens: List[int] = []
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
                try:
                    return int(t[2:])
                except Exception:
                    return 0
            try:
                return int(t)
            except Exception:
                return 0
        xs = [to_sc_code(x) for x in spec]
        xs = [x for x in xs if x]
        return self._validate(xs)
