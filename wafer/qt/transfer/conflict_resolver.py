from __future__ import annotations

from pathlib import Path
from collections.abc import Iterable

from PySide6 import QtWidgets

from ...core.logs import AppLogger
from ...core.common.paths import normalize_path
from ...core.platform.file_operations import PasteAnswer, PasteCancelledError, PasteConflict, PasteDecision
from ...core.platform.path_utils import check_copy_conflict
from ...core.lang.manager import t
from ..widgets.dialogs import FileConflictDialog, FolderConflictDialog, SingleFileConflictDialog


class PrecheckResolver:
    def __init__(self, *, op: str, overwrite_mode: str, parent: object | None):
        self._op = op
        self._overwrite_mode = overwrite_mode
        self._parent = parent
        self._same_path_apply_all: str | None = None
        self._subpath_apply_all = False

    def resolve(self, plans: list) -> dict[int, PasteDecision]:
        same_path: list[tuple[int, object]] = []
        subpath: list[tuple[int, object]] = []
        for p in plans:
            src = getattr(p, "src", None)
            dst = getattr(p, "dst_default", None)
            if src is None or dst is None:
                continue
            c = check_copy_conflict(src, dst)
            if c == "same_path" and not (self._op == "move" and Path(src).name != Path(dst).name):
                same_path.append((int(p.index), src))
            elif c == "subpath":
                subpath.append((int(p.index), src))

        decisions: dict[int, PasteDecision] = {}
        for idx, src in subpath:
            self._notify_subpath(src, show_apply_all=len(subpath) > 1)
            decisions[idx] = PasteDecision(mode="skip")
        for idx, src in same_path:
            decisions[idx] = self._ask_same_path(src, show_apply_all=len(same_path) > 1)
        return decisions

    def _notify_subpath(self, src, *, show_apply_all: bool) -> None:
        if self._subpath_apply_all:
            return
        _, apply_all = SingleFileConflictDialog.ask(
            t("Skipping: the destination is inside the source."),
            path=normalize_path(str(src)),
            name=Path(src).name,
            op=self._op,
            show_apply_all=show_apply_all,
            parent=self._parent,
        )
        if apply_all:
            self._subpath_apply_all = True

    def _ask_same_path(self, src, *, show_apply_all: bool) -> PasteDecision:
        if self._overwrite_mode == "rename":
            return PasteDecision(mode="rename")
        if self._overwrite_mode in ("overwrite", "skip"):
            return PasteDecision(mode="skip")
        if self._same_path_apply_all is not None:
            return PasteDecision(mode=self._same_path_apply_all)

        src_path = normalize_path(str(src))
        choice, apply_all = FileConflictDialog.ask(
            t("Same path. Save with a new name?"),
            src_path=src_path,
            dst_path=src_path,
            src_name=Path(src).name,
            op=self._op,
            show_apply_all=show_apply_all,
            choices=("rename", "skip", "cancel"),
            parent=self._parent,
        )
        if choice in (None, "cancel"):
            raise PasteCancelledError()
        mode = "rename" if choice == "rename" else "skip"
        if apply_all:
            self._same_path_apply_all = mode
        return PasteDecision(mode=mode)


class ConflictAsker:
    def __init__(
        self,
        *,
        op: str,
        overwrite_mode: str,
        parent: object | None,
        item_count: int,
        folder_message: str = "Folder with the same name already exists. Proceed?",
    ):
        self._op = op
        self._overwrite_mode = overwrite_mode
        self._parent = parent
        self._item_count = item_count
        self._folder_message = folder_message
        self._folder_apply_all: PasteAnswer | None = None
        self._file_apply_all: PasteAnswer | None = None

    def __call__(self, conflict: PasteConflict) -> PasteAnswer:
        if conflict.folders:
            return self._folder(conflict)
        return self._file(conflict)

    def _protects(self, conflict: PasteConflict) -> bool:
        return conflict.from_this_paste and (self._op == "move" or conflict.src is None)

    def _keep_both(self, conflict: PasteConflict) -> PasteAnswer:
        AppLogger.info(f"[{self._op}] {conflict.dst} was placed by this paste and has no other copy, so it is kept and {conflict.name} is saved under a new name")
        return "rename"

    def _dialog_parent(self):
        return QtWidgets.QApplication.activeModalWidget() or self._parent

    def _show_apply_all(self, conflict: PasteConflict) -> bool:
        return self._item_count > 1 or conflict.in_merge

    def _message(self, conflict: PasteConflict, existing: str) -> str:
        return t("Another selected item has the same name.") if conflict.from_this_paste else existing

    def _folder(self, conflict: PasteConflict) -> PasteAnswer:
        if self._overwrite_mode == "overwrite":
            return "merge"
        if self._overwrite_mode in ("rename", "skip"):
            return self._overwrite_mode
        if self._folder_apply_all is not None:
            return self._folder_apply_all

        choice, apply_all = FolderConflictDialog.ask(
            self._message(conflict, t(self._folder_message)),
            src_path=normalize_path(str(conflict.src)),
            dst_path=normalize_path(str(conflict.dst)),
            src_name=conflict.name,
            op=self._op,
            show_apply_all=self._show_apply_all(conflict),
            parent=self._dialog_parent(),
        )
        if choice in (None, "cancel"):
            raise PasteCancelledError()
        answer: PasteAnswer = choice if choice in ("merge", "skip") else "rename"
        if apply_all:
            self._folder_apply_all = answer
        return answer

    def _file(self, conflict: PasteConflict) -> PasteAnswer:
        if self._overwrite_mode in ("rename", "skip"):
            return self._overwrite_mode
        if self._overwrite_mode == "overwrite":
            return self._keep_both(conflict) if self._protects(conflict) else "overwrite"
        if self._file_apply_all is not None:
            if self._file_apply_all == "overwrite" and self._protects(conflict):
                return self._keep_both(conflict)
            return self._file_apply_all

        choices = ("rename", "skip", "cancel") if self._protects(conflict) else ("overwrite", "rename", "skip", "cancel")
        src = str(conflict.src) if conflict.src is not None else ""
        choice, apply_all = FileConflictDialog.ask(
            self._message(conflict, t("An item with the same name already exists.")),
            src_path=normalize_path(src) if src else "",
            dst_path=normalize_path(str(conflict.dst)),
            src_name=conflict.name,
            src_bytes=conflict.src_bytes,
            op=self._op,
            show_apply_all=self._show_apply_all(conflict),
            choices=choices,
            parent=self._dialog_parent(),
        )
        if choice in (None, "cancel"):
            raise PasteCancelledError()
        answer: PasteAnswer = choice if choice in ("overwrite", "skip") else "rename"
        if apply_all:
            self._file_apply_all = answer
        return answer


def precheck_paste_plans_with_ui(
    *,
    plans: Iterable[object],
    overwrite_mode: str,
    parent: object | None,
    op: str = "copy",
) -> dict[int, PasteDecision]:
    ps = list(plans or [])
    if not ps:
        return {}
    return PrecheckResolver(op=op, overwrite_mode=overwrite_mode, parent=parent).resolve(ps)
