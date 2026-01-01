from typing import Tuple, List, Optional, Dict, Any

class KeySequence:
    def __init__(self, keys: Tuple[str, ...] | List[str]):
        if isinstance(keys, str):
            raise TypeError("KeySequence requires tuple or list, not string")
        self._keys = tuple(keys[:2]) if len(keys) > 2 else tuple(keys)
        if not self._keys:
            raise ValueError("KeySequence requires at least one key")
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KeySequence":
        modifier = data.get("modifier", "")
        key = data.get("key", "")
        if not key:
            raise ValueError("Key is required in dictionary")
        if modifier:
            return cls([modifier, key])
        return cls([key])
    
    def to_dict(self) -> Dict[str, str]:
        if len(self._keys) == 1:
            return {"key": self._keys[0]}
        return {"modifier": self._keys[0], "key": self._keys[1]}
    
    def to_tuple(self) -> Tuple[str, ...]:
        return self._keys
    
    @property
    def modifier(self) -> Optional[str]:
        return self._keys[0] if len(self._keys) > 1 else None
    
    @property
    def key(self) -> str:
        return self._keys[-1]
    
    def __str__(self) -> str:
        if len(self._keys) == 1:
            return self._keys[0]
        return f"{self._keys[0]}+{self._keys[1]}"
    
    def __repr__(self) -> str:
        return f"KeySequence({self._keys})"
    
    def __eq__(self, other) -> bool:
        if isinstance(other, KeySequence):
            return self._keys == other._keys
        return False
    
    def __lt__(self, other) -> bool:
        if not isinstance(other, KeySequence):
            return NotImplemented
        return self._keys < other._keys
    
    def __hash__(self) -> int:
        return hash(self._keys)

class KeySpecCatalog:
    def __init__(self):
        self.modifiers = ["Control", "Shift", "Alt", "Meta"]
        self.special = ["Space", "Tab", "Return", "Enter", "Escape", "Backspace"]
        self.arrows = {"Left": 0, "Right": 1, "Up": 2, "Down": 3}
        self.nav = ["Home", "End", "PageUp", "PageDown", "Insert", "Delete"]
    def modifier_priority(self, name: str) -> int:
        return self.modifiers.index(name) if name in self.modifiers else 9
    def sort_modifiers(self, mods: List[str]) -> List[str]:
        xs = [m for m in mods if m not in ("(すべて)", "(なし)")]
        xs.sort(key=lambda x: (self.modifier_priority(x), x))
        return xs
    def key_sort_tuple(self, k: str) -> Tuple[int, object, str]:
        if not k:
            return (9, "", "")
        if k in self.modifiers:
            return (0, self.modifier_priority(k), k)
        if k in self.special:
            return (1, self.special.index(k), k)
        if k in self.arrows:
            return (3, self.arrows[k], k)
        if k in self.nav:
            return (3, 10 + self.nav.index(k), k)
        if k.startswith("F") and k[1:].isdigit():
            try:
                return (2, int(k[1:]), k)
            except ValueError:
                return (2, 9999, k)
        if len(k) == 1 and ("0" <= k <= "9"):
            return (4, int(k), k)
        if len(k) == 1 and ("A" <= k <= "Z"):
            return (5, k, k)
        return (2, k, k)
    def sort_main_keys(self, keys: List[str]) -> List[str]:
        xs = [k for k in keys if k not in ("(すべて)",)]
        xs.sort(key=lambda k: self.key_sort_tuple(k))
        return xs
