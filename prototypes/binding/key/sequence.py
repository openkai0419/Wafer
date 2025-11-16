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
