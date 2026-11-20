from __future__ import annotations

import os
from pathlib import Path
from collections.abc import Iterable

from ...core.logs import AppLogger
from ...core.common.paths import normalize_path
from ...core.platform.file_operations import (
    MergeConflictItem,
    PasteCancelledError,
    PasteDecision,
    scan_merge_conflicts,
)
from ...core.platform.path_utils import check_copy_conflict
from ...core.lang.manager import t
from ..widgets.dialogs import FileConflictDialog, FolderConflictDialog, SingleFileConflictDialog


def _destination_key(path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def _earlier_with_same_destination(plans: list) -> dict[int, list]:
    seen: dict[str, list] = {}
    earlier: dict[int, list] = {}
    for p in plans:
        dst = getattr(p, "dst_default", None)
        if dst is None:
            continue
        same = seen.setdefault(_destination_key(dst), [])
        if same:
            earlier[int(getattr(p, "index", 0) or 0)] = list(same)
        same.append(p)
    return earlier


def _landing_source(p) -> Path:
    src = getattr(p, "src", None)
    return Path(src) if src is not None else Path(getattr(p, "dst_default", ""))


class ConflictResolver:
    def __init__(
        self,
        *,
        op: str,
        overwrite_mode: str,
        parent: object | None,
        folder_message: str,
    ):
        self._op = op
        self._overwrite_mode = overwrite_mode
        self._parent = parent
        self._folder_message = folder_message
        self._folder_apply_all: str | None = None
        self._file_apply_all: str | None = None
        self._same_path_apply_all: str | None = None
        self._subpath_apply_all: bool = False
        self._show_folder_apply_all: bool = False
        self._show_file_apply_all: bool = False
        self._show_same_path_apply_all: bool = False
        self._show_subpath_apply_all: bool = False

    def resolve_plans(self, plans: list) -> dict[int, PasteDecision]:
        folder_conflicts: list[tuple[int, object]] = []
        file_conflicts: list[tuple[int, object]] = []
        same_path_items: list[tuple[int, object]] = []
        subpath_items: list[tuple[int, object]] = []
        no_conflict: list[tuple[int, object]] = []
        self._earlier = _earlier_with_same_destination(plans)
        self._decisions: dict[int, PasteDecision] = {}

        for p in plans:
            src = getattr(p, "src", None)
            dst = getattr(p, "dst_default", None)
            idx = int(getattr(p, "index", 0) or 0)

            if dst is None:
                no_conflict.append((idx, p))
                continue

            if src is not None:
                c = check_copy_conflict(src, dst)
                if c == "same_path":
                    if self._op == "move" and Path(src).name != Path(dst).name:
                        no_conflict.append((idx, p))
                    else:
                        same_path_items.append((idx, p))
                    continue
                if c == "subpath":
                    subpath_items.append((idx, p))
                    continue

            if not (bool(getattr(p, "conflict", False)) or idx in self._earlier):
                no_conflict.append((idx, p))
                continue

            if bool(getattr(p, "is_dir", False)) and src is not None:
                folder_conflicts.append((idx, p))
            else:
                file_conflicts.append((idx, p))

        self._show_folder_apply_all = len(folder_conflicts) > 1
        self._show_same_path_apply_all = len(same_path_items) > 1
        self._show_subpath_apply_all = len(subpath_items) > 1
        merge_scans = self._count_file_conflicts(file_conflicts, folder_conflicts)

        decisions = self._decisions

        for idx, _ in no_conflict:
            decisions[idx] = PasteDecision(mode="create")

        for idx, p in subpath_items:
            self._notify_subpath(getattr(p, "src", None))
            decisions[idx] = PasteDecision(mode="skip")

        for idx, p in same_path_items:
            decisions[idx] = self._ask_same_path(getattr(p, "src", None))

        for idx, p in folder_conflicts:
            occupants = self._occupants(idx, p)
            if not occupants:
                decisions[idx] = PasteDecision(mode="create")
                continue
            src = Path(getattr(p, "src", ""))
            occupant, in_batch = occupants[-1]
            decisions[idx] = self._ask_folder(src, occupant, in_batch=in_batch)

        pending_merge_files: list[tuple[int, object, MergeConflictItem]] = []
        for idx, p in folder_conflicts:
            dec = decisions.get(idx)
            if self._overwrite_mode == "ask" and dec and dec.mode == "merge":
                occupant_paths = [path for path, _ in self._occupants(idx, p)]
                conflicts = merge_scans[idx] if idx in merge_scans else self._scan_merge(p, occupant_paths)
                pending_merge_files.extend((idx, p, c) for c in conflicts)

        for idx, p in file_conflicts:
            occupants = self._occupants(idx, p)
            if not occupants:
                decisions[idx] = PasteDecision(mode="create")
                continue
            src = getattr(p, "src", None)
            src_path = str(src) if src else ""
            name = str(getattr(src, "name", "") or getattr(p, "name", "") or "")
            src_bytes = None
            if src is None:
                item = getattr(p, "parsed_item", None)
                if item and getattr(item, "is_binary", False):
                    src_bytes = getattr(item, "source", None)
            occupant, in_batch = occupants[-1]
            decisions[idx] = self._ask_file(src_path, str(occupant), name, src_bytes, in_batch=in_batch)

        for idx, p, conflict in pending_merge_files:
            in_batch = not _destination_key(conflict.dst).startswith(_destination_key(p.dst_default) + os.sep)
            dec = self._ask_file(str(conflict.src), str(conflict.dst), conflict.src.name, None, in_batch=in_batch)
            parent_dec = decisions[idx]
            if parent_dec.merge_decisions is None:
                parent_dec.merge_decisions = {}
            parent_dec.merge_decisions[conflict.rel_path] = dec

        return decisions

    def _occupants(self, idx: int, p) -> list[tuple[Path, bool]]:
        dst = Path(getattr(p, "dst_default", ""))
        occupants = [(dst, False)] if bool(getattr(p, "conflict", False)) else []
        for earlier in self._earlier.get(idx, ()):
            dec = self._decisions.get(int(getattr(earlier, "index", 0) or 0))
            mode = dec.mode if dec else "create"
            if mode in ("create", "overwrite"):
                occupants = [(_landing_source(earlier), True)]
            elif mode == "merge":
                occupants.append((_landing_source(earlier), True))
        return occupants

    @staticmethod
    def _scan_merge(p, occupants: list[Path], limit: int | None = None) -> list[MergeConflictItem]:
        by_rel_path: dict[str, MergeConflictItem] = {}
        for occupant in occupants:
            for c in scan_merge_conflicts(Path(p.src), occupant, limit=limit):
                by_rel_path[c.rel_path] = c
        return list(by_rel_path.values())

    def _count_file_conflicts(self, file_conflicts: list, folder_conflicts: list) -> dict[int, list[MergeConflictItem]]:
        complete_scans: dict[int, list[MergeConflictItem]] = {}
        if self._overwrite_mode != "ask":
            return complete_scans
        total = len(file_conflicts)
        for idx, p in folder_conflicts:
            if total > 1:
                break
            limit = 2 - total
            batch = idx in self._earlier
            occupants = [Path(p.dst_default), *(_landing_source(e) for e in self._earlier.get(idx, ()))]
            found = self._scan_merge(p, occupants, limit=limit)
            if len(found) < limit and not batch:
                complete_scans[idx] = found
            total += len(found)
        self._show_file_apply_all = total > 1
        return complete_scans

    def _notify_subpath(self, src) -> None:
        if self._subpath_apply_all:
            return
        name = str(getattr(src, "name", "") or "")
        _, apply_all = SingleFileConflictDialog.ask(
            t("Skipping: the destination is inside the source."),
            path=normalize_path(str(src)),
            name=name,
            op=self._op,
            show_apply_all=self._show_subpath_apply_all,
            parent=self._parent,
        )
        if apply_all:
            self._subpath_apply_all = True

    def _ask_same_path(self, src) -> PasteDecision:
        if self._overwrite_mode == "rename":
            return PasteDecision(mode="rename")
        if self._overwrite_mode in ("overwrite", "skip"):
            return PasteDecision(mode="skip")

        if self._same_path_apply_all is not None:
            return PasteDecision(mode=self._same_path_apply_all)

        name = str(getattr(src, "name", "") or "")
        src_path = normalize_path(str(src)) if src else ""
        choice, apply_all = FileConflictDialog.ask(
            t("Same path. Save with a new name?"),
            src_path=src_path,
            dst_path=src_path,
            src_name=name,
            op=self._op,
            show_apply_all=self._show_same_path_apply_all,
            choices=("rename", "skip", "cancel"),
            parent=self._parent,
        )
        if choice in (None, "cancel"):
            raise PasteCancelledError()
        if choice == "rename":
            if apply_all:
                self._same_path_apply_all = "rename"
            return PasteDecision(mode="rename")
        if apply_all:
            self._same_path_apply_all = "skip"
        return PasteDecision(mode="skip")

    def _keep_both(self, src: Path) -> PasteDecision:
        AppLogger.info(f"[{self._op}] another selected item is also named {src.name}; both are kept, this one under a new name")
        return PasteDecision(mode="rename")

    def _ask_folder(self, src: Path, dst: Path, *, in_batch: bool = False) -> PasteDecision:
        if in_batch and self._overwrite_mode == "overwrite":
            return self._keep_both(src)
        if self._overwrite_mode in ("overwrite", "rename", "skip"):
            mode_map = {"overwrite": "merge", "rename": "rename", "skip": "skip"}
            return PasteDecision(mode=mode_map[self._overwrite_mode])

        if self._folder_apply_all is not None:
            return PasteDecision(mode=self._folder_apply_all)

        choice, apply_all = FolderConflictDialog.ask(
            t("Another selected item has the same name.") if in_batch else t(self._folder_message),
            src_path=normalize_path(str(src)),
            dst_path=normalize_path(str(dst)),
            src_name=src.name,
            op=self._op,
            show_apply_all=self._show_folder_apply_all,
            parent=self._parent,
        )

        if choice in (None, "cancel"):
            raise PasteCancelledError()
        if choice == "skip":
            if apply_all:
                self._folder_apply_all = "skip"
            return PasteDecision(mode="skip")
        if choice == "merge":
            if apply_all:
                self._folder_apply_all = "merge"
            return PasteDecision(mode="merge")
        if apply_all:
            self._folder_apply_all = "rename"
        return PasteDecision(mode="rename")

    def _ask_file(self, src_path: str, dst_path: str, name: str, src_bytes: bytes | bytearray | None, *, in_batch: bool = False) -> PasteDecision:
        if in_batch and self._overwrite_mode == "overwrite":
            return self._keep_both(Path(src_path or name))
        if self._overwrite_mode in ("overwrite", "rename", "skip"):
            return PasteDecision(mode=self._overwrite_mode)

        if self._file_apply_all is not None:
            if in_batch and self._file_apply_all == "overwrite":
                return self._keep_both(Path(src_path or name))
            return PasteDecision(mode=self._file_apply_all)

        choices = ("rename", "skip", "cancel") if in_batch and self._op == "move" else ("overwrite", "rename", "skip", "cancel")
        choice, apply_all = FileConflictDialog.ask(
            t("Another selected item has the same name.") if in_batch else t("An item with the same name already exists."),
            src_path=normalize_path(src_path) if src_path else "",
            dst_path=normalize_path(dst_path),
            src_name=name,
            src_bytes=src_bytes,
            op=self._op,
            show_apply_all=self._show_file_apply_all,
            choices=choices,
            parent=self._parent,
        )

        if choice in (None, "cancel"):
            raise PasteCancelledError()
        if choice == "skip":
            if apply_all:
                self._file_apply_all = "skip"
            return PasteDecision(mode="skip")
        if choice == "overwrite":
            if apply_all:
                self._file_apply_all = "overwrite"
            return PasteDecision(mode="overwrite")
        if apply_all:
            self._file_apply_all = "rename"
        return PasteDecision(mode="rename")


def resolve_paste_plans_with_ui(
    *,
    plans: Iterable[object],
    overwrite_mode: str,
    parent: object | None,
    op: str = "copy",
    folder_message: str = "Folder with the same name already exists. Proceed?",
) -> dict[int, PasteDecision]:
    ps = list(plans or [])
    if not ps:
        return {}
    resolver = ConflictResolver(
        op=op,
        overwrite_mode=overwrite_mode,
        parent=parent,
        folder_message=folder_message,
    )
    return resolver.resolve_plans(ps)
