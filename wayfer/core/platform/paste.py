from __future__ import annotations

import re
import struct
import sys
from pathlib import Path
from typing import Dict, List, Literal, Optional

from PySide6 import QtCore, QtGui

from ...utils.logs import AppLogger
from .path_utils import unique_path
from .file_operations import (
    CutCopy,
    DropPlanItem,
    OperationResult,
    PasteCancelledError,
    PasteDecision,
    PasteExecutor,
    PastePlanItem,
    build_drop_plans,
)


class ClipboardFilePaster:
    def __init__(self):
        self.clipboard = QtGui.QGuiApplication.clipboard()

    def _extract_windows_drop_effect(self, md: QtCore.QMimeData) -> Optional[str]:
        if not sys.platform.startswith("win"):
            return None
        keys = [
            "Preferred DropEffect",
            'application/x-qt-windows-mime;value="Preferred DropEffect"',
        ]
        for k in keys:
            if md.hasFormat(k):
                try:
                    data = bytes(md.data(k))
                    (effect,) = struct.unpack("<I", data[:4])
                    return "cut" if effect == 2 else "copy"
                except (TypeError, ValueError, struct.error):
                    continue
        return None

    def _extract_from_special_clipboard(self, md: QtCore.QMimeData, fmt: str) -> Optional[CutCopy]:
        if not md.hasFormat(fmt):
            return None
        try:
            raw = bytes(md.data(fmt)).decode("utf-8", errors="replace")
            lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
            if not lines:
                return None
            action: Literal["copy", "cut"] = "cut" if lines[0].lower() == "cut" else "copy"
            paths: List[Path] = []
            for ln in lines[1:]:
                url = QtCore.QUrl(ln)
                if url.isLocalFile():
                    p = Path(url.toLocalFile())
                    if p.exists():
                        paths.append(p)
            return (action, paths) if paths else None
        except Exception:
            return None

    def _parse_uri_list_text(self, text: str) -> List[Path]:
        paths: List[Path] = []
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                url = QtCore.QUrl(line)
                if url.isLocalFile():
                    p = Path(url.toLocalFile())
                    if p.exists():
                        paths.append(p)
            except (OSError, ValueError) as e:
                AppLogger.warning(f"_parse_uri_list_text failed: {line}", exc=e)
        return paths

    def _parse_plain_text_paths(self, text: str) -> List[Path]:
        cand: List[str] = []
        cand.extend([s.strip('"') for s in re.split(r"[\r\n]+", text) if s.strip()])
        cand.extend(re.findall(r'"([^"]+)"', text))
        cand.extend(re.findall(r'(?:(?:[A-Za-z]:)?[\\/][^\s"\'<>|]+)', text))
        paths: List[Path] = []
        for s in cand:
            try:
                p = Path(s)
                if p.exists():
                    paths.append(p)
            except (OSError, ValueError) as e:
                AppLogger.warning(f"_parse_plain_text_paths failed: {s}", exc=e)
        return list(dict.fromkeys(paths))

    def collect_clipboard_files(self) -> Optional[CutCopy]:
        md = self.clipboard.mimeData()
        if md is None:
            return None

        for fmt in ("x-special/gnome-copied-files", "x-special/nautilus-clipboard"):
            res = self._extract_from_special_clipboard(md, fmt)
            if res:
                return res

        paths: List[Path] = []
        if md.hasUrls():
            for url in md.urls():
                if url.isLocalFile():
                    p = Path(url.toLocalFile())
                    if p.exists():
                        paths.append(p)
        if not paths and md.hasFormat("text/uri-list"):
            try:
                text = bytes(md.data("text/uri-list")).decode("utf-8", errors="replace")
                paths = self._parse_uri_list_text(text)
            except Exception as e:
                AppLogger.warning("clipboard uri-list decode failed", exc=e)
        if not paths and md.hasText():
            paths = self._parse_plain_text_paths(md.text())

        if not paths:
            return None

        action = self._extract_windows_drop_effect(md) or "copy"
        return (action, paths)

    def build_paste_plan(self, destination_dir: Path | str) -> List[PastePlanItem]:
        dest_dir = Path(destination_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)

        extracted = self.collect_clipboard_files()
        if not extracted:
            return []

        action, paths = extracted
        plan: List[PastePlanItem] = []
        for i, src in enumerate(paths):
            dst_default = dest_dir / src.name
            conflict = dst_default.exists()
            suggested = Path(unique_path(dest_dir, src.name)) if conflict else None
            plan.append(
                PastePlanItem(
                    index=i,
                    src=src,
                    is_dir=src.is_dir(),
                    action=action,
                    dst_default=dst_default,
                    conflict=conflict,
                    suggested_dst=suggested,
                )
            )
        return plan


def _resolve_conflicts_with_ui(
    plans: List[PastePlanItem] | List[DropPlanItem],
    *,
    op: str,
    overwrite_mode: str = "ask",
    parent: object | None = None,
    folder_message: str = "Folder with the same name already exists. Proceed?",
) -> Dict[int, PasteDecision]:
    if overwrite_mode not in ("ask", "overwrite", "skip", "rename"):
        raise ValueError(f"Invalid overwrite_mode: {overwrite_mode}")

    from ..qt.file_conflict_resolver import resolve_paste_plans_with_ui

    return resolve_paste_plans_with_ui(
        plans=plans,
        overwrite_mode=overwrite_mode,
        parent=parent,
        op=op,
        folder_message=folder_message,
    )


def paste_clipboard_files(
    destination_dir: Path | str,
    *,
    overwrite_mode: str = "ask",
    parent: object | None = None,
    folder_message: str = "Folder with the same name already exists. Proceed?",
) -> List[OperationResult]:
    plans = ClipboardFilePaster().build_paste_plan(destination_dir)
    if not plans:
        return []
    op = "move" if plans[0].action == "cut" else "copy"
    try:
        decisions = _resolve_conflicts_with_ui(
            plans=plans, op=op, overwrite_mode=overwrite_mode, parent=parent, folder_message=folder_message
        )
    except PasteCancelledError:
        return []
    return PasteExecutor().execute_plans(plans, decisions)


def execute_paste_plans_with_ui(
    plans: List[PastePlanItem],
    *,
    overwrite_mode: str = "ask",
    parent: object | None = None,
    folder_message: str = "Folder with the same name already exists. Proceed?",
) -> List[OperationResult]:
    if not plans:
        return []
    op = "move" if plans[0].action == "cut" else "copy"
    try:
        decisions = _resolve_conflicts_with_ui(
            plans=plans, op=op, overwrite_mode=overwrite_mode, parent=parent, folder_message=folder_message
        )
    except PasteCancelledError:
        return []
    return PasteExecutor().execute_plans(plans, decisions)


def drop_files_with_ui(
    parsed_items: list,
    destination_dir: str,
    op: str,
    *,
    overwrite_mode: str = "ask",
    parent: object | None = None,
    folder_message: str = "Folder with the same name already exists. Proceed?",
) -> List[OperationResult]:
    if op not in ("copy", "move"):
        raise ValueError(f"Invalid op: {op}")
    if overwrite_mode not in ("overwrite", "rename", "skip", "ask"):
        raise ValueError(f"Invalid overwrite_mode: {overwrite_mode}")
    plans = build_drop_plans(parsed_items, destination_dir, op)
    if not plans:
        return []
    try:
        decisions = _resolve_conflicts_with_ui(
            plans=plans, op=op, overwrite_mode=overwrite_mode, parent=parent, folder_message=folder_message
        )
    except PasteCancelledError:
        return []
    return PasteExecutor().execute_drop_plans(plans, decisions, op=op)
