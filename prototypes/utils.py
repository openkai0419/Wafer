from typing import Any, Dict, Union, List, Optional
from pathlib import Path
import json
from PySide6 import QtWidgets

class CommandPayload:
    def __init__(self, id: str, args: Optional[Dict[str, Any]] = None):
        if not isinstance(id, str) or not id:
            raise ValueError('id must be non-empty string')
        self.id = id
        self.args = dict(args or {})

    def to_dict(self) -> Dict[str, Any]:
        return {'id': self.id, 'args': self.args}
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(',', ':'))
    
    @staticmethod
    def from_dict(d: Dict[str, Any]) -> 'CommandPayload':
        if not isinstance(d, dict) or 'id' not in d:
            raise TypeError('payload dict must contain id')
        return CommandPayload(str(d.get('id')), d.get('args'))
    @staticmethod
    def from_json(s: str) -> 'CommandPayload':
        try:
            return CommandPayload.from_dict(json.loads(s))
        except Exception as e:
            raise TypeError('invalid json text') from e
    @staticmethod
    def from_any(v: Any) -> 'CommandPayload':
        if isinstance(v, CommandPayload):
            return v
        if isinstance(v, dict):
            return CommandPayload.from_dict(v)
        raise TypeError('CommandPayload required')

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
    import sys
    print(f"{title}: {text}", file=sys.stderr)
    raise RuntimeError(text)

def _ordered_arg_values(cid: str, args: Dict[str, Any]) -> List[str]:
    from .command.core import CommandRegistry
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
        p = CommandPayload.from_any(data)
    except Exception:
        try:
            return str(data)
        except Exception:
            return ""
    cid = p.id
    args = dict(p.args or {})
    from .command.core import CommandRegistry
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
