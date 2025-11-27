from __future__ import annotations
from typing import Any, Callable, Dict, List, Optional
from .core import register_command_defs


def split_parts(raw: str) -> List[str]:
    return [p for p in raw.split("/") if p]


def is_sep_token(s: Any) -> bool:
    if not isinstance(s, str):
        return False
    parts = split_parts(s.strip())
    return bool(parts) and parts[-1] == "-"


def sep_path(s: str) -> List[str]:
    parts = split_parts(s.strip())
    return parts[:-1] if parts and parts[-1] == "-" else []


def is_section_token(s: Any) -> bool:
    if not isinstance(s, str):
        return False
    parts = split_parts(s)
    return bool(parts) and str(parts[-1]).startswith(":")


def section_parts(s: str) -> List[str]:
    parts = split_parts(s)
    if not parts:
        return []
    head = parts[:-1]
    label = parts[-1][1:] if parts[-1].startswith(":") else parts[-1]
    return head + [label]


def chain_providers(*providers: Optional[Callable[[], Dict[str, Any]]]) -> Optional[Callable[[], Dict[str, Any]]]:
    ps = [p for p in providers if callable(p)]
    if not ps:
        return None
    def _p():
        r: Dict[str, Any] = {}
        for fn in ps:
            try:
                v = fn() or {}
                if isinstance(v, dict):
                    r.update(v)
            except Exception:
                pass
        return r
    return _p


def prefixed_path(base_parts: List[str], p: str) -> str:
    pparts = split_parts(p)
    if not base_parts:
        return "/".join(pparts)
    if pparts[:len(base_parts)] == base_parts:
        return "/".join(pparts)
    return "/".join(base_parts + pparts)


def prefixed_item_token(base_parts: List[str], s: str) -> str:
    if not base_parts:
        return s
    if is_sep_token(s):
        sparts = sep_path(s)
        return "/".join(base_parts + sparts + ["-"])
    if is_section_token(s):
        sparts = section_parts(s)
        if not sparts:
            return s
        head, label = sparts[:-1], sparts[-1]
        if head[:len(base_parts)] == base_parts:
            return "/".join(head + [":" + label])
        return "/".join(base_parts + head + [":" + label])
    return prefixed_path(base_parts, s)


def normalize_def(base_parts: List[str], e: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(e, dict) or ("meta" not in e):
        raise ValueError("Definition must be a dict with 'meta' and 'path'")
    meta = e["meta"]
    full_path = e.get("path")
    if not full_path:
        raise ValueError("Command 'path' is required and id is derived from its last segment")
    full_path = prefixed_path(base_parts, str(full_path))
    parts = split_parts(full_path)
    if not parts or parts[-1] == "-" or str(parts[-1]).startswith(":"):
        raise ValueError(f"Invalid command path: {full_path}")
    cid = parts[-1]
    if hasattr(meta, "id"):
        setattr(meta, "id", cid)
    e["path"] = "/".join(parts)
    return e


def extract_raw_lists(res: Any) -> tuple[list[Dict[str, Any]], list[str], str]:
    raw_defs_list: List[Dict[str, Any]] = []
    raw_items_list: List[str] = []
    kind = "none"
    if isinstance(res, tuple) and len(res) == 2:
        a, b = res  # type: ignore
        if isinstance(a, list):
            raw_defs_list = a
        if isinstance(b, list):
            raw_items_list = b
        kind = "tuple"
    elif isinstance(res, list):
        for e in res:  # type: ignore
            if isinstance(e, str):
                raw_items_list.append(e)
            elif isinstance(e, dict) and ("meta" in e):
                raw_defs_list.append(e)
        kind = "list"
    elif res:
        raw_defs_list = res  # type: ignore
        kind = "defs"
    return raw_defs_list, raw_items_list, kind


class RegistryBackedMenu:
    _flags: Dict[type, bool] = {}
    _items: Dict[type, List[str]] = {}
    _cmd_paths: Dict[type, Dict[str, str]] = {}

    def __init__(self):
        self.ensure_registered()

    def __init_subclass__(cls):
        super().__init_subclass__()
        if cls not in RegistryBackedMenu._flags:
            try:
                cls()
            except Exception:
                pass

    def ensure_registered(self):
        t = type(self)
        if self._flags.get(t, False):
            return
        res = self.create_definitions()
        base = getattr(self, "path_prefix", None)
        base_parts = split_parts(base) if isinstance(base, str) and base else []
        defs: List[Dict[str, Any]] = []
        items: List[str] = []
        cmd_paths: Dict[str, str] = {}
        raw_defs_list, raw_items_list, kind = extract_raw_lists(res)
        if kind == "list":
            defs = []
            items = []
            for e in res:  # type: ignore
                if isinstance(e, str):
                    items.append(prefixed_item_token(base_parts, e))
                elif isinstance(e, dict) and ("meta" in e):
                    ne = normalize_def(base_parts, e)
                    defs.append(ne)
                    items.append(ne["path"])
        else:
            for e in raw_defs_list:
                defs.append(normalize_def(base_parts, e))
            for s in raw_items_list:
                if isinstance(s, str):
                    items.append(prefixed_item_token(base_parts, s))
            if kind == "defs" and defs:
                for e in defs:
                    items.append(e["path"])
        for s in items:
            if not isinstance(s, str) or not s or is_section_token(s) or is_sep_token(s):
                continue
            parts = [p for p in s.split("/") if p]
            if parts:
                cid = parts[-1]
                if cid in cmd_paths:
                    raise ValueError(f"Duplicate command id in {t.__name__}: {cid}")
                cmd_paths[cid] = s
        if defs:
            register_command_defs(defs)
        if items:
            self._items[t] = items
        if cmd_paths:
            self._cmd_paths[t] = cmd_paths
        try:
            MenuHub().register_paths(t, cmd_paths, items)
        except Exception:
            pass
        self._flags[t] = True

    def create_definitions(self) -> Any:
        return []


class MenuHub:
    _instance: Optional["MenuHub"] = None
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._all_paths = {}
            cls._instance._by_menu = {}
            cls._instance._menu_items = {}
            cls._instance._folder_blocks = {}
        return cls._instance
    
    def register_paths(self, menu_cls: type, cmd_paths: Dict[str, str], items: Optional[List[str]] = None):
        if cmd_paths:
            self._by_menu[menu_cls] = dict(cmd_paths)
            for k, v in cmd_paths.items():
                if k in self._all_paths and self._all_paths[k] != v:
                    raise ValueError(f"Command id already registered: {k}")
                self._all_paths[k] = v
        if items is not None:
            self._menu_items[menu_cls] = list(items)
            self._index_folder_blocks(items)

    def get_path_by_command_id(self, command_id: str) -> str:
        return self._all_paths.get(command_id, "")
    
    def has_folder(self, folder: str) -> bool:
        f = folder.strip("/")
        if not f:
            return False
        for p in self._all_paths.values():
            parts = split_parts(p)
            if len(parts) <= 1:
                continue
            if f in parts[:-1]:
                return True
        return False
    
    def find_folder_prefixes(self, name: str) -> List[str]:
        n = name.strip("/")
        if not n:
            return []
        seen: Dict[str, None] = {}
        out: List[str] = []
        for p in self._all_paths.values():
            parts = split_parts(p)
            if len(parts) <= 1:
                continue
            for i in range(len(parts) - 1):
                if parts[i] == n:
                    pref = "/".join(parts[: i + 1])
                    if pref not in seen:
                        seen[pref] = None
                        out.append(pref)
        return out
    
    def collect_items_by_folder(self, folder: str, rebase_to: Optional[str] = None) -> List[str]:
        f = folder.strip("/")
        fparts = split_parts(f)
        filtered: List[List[str]] = self._folder_blocks.get(f, [])
        out: List[str] = []
        pre = rebase_to.strip("/") if rebase_to else f
        first = True
        for b in filtered:
            if not first:
                out.append(f"{pre}/-")
            first = False
            for s in b:
                if not isinstance(s, str) or not s:
                    continue
                if is_sep_token(s):
                    src = sep_path(str(s))
                    if not src:
                        out.append(f"{pre}/-")
                        continue
                    if src[:len(fparts)] != fparts:
                        continue
                    rel = src[len(fparts):]
                    out.append("/".join([pre] + rel + ["-"]))
                    continue
                if is_section_token(s):
                    parts = section_parts(s)
                    if not parts:
                        continue
                    head = parts[:-1]
                    label = parts[-1]
                    if head[:len(fparts)] != fparts:
                        continue
                    rel = head[len(fparts):]
                    out.append("/".join([pre] + rel + [":" + label]))
                    continue
                if "/" in s:
                    pfull = s
                else:
                    pfull = self._all_paths.get(s, "")
                if pfull and pfull.startswith(f + "/"):
                    rel = pfull[len(f) + 1:]
                    out.append(f"{pre}/{rel}".lstrip("/"))
        return out

    def _index_folder_blocks(self, items: List[str]):
        cur: List[str] = []
        def _flush():
            nonlocal cur
            if not cur:
                return
            folders: Dict[str, None] = {}
            for s in cur:
                if not isinstance(s, str) or not s or is_sep_token(s) or is_section_token(s):
                    continue
                if "/" in s:
                    pfull = s
                else:
                    pfull = self._all_paths.get(s, "")
                if not pfull:
                    continue
                parts = split_parts(pfull)
                for i in range(1, len(parts)):
                    f = "/".join(parts[:i])
                    if f not in folders:
                        folders[f] = None
            for f in folders.keys():
                self._folder_blocks.setdefault(f, []).append(list(cur))
            cur = []
        for s in items:
            if is_sep_token(s) and not sep_path(str(s)):
                _flush()
                continue
            cur.append(s)
        _flush()
