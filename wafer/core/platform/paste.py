from __future__ import annotations

import re
import struct
import sys
from pathlib import Path
from typing import Literal
from collections.abc import Callable

from PySide6 import QtCore, QtGui, QtWidgets

from ...utils.logs import AppLogger
from ...utils.notifier import Notifier
from ...core.lang.manager import t
from ...core.app_settings import app_settings
from ...utils.paths import safe_exists, safe_is_dir
from ...utils.virtual_paths import is_virtual_path
from .path_utils import unique_path
from .file_operations import (
    CutCopy,
    DropPlanItem,
    FileExecutor,
    OperationResult,
    PasteCancelledError,
    PasteDecision,
    PastePlanItem,
    _safe_remove,
    _save_remote_item,
    build_drop_plans,
    count_operation_units,
)


DROP_OPERATION_SETTING_KEY = "file/drop_operation"
DropOperation = Literal["copy", "move", "ask"]


def normalize_drop_operation(value: object, default: Literal["copy", "move"] = "copy") -> Literal["copy", "move"]:
    v = str(value or "").lower()
    if v in ("copy", "move"):
        return v  # type: ignore[return-value]
    return default if default in ("copy", "move") else "copy"


def get_saved_drop_operation(default: Literal["copy", "move"] = "copy") -> Literal["copy", "move"]:
    return normalize_drop_operation(app_settings.get(DROP_OPERATION_SETTING_KEY, default), default)


def save_drop_operation(op: str) -> Literal["copy", "move"]:
    resolved = normalize_drop_operation(op)
    app_settings.save_immediate(DROP_OPERATION_SETTING_KEY, resolved)
    return resolved


def resolve_drop_operation_with_ui(op: DropOperation, *, parent: object | None = None, message: str | None = None) -> Literal["copy", "move"] | None:
    if op in ("copy", "move"):
        return op
    if op != "ask":
        raise ValueError(f"Invalid op: {op}")
    from ...ui.dialogs import DropOperationDialog

    default = get_saved_drop_operation()
    selected = DropOperationDialog.ask(message or t("Choose drop operation."), default=default, parent=parent)
    if selected is None:
        return None
    return save_drop_operation(selected)


class ClipboardFilePaster:
    def __init__(self):
        self.clipboard = QtGui.QGuiApplication.clipboard()

    def _extract_windows_drop_effect(self, md: QtCore.QMimeData) -> str | None:
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

    def _extract_from_special_clipboard(self, md: QtCore.QMimeData, fmt: str) -> CutCopy | None:
        if not md.hasFormat(fmt):
            return None
        try:
            raw = bytes(md.data(fmt)).decode("utf-8", errors="replace")
            lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
            if not lines:
                return None
            action: Literal["copy", "cut"] = "cut" if lines[0].lower() == "cut" else "copy"
            paths: list[Path] = []
            for ln in lines[1:]:
                url = QtCore.QUrl(ln)
                if url.isLocalFile():
                    p = Path(url.toLocalFile())
                    if p.exists():
                        paths.append(p)
            return (action, paths) if paths else None
        except (OSError, RuntimeError, UnicodeDecodeError):
            return None

    def _parse_uri_list_text(self, text: str) -> list[Path]:
        paths: list[Path] = []
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

    def _parse_plain_text_paths(self, text: str) -> list[Path]:
        cand: list[str] = []
        cand.extend([s.strip('"') for s in re.split(r"[\r\n]+", text) if s.strip()])
        cand.extend(re.findall(r'"([^"]+)"', text))
        cand.extend(re.findall(r'(?:(?:[A-Za-z]:)?[\\/][^\s"\'<>|]+)', text))
        paths: list[Path] = []
        for s in cand:
            try:
                p = Path(s)
                if p.exists():
                    paths.append(p)
            except (OSError, ValueError) as e:
                AppLogger.warning(f"_parse_plain_text_paths failed: {s}", exc=e)
        return list(dict.fromkeys(paths))

    def collect_clipboard_files(self) -> CutCopy | None:
        md = self.clipboard.mimeData()
        if md is None:
            return None

        for fmt in ("x-special/gnome-copied-files", "x-special/nautilus-clipboard"):
            res = self._extract_from_special_clipboard(md, fmt)
            if res:
                return res

        paths: list[Path] = []
        if md.hasUrls():
            for url in md.urls():
                if url.isLocalFile():
                    p = Path(url.toLocalFile())
                    if safe_exists(p):
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

    def build_paste_plan(self, destination_dir: Path | str) -> list[PastePlanItem]:
        if _reject_virtual_destination(destination_dir, "paste"):
            return []
        dest_dir = Path(destination_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)

        extracted = self.collect_clipboard_files()
        if not extracted:
            return []

        action, paths = extracted
        unique_paths: list[Path] = []
        seen: set[str] = set()
        for src in paths:
            key = str(src)
            if key in seen:
                continue
            seen.add(key)
            unique_paths.append(src)
        if len(unique_paths) != len(paths):
            AppLogger.warning(f"[paste] duplicate sources dropped: {len(paths)} -> {len(unique_paths)}")
        plan: list[PastePlanItem] = []
        for i, src in enumerate(unique_paths):
            dst_default = dest_dir / src.name
            conflict = safe_exists(dst_default)
            suggested = Path(unique_path(dest_dir, src.name)) if conflict else None
            is_dir = safe_is_dir(src)
            plan.append(
                PastePlanItem(
                    index=i,
                    src=src,
                    is_dir=is_dir,
                    action=action,
                    dst_default=dst_default,
                    conflict=conflict,
                    suggested_dst=suggested,
                )
            )
        return plan


def _reject_virtual_destination(destination_dir: Path | str, operation: str) -> bool:
    if is_virtual_path(str(destination_dir)):
        AppLogger.warning(f"[{operation}] virtual destination rejected: {destination_dir} (file ops must target source files)")
        return True
    return False


def _is_virtual_plan_path(path: Path | None) -> bool:
    return bool(path and is_virtual_path(str(path)))


def _virtual_paste_plan_result(item: PastePlanItem) -> OperationResult:
    action = "move" if item.action == "cut" else "copy"
    dst = item.suggested_dst if _is_virtual_plan_path(item.suggested_dst) else item.dst_default
    return OperationResult(action=action, src=str(item.src), dst=str(dst), status="skipped", error="virtual path rejected")


def _partition_virtual_paste_plans(plans: list[PastePlanItem]) -> tuple[list[tuple[int, PastePlanItem]], dict[int, OperationResult]]:
    accepted: list[tuple[int, PastePlanItem]] = []
    rejected: dict[int, OperationResult] = {}
    for position, item in enumerate(plans):
        if _is_virtual_plan_path(item.src) or _is_virtual_plan_path(item.dst_default) or _is_virtual_plan_path(item.suggested_dst):
            rejected[position] = _virtual_paste_plan_result(item)
            continue
        accepted.append((position, item))
    if rejected:
        AppLogger.warning(f"[paste] virtual paths rejected: {len(rejected)} plan(s) (file ops must target source files)")
    return accepted, rejected


def _merge_paste_plan_results(
    total: int,
    accepted: list[tuple[int, PastePlanItem]],
    accepted_results: list[OperationResult],
    rejected: dict[int, OperationResult],
) -> list[OperationResult]:
    merged: list[OperationResult | None] = [None] * total
    for (position, _), result in zip(accepted, accepted_results):
        merged[position] = result
    for position, result in rejected.items():
        merged[position] = result
    return [result for result in merged if result is not None]


def _confirm_action(message: str, parent: object | None) -> bool:
    pw = parent if isinstance(parent, QtWidgets.QWidget) else QtWidgets.QApplication.activeWindow()
    return (
        QtWidgets.QMessageBox.question(
            pw,
            t("Confirm"),
            message,
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        == QtWidgets.QMessageBox.Yes
    )


def _resolve_conflicts_with_ui(
    plans: list[PastePlanItem] | list[DropPlanItem],
    *,
    op: str,
    overwrite_mode: str = "ask",
    parent: object | None = None,
    folder_message: str = "Folder with the same name already exists. Proceed?",
) -> dict[int, PasteDecision]:
    if overwrite_mode not in ("ask", "overwrite", "skip", "rename"):
        raise ValueError(f"Invalid overwrite_mode: {overwrite_mode}")

    from ...ui.file_conflict_resolver import resolve_paste_plans_with_ui

    return resolve_paste_plans_with_ui(
        plans=plans,
        overwrite_mode=overwrite_mode,
        parent=parent,
        op=op,
        folder_message=folder_message,
    )


def _run_with_progress(
    parent: QtWidgets.QWidget | None,
    label: str,
    total: int,
    execute_fn: Callable[..., OperationResult],
    *,
    progress_total_provider: Callable[[Callable[[], bool]], int] | None = None,
    manual_progress: bool = False,
) -> list[OperationResult]:
    if total == 0:
        return []

    from ...core.qt.dispatcher import CancelToken, Dispatcher
    from ...core.qt.thread import utility_pool

    token = CancelToken()
    results: list[OperationResult] = []
    progress_value = 0
    progress_limit: int | None = None

    dialog = QtWidgets.QProgressDialog(label, t("Cancel"), 0, 0, parent)
    dialog.setWindowModality(QtCore.Qt.WindowModal)
    dialog.setMinimumDuration(0)
    dialog.setAutoReset(False)
    dialog.setAutoClose(False)
    dialog.canceled.connect(token.cancel)
    dialog.setValue(0)

    dispatcher = Dispatcher(utility_pool)

    def _close_dialog():
        try:
            dialog.canceled.disconnect(token.cancel)
        except RuntimeError:
            pass
        dialog.close()

    def _set_progress_limit(limit: int):
        nonlocal progress_limit, progress_value
        progress_limit = max(1, int(limit))
        progress_value = min(progress_value, progress_limit)
        dialog.setRange(0, progress_limit)
        dialog.setValue(progress_value)

    def advance(units: int = 1):
        nonlocal progress_value
        if units <= 0:
            return
        progress_value += units
        if progress_limit is not None:
            progress_value = min(progress_value, progress_limit)
        dispatcher.invoke(lambda v=progress_value: dialog.setValue(v))

    def bg_task():
        if progress_total_provider is not None:
            try:
                progress_total = progress_total_provider(token.is_cancelled)
            except PasteCancelledError:
                dispatcher.invoke(_close_dialog)
                return
            except Exception as e:
                AppLogger.warning("progress total calculation failed", exc=e)
                progress_total = total
            if token.is_cancelled():
                dispatcher.invoke(_close_dialog)
                return
            dispatcher.invoke(lambda value=progress_total: _set_progress_limit(value))
        for i in range(total):
            if token.is_cancelled():
                break
            if manual_progress:
                result = execute_fn(i, advance, token.is_cancelled)
            else:
                result = execute_fn(i)
                advance()
            results.append(result)
        dispatcher.invoke(_close_dialog)

    dispatcher.post(bg_task)
    dialog.exec()

    ok_count = sum(1 for r in results if r.status == "ok")
    if token.is_cancelled():
        Notifier.info(t("Operation cancelled ({count} completed)", count=ok_count))
    elif ok_count:
        Notifier.info(t("{count} file(s) processed", count=ok_count))
    return results


def _execute_paste_items(
    plans: list[PastePlanItem],
    decisions: dict[int, PasteDecision],
    parent: QtWidgets.QWidget | None,
    op: str,
) -> list[OperationResult]:
    label = t("Moving files...") if op == "move" else t("Copying files...")

    def step(i: int, advance: Callable[[int], None], is_cancelled: Callable[[], bool]) -> OperationResult:
        item = plans[i]
        dec = decisions.get(item.index, PasteDecision(mode="skip"))
        executor = FileExecutor(progress_callback=advance, cancel_check=is_cancelled)
        return executor._execute_item(item.src, item.dst_default, item.action, dec)

    def progress_total_provider(is_cancelled: Callable[[], bool]) -> int:
        return sum(count_operation_units(item.src, item.dst_default, item.action, cancel_check=is_cancelled) for item in plans)

    return _run_with_progress(parent, label, len(plans), step, progress_total_provider=progress_total_provider, manual_progress=True)


def _execute_drop_items(
    plans: list[DropPlanItem],
    decisions: dict[int, PasteDecision],
    parent: QtWidgets.QWidget | None,
    op: str,
) -> list[OperationResult]:
    action: Literal["copy", "cut"] = "cut" if op == "move" else "copy"
    label = t("Moving files...") if op == "move" else t("Copying files...")

    def step(i: int, advance: Callable[[int], None], is_cancelled: Callable[[], bool]) -> OperationResult:
        plan = plans[i]
        dec = decisions.get(plan.index)
        if dec is None or dec.mode == "skip":
            advance()
            return OperationResult(action="skip", src=str(plan.src or ""), dst="", status="skipped")
        if plan.src is not None:
            executor = FileExecutor(progress_callback=advance, cancel_check=is_cancelled)
            return executor._execute_item(plan.src, plan.dst_default, action, dec)
        dst_path = str(plan.dst_default)
        if dec.mode == "rename" and plan.suggested_dst:
            dst_path = str(plan.suggested_dst)
        elif dec.mode == "overwrite" and plan.conflict:
            _safe_remove(dst_path)
        result = _save_remote_item(plan.parsed_item, dst_path, move=(op == "move"))
        advance()
        return result

    def progress_total_provider(is_cancelled: Callable[[], bool]) -> int:
        return sum(count_operation_units(plan.src, plan.dst_default, action, cancel_check=is_cancelled) if plan.src is not None else 1 for plan in plans)

    return _run_with_progress(parent, label, len(plans), step, progress_total_provider=progress_total_provider, manual_progress=True)


def paste_clipboard_files(
    destination_dir: Path | str,
    *,
    overwrite_mode: str = "ask",
    parent: object | None = None,
    folder_message: str = "Folder with the same name already exists. Proceed?",
) -> list[OperationResult]:
    if _reject_virtual_destination(destination_dir, "paste"):
        return []
    plans = ClipboardFilePaster().build_paste_plan(destination_dir)
    if not plans:
        return []
    op = "move" if plans[0].action == "cut" else "copy"
    try:
        decisions = _resolve_conflicts_with_ui(plans=plans, op=op, overwrite_mode=overwrite_mode, parent=parent, folder_message=folder_message)
    except PasteCancelledError:
        return []
    return _execute_paste_items(plans, decisions, parent, op)


def execute_paste_plans_with_ui(
    plans: list[PastePlanItem],
    *,
    overwrite_mode: str = "ask",
    parent: object | None = None,
    folder_message: str = "Folder with the same name already exists. Proceed?",
    confirm_message: str | None = None,
) -> list[OperationResult]:
    if not plans:
        return []
    accepted, rejected = _partition_virtual_paste_plans(plans)
    if not accepted:
        return _merge_paste_plan_results(len(plans), accepted, [], rejected)
    if confirm_message and not _confirm_action(confirm_message, parent):
        return []
    accepted_plans = [item for _, item in accepted]
    op = "move" if accepted_plans[0].action == "cut" else "copy"
    try:
        decisions = _resolve_conflicts_with_ui(plans=accepted_plans, op=op, overwrite_mode=overwrite_mode, parent=parent, folder_message=folder_message)
    except PasteCancelledError:
        return []
    accepted_results = _execute_paste_items(accepted_plans, decisions, parent, op)
    return _merge_paste_plan_results(len(plans), accepted, accepted_results, rejected)


def drop_files_with_ui(
    parsed_items: list,
    destination_dir: str,
    op: DropOperation,
    *,
    overwrite_mode: str = "ask",
    parent: object | None = None,
    folder_message: str = "Folder with the same name already exists. Proceed?",
    confirm_message: str | None = None,
) -> list[OperationResult]:
    if op not in ("copy", "move", "ask"):
        raise ValueError(f"Invalid op: {op}")
    if overwrite_mode not in ("overwrite", "rename", "skip", "ask"):
        raise ValueError(f"Invalid overwrite_mode: {overwrite_mode}")
    resolved_op = resolve_drop_operation_with_ui(op, parent=parent, message=confirm_message)
    if resolved_op is None:
        return []
    plans = build_drop_plans(parsed_items, destination_dir, resolved_op)
    if not plans:
        return []
    if op != "ask" and confirm_message and not _confirm_action(confirm_message, parent):
        return []
    try:
        decisions = _resolve_conflicts_with_ui(plans=plans, op=resolved_op, overwrite_mode=overwrite_mode, parent=parent, folder_message=folder_message)
    except PasteCancelledError:
        return []
    return _execute_drop_items(plans, decisions, parent, resolved_op)
