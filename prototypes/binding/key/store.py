from __future__ import annotations
from typing import Dict, Optional
from pathlib import Path
import json
from source.common.errors import show_warning
from ...command.payload import CommandPayload
from .sequence import KeySequence

class KeyBindingStore:
    _instance: Optional["KeyBindingStore"] = None
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._data = {}
            try:
                path = Path(__file__).resolve().parent.parent.parent / "key_bindings.json"
                if path.exists():
                    cls._instance.load_from_file(str(path))
            except Exception as e:
                show_warning(None, f"KeyBindingStore init load failed: {path}", exc=e)
        return cls._instance
    def get_all(self) -> Dict[KeySequence, Dict[str, CommandPayload]]:
        return {k: dict(v) for k, v in self._data.items()}
    
    def set_all(self, data: Dict[KeySequence, Dict[str, CommandPayload]]):
        self._data = {k: dict(v) for k, v in data.items()}
    
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
            with open(path, "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False, indent=2)
        except Exception as e:
            show_warning(None, f"KeyBindingStore.save_to_file failed: {path}", exc=e)
    
    def load_from_file(self, path: str) -> bool:
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception:
            return False
        data: Dict[KeySequence, Dict[str, CommandPayload]] = {}
        if isinstance(raw, list):
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
