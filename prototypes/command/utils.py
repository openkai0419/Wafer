from typing import Any, Dict, Union
from pathlib import Path
import json
from PySide6 import QtWidgets

def is_json_text(s: str) -> bool:
    if not isinstance(s, str):
        return False
    t = s.strip()
    return t.startswith("{") and t.endswith("}")

def normalize_payload_dict(data: Any) -> Dict[str, Any]:
    if isinstance(data, dict):
        cid = str(data.get("id")) if "id" in data else None
        args = dict(data.get("args") or {}) if "args" in data else {}
        if not cid:
            raise ValueError("Payload missing id")
        return {"id": cid, "args": args}
    if isinstance(data, str):
        if is_json_text(data):
            v = json.loads(data)
            return normalize_payload_dict(v)
        s = data.strip()
        if not s:
            raise ValueError("Empty command id")
        return {"id": s, "args": {}}
    raise ValueError("Unsupported payload type")

def to_payload_json(data: Any) -> str:
    if isinstance(data, str) and is_json_text(data):
        return data.strip()
    p = normalize_payload_dict(data)
    return json.dumps(p, ensure_ascii=False, separators=(",", ":"))

def read_json_file(path: Union[str, Path], default: Any = None) -> Any:
    try:
        p = Path(path)
        if not p.exists():
            return default
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def write_json_file(path: Union[str, Path], data: Any, indent: int = 2, ensure_ascii: bool = False) -> bool:
    try:
        p = Path(path)
        with p.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=ensure_ascii, indent=indent)
        return True
    except Exception:
        return False

def show_error(parent: QtWidgets.QWidget, text: str, title: str = "Error") -> None:
    try:
        QtWidgets.QMessageBox.critical(parent, title, text)
    except Exception:
        pass
