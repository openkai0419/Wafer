from __future__ import annotations

import os
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from collections.abc import Callable

from ..logs import AppLogger
from ..common.paths import profile_allows_file_write, safe_exists, safe_is_dir
from ..common.profile import current_profile
from ..common.virtual_paths import is_virtual_path
from .path_utils import check_copy_conflict, is_http_url, unique_path

if TYPE_CHECKING:
    from ...qt.transfer.dragparser import ParsedItem


ProgressCallback = Callable[[int], None]
CancelCheck = Callable[[], bool]


def _check_cancel(cancel_check: CancelCheck | None) -> None:
    if cancel_check and cancel_check():
        raise PasteCancelledError()


def _advance(progress_callback: ProgressCallback | None, units: int = 1) -> None:
    if progress_callback and units > 0:
        progress_callback(units)


def _rmtree_onerror(func, path, exc_info):
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except OSError as e:
        AppLogger.warning(f"rmtree fallback failed: {path} ({e})")


def _safe_remove(path: str | Path) -> None:
    p = Path(path)
    if not p.exists() and not p.is_symlink():
        return
    if p.is_symlink() or p.is_file():
        p.unlink(missing_ok=True)
        return
    if p.is_dir():
        shutil.rmtree(p, onerror=_rmtree_onerror)


def _staging_path(dst: Path, tag: str) -> Path:
    return Path(unique_path(dst.parent, f"{dst.name}.{tag}"))


def _put_back(staged: Path, original: Path) -> list[Path]:
    if not os.path.lexists(staged):
        return []
    if not os.path.lexists(original):
        try:
            os.rename(staged, original)
            return []
        except OSError as e:
            AppLogger.debug(f"put back by rename failed, restoring one by one: {staged} ({e})")
    if os.path.lexists(original):
        return _drop_staged_duplicate(staged, original)
    try:
        _move_any(staged, original)
        return []
    except OSError as e:
        AppLogger.warning(f"could not put {original.name} back; it is kept at {staged}", exc=e)
        if os.path.lexists(staged) and os.path.isfile(original):
            try:
                original.unlink()
            except OSError as partial_error:
                AppLogger.warning(f"an incomplete copy is left at {original}; the complete file is {staged}", exc=partial_error)
        return [staged]


def _drop_staged_duplicate(staged: Path, original: Path) -> list[Path]:
    if original.is_dir() and not original.is_symlink():
        return [staged]
    try:
        staged.unlink()
        return []
    except OSError as e:
        AppLogger.warning(f"a copy of {original.name} is left at {staged}", exc=e)
        return [staged]


def _write_replacing(target: Path, chunks) -> None:
    partial = _staging_path(target, "wafer-partial")
    try:
        with open(partial, "wb") as f:
            for chunk in chunks:
                if chunk:
                    f.write(chunk)
        os.replace(partial, target)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise


def _copy_file(src: Path, dst: Path, follow_symlinks: bool = True, progress_callback: ProgressCallback | None = None, cancel_check: CancelCheck | None = None) -> Path:
    _check_cancel(cancel_check)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst, follow_symlinks=follow_symlinks)
    _advance(progress_callback)
    return dst


def _copy_dir(src: Path, dst: Path, follow_symlinks: bool = True, progress_callback: ProgressCallback | None = None, cancel_check: CancelCheck | None = None) -> Path:
    _check_cancel(cancel_check)
    if dst.exists():
        raise FileExistsError(f"Destination exists: {dst}")
    copied_files = 0

    def copy_function(src_name, dst_name):
        nonlocal copied_files
        copied_files += 1
        return _copy_file(Path(src_name), Path(dst_name), follow_symlinks=follow_symlinks, progress_callback=progress_callback, cancel_check=cancel_check)

    shutil.copytree(src, dst, symlinks=not follow_symlinks, dirs_exist_ok=False, copy_function=copy_function)
    if copied_files == 0:
        _advance(progress_callback)
    return dst


def _existing_anchor(path: Path) -> Path:
    p = path if path.exists() else path.parent
    while not p.exists() and p.parent != p:
        p = p.parent
    return p


def _same_device(src: Path, dst: Path) -> bool:
    try:
        return os.stat(src).st_dev == os.stat(_existing_anchor(dst)).st_dev
    except OSError:
        return os.path.splitdrive(str(src))[0].lower() == os.path.splitdrive(str(dst))[0].lower()


def _move_any(
    src: Path,
    dst: Path,
    *,
    follow_symlinks: bool = True,
    progress_callback: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> Path:
    _check_cancel(cancel_check)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir() and not _same_device(src, dst):
        _copy_dir(src, dst, follow_symlinks=follow_symlinks, progress_callback=progress_callback, cancel_check=cancel_check)
        shutil.rmtree(src, onerror=_rmtree_onerror)
        return dst
    if src.is_file() and not _same_device(src, dst):
        done = _copy_file(src, dst, follow_symlinks=follow_symlinks, progress_callback=progress_callback, cancel_check=cancel_check)
        src.unlink()
        return done
    done = Path(shutil.move(str(src), str(dst)))
    _advance(progress_callback)
    return done


def _copy_or_move(
    src: Path,
    dst: Path,
    *,
    action: Literal["copy", "cut"],
    follow_symlinks: bool = True,
    progress_callback: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> Path:
    if action == "cut":
        return _move_any(src, dst, follow_symlinks=follow_symlinks, progress_callback=progress_callback, cancel_check=cancel_check)
    if src.is_dir():
        return _copy_dir(src, dst, follow_symlinks, progress_callback=progress_callback, cancel_check=cancel_check)
    return _copy_file(src, dst, follow_symlinks, progress_callback=progress_callback, cancel_check=cancel_check)


def _operation_name(action: Literal["copy", "cut"]) -> str:
    return "move" if action == "cut" else "copy"


def _is_virtual_operation_path(path: str | Path | None) -> bool:
    return bool(path and is_virtual_path(str(path)))


def _profile_refusal(action: str, paths: list[str | Path]) -> bool:
    for p in paths:
        if not profile_allows_file_write(str(p)):
            AppLogger.warning(f"[{action}] refused outside the debug profile scratch area: {p}")
            return True
    return False


def count_operation_units(src: Path, dst: Path, action: Literal["copy", "cut"], cancel_check: CancelCheck | None = None) -> int:
    if not src.is_dir():
        return 1
    if action == "cut" and _same_device(src, dst):
        return 1
    total = 0
    try:
        _check_cancel(cancel_check)
        for _, _, files in os.walk(src):
            _check_cancel(cancel_check)
            total += len(files)
    except OSError as e:
        AppLogger.warning(f"count_operation_units failed: {src}", exc=e)
        return 1
    return max(1, total)


def _save_remote_item(item: ParsedItem, target_path: str) -> OperationResult:
    src_info = str(getattr(item, "source", ""))
    if _is_virtual_operation_path(target_path):
        AppLogger.warning(f"[save] virtual destination rejected: {target_path} (file ops must target source files)")
        return OperationResult(action="save", src=src_info, dst=str(target_path), status="skipped", error="virtual path rejected")

    target = Path(target_path)
    if getattr(item, "is_binary", False) and isinstance(getattr(item, "source", None), (bytes, bytearray)):
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            _write_replacing(target, [item.source])
            AppLogger.info(f"Saved binary data to {target_path}")
            return OperationResult(action="save", src="(binary)", dst=target_path, status="ok")
        except Exception as e:
            AppLogger.warning(f"Failed to save dropped data to {target_path}", exc=e)
            return OperationResult(action="save", src="(binary)", dst=target_path, status="error", error=repr(e))

    if is_http_url(src_info):
        try:
            import requests

            target.parent.mkdir(parents=True, exist_ok=True)
            session = requests.Session()
            session.max_redirects = 5
            with session.get(src_info, timeout=10, stream=True) as resp:
                if resp.status_code != 200:
                    raise ValueError(f"HTTP {resp.status_code}")
                _write_replacing(target, resp.iter_content(chunk_size=1024 * 256))
            AppLogger.info(f"Downloaded: {src_info} -> {target_path}")
            return OperationResult(action="download", src=src_info, dst=target_path, status="ok")
        except Exception as e:
            AppLogger.warning(f"Failed to download {src_info}: {e}")
            return OperationResult(action="download", src=src_info, dst=target_path, status="error", error=repr(e))

    return OperationResult(action="unknown", src=src_info, dst=target_path, status="error", error="Invalid item type")


@dataclass
class OperationResult:
    action: str
    src: str
    dst: str
    status: str
    error: str = ""


CutCopy = tuple[Literal["copy", "cut"], list[Path]]


@dataclass
class PastePlanItem:
    index: int
    src: Path
    is_dir: bool
    action: Literal["copy", "cut"]
    dst_default: Path
    conflict: bool
    suggested_dst: Path | None


@dataclass
class DropPlanItem:
    index: int
    src: Path | None
    name: str
    is_dir: bool
    action: str
    dst_default: Path
    conflict: bool
    suggested_dst: Path | None
    parsed_item: object


@dataclass
class PasteDecision:
    mode: Literal["create", "rename", "skip"]
    new_name_or_path: str | None = None


class PasteCancelledError(Exception):
    pass


CANCELLED = "cancelled"


@dataclass
class PasteConflict:
    src: Path | None
    dst: Path
    name: str
    folders: bool
    from_this_paste: bool
    in_merge: bool
    src_bytes: bytes | bytearray | None = None


PasteAnswer = Literal["overwrite", "merge", "rename", "skip"]
AskConflict = Callable[[PasteConflict], PasteAnswer]


def keep_both(conflict: PasteConflict) -> PasteAnswer:
    AppLogger.info(f"{conflict.dst} already exists, so it is kept and {conflict.name} is saved under a new name")
    return "rename"


def _destination_key(path: str | Path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


class FileExecutor:
    def __init__(
        self,
        *,
        follow_symlinks: bool = True,
        progress_callback: ProgressCallback | None = None,
        cancel_check: CancelCheck | None = None,
        ask_conflict: AskConflict | None = None,
    ):
        self._follow_symlinks = follow_symlinks
        self._progress_callback = progress_callback
        self._cancel_check = cancel_check
        self._ask_conflict = ask_conflict or keep_both
        self._written: set[str] = set()
        self._cancelled = False

    def _advance(self, units: int = 1) -> None:
        _advance(self._progress_callback, units)

    def _advance_item(self, src: Path, dst: Path, action: Literal["copy", "cut"]) -> None:
        self._advance(count_operation_units(src, dst, action))

    def _record(self, path: Path) -> None:
        self._written.add(_destination_key(path))

    def _from_this_paste(self, path: Path) -> bool:
        if not self._written:
            return False
        key = _destination_key(path)
        while key not in self._written:
            parent = os.path.dirname(key)
            if parent == key:
                return False
            key = parent
        return True

    def _ask(self, src: Path | None, dst: Path, name: str, *, folders: bool, in_merge: bool, src_bytes: bytes | bytearray | None = None) -> PasteAnswer:
        return self._ask_conflict(
            PasteConflict(
                src=src,
                dst=dst,
                name=name,
                folders=folders,
                from_this_paste=self._from_this_paste(dst),
                in_merge=in_merge,
                src_bytes=src_bytes,
            )
        )

    def execute_plans(
        self,
        plans: list[PastePlanItem] | list[DropPlanItem],
        decisions: dict[int, PasteDecision],
    ) -> list[OperationResult]:
        return [self.execute_one(plan, decisions.get(plan.index)) for plan in plans]

    def execute_one(self, plan: PastePlanItem | DropPlanItem, decision: PasteDecision | None) -> OperationResult:
        decision = decision or PasteDecision(mode="create")
        if self._cancelled:
            return OperationResult(action="skip", src=str(plan.src or ""), dst=str(plan.dst_default), status="skipped", error=CANCELLED)
        if plan.src is not None:
            result = self._execute_item(plan.src, plan.dst_default, plan.action, decision)
        else:
            result = self._execute_remote(plan, decision)
        if result.error == CANCELLED:
            self._cancelled = True
        return result

    def _execute_remote(self, plan: DropPlanItem, decision: PasteDecision) -> OperationResult:
        if decision.mode == "skip":
            self._advance()
            return OperationResult(action="skip", src="", dst="", status="skipped")
        final_dst = self._resolve_dst(plan.dst_default, decision)
        if os.path.lexists(final_dst):
            item = plan.parsed_item
            src_bytes = item.source if getattr(item, "is_binary", False) and isinstance(getattr(item, "source", None), (bytes, bytearray)) else None
            try:
                answer = self._ask(None, final_dst, plan.name or final_dst.name, folders=False, in_merge=False, src_bytes=src_bytes)
            except PasteCancelledError:
                self._advance()
                return OperationResult(action="save", src="(remote)", dst=str(final_dst), status="skipped", error=CANCELLED)
            if answer == "skip":
                self._advance()
                return OperationResult(action="skip", src="", dst=str(final_dst), status="skipped")
            if answer == "rename" or final_dst.is_dir():
                final_dst = Path(unique_path(final_dst.parent, final_dst.name))
        if _profile_refusal("save", [final_dst]):
            self._advance()
            return OperationResult(action="save", src="(remote)", dst=str(final_dst), status="error", error="refused by debug profile")
        result = _save_remote_item(plan.parsed_item, str(final_dst))
        if result.status == "ok":
            self._record(final_dst)
        self._advance()
        return result

    def _execute_item(
        self,
        src: Path,
        dst: Path,
        action: Literal["copy", "cut"],
        decision: PasteDecision,
    ) -> OperationResult:
        op = _operation_name(action)
        if _is_virtual_operation_path(src) or _is_virtual_operation_path(dst):
            AppLogger.warning(f"[{op}] virtual path rejected: {src} -> {dst} (file ops must target source files)")
            return OperationResult(action=op, src=str(src), dst=str(dst), status="skipped", error="virtual path rejected")
        is_dir = src.is_dir()
        if decision.mode == "skip":
            self._advance_item(src, dst, action)
            return OperationResult(action="skip", src=str(src), dst="", status="skipped")

        final_dst = self._resolve_dst(dst, decision)
        if _is_virtual_operation_path(final_dst):
            AppLogger.warning(f"[{op}] virtual destination rejected: {src} -> {final_dst} (file ops must target source files)")
            return OperationResult(action=op, src=str(src), dst=str(final_dst), status="skipped", error="virtual path rejected")
        guarded = [final_dst, src] if action == "cut" else [final_dst]
        if _profile_refusal(op, guarded):
            return OperationResult(action=op, src=str(src), dst=str(final_dst), status="error", error="refused by debug profile")

        conflict = check_copy_conflict(src, final_dst)
        if conflict == "same_path":
            if action == "cut" and str(src) == str(final_dst):
                self._advance_item(src, final_dst, action)
                return OperationResult(action="skip", src=str(src), dst=str(final_dst), status="skipped")
            if action == "cut":
                try:
                    _check_cancel(self._cancel_check)
                    src.rename(final_dst)
                    self._advance()
                    self._record(final_dst)
                    return OperationResult(action="move", src=str(src), dst=str(final_dst), status="ok")
                except PasteCancelledError:
                    return OperationResult(action="move", src=str(src), dst=str(final_dst), status="skipped", error=CANCELLED)
                except Exception as e:
                    self._advance()
                    return OperationResult(action="move", src=str(src), dst=str(final_dst), status="error", error=repr(e))
            final_dst = Path(unique_path(final_dst.parent, final_dst.name))
        if is_dir and conflict == "subpath":
            self._advance_item(src, final_dst, action)
            error = "cannot move into itself" if action == "cut" else "cannot copy into itself"
            return OperationResult(action=op, src=str(src), dst=str(final_dst), status="skipped", error=error)

        try:
            answer: PasteAnswer | None = None
            if os.path.lexists(final_dst):
                folders = is_dir and final_dst.is_dir() and not final_dst.is_symlink()
                answer = self._ask(src, final_dst, src.name, folders=folders, in_merge=False)
                if answer == "skip":
                    self._advance_item(src, final_dst, action)
                    return OperationResult(action="skip", src=str(src), dst=str(final_dst), status="skipped")
                if answer == "rename":
                    final_dst = Path(unique_path(final_dst.parent, final_dst.name))
                    answer = None
            if answer is not None and is_dir and final_dst.is_dir() and not final_dst.is_symlink():
                self._merge_dir(src, final_dst, action=action)
                return OperationResult(action=op, src=str(src), dst=str(final_dst), status="ok")
            if answer is not None:
                done = self._overwrite(src, final_dst, action)
            else:
                done = self._copy_or_move(src, final_dst, action)
            self._record(done)
            return OperationResult(action=op, src=str(src), dst=str(done), status="ok")
        except PasteCancelledError:
            return OperationResult(action=op, src=str(src), dst=str(final_dst), status="skipped", error=CANCELLED)
        except Exception as e:
            AppLogger.warning(f"copy/move failed: {src} -> {final_dst}", exc=e)
            return OperationResult(action=op, src=str(src), dst=str(final_dst), status="error", error=repr(e))

    def _copy_or_move(self, src: Path, dst: Path, action: Literal["copy", "cut"]) -> Path:
        return _copy_or_move(src, dst, action=action, follow_symlinks=self._follow_symlinks, progress_callback=self._progress_callback, cancel_check=self._cancel_check)

    def _overwrite(self, src: Path, dst: Path, action: Literal["copy", "cut"]) -> Path:
        if src.is_dir() or dst.is_dir():
            renamed = Path(unique_path(dst.parent, dst.name))
            AppLogger.info(f"[{_operation_name(action)}] {dst} is kept because a file and a folder share the name; saved as {renamed.name}")
            return self._copy_or_move(src, renamed, action)
        staged = _staging_path(dst, "wafer-partial")
        try:
            self._copy_or_move(src, staged, action)
            os.replace(staged, dst)
        except BaseException:
            self._undo_staging(src, staged, action)
            raise
        return dst

    @staticmethod
    def _undo_staging(src: Path, staged: Path, action: Literal["copy", "cut"]) -> None:
        if action != "cut":
            _safe_remove(staged)
            return
        left = _put_back(staged, src)
        if left:
            AppLogger.error(f"[move] could not put {len(left)} item(s) back into {src}; they are kept in {staged}")

    @staticmethod
    def _resolve_dst(dst: Path, decision: PasteDecision) -> Path:
        if decision.mode != "rename":
            return dst
        if decision.new_name_or_path:
            p = Path(decision.new_name_or_path)
            final = p if p.is_absolute() else (dst.parent / p)
        else:
            final = dst
        if os.path.lexists(final):
            final = Path(unique_path(final.parent, final.name))
        return final

    def _merge_dir(self, src: Path, dst: Path, *, action: Literal["copy", "cut"]) -> None:
        dst.mkdir(parents=True, exist_ok=True)
        with os.scandir(src) as it:
            entries = list(it)
        for entry in entries:
            source = Path(entry.path)
            d = dst / entry.name
            try:
                existing = os.lstat(d)
            except FileNotFoundError:
                self._record(self._copy_or_move(source, d, action))
                continue
            source_is_dir = entry.is_dir()
            if source_is_dir and stat.S_ISDIR(existing.st_mode):
                self._merge_dir(source, d, action=action)
                continue
            answer = self._ask(source, d, entry.name, folders=False, in_merge=True)
            if answer == "skip":
                if source_is_dir:
                    self._advance_item(source, d, action)
                else:
                    self._advance()
                continue
            if answer == "rename":
                self._record(self._copy_or_move(source, Path(unique_path(d.parent, d.name)), action))
            else:
                self._record(self._overwrite(source, d, action))

        if action == "cut":
            try:
                src.rmdir()
            except OSError as e:
                AppLogger.debug(f"cut: source dir not removed: {src} ({e})")


def build_drop_plans(parsed_items: list[ParsedItem], dst_dir: str, op: str) -> list[DropPlanItem]:
    if not dst_dir:
        return []
    if is_virtual_path(str(dst_dir)):
        AppLogger.warning(f"[drop] virtual destination rejected: {dst_dir} (file ops must target source files)")
        return []
    plans = []
    seen_local_sources: set[str] = set()
    for item in parsed_items:
        name = str(getattr(item, "name", "") or "")
        if not name:
            continue
        if getattr(item, "is_local_file", lambda: False)():
            src_key = os.path.abspath(str(getattr(item, "source", "") or ""))
            if src_key and src_key in seen_local_sources:
                AppLogger.warning(f"[drop] duplicate source dropped: {src_key}")
                continue
            if src_key:
                seen_local_sources.add(src_key)
        dst_default = os.path.join(dst_dir, name)
        conflict = safe_exists(dst_default)
        if getattr(item, "is_local_file", lambda: False)():
            src_abs = os.path.abspath(str(getattr(item, "source", "") or ""))
            if not src_abs or not safe_exists(src_abs):
                continue
            plans.append(
                DropPlanItem(
                    index=len(plans),
                    src=Path(src_abs),
                    name=name,
                    is_dir=safe_is_dir(src_abs),
                    action=("cut" if op == "move" else "copy"),
                    dst_default=Path(dst_default),
                    conflict=conflict,
                    suggested_dst=Path(unique_path(dst_dir, name)) if conflict else None,
                    parsed_item=item,
                )
            )
        else:
            plans.append(
                DropPlanItem(
                    index=len(plans),
                    src=None,
                    name=name,
                    is_dir=False,
                    action=("cut" if op == "move" else "copy"),
                    dst_default=Path(dst_default),
                    conflict=conflict,
                    suggested_dst=Path(unique_path(dst_dir, name)) if conflict else None,
                    parsed_item=item,
                )
            )
    return plans


def delete_to_trash(paths: list[str | Path]) -> list[OperationResult]:
    physical = [p for p in paths if p and not is_virtual_path(str(p))]
    rejected = len(paths) - len(physical)
    if rejected:
        AppLogger.warning(f"[delete] virtual paths rejected: {rejected} entries (file ops must target source files)")
    raw = [os.path.normpath(os.path.abspath(str(p))) for p in physical]
    norm = list(dict.fromkeys(raw))
    if len(norm) != len(raw):
        AppLogger.warning(f"[delete] duplicate sources dropped: {len(raw)} -> {len(norm)}")
    if not norm:
        return []
    guarded = current_profile() is not None
    refused = {p for p in norm if guarded and not profile_allows_file_write(p)}
    for p in norm:
        if p in refused:
            AppLogger.warning(f"[delete] refused outside the debug profile scratch area: {p}")
    from send2trash import send2trash

    existing = [p for p in norm if p not in refused and os.path.lexists(p)]
    results = {p: OperationResult(action="delete", src=p, dst="", status="skipped") for p in norm}
    for p in refused:
        results[p] = OperationResult(action="delete", src=p, dst="", status="error", error="refused by debug profile")
    AppLogger.info(f"Deleting {len(existing)} files")
    try:
        if existing:
            send2trash(existing)
        for p in existing:
            results[p] = OperationResult(action="delete", src=p, dst="", status="ok")
    except Exception as e:
        AppLogger.warning(f"send2trash failed for {len(existing)} items; retrying one by one", exc=e)
        for p in existing:
            results[p] = _trash_one(send2trash, p)
    return [results[p] for p in norm]


def _trash_one(send2trash, path: str) -> OperationResult:
    if not os.path.lexists(path):
        return OperationResult(action="delete", src=path, dst="", status="ok")
    try:
        send2trash(path)
        return OperationResult(action="delete", src=path, dst="", status="ok")
    except Exception as e:
        AppLogger.warning(f"Could not move to the Recycle Bin, so it was not deleted: {path}", exc=e)
        return OperationResult(action="delete", src=path, dst="", status="error", error=repr(e))
