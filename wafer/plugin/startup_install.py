import os
import time

from ..utils.logs import AppLogger
from ..utils.notifier import Notifier
from ..utils.process_lock import SafeProcessLock
from . import installer_queue
from .installer import cleanup_legacy_dirs, install_requirements_only, run_post_install


_INSTALL_LOCK_NAME = "wafer_installer"
_LOCK_WAIT_TIMEOUT = 1800.0
_LOCK_POLL_INTERVAL = 0.5


def run_pending_installs(extensions_dir: str) -> bool:
    cleanup_legacy_dirs(extensions_dir)
    if not installer_queue.has_pending_queue(extensions_dir):
        return False

    lock = SafeProcessLock(_INSTALL_LOCK_NAME)
    if not _acquire_with_wait(lock, _LOCK_WAIT_TIMEOUT):
        AppLogger.warning("[StartupInstall] Could not acquire installer lock; skipping")
        return False

    try:
        entries = installer_queue.read_queue(extensions_dir)
        if not entries:
            AppLogger.info("[StartupInstall] Queue already drained by another process")
            return False
        AppLogger.info(f"[StartupInstall] Processing {len(entries)} queued install(s)")
        _terminate_stale_workers()
        processed, failed = _execute_installs(extensions_dir, entries)
        installer_queue.remove_entries(extensions_dir, processed + failed)
        _notify_result(processed, failed)
        return True
    finally:
        lock.release()


def _terminate_stale_workers() -> None:
    from ..core.platform.process import AppProcess

    targets = []
    for flag in ("--tray", "--indexer", "--collector", "--parser"):
        targets.extend(AppProcess.get_by_args_subset(flag))
    my_pid = os.getpid()
    targets = [p for p in targets if p.pid != my_pid]
    if not targets:
        return
    AppLogger.info(f"[StartupInstall] Terminating {len(targets)} stale process(es) to free package files")
    AppProcess.terminate_and_wait(targets)


def _install_one_phase_a(extensions_dir: str, entry, on_log=None) -> bool:
    plugin_dir = entry.plugin_dir or os.path.join(extensions_dir, entry.name)
    if not os.path.isdir(plugin_dir):
        AppLogger.warning(f"[StartupInstall] Plugin folder missing, skipping: {entry.name}")
        return False
    try:
        result = install_requirements_only(plugin_dir, extensions_dir, on_log=on_log)
        if result.success:
            AppLogger.info(f"[StartupInstall] pip install complete: {entry.name}")
            return True
        AppLogger.warning(f"[StartupInstall] pip install failed: {entry.name}")
        return False
    except Exception as e:
        AppLogger.warning(f"[StartupInstall] pip install raised for {entry.name}: {e}", exc=e)
        return False


def _install_one_phase_b(extensions_dir: str, entry, on_log=None) -> bool:
    plugin_dir = entry.plugin_dir or os.path.join(extensions_dir, entry.name)
    if not os.path.isdir(plugin_dir):
        return False
    try:
        result = run_post_install(plugin_dir, extensions_dir, on_log=on_log)
        if result.success and result.post_install_ok:
            AppLogger.info(f"[StartupInstall] post_install complete: {entry.name}")
            return True
        AppLogger.warning(f"[StartupInstall] post_install failed: {entry.name}")
        return False
    except Exception as e:
        AppLogger.warning(f"[StartupInstall] post_install raised for {entry.name}: {e}", exc=e)
        return False


def _acquire_with_wait(lock: SafeProcessLock, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while True:
        if lock.acquire():
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(_LOCK_POLL_INTERVAL)


def _notify_result(processed: list, failed: list) -> None:
    if processed:
        msg = f"Extensions installed: {', '.join(processed)}"
        AppLogger.info(f"[StartupInstall] {msg}")
        Notifier.info(msg)
    if failed:
        msg = f"Extension install failed: {', '.join(failed)}"
        AppLogger.warning(f"[StartupInstall] {msg}")
        Notifier.warning(msg)


def _execute_installs(extensions_dir: str, entries: list):
    try:
        from PySide6 import QtWidgets
    except ImportError:
        return _run_installs_blocking(extensions_dir, entries)

    app = QtWidgets.QApplication.instance()
    if app is None:
        return _run_installs_blocking(extensions_dir, entries)

    return _run_installs_threaded(app, extensions_dir, entries)


def _run_installs_blocking(extensions_dir: str, entries: list):
    processed: list = []
    failed: list = []
    total = len(entries)
    for i, entry in enumerate(entries, 1):
        AppLogger.info(f"[StartupInstall] pip ({i}/{total}) {entry.name}")
        if not _install_one_phase_a(extensions_dir, entry):
            failed.append(entry.name)
    pending = [e for e in entries if e.name not in failed]
    for i, entry in enumerate(pending, 1):
        AppLogger.info(f"[StartupInstall] post_install ({i}/{len(pending)}) {entry.name}")
        if _install_one_phase_b(extensions_dir, entry):
            processed.append(entry.name)
        else:
            failed.append(entry.name)
    return processed, failed


def _run_installs_threaded(app, extensions_dir: str, entries: list):
    from PySide6 import QtCore

    splash = _try_create_splash(len(entries))
    if splash is not None:
        splash.show()

    worker = _InstallWorker(extensions_dir, entries)
    thread = QtCore.QThread()
    worker.moveToThread(thread)

    state = {"done": False, "processed": [], "failed": []}

    def on_progress(phase: str, i: int, total: int, name: str):
        if splash is not None:
            label = "Installing" if phase == "pip" else "Setting up"
            splash.set_message(f"{label} {name} ({i}/{total})")

    def on_finished(processed: list, failed: list):
        state["processed"] = list(processed)
        state["failed"] = list(failed)
        state["done"] = True
        thread.quit()

    worker.progress.connect(on_progress)
    worker.finished.connect(on_finished)
    if splash is not None:
        worker.log.connect(splash.append_log)
    thread.started.connect(worker.run)
    thread.start()

    loop = QtCore.QEventLoop()
    timer = QtCore.QTimer()
    timer.setInterval(50)
    timer.timeout.connect(lambda: state["done"] and loop.quit())
    timer.start()
    loop.exec()
    timer.stop()

    thread.wait(5000)
    if splash is not None:
        splash.close()
    return state["processed"], state["failed"]


def _try_create_splash(count: int):
    try:
        from ..ui.splash import InstallSplash
    except (ImportError, RuntimeError) as e:
        AppLogger.warning(f"[StartupInstall] Splash unavailable: {e}", exc=e)
        return None
    try:
        return InstallSplash("Installing extensions", icon=_load_app_icon(), message=f"Installing {count} extension(s)")
    except (RuntimeError, AttributeError) as e:
        AppLogger.warning(f"[StartupInstall] Splash creation failed: {e}", exc=e)
        return None


def _load_app_icon():
    try:
        from PySide6 import QtGui
        from ..utils.paths import get_resource_path

        icon = QtGui.QIcon(str(get_resource_path() / "icon.ico"))
        if icon.isNull():
            return None
        return icon
    except Exception as e:
        AppLogger.warning(f"[StartupInstall] Icon load failed: {e}", exc=e)
        return None


try:
    from PySide6 import QtCore as _QtCore

    class _InstallWorker(_QtCore.QObject):
        progress = _QtCore.Signal(str, int, int, str)
        log = _QtCore.Signal(str)
        finished = _QtCore.Signal(list, list)

        def __init__(self, extensions_dir: str, entries: list):
            super().__init__()
            self._extensions_dir = extensions_dir
            self._entries = entries

        def run(self):
            processed: list = []
            failed: list = []
            total = len(self._entries)
            for i, entry in enumerate(self._entries, 1):
                self.progress.emit("pip", i, total, entry.name)
                if not _install_one_phase_a(self._extensions_dir, entry, on_log=self.log.emit):
                    failed.append(entry.name)
            pending = [e for e in self._entries if e.name not in failed]
            for i, entry in enumerate(pending, 1):
                self.progress.emit("post", i, len(pending), entry.name)
                if _install_one_phase_b(self._extensions_dir, entry, on_log=self.log.emit):
                    processed.append(entry.name)
                else:
                    failed.append(entry.name)
            self.finished.emit(processed, failed)
except ImportError:
    _InstallWorker = None
