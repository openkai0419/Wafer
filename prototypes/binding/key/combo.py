from typing import Dict, List, Tuple, Union, FrozenSet, Set, Optional
from ...utils import CommandPayload
from .runtime import KeyNameResolver, KeySpec
from .sequence import KeySequence

KeyChordSpec = Union[Tuple[KeySpec, ...], List[KeySpec]]

class ComboParser:
    def __init__(self, resolver: KeyNameResolver, max_len: int = 2):
        self._resolver = resolver
        self._max_len = max_len
    def from_sequence(self, seq: KeySequence) -> FrozenSet[int]:
        tokens: List[int] = []
        for key_name in seq.to_tuple():
            tokens.append(self._resolver.to_key_code(self._resolver.normalize_token(key_name)))
        xs = [t for t in tokens if t]
        if not xs or len(xs) > self._max_len:
            return frozenset()
        if len(xs) == 2 and xs[0] == xs[1]:
            return frozenset()
        return frozenset(xs)
    def from_string(self, s: str) -> FrozenSet[int]:
        if not s:
            return frozenset()
        head = s.split(",")[0].strip()
        if not head:
            return frozenset()
        parts = [p.strip() for p in head.replace("&", "+").split("+") if p.strip()]
        tokens: List[int] = []
        for p in parts:
            tokens.append(self._resolver.to_key_code(self._resolver.normalize_token(p)))
        xs = [t for t in tokens if t]
        if not xs or len(xs) > self._max_len:
            return frozenset()
        if len(xs) == 2 and xs[0] == xs[1]:
            return frozenset()
        return frozenset(xs)
    def from_spec(self, spec: KeyChordSpec) -> FrozenSet[int]:
        xs = [self._resolver.to_key_code(x) for x in spec]
        xs = [x for x in xs if x]
        if not xs or len(xs) > self._max_len:
            return frozenset()
        if len(xs) == 2 and xs[0] == xs[1]:
            return frozenset()
        return frozenset(xs)
    def from_sc_spec(self, spec: KeyChordSpec) -> FrozenSet[int]:
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
        if not xs or len(xs) > self._max_len:
            return frozenset()
        if len(xs) == 2 and xs[0] == xs[1]:
            return frozenset()
        return frozenset(xs)

class ComboMatcher:
    @staticmethod
    def best_match(pressed: Set[int], combos: Dict[FrozenSet[int], CommandPayload], require_len: int = 0) -> Optional[FrozenSet[int]]:
        best: Optional[FrozenSet[int]] = None
        for c in combos.keys():
            if require_len and len(c) != require_len:
                continue
            if c.issubset(pressed):
                if not best or len(c) > len(best):
                    best = c
        return best
