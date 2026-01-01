from __future__ import annotations
from typing import Any, Dict, Optional
from pathlib import Path
import json
from source.common.errors import show_warning
from ...command.payload import CommandPayload, normalize_scoped_payloads
from .sequence import KeySequence

class KeyBindingStore:
    _instance: Optional["KeyBindingStore"] = None
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._data = {}
        return cls._instance
    def get_all(self) -> Dict[KeySequence, Dict[str, CommandPayload]]:
        return {k: dict(v) for k, v in self._data.items()}

    @staticmethod
    def normalize_specs(data: Dict[Any, Any]) -> Dict[KeySequence, Dict[str, CommandPayload]]:
        nm: Dict[KeySequence, Dict[str, CommandPayload]] = {}
        for k, scopes in (data or {}).items():
            seq = k if isinstance(k, KeySequence) else KeySequence(k)
            dst = normalize_scoped_payloads(scopes)
            if dst:
                nm[seq] = dst
        return nm
    
    def set_all(self, data: Dict[KeySequence, Any]):
        nm: Dict[KeySequence, Dict[str, CommandPayload]] = {}
        for seq, scopes in data.items():
            if not isinstance(seq, KeySequence):
                raise TypeError("KeyBindingStore.set_all key must be KeySequence")
            try:
                dst = normalize_scoped_payloads(scopes)
            except Exception as e:
                raise TypeError(f"KeyBindingStore requires CommandPayload: {seq}") from e
            if dst:
                nm[seq] = dst
        self._data = nm

    def set_all_from_specs(self, data: Dict[Any, Any]):
        self._data = self.normalize_specs(data)
    
    def save_to_file(self, path: str):
        out = []
        for seq, scopes in self._data.items():
            entry = seq.to_dict()
            entry["scopes"] = {}
            for scope, payload in scopes.items():
                if isinstance(payload, CommandPayload):
                    entry["scopes"][scope] = {"id": payload.id, "args": payload.args}
            if entry.get("scopes"):
                out.append(entry)
        try:
            p = Path(path)
            if p.parent:
                p.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False, indent=2)
        except Exception as e:
            show_warning(None, f"KeyBindingStore.save_to_file failed: {path}", exc=e)
    
    def load_from_file(self, path: str) -> bool:
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, ValueError, TypeError):
            return False
        if not isinstance(raw, list):
            return False
        data: Dict[KeySequence, Dict[str, CommandPayload]] = {}
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            try:
                seq = KeySequence.from_dict(entry)
            except (ValueError, TypeError, KeyError):
                continue
            scopes = entry.get("scopes", {})
            scd: Dict[str, CommandPayload] = {}
            if isinstance(scopes, dict):
                for scope, obj in scopes.items():
                    if isinstance(obj, dict):
                        cid = obj.get("id")
                        args = obj.get("args", {})
                        if cid:
                            scd[scope] = CommandPayload(cid, args if isinstance(args, dict) else {})
            if scd:
                data[seq] = scd
        self._data = data
        return True
