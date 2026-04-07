from __future__ import annotations

from pathlib import Path
from collections.abc import Iterable

from ...utils.paths import normalize_path
from ..platform.file_operations import (
    MergeConflictItem,
    PasteCancelledError,
    PasteDecision,
    scan_merge_conflicts,
)
from ..platform.path_utils import check_copy_conflict
from .dialog import FileConflictDialog, FolderConflictDialog, SingleFileConflictDialog


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
                    same_path_items.append((idx, p))
                    continue
                if c == "subpath":
                    subpath_items.append((idx, p))
                    continue

            if not bool(getattr(p, "conflict", False)):
                no_conflict.append((idx, p))
                continue

            if bool(getattr(p, "is_dir", False)) and src is not None:
                folder_conflicts.append((idx, p))
            else:
                file_conflicts.append((idx, p))

        self._show_folder_apply_all = len(folder_conflicts) > 1
        self._show_same_path_apply_all = len(same_path_items) > 1
        self._show_subpath_apply_all = len(subpath_items) > 1
        total_file_conflicts = len(file_conflicts)
        for _, p in folder_conflicts:
            src = getattr(p, "src", None)
            dst = getattr(p, "dst_default", None)
            if src and dst:
                total_file_conflicts += len(scan_merge_conflicts(Path(src), Path(dst)))
        self._show_file_apply_all = total_file_conflicts > 1

        decisions: dict[int, PasteDecision] = {}

        for idx, _ in no_conflict:
            decisions[idx] = PasteDecision(mode="overwrite")

        for idx, p in subpath_items:
            self._notify_subpath(getattr(p, "src", None))
            decisions[idx] = PasteDecision(mode="skip")

        for idx, p in same_path_items:
            decisions[idx] = self._ask_same_path(getattr(p, "src", None))

        for idx, p in folder_conflicts:
            src = Path(getattr(p, "src", ""))
            dst = Path(getattr(p, "dst_default", ""))
            dec = self._ask_folder(src, dst)
            decisions[idx] = dec

        pending_merge_files: list[tuple[int, MergeConflictItem]] = []
        for idx, p in folder_conflicts:
            dec = decisions.get(idx)
            if dec and dec.mode == "merge":
                src = Path(getattr(p, "src", ""))
                dst = Path(getattr(p, "dst_default", ""))
                for c in scan_merge_conflicts(src, dst):
                    pending_merge_files.append((idx, c))

        for idx, p in file_conflicts:
            src = getattr(p, "src", None)
            dst = Path(getattr(p, "dst_default", ""))
            src_path = str(src) if src else ""
            name = str(getattr(src, "name", "") or getattr(p, "name", "") or "")
            src_bytes = None
            if src is None:
                item = getattr(p, "parsed_item", None)
                if item and getattr(item, "is_binary", False):
                    src_bytes = getattr(item, "source", None)
            dec = self._ask_file(src_path, str(dst), name, src_bytes)
            decisions[idx] = dec

        for idx, conflict in pending_merge_files:
            dec = self._ask_file(str(conflict.src), str(conflict.dst), conflict.src.name, None)
            parent_dec = decisions[idx]
            if parent_dec.merge_decisions is None:
                parent_dec.merge_decisions = {}
            parent_dec.merge_decisions[conflict.rel_path] = dec

        return decisions

    def _notify_subpath(self, src) -> None:
        if self._subpath_apply_all:
            return
        name = str(getattr(src, "name", "") or "")
        _, apply_all = SingleFileConflictDialog.ask(
            "コピー先がコピー元の中にあるためスキップします。",
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
        res, apply_all = FileConflictDialog.ask(
            "同一パスです。別名で保存しますか?",
            src_path=src_path,
            dst_path=src_path,
            src_name=name,
            op=self._op,
            show_apply_all=self._show_same_path_apply_all,
            buttons=("別名で保存", "スキップ", "キャンセル"),
            parent=self._parent,
        )
        choice = FileConflictDialog.parse_choice(res)
        if choice == "cancel":
            raise PasteCancelledError()
        if choice == "rename":
            if apply_all:
                self._same_path_apply_all = "rename"
            return PasteDecision(mode="rename")
        if apply_all:
            self._same_path_apply_all = "skip"
        return PasteDecision(mode="skip")

    def _ask_folder(self, src: Path, dst: Path) -> PasteDecision:
        if self._overwrite_mode in ("overwrite", "rename", "skip"):
            mode_map = {"overwrite": "merge", "rename": "rename", "skip": "skip"}
            return PasteDecision(mode=mode_map[self._overwrite_mode])

        if self._folder_apply_all is not None:
            return PasteDecision(mode=self._folder_apply_all)

        res, apply_all = FolderConflictDialog.ask(
            self._folder_message,
            src_path=normalize_path(str(src)),
            dst_path=normalize_path(str(dst)),
            src_name=src.name,
            op=self._op,
            show_apply_all=self._show_folder_apply_all,
            parent=self._parent,
        )
        choice = FolderConflictDialog.parse_choice(res)

        if choice == "cancel":
            raise PasteCancelledError()
        if choice is None or choice == "skip":
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

    def _ask_file(self, src_path: str, dst_path: str, name: str, src_bytes: bytes | bytearray | None) -> PasteDecision:
        if self._overwrite_mode in ("overwrite", "rename", "skip"):
            return PasteDecision(mode=self._overwrite_mode)

        if self._file_apply_all is not None:
            return PasteDecision(mode=self._file_apply_all)

        res, apply_all = FileConflictDialog.ask(
            "同名の項目が存在します。",
            src_path=normalize_path(src_path) if src_path else "",
            dst_path=normalize_path(dst_path),
            src_name=name,
            src_bytes=src_bytes,
            op=self._op,
            show_apply_all=self._show_file_apply_all,
            parent=self._parent,
        )
        choice = FileConflictDialog.parse_choice(res)

        if choice == "cancel":
            raise PasteCancelledError()
        if choice is None or choice == "skip":
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
