from __future__ import annotations

from dataclasses import dataclass

from ..common.funcs import normalize_path
from ..os.file_transfer_utils import check_copy_conflict
from .dialog import FileConflictDialog, SingleFileConflictDialog


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
            "同名ファイルが存在します。",
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
