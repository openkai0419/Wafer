from __future__ import annotations

from typing import Any, Dict, List, Optional
import json


class CommandPayload:
    def __init__(self, id: str, args: Optional[Dict[str, Any]] = None):
        if not isinstance(id, str) or not id:
            raise ValueError("id must be non-empty string")
        self.id = id
        self.args = dict(args or {})

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "args": self.args}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "CommandPayload":
        if not isinstance(d, dict) or "id" not in d:
            raise TypeError("payload dict must contain id")
        return CommandPayload(str(d.get("id")), d.get("args"))

    @staticmethod
    def from_json(s: str) -> "CommandPayload":
        try:
            return CommandPayload.from_dict(json.loads(s))
        except (TypeError, ValueError) as e:
            raise TypeError("invalid json text") from e

    @staticmethod
    def from_any(v: Any) -> "CommandPayload":
        if isinstance(v, CommandPayload):
            return v
        if isinstance(v, dict):
            return CommandPayload.from_dict(v)
        raise TypeError("CommandPayload required")


def _ordered_arg_values(cid: str, args: Dict[str, Any]) -> List[str]:
    from .core import CommandRegistry
    cls = CommandRegistry().get_command(cid)
    if not cls:
        return [str(v) for v in args.values()]
    meta = getattr(cls, "meta", None)
    out: List[str] = []
    seen: Dict[str, None] = {}
    params = getattr(meta, "params", None) if meta else None
    if params:
        for p in params:
            name = getattr(p, "name", None)
            if isinstance(name, str) and name in args:
                out.append(str(args[name]))
                seen[name] = None
    for k in args.keys():
        if k not in seen:
            out.append(str(args[k]))
    return out


def format_payload_display(data: Any) -> str:
    try:
        p = CommandPayload.from_any(data)
    except (TypeError, ValueError):
        try:
            return str(data)
        except Exception as e:
            from source.utils.logs import AppLogger
            AppLogger.warning("format_payload_display str() failed", exc=e)
            return ""
    cid = p.id
    args = dict(p.args or {})
    from .core import CommandRegistry
    cls = CommandRegistry().get_command(cid)
    name = cid
    meta = getattr(cls, "meta", None) if cls else None
    if meta is not None:
        try:
            name = str(getattr(meta, "display", cid) or cid)
        except Exception as e:
            from source.utils.logs import AppLogger
            AppLogger.warning("format_payload_display meta.display failed", exc=e)
            name = cid
    if not args:
        return name
    vals = _ordered_arg_values(cid, args)
    if not vals:
        return name
    return f"{name} - {' '.join(vals)}"


class ScopedPayloads:
    def __init__(self, scopes: Dict[str, Any]):
        if not isinstance(scopes, dict):
            raise TypeError("scopes must be dict")
        self.scopes = scopes

    def to_dict(self) -> Dict[str, Any]:
        return self.scopes

    @staticmethod
    def from_any(v: Any) -> "ScopedPayloads":
        if isinstance(v, ScopedPayloads):
            return v
        if isinstance(v, dict):
            if "id" in v:
                return ScopedPayloads({"*": v})
            return ScopedPayloads(v)
        raise TypeError("scopes must be dict or ScopedPayloads")


def normalize_scoped_payloads(v: Any) -> Dict[str, CommandPayload]:
    scopes = ScopedPayloads.from_any(v).to_dict()
    out: Dict[str, CommandPayload] = {}
    for scope, payload in scopes.items():
        if payload is None:
            continue
        out[str(scope)] = CommandPayload.from_any(payload)
    return out
