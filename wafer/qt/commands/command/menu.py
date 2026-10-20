from __future__ import annotations
from typing import Any
from collections.abc import Sequence
from ....core.profiling import profiler
from .core import register_command_defs, CommandMeta
from ....core.logs import AppLogger
from ....plugin.registry import PluginBase

MENU_SEPARATOR = "-"
MENU_SECTION_PREFIX = ":"


class MenuPath:
    FILE = "File"
    SELECTION = "Selection"
    QUERY = "Query"
    WIDGETS = "Widgets"
    PANEL = "Panel"
    WORKSPACE = "Workspace"
    PROCESS = "Process"
    SETTING = "Setting"
    ROOTS = (FILE, SELECTION, QUERY, WIDGETS, PANEL, WORKSPACE, PROCESS, SETTING)

    FOLDER_TREE = f"{WIDGETS}/FolderTree"
    GRID_VIEW = f"{WIDGETS}/GridView"
    FILE_VIEWER = f"{WIDGETS}/FileViewer"
    WINDOW = f"{WIDGETS}/Window"
    MENUS = f"{WIDGETS}/Menus"


def split_menu_path(raw: str) -> list[str]:
    return [p for p in raw.split("/") if p]


def is_sep_token(s: Any) -> bool:
    if not isinstance(s, str):
        return False
    parts = split_menu_path(s.strip())
    return bool(parts) and parts[-1] == MENU_SEPARATOR


def sep_path(s: str) -> list[str]:
    parts = split_menu_path(s.strip())
    return parts[:-1] if parts and parts[-1] == MENU_SEPARATOR else []


def is_section_token(s: Any) -> bool:
    if not isinstance(s, str):
        return False
    parts = split_menu_path(s)
    return bool(parts) and str(parts[-1]).startswith(MENU_SECTION_PREFIX)


def section_parts(s: str) -> list[str]:
    parts = split_menu_path(s)
    if not parts:
        return []
    head = parts[:-1]
    label = parts[-1][1:] if parts[-1].startswith(MENU_SECTION_PREFIX) else parts[-1]
    return head + [label]


def prefixed_path(base_parts: list[str], p: str) -> str:
    pparts = split_menu_path(p)
    if not base_parts:
        return "/".join(pparts)
    if pparts[: len(base_parts)] == base_parts:
        return "/".join(pparts)
    return "/".join(base_parts + pparts)


def prefixed_item_token(base_parts: list[str], s: str) -> str:
    if not base_parts:
        return s
    if is_sep_token(s):
        sparts = sep_path(s)
        return "/".join(base_parts + sparts + [MENU_SEPARATOR])
    if is_section_token(s):
        sparts = section_parts(s)
        if not sparts:
            return s
        head, label = sparts[:-1], sparts[-1]
        if head[: len(base_parts)] == base_parts:
            return "/".join(head + [MENU_SECTION_PREFIX + label])
        return "/".join(base_parts + head + [MENU_SECTION_PREFIX + label])
    return prefixed_path(base_parts, s)


def normalize_command_meta(base_parts: list[str], meta: CommandMeta) -> CommandMeta:
    if not meta.path:
        raise ValueError("CommandMeta.path is required and id is derived from its last segment")
    full_path = prefixed_path(base_parts, str(meta.path))
    parts = split_menu_path(full_path)
    if not parts or parts[-1] == MENU_SEPARATOR or str(parts[-1]).startswith(MENU_SECTION_PREFIX):
        raise ValueError(f"Invalid command path: {full_path}")
    meta.id = parts[-1]
    meta.path = "/".join(parts)
    return meta


class MenuGroup(PluginBase):
    SCOPE: str = "viewer"
    _flags: dict[type, bool] = {}
    _items: dict[type, list[str]] = {}
    _cmd_paths: dict[type, dict[str, str]] = {}

    def __init__(self):
        self._ensure_registered()

    @classmethod
    def register(cls) -> None:
        cls()

    @classmethod
    def commands(cls) -> list:
        return []

    @profiler.profile
    def _ensure_registered(self):
        t = type(self)
        if self._flags.get(t, False):
            return
        res = t.commands()
        base_parts = split_menu_path(t.NAME) if t.NAME else []
        defs: list[CommandMeta] = []
        items: list[str] = []
        cmd_paths: dict[str, str] = {}
        placed_ids: set[str] = set()
        if not isinstance(res, list):
            raise ValueError("commands() must return list[str|CommandMeta]")
        for e in res:
            if isinstance(e, str):
                items.append(prefixed_item_token(base_parts, e))
                continue
            if isinstance(e, CommandMeta):
                meta = normalize_command_meta(base_parts, e)
                defs.append(meta)
                if not meta.hidden:
                    items.append(meta.path)
                continue
            raise ValueError("commands must be list[str|CommandMeta]")
        for meta in defs:
            cid = meta.id
            path = meta.path
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
            placed_ids.add(cid)
        if defs:
            register_command_defs(defs)
        if items:
            self._items[t] = items
        if cmd_paths:
            self._cmd_paths[t] = cmd_paths
        try:
            MenuHub.instance().register_paths(t, cmd_paths, items, placed_ids=placed_ids)
        except Exception as e:
            AppLogger.warning(f"MenuHub.register_paths failed: {t.__name__}", exc=e)
        self._flags[t] = True


class DragMenuGroup(MenuGroup):
    @profiler.profile
    def _ensure_registered(self):
        t = type(self)
        if self._flags.get(t, False):
            return
        res = t.commands()
        base_parts = split_menu_path(t.NAME) if t.NAME else []
        defs: list[CommandMeta] = []
        if not isinstance(res, list):
            raise ValueError("commands() must return list[CommandMeta]")
        for e in res:
            if isinstance(e, CommandMeta):
                defs.append(normalize_command_meta(base_parts, e))
                continue
            raise ValueError("commands() must return list[CommandMeta]")
        if defs:
            register_command_defs(defs)
        self._flags[t] = True


def register_menu_classes(menu_classes: Sequence[type[MenuGroup]]) -> None:
    for cls in list(menu_classes or []):
        if cls is None:
            continue
        try:
            cls.register()
        except Exception as e:
            AppLogger.warning(f"register_menu_classes failed: {getattr(cls, '__name__', str(cls))}", exc=e)


class MenuHub:
    _instance: MenuHub | None = None

    @classmethod
    def instance(cls) -> MenuHub:
        if cls._instance is None:
            inst = object.__new__(cls)
            inst._all_paths = {}
            inst._by_menu = {}
            inst._menu_items = {}
            inst._folder_blocks = {}
            inst._folder_set = set()
            inst._folder_prefix_map = {}
            inst._menu_order = []
            inst._placed_only = set()
            cls._instance = inst
        return cls._instance

    def set_menu_order(self, order: list[str]):
        self._menu_order = list(order)
        self._reindex_folder_blocks()

    def ordered_menu_classes(self) -> list[type]:
        order_map = {name: i for i, name in enumerate(self._menu_order)}

        def block_key(cls: type) -> tuple[int, int]:
            name = getattr(cls, "NAME", "")
            return (1, order_map[name]) if name in order_map else (0, 0)

        return sorted(self._menu_items, key=block_key)

    @profiler.profile
    def register_paths(self, menu_cls: type, cmd_paths: dict[str, str], items: list[str] | None = None, *, placed_ids: set[str] | frozenset[str] = frozenset()):
        if cmd_paths:
            self._by_menu[menu_cls] = dict(cmd_paths)
            for k, v in cmd_paths.items():
                existing = self._all_paths.get(k)
                if k in placed_ids:
                    if existing is None:
                        self._all_paths[k] = v
                        self._placed_only.add(k)
                    continue
                if existing is not None and existing != v and k not in self._placed_only:
                    AppLogger.warning(f"Command '{k}' path conflict: '{existing}' vs '{v}', keeping existing")
                    continue
                self._all_paths[k] = v
                self._placed_only.discard(k)
        if items is not None:
            self._menu_items[menu_cls] = list(items)
            self._reindex_folder_blocks()
        self._rebuild_folder_caches()

    def _reindex_folder_blocks(self):
        self._folder_blocks.clear()
        for cls in self.ordered_menu_classes():
            self._index_folder_blocks(self._menu_items[cls])

    def get_path_by_command_id(self, command_id: str) -> str:
        return self._all_paths.get(command_id, "")

    def has_folder(self, folder: str) -> bool:
        f = folder.strip("/")
        return f in self._folder_set if f else False

    def find_folder_prefixes(self, name: str) -> list[str]:
        n = name.strip("/")
        return self._folder_prefix_map.get(n, []) if n else []

    @profiler.profile
    def _rebuild_folder_caches(self):
        self._folder_set.clear()
        self._folder_prefix_map.clear()
        for p in self._all_paths.values():
            parts = split_menu_path(p)
            if len(parts) <= 1:
                continue
            for i in range(len(parts) - 1):
                folder_name = parts[i]
                folder_path = "/".join(parts[: i + 1])
                self._folder_set.add(folder_path)
                if folder_name not in self._folder_prefix_map:
                    self._folder_prefix_map[folder_name] = []
                if folder_path not in self._folder_prefix_map[folder_name]:
                    self._folder_prefix_map[folder_name].append(folder_path)

    @profiler.profile
    def collect_items_by_folder(self, folder: str, rebase_to: str | None = None) -> list[str]:
        f = folder.strip("/")
        fparts = split_menu_path(f)
        filtered: list[list[str]] = self._folder_blocks.get(f, [])
        out: list[str] = []
        pre = rebase_to.strip("/") if rebase_to else f
        prev_submenu: str | None = None
        for i, b in enumerate(filtered):
            submenu = self._single_submenu(b, fparts)
            if i > 0 and not (prev_submenu and submenu):
                out.append(f"{pre}/{MENU_SEPARATOR}")
            prev_submenu = submenu
            for s in b:
                if not isinstance(s, str) or not s:
                    continue
                if is_sep_token(s):
                    src = sep_path(str(s))
                    if not src:
                        out.append(f"{pre}/{MENU_SEPARATOR}")
                        continue
                    if src[: len(fparts)] != fparts:
                        continue
                    rel = src[len(fparts) :]
                    out.append("/".join([pre] + rel + [MENU_SEPARATOR]))
                    continue
                if is_section_token(s):
                    parts = section_parts(s)
                    if not parts:
                        continue
                    head = parts[:-1]
                    label = parts[-1]
                    if head[: len(fparts)] != fparts:
                        continue
                    rel = head[len(fparts) :]
                    out.append("/".join([pre] + rel + [MENU_SECTION_PREFIX + label]))
                    continue
                if "/" in s:
                    pfull = s
                else:
                    pfull = self._all_paths.get(s, "")
                if pfull and pfull.startswith(f + "/"):
                    rel = pfull[len(f) + 1 :]
                    out.append(f"{pre}/{rel}".lstrip("/"))
        return out

    def _token_parts(self, s: str) -> list[str]:
        if is_sep_token(s) or is_section_token(s) or "/" in s:
            return split_menu_path(s)
        return split_menu_path(self._all_paths.get(s, ""))

    def _single_submenu(self, block: list[str], fparts: list[str]) -> str | None:
        submenus: set[str] = set()
        for s in block:
            if not isinstance(s, str) or not s:
                continue
            parts = self._token_parts(s)
            if parts[: len(fparts)] != fparts:
                continue
            rel = parts[len(fparts) :]
            if len(rel) < 2:
                return None
            submenus.add(rel[0])
        return submenus.pop() if len(submenus) == 1 else None

    @profiler.profile
    def _index_folder_blocks(self, items: list[str]):
        cur: list[str] = []

        def _flush():
            nonlocal cur
            if not cur:
                return
            folders: dict[str, None] = {}
            for s in cur:
                if not isinstance(s, str) or not s or is_sep_token(s) or is_section_token(s):
                    continue
                if "/" in s:
                    pfull = s
                else:
                    pfull = self._all_paths.get(s, "")
                if not pfull:
                    continue
                parts = split_menu_path(pfull)
                for i in range(1, len(parts)):
                    f = "/".join(parts[:i])
                    if f not in folders:
                        folders[f] = None
            for f in folders:
                self._folder_blocks.setdefault(f, []).append(list(cur))
            cur = []

        for s in items:
            if is_sep_token(s) and not sep_path(str(s)):
                _flush()
                continue
            cur.append(s)
        _flush()
