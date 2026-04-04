from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .core import CommandMeta, CommandRegistry, register_command_defs
from .menu import MenuHub, MENU_SEPARATOR, MENU_SECTION_PREFIX, is_section_token, is_sep_token, split_menu_path, normalize_command_meta


@dataclass(frozen=True)
class _ResolvedItem:
    token: str
    kind: str
    command_id: str
    canonical_path: str


class MenuPlan:
    def __init__(self, hub: MenuHub, items: list[_ResolvedItem]):
        self._hub = hub
        self._items = list(items)

    def resolve_tokens(self) -> list[str]:
        return [x.token for x in self._items]

    def hide(self, targets: Iterable[str]) -> "MenuPlan":
        ts = [str(t).strip().strip("/") for t in list(targets or []) if str(t).strip()]
        if not ts:
            return self
        items = list(self._items)
        for t in ts:
            before = len(items)
            if "/" in t:
                items = [x for x in items if not (x.kind == "cmd" and (x.token.strip("/") == t or x.canonical_path.strip("/") == t))]
            else:
                items = [x for x in items if not (x.kind == "cmd" and x.command_id == t)]
            if len(items) == before:
                raise ValueError(f"hide target not found: {t}")
        return MenuPlan(self._hub, items)

    def add(self, items: Any) -> "MenuPlan":
        extra = self._resolve_items(items)
        return MenuPlan(self._hub, list(self._items) + extra)

    def insert(self, target: str, items: Any) -> "MenuPlan":
        t = str(target or "").strip().strip("/")
        if not t:
            raise ValueError("insert target is required")
        extra = self._resolve_items(items)
        out = list(self._items)
        idxs = self._find_target_indexes(t)
        if not idxs:
            raise ValueError(f"insert target not found: {t}")
        shift = 0
        for i in idxs:
            at = i + 1 + shift
            out[at:at] = list(extra)
            shift += len(extra)
        return MenuPlan(self._hub, out)

    def _find_target_indexes(self, t: str) -> list[int]:
        if "/" in t:
            token_matches = [i for i, x in enumerate(self._items) if x.kind == "cmd" and x.token.strip("/") == t]
            if token_matches:
                if len(token_matches) > 1:
                    raise ValueError(f"insert target is ambiguous: {t}")
                return token_matches
            canon_matches = [i for i, x in enumerate(self._items) if x.kind == "cmd" and x.canonical_path.strip("/") == t]
            if canon_matches and len(canon_matches) > 1:
                raise ValueError(f"insert target is ambiguous: {t}")
            return canon_matches
        return [i for i, x in enumerate(self._items) if x.kind == "cmd" and x.command_id == t]

    def _resolve_items(self, raw_items: Any) -> list[_ResolvedItem]:
        out: list[_ResolvedItem] = []
        for entry in MenuMaker._normalize_menu_items(raw_items):
            if isinstance(entry, CommandMeta):
                out.append(MenuMaker._meta_to_resolved(entry))
                continue
            for it in MenuMaker._resolve_one(self._hub, str(entry)):
                out.append(it)
        return out


class MenuMaker:
    def __init__(self):
        self._hub = MenuHub.instance()

    @staticmethod
    def _normalize_menu_items(items: Any) -> list[Any]:
        if items is None:
            return []
        if isinstance(items, str):
            s = items.strip()
            return [s] if s else []
        if isinstance(items, (list, tuple)):
            out: list[Any] = []
            for x in items:
                if x is None:
                    continue
                if isinstance(x, CommandMeta):
                    out.append(x)
                    continue
                s = str(x).strip()
                if s:
                    out.append(s)
            return out
        raise TypeError(f"items must be str or list[str], got: {type(items).__name__}")

    @staticmethod
    def _meta_to_resolved(meta: CommandMeta) -> _ResolvedItem:
        m = normalize_command_meta([], meta)
        if not CommandRegistry.instance().has_command(str(m.id)):
            register_command_defs([m])
        return _ResolvedItem(token=str(m.path), kind="cmd", command_id=str(m.id), canonical_path=str(m.path))

    @staticmethod
    def _item_to_resolved(hub: MenuHub, token: str) -> _ResolvedItem:
        if is_sep_token(token):
            return _ResolvedItem(token=str(token), kind="sep", command_id="", canonical_path="")
        if is_section_token(token):
            return _ResolvedItem(token=str(token), kind="section", command_id="", canonical_path="")
        parts = split_menu_path(str(token))
        cid = parts[-1] if parts else str(token)
        canon = hub.get_path_by_command_id(cid)
        if not canon:
            if CommandRegistry.instance().has_command(cid):
                canon = str(token)
            else:
                raise ValueError(f"Unknown command id: {cid}")
        return _ResolvedItem(token=str(token), kind="cmd", command_id=cid, canonical_path=str(canon))

    @staticmethod
    def _resolve_one(hub: MenuHub, it: str) -> list[_ResolvedItem]:
        s = str(it or "").strip()
        if not s:
            return []
        if is_sep_token(s) or is_section_token(s):
            return [MenuMaker._item_to_resolved(hub, s)]
        if "/" in s:
            parts = split_menu_path(s)
            if len(parts) >= 2:
                orig_folder = parts[-1]
                if hub.has_folder(orig_folder):
                    prefs = hub.find_folder_prefixes(orig_folder)
                    if not prefs:
                        raise ValueError(f"Unknown folder: {orig_folder}")
                    if len(prefs) > 1:
                        raise ValueError(f"Ambiguous folder: {orig_folder}")
                    names = hub.collect_items_by_folder(prefs[0], rebase_to=s)
                    return [MenuMaker._item_to_resolved(hub, n) for n in names]
            if hub.has_folder(s):
                names = hub.collect_items_by_folder(s, rebase_to=s)
                return [MenuMaker._item_to_resolved(hub, n) for n in names]
            cid = split_menu_path(s)[-1]
            if not hub.get_path_by_command_id(cid):
                raise ValueError(f"Unknown command path or folder: {s}")
            return [MenuMaker._item_to_resolved(hub, s)]
        canon = hub.get_path_by_command_id(s)
        if canon:
            return [MenuMaker._item_to_resolved(hub, s)]
        prefs = hub.find_folder_prefixes(s)
        if len(prefs) > 1:
            raise ValueError(f"Ambiguous folder: {s}")
        if len(prefs) == 1:
            names = hub.collect_items_by_folder(prefs[0], rebase_to=s)
            return [MenuMaker._item_to_resolved(hub, n) for n in names]
        if hub.has_folder(s):
            names = hub.collect_items_by_folder(s, rebase_to=s)
            return [MenuMaker._item_to_resolved(hub, n) for n in names]
        raise ValueError(f"Unknown command or folder id: {s}")

    @staticmethod
    def _flatten_for_use(hub: MenuHub, token: str, base: str) -> str:
        s = str(token)
        if is_sep_token(s):
            parts = split_menu_path(s.strip())
            if parts and parts[0] == base:
                rel = parts[1:-1]
                return "/".join(rel + [MENU_SEPARATOR]) if rel else MENU_SEPARATOR
            return s
        if is_section_token(s):
            parts = split_menu_path(s)
            if parts and parts[0] == base:
                head = parts[1:-1]
                label = parts[-1]
                return "/".join(head + [label]) if head else label
            return s
        parts = split_menu_path(s)
        if parts and parts[0] == base:
            rel = parts[1:]
            return "/".join(rel)
        return s

    def menu(self, items: Any) -> MenuPlan:
        resolved: list[_ResolvedItem] = []
        for it in self._normalize_menu_items(items):
            if isinstance(it, CommandMeta):
                resolved.append(self._meta_to_resolved(it))
                continue
            resolved.extend(self._resolve_one(self._hub, str(it)))
        return MenuPlan(self._hub, resolved)

    def from_folder(self, folder: str) -> MenuPlan:
        s = (str(folder or "")).strip("/")
        if not s:
            raise ValueError("Folder is required")
        if self._hub.get_path_by_command_id(s):
            raise ValueError(f"Command id is not allowed: {s}")
        if "/" in s:
            if not self._hub.has_folder(s):
                raise ValueError(f"Unknown folder: {s}")
            names = self._hub.collect_items_by_folder(s, rebase_to=s)
        else:
            prefs = self._hub.find_folder_prefixes(s)
            if not self._hub.has_folder(s) and not prefs:
                raise ValueError(f"Unknown folder: {s}")
            if len(prefs) > 1:
                raise ValueError(f"Ambiguous folder: {s}")
            pref = prefs[0] if prefs else s
            names = self._hub.collect_items_by_folder(pref, rebase_to=s)
        if not names:
            raise ValueError(f"No items under folder: {s}")
        flat = [self._flatten_for_use(self._hub, n, s) for n in names]
        return self.menu(flat)

    def all_roots(self) -> MenuPlan:
        root_priority: dict[str, int] = {}
        for cls, items in self._hub._menu_items.items():
            priority = getattr(cls, 'PRIORITY', 0)
            for s in items:
                if not isinstance(s, str) or not s or s == "---" or s.startswith(MENU_SECTION_PREFIX):
                    continue
                parts = split_menu_path(s)
                if len(parts) < 2:
                    continue
                r = parts[0]
                if r not in root_priority or priority < root_priority[r]:
                    root_priority[r] = priority
        if not root_priority:
            raise ValueError("No top-level menus registered")
        menu_order = self._hub._menu_order
        if menu_order:
            order_map = {name: i for i, name in enumerate(menu_order)}
            roots = sorted(root_priority, key=lambda r: (1, order_map[r]) if r in order_map else (0, root_priority[r]))
        else:
            roots = sorted(root_priority, key=lambda r: root_priority[r])
        return self.menu(roots)
