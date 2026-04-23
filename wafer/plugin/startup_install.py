import os
import time

import psutil

from ..utils.logs import AppLogger
from ..utils.notifier import Notifier
from . import failed_installs, installer_queue
from .install_status import InstallStatusWriter, clear_cancel, clear_status, is_cancel_requested
from .installer import cleanup_legacy_dirs, install_requirements_only, run_post_install


def run_pending_installs(extensions_dir: str) -> bool:
    cleanup_legacy_dirs(extensions_dir)
    if not installer_queue.has_pending_queue(extensions_dir):
        clear_status()
        return False

    entries = installer_queue.read_queue(extensions_dir)
    if not entries:
        clear_status()
        return False

    clear_cancel()
    AppLogger.info(f"[StartupInstall] Processing {len(entries)} queued install(s)")
    _terminate_processes_holding_packages(extensions_dir)
    started_at = time.monotonic()
    writer = InstallStatusWriter(total=len(entries))
    processed, failed, cancelled = _execute_installs(extensions_dir, entries, writer)
    installer_queue.remove_entries(extensions_dir, [name for name, _ in processed] + [name for name, _ in failed])
    failed_installs.clear(extensions_dir, [name for name, _ in processed])
    for name, reason in failed:
        failed_installs.mark_failed(extensions_dir, name, reason)
    elapsed = time.monotonic() - started_at
    AppLogger.info(f"[StartupInstall] Completed in {elapsed:.1f}s (ok={len(processed)}, failed={len(failed)}, cancelled={len(cancelled)})")
    error = None
    if cancelled:
        error = f"Cancelled: {', '.join(cancelled)}"
    elif failed:
        error = f"Failed: {', '.join(name for name, _ in failed)}"
    writer.finish(error=error)
    clear_status()
    clear_cancel()
    _notify_result(
        [name for name, _ in processed],
        [name for name, _ in failed],
        cancelled,
    )
    return True


def _execute_installs(extensions_dir: str, entries: list, writer: InstallStatusWriter):
    processed: list[tuple[str, str]] = []
    failed: list[tuple[str, str]] = []
    cancelled: list[str] = []
    failed_names: set[str] = set()
    total = len(entries)
    for i, entry in enumerate(entries, 1):
        if is_cancel_requested():
            cancelled.extend(e.name for e in entries[i - 1 :] if e.name not in cancelled)
            break
        writer.begin_item(i, entry.name, "pip")
        AppLogger.info(f"[StartupInstall] pip ({i}/{total}) {entry.name}")
        ok, was_cancelled, reason = _install_one_phase_a(extensions_dir, entry, on_log=writer.append_log)
        if was_cancelled:
            cancelled.append(entry.name)
            cancelled.extend(e.name for e in entries[i:] if e.name not in cancelled)
            break
        if not ok:
            failed.append((entry.name, reason))
            failed_names.add(entry.name)
    pending = [e for e in entries if e.name not in failed_names and e.name not in cancelled]
    for i, entry in enumerate(pending, 1):
        if is_cancel_requested():
            cancelled.extend(e.name for e in pending[i - 1 :] if e.name not in cancelled)
            break
        writer.begin_item(i, entry.name, "post_install")
        AppLogger.info(f"[StartupInstall] post_install ({i}/{len(pending)}) {entry.name}")
        ok, was_cancelled, reason = _install_one_phase_b(extensions_dir, entry, on_log=writer.append_log)
        if was_cancelled:
            cancelled.append(entry.name)
            cancelled.extend(e.name for e in pending[i:] if e.name not in cancelled)
            break
        if ok:
            processed.append((entry.name, ""))
        else:
            failed.append((entry.name, reason))
    return processed, failed, cancelled


def _install_one_phase_a(extensions_dir: str, entry, on_log=None):
    plugin_dir = entry.plugin_dir or os.path.join(extensions_dir, entry.name)
    if not os.path.isdir(plugin_dir):
        msg = f"Plugin folder missing: {plugin_dir}"
        AppLogger.warning(f"[StartupInstall] {msg}")
        return False, False, msg
    try:
        result = install_requirements_only(plugin_dir, extensions_dir, on_log=on_log, is_cancelled=is_cancel_requested)
        if result.cancelled:
            AppLogger.info(f"[StartupInstall] pip install cancelled: {entry.name}")
            return False, True, ""
        if result.success:
            AppLogger.info(f"[StartupInstall] pip install complete: {entry.name}")
            return True, False, ""
        AppLogger.warning(f"[StartupInstall] pip install failed: {entry.name}")
        return False, False, "pip install failed (see log)"
    except Exception as e:
        AppLogger.warning(f"[StartupInstall] pip install raised for {entry.name}: {e}", exc=e)
        return False, False, f"pip install error: {e}"


def _install_one_phase_b(extensions_dir: str, entry, on_log=None):
    plugin_dir = entry.plugin_dir or os.path.join(extensions_dir, entry.name)
    if not os.path.isdir(plugin_dir):
        return False, False, f"Plugin folder missing: {plugin_dir}"
    try:
        result = run_post_install(plugin_dir, extensions_dir, on_log=on_log, is_cancelled=is_cancel_requested)
        if result.cancelled:
            AppLogger.info(f"[StartupInstall] post_install cancelled: {entry.name}")
            return False, True, ""
        if result.success and result.post_install_ok:
            AppLogger.info(f"[StartupInstall] post_install complete: {entry.name}")
            return True, False, ""
        AppLogger.warning(f"[StartupInstall] post_install failed: {entry.name}")
        return False, False, "post_install failed (see log)"
    except Exception as e:
        AppLogger.warning(f"[StartupInstall] post_install raised for {entry.name}: {e}", exc=e)
        return False, False, f"post_install error: {e}"


def _notify_result(processed: list, failed: list, cancelled: list) -> None:
    if processed:
        msg = f"Extensions installed: {', '.join(processed)}"
        AppLogger.info(f"[StartupInstall] {msg}")
        Notifier.info(msg)
    if failed:
        msg = f"Extension install failed: {', '.join(failed)}"
        AppLogger.warning(f"[StartupInstall] {msg}")
        Notifier.warning(msg)
    if cancelled:
        msg = f"Extension install cancelled: {', '.join(cancelled)} (will retry on next start)"
        AppLogger.info(f"[StartupInstall] {msg}")
        Notifier.info(msg)


def _terminate_processes_holding_packages(extensions_dir: str) -> None:
    target_root = os.path.realpath(os.path.join(extensions_dir, ".packages"))
    if not os.path.isdir(target_root):
        return
    my_pid = os.getpid()
    targets: list[psutil.Process] = []
    for proc in psutil.process_iter(["pid"]):
        if proc.pid == my_pid:
            continue
        try:
            for handle in proc.open_files():
                if os.path.realpath(handle.path).startswith(target_root):
                    targets.append(proc)
                    break
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    if not targets:
        return
    names = ", ".join(f"pid={p.pid}" for p in targets)
    AppLogger.info(f"[StartupInstall] terminating {len(targets)} process(es) holding package files: {names}")
    from ..core.platform.process import AppProcess

    AppProcess.terminate_and_wait(targets)
