from typing import Any, Dict, Union, List
from pathlib import Path
import json
from PySide6 import QtWidgets
from .command.core import CommandRegistry

def is_json_text(s: str) -> bool:
    if not isinstance(s, str):
        return False
    t = s.strip()
    return t.startswith('{') and t.endswith('}')

def normalize_payload_dict(data: Any) -> Dict[str, Any]:
    if isinstance(data, dict):
        cid = str(data.get('id')) if 'id' in data else None
        args = dict(data.get('args') or {}) if 'args' in data else {}
        if not cid:
            raise ValueError('Payload missing id')
        return {'id': cid, 'args': args}
    if isinstance(data, str):
        if is_json_text(data):
            v = json.loads(data)
            return normalize_payload_dict(v)
        s = data.strip()
        if not s:
            raise ValueError('Empty command id')
        return {'id': s, 'args': {}}
    raise ValueError('Unsupported payload type')

def to_payload_json(data: Any) -> str:
    if isinstance(data, str) and is_json_text(data):
        return data.strip()
    p = normalize_payload_dict(data)
    return json.dumps(p, ensure_ascii=False, separators=(',', ':'))

def read_json_file(path: Union[str, Path], default: Any = None) -> Any:
    try:
        p = Path(path)
        if not p.exists():
            return default
        with p.open('r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default

def write_json_file(path: Union[str, Path], data: Any, indent: int = 2, ensure_ascii: bool = False) -> bool:
    try:
        p = Path(path)
        with p.open('w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=ensure_ascii, indent=indent)
        return True
    except Exception:
        return False

def show_error(parent: QtWidgets.QWidget, text: str, title: str = 'Error') -> None:
    try:
        QtWidgets.QMessageBox.critical(parent, title, text)
    except Exception:
        pass

def _ordered_arg_values(cid: str, args: Dict[str, Any]) -> List[str]:
    cls = CommandRegistry().get_command(cid)
    if not cls:
        return [str(v) for k, v in args.items()]
    meta = getattr(cls, "meta", None)
    out: List[str] = []
    seen: Dict[str, None] = {}
    if meta and getattr(meta, "params", None):
        for p in meta.params:  # type: ignore
            if p.name in args:
                out.append(str(args[p.name]))
                seen[p.name] = None
    for k in args.keys():
        if k not in seen:
            out.append(str(args[k]))
    return out

def format_payload_display(data: Any) -> str:
    try:
        p = normalize_payload_dict(data)
    except Exception:
        try:
            if isinstance(data, str) and is_json_text(data):
                return data.strip()
            return str(data)
        except Exception:
            return ""
    cid = p.get('id')
    args = dict(p.get('args') or {})
    cls = CommandRegistry().get_command(cid)
    name = cid
    if cls and getattr(cls, 'meta', None):
        try:
            name = str(getattr(cls.meta, 'display', cid) or cid)
        except Exception:
            name = cid
    if not args:
        return name
    vals = _ordered_arg_values(cid, args)
    if not vals:
        return name
    return f"{name} - {' '.join(vals)}"
