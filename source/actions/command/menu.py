from __future__ import annotations
from typing import Any, Callable, Dict, List, Optional, Sequence
from source.common.profiling import profiler
from .core import register_command_defs, CommandMeta
from source.common.logs import AppLogger


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


@profiler.profile
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
            except Exception as e:
                AppLogger.warning(f"chain_providers failed: {getattr(fn, '__name__', str(fn))}", exc=e)
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


def normalize_meta(base_parts: List[str], meta: CommandMeta) -> CommandMeta:
    full_path = getattr(meta, "path", "")
    if not full_path:
        raise ValueError("CommandMeta.path is required and id is derived from its last segment")
    full_path = prefixed_path(base_parts, str(full_path))
    parts = split_parts(full_path)
    if not parts or parts[-1] == "-" or str(parts[-1]).startswith(":"):
        raise ValueError(f"Invalid command path: {full_path}")
    meta.id = parts[-1]
    meta.path = "/".join(parts)
    return meta


class RegistryBackedMenu:
    _flags: Dict[type, bool] = {}
    _items: Dict[type, List[str]] = {}
    _cmd_paths: Dict[type, Dict[str, str]] = {}

    def __init__(self):
        self._ensure_registered()

    @classmethod
    def register(cls) -> None:
        cls()

    @profiler.profile
    def _ensure_registered(self):
        t = type(self)
        if self._flags.get(t, False):
            return
        res = getattr(t, "commands", None)
        base = getattr(t, "prefix", None)
        base_parts = split_parts(base) if isinstance(base, str) and base else []
        defs: List[CommandMeta] = []
        items: List[str] = []
        cmd_paths: Dict[str, str] = {}
        if res is None:
            res = []
        if not isinstance(res, list):
            raise ValueError("commands must be list[str|CommandMeta]")
        for e in res:
            if isinstance(e, str):
                items.append(prefixed_item_token(base_parts, e))
                continue
            if isinstance(e, CommandMeta):
                meta = normalize_meta(base_parts, e)
                defs.append(meta)
                if not bool(getattr(meta, "hidden", False)):
                    items.append(meta.path)
                continue
            raise ValueError("commands must be list[str|CommandMeta]")
        for meta in defs:
            cid = str(getattr(meta, "id", "") or "")
            path = str(getattr(meta, "path", "") or "")
            if not cid or not path:
                continue
            if cid in cmd_paths and cmd_paths[cid] != path:
                raise ValueError(f"Duplicate command id in {t.__name__}: {cid}")
            cmd_paths[cid] = path
        for s in items:
            if not isinstance(s, str) or not s or is_section_token(s) or is_sep_token(s):
                continue
            parts = [p for p in s.split("/") if p]
            if not parts:
                continue
            cid = parts[-1]
            if cid in cmd_paths:
                if cmd_paths[cid] != s:
                    raise ValueError(f"Duplicate command id in {t.__name__}: {cid}")
                continue
            cmd_paths[cid] = s
        if defs:
            register_command_defs(defs)
        if items:
            self._items[t] = items
        if cmd_paths:
            self._cmd_paths[t] = cmd_paths
        try:
            MenuHub().register_paths(t, cmd_paths, items)
        except Exception as e:
            AppLogger.warning(f"MenuHub.register_paths failed: {t.__name__}", exc=e)
        self._flags[t] = True


class RegistryBackedCommandSet:
    _flags: Dict[type, bool] = {}

    def __init__(self):
        self._ensure_registered()

    @classmethod
    def register(cls) -> None:
        cls()

    @profiler.profile
    def _ensure_registered(self):
        t = type(self)
        if self._flags.get(t, False):
            return
        res = getattr(t, "commands", None)
        base = getattr(t, "prefix", None)
        base_parts = split_parts(base) if isinstance(base, str) and base else []
        defs: List[CommandMeta] = []
        if res is None:
            res = []
        if not isinstance(res, list):
            raise ValueError("commands must be list[CommandMeta]")
        for e in res:
            if isinstance(e, CommandMeta):
                defs.append(normalize_meta(base_parts, e))
                continue
            raise ValueError("commands must be list[CommandMeta]")
        if defs:
            register_command_defs(defs)
        self._flags[t] = True


def register_menu_classes(menu_classes: Sequence[type[RegistryBackedMenu]]) -> None:
    for cls in list(menu_classes or []):
        if cls is None:
            continue
        try:
            cls.register()
        except Exception as e:
            AppLogger.warning(f"register_menu_classes failed: {getattr(cls, '__name__', str(cls))}", exc=e)


class MenuHub:
    _instance: Optional["MenuHub"] = None
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._all_paths = {}
            cls._instance._by_menu = {}
            cls._instance._menu_items = {}
            cls._instance._folder_blocks = {}
            cls._instance._folder_set = set()
            cls._instance._folder_prefix_map = {}
        return cls._instance
    
    @profiler.profile
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
        self._rebuild_folder_caches()

    def get_path_by_command_id(self, command_id: str) -> str:
        return self._all_paths.get(command_id, "")
    
    def has_folder(self, folder: str) -> bool:
        f = folder.strip("/")
        return f in self._folder_set if f else False
    
    def find_folder_prefixes(self, name: str) -> List[str]:
        n = name.strip("/")
        return self._folder_prefix_map.get(n, []) if n else []
    
    @profiler.profile
    def _rebuild_folder_caches(self):
        self._folder_set.clear()
        self._folder_prefix_map.clear()
        for p in self._all_paths.values():
            parts = split_parts(p)
            if len(parts) <= 1:
                continue
            for i in range(len(parts) - 1):
                folder_name = parts[i]
                folder_path = "/".join(parts[:i + 1])
                self._folder_set.add(folder_path)
                if folder_name not in self._folder_prefix_map:
                    self._folder_prefix_map[folder_name] = []
                if folder_path not in self._folder_prefix_map[folder_name]:
                    self._folder_prefix_map[folder_name].append(folder_path)
    
    @profiler.profile
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

    @profiler.profile
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
