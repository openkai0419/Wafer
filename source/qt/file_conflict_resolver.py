from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from ..common.funcs import normalize_path
from ..os.save import ClipboardFilePaster, PasteDecision, check_copy_conflict
from .dialog import ConfirmDialog, FileConflictDialog, SingleFileConflictDialog


@dataclass
class ConflictResolveSession:
    op: str
    parent: object | None
    show_apply_all: bool
    confirmed_mode: str | None = None
    same_apply_all: bool = False

    def _skip_same_path(self, *, conflict: str, src_path: str, name: str) -> bool:
        if conflict not in ("same_path", "subpath"):
            return False
        if self.same_apply_all:
            return True
        msg = "同一パスのためスキップします。" if conflict == "same_path" else "コピー先がコピー元の中にあるためスキップします。"
        _, apply_all = SingleFileConflictDialog.ask(
            msg,
            path=normalize_path(src_path),
            name=name,
            op=self.op,
            show_apply_all=self.show_apply_all,
            parent=self.parent,
        )
        if apply_all:
            self.same_apply_all = True
        return True

    def resolve_copy_conflict(self, *, src_path: str, dst_path: str, name: str) -> bool:
        conflict = check_copy_conflict(src_path, dst_path)
        return self._skip_same_path(conflict=conflict or "", src_path=src_path, name=name)

    def resolve_exists(
        self,
        *,
        src_path: str | None,
        dst_path: str,
        name: str,
        src_bytes: bytes | bytearray | None,
        default_mode: str,
    ) -> str:
        if default_mode in ("overwrite", "rename", "skip"):
            return default_mode
        if self.confirmed_mode is not None:
            return self.confirmed_mode
        res, apply_all = FileConflictDialog.ask(
            "同名の項目が存在します。",
            src_path=normalize_path(src_path) if src_path else "",
            dst_path=normalize_path(dst_path),
            src_name=name,
            src_bytes=src_bytes,
            op=self.op,
            show_apply_all=self.show_apply_all,
            parent=self.parent,
        )
        choice = FileConflictDialog.parse_choice(res)
        if choice is None or choice == "cancel":
            if apply_all:
                self.confirmed_mode = "skip"
            return "skip"
        mode = "overwrite" if choice == "overwrite" else "rename"
        if apply_all:
            self.confirmed_mode = mode
        return mode


def make_session(*, op: str, parent: object | None, item_count: int) -> ConflictResolveSession:
    if op not in ("copy", "move"):
        raise ValueError(f"Invalid op: {op}")
    return ConflictResolveSession(op=op, parent=parent, show_apply_all=item_count > 1)


def make_paste_resolver(
    *,
    op: str,
    overwrite_mode: str,
    parent: object | None,
    item_count: int,
    folder_message: str = "同名フォルダが存在します。ペーストしますか？",
) -> tuple[ConflictResolveSession, Callable[[Path, Path, bool, str], PasteDecision]]:
    session = make_session(op=op, parent=parent, item_count=item_count)

    def resolve_exists(src: Path, dst: Path, is_dir: bool, action: str) -> PasteDecision:
        if is_dir:
            res = ConfirmDialog.ask(folder_message, title="Confirm", buttons=("OK", "キャンセル"), parent=parent)
            return PasteDecision(mode=("merge" if res == "OK" else "skip"))
        if overwrite_mode in ("overwrite", "rename", "skip"):
            return PasteDecision(mode=overwrite_mode)
        mode = session.resolve_exists(
            src_path=str(src),
            dst_path=str(dst),
            name=str(getattr(src, "name", "") or ""),
            src_bytes=None,
            default_mode="ask",
        )
        return PasteDecision(mode=(mode if mode in ("overwrite", "rename", "skip") else "skip"))

    return session, resolve_exists


def resolve_paste_plans_with_ui(
    *,
    plans: Iterable[object],
    overwrite_mode: str,
    parent: object | None,
    op: str = "copy",
    folder_message: str = "同名フォルダが存在します。ペーストしますか？",
) -> tuple[dict[int, PasteDecision], Callable[[Path, Path, bool, str], PasteDecision]]:
    ps = list(plans or [])
    if not ps:
        return {}, lambda *_: PasteDecision(mode="skip")

    paster = ClipboardFilePaster()

    special_conflict_count = 0
    merge_child_conflict_count = 0
    exists_conflict_count = 0
    for p in ps:
        src = getattr(p, "src", None)
        dst = getattr(p, "dst_default", None)
        if src is None or dst is None:
            continue
        if bool(getattr(p, "conflict", False)):
            exists_conflict_count += 1
        c = check_copy_conflict(src, dst)
        if c in ("same_path", "subpath"):
            special_conflict_count += 1
        if bool(getattr(p, "is_dir", False)) and bool(getattr(p, "conflict", False)):
            merge_child_conflict_count += paster.estimate_merge_conflict_count(Path(src), Path(dst), stop_at=2)

    conflict_count = exists_conflict_count + special_conflict_count
    if conflict_count <= 1 and merge_child_conflict_count > 1:
        conflict_count = 2

    session, resolve_exists = make_paste_resolver(
        op=op,
        overwrite_mode=overwrite_mode,
        parent=parent,
        item_count=conflict_count,
        folder_message=folder_message,
    )

    decisions: dict[int, PasteDecision] = {}
    for p in ps:
        idx = int(getattr(p, "index", 0) or 0)
        src = getattr(p, "src", None)
        dst = getattr(p, "dst_default", None)
        if dst is None:
            decisions[idx] = PasteDecision(mode="skip")
            continue

        if src is None:
            if not bool(getattr(p, "conflict", False)):
                decisions[idx] = PasteDecision(mode="overwrite")
            else:
                decisions[idx] = resolve_exists(Path(dst), Path(dst), False, str(getattr(p, "action", "copy")))
            continue

        c = check_copy_conflict(src, dst)
        if c in ("same_path", "subpath"):
            if session.resolve_copy_conflict(src_path=str(src), dst_path=str(dst), name=str(getattr(src, "name", "") or "")):
                decisions[idx] = PasteDecision(mode="skip")
                continue

        if not bool(getattr(p, "conflict", False)):
            decisions[idx] = PasteDecision(mode="overwrite")
            continue

        decisions[idx] = resolve_exists(Path(src), Path(dst), bool(getattr(p, "is_dir", False)), str(getattr(p, "action", "copy")))

    return decisions, resolve_exists


def execute_paste_plans_with_ui(
    *,
    plans: Iterable[object],
    overwrite_mode: str,
    parent: object | None,
    folder_message: str = "同名フォルダが存在します。ペーストしますか？",
) -> list[dict[str, str]]:
    ps = list(plans or [])
    if not ps:
        return []
    op = "move" if (ps and getattr(ps[0], "action", "copy") == "cut") else "copy"
    decisions, resolve_exists = resolve_paste_plans_with_ui(
        plans=ps,
        overwrite_mode=overwrite_mode,
        parent=parent,
        op=op,
        folder_message=folder_message,
    )
    paster = ClipboardFilePaster()
    return paster.execute_paste(ps, decisions, resolve_exists=resolve_exists)
