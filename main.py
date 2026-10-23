import argparse
import atexit
import faulthandler
import io
import os
import signal
import sys
import threading

os.environ.setdefault('QSG_RHI_BACKEND', 'opengl')

import setproctitle

if sys.stdout is None:
    sys.stdout = io.StringIO()
if sys.stderr is None:
    sys.stderr = io.StringIO()

from wafer.core.common.paths import list_setting_db_names, resolve_data_path
from wafer.core.platform.process_lock import SafeProcessLock
from wafer.core.logs import AppLogger


def _setup_faulthandler(force=False):
    # WARNING: faulthandler conflicts with LuaJIT SEH (0xe24c4a02) in libmpv-2.dll.
    # Enabling this WILL cause process crashes when video playback is active.
    # Only enable via WAFER_FAULTHANDLER=1 for debugging non-mpv fatal crashes.
    # Root fix: rebuild libmpv with -Dlua=disabled (see jaseg/python-mpv#305).
    if not os.environ.get('WAFER_FAULTHANDLER') and not force:
        return
    crash_dir = resolve_data_path(".crashlog")
    os.makedirs(crash_dir, exist_ok=True)
    crash_path = os.path.join(crash_dir, f"crash_{os.getpid()}.log")
    try:
        crash_file = open(crash_path, "w", encoding="utf-8")
        faulthandler.enable(file=crash_file)
    except Exception:
        faulthandler.enable()


_setup_faulthandler()
from wafer import __version__
from wafer.constants import APP_DATA_DIR_NAME, APP_ID, APP_NAME, DEFAULT_DB_NAME, TRAY_LOCK_NAME
from wafer.core.common.paths import get_plugin_dir
from wafer.core.platform.process import AppProcess
import wafer.constants as constants

def set_app_user_model_id(app_id):
    if sys.platform == 'win32':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
set_app_user_model_id(APP_ID)


def _load_plugins():
    from wafer.plugin.loader import load_plugins

    load_plugins()


def _bootstrap_plugins_for_tray():
    from wafer.plugin.startup_install import run_pending_installs

    run_pending_installs(get_plugin_dir())
    _load_plugins()
    from wafer.plugin.loader import get_command_registry

    get_command_registry().activate('tray')


def _wait_install_then_load_plugins(app):
    from wafer.qt.common.app_icon import get_icon
    from wafer.qt.install.waiter import wait_for_install_complete

    wait_for_install_complete(icon=get_icon(), app=app)
    _load_plugins()


def _ensure_tray_unless_pending():
    from wafer.plugin import installer_queue

    if not installer_queue.has_pending_queue(get_plugin_dir()):
        AppProcess.ensure_tray()


def _sync_explorer_menu():
    from wafer.core.platform import explorer_menu

    try:
        explorer_menu.sync()
    except OSError as exc:
        AppLogger.warning(f'Could not update the Explorer "Open with Wafer" entry: {exc}')


def _enable_shared_opengl_contexts():
    from PySide6 import QtCore

    QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_ShareOpenGLContexts, True)


def _create_app(*, shared_opengl=True):
    from PySide6 import QtWidgets
    from wafer.qt.common.app_icon import get_icon
    from wafer.qt.common.tooltip import install_instant_tooltips

    if shared_opengl:
        _enable_shared_opengl_contexts()
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setWindowIcon(get_icon())
    install_instant_tooltips(app)
    return app

def _start_viewer_profiling():
    if constants.DEV_MODE:
        from wafer.core.profiling import profiler
        profiler.start()
    if constants.MEMWATCH:
        from wafer.core.profiling import memwatch
        memwatch.start(trace=constants.MEMWATCH_TRACE)

def _entry_viewer(app, lock=None, pick=False, seed_slot=None, open_request=None):
    setproctitle.setproctitle(f'{APP_NAME}')
    _start_viewer_profiling()
    from wafer.app.viewer.workspace_launch import run_pick, run_viewer
    if pick:
        run_pick(app, seed_slot)
    run_viewer(app, lock, open_request=open_request)

def _entry_launcher(path):
    setproctitle.setproctitle(f'{APP_NAME}-launcher')
    app = _create_app(shared_opengl=False)
    _ensure_tray_unless_pending()
    _sync_explorer_menu()
    from wafer.app.viewer.workspace_launch import run_open_path
    run_open_path(app, path)

def _open_request(args):
    if not args.open_path:
        return None
    from wafer.app.viewer.workspace_launch import OpenRequest
    return OpenRequest(args.open_path, args.open_database or '')

def _entry_tray():
    try:
        setproctitle.setproctitle(f'{APP_NAME}-tray')

        with SafeProcessLock(TRAY_LOCK_NAME):
            _bootstrap_plugins_for_tray()
            from wafer.app.tray.main_tray import TrayApp
            from wafer.qt.common.app_icon import get_icon

            procs = AppProcess.get_by_args_subset('--indexer')
            AppProcess.terminate_and_wait(procs)
            AppLogger.info('TRAY RUNNING')

            app = _create_app()
            app.setQuitOnLastWindowClosed(False)
            app.aboutToQuit.connect(AppProcess.shutdown_children)
            tray_icon = TrayApp(get_icon())
            tray_icon.show()

            names = list_setting_db_names() or [DEFAULT_DB_NAME]
            my_pid = str(os.getpid())
            for name in names:
                AppProcess.new_main('--indexer', f'{name}', '--parent-pid', my_pid)

            sys.exit(app.exec())
    except FileExistsError:
        AppLogger.info('tray already running, this instance exits (single-tray lock held by another process)')
        return

def _entry_indexer(name, parent_pid=None):
    try:
        setproctitle.setproctitle(f'{APP_NAME}-indexer-{name}')
        with SafeProcessLock(f'{APP_DATA_DIR_NAME}_{name}', parent_pid=parent_pid):
            AppLogger.info(f'indexer start: {name}')
            from wafer.app.indexer.main_indexer import IndexerProcess
            from wafer.core.platform.process_checker import ParentProcessChecker

            stop_event = threading.Event()
            indexer = IndexerProcess(name, stop_event=stop_event, tray_pid=parent_pid)
            indexer.start_watch()
            shutdown_once = threading.Event()

            def shutdown():
                if shutdown_once.is_set():
                    return
                shutdown_once.set()
                AppLogger.info('[Indexer] Shutting down...')
                indexer.stop()
                stop_event.set()

            signal.signal(signal.SIGINT, lambda s, f: stop_event.set() or shutdown_once.set())
            signal.signal(signal.SIGTERM, lambda s, f: stop_event.set() or shutdown_once.set())

            checker = None
            if parent_pid is not None:
                checker = ParentProcessChecker(parent_pid, on_orphan=lambda: stop_event.set() or shutdown_once.set())
                checker.start()
            indexer.zmq.on_broker_lost(lambda: stop_event.set() or shutdown_once.set())

            AppLogger.info('[Indexer] Running. Press Ctrl+C to exit.')
            stop_event.wait()
            shutdown()

            if checker:
                checker.stop()
    except FileExistsError:
        AppLogger.info(f"Indexer '{name}' is already running.")

def _entry_collector(name, plugin, parent_pid=None):
    try:
        setproctitle.setproctitle(f'{APP_NAME}-collector-{plugin}')
        from wafer.app.collector.worker import run_collector as _run
        _run(name, plugin, parent_pid=parent_pid)
    except FileExistsError:
        AppLogger.info(f"Collector '{plugin}' for '{name}' is already running.")

def _entry_parser(name, plugin, parent_pid=None):
    try:
        setproctitle.setproctitle(f'{APP_NAME}-parser-{plugin}')
        from wafer.app.parser.worker import run_parser as _run
        _run(name, plugin, parent_pid=parent_pid)
    except FileExistsError:
        AppLogger.info(f"Parser '{plugin}' for '{name}' is already running.")

def _entry_webui(args):
    try:
        setproctitle.setproctitle(f'{APP_NAME}-webui')
        AppLogger.set_role('webui')
        if os.environ.pop('WAFER_REPLACE_WEBUI', None):
            AppProcess.terminate_cmd('--webui', wait=True, exclude_self=True)
        from wafer.app.webui.settings import WebUISettings
        host, port = WebUISettings().resolve_bind(args.host, args.port)
        with SafeProcessLock(f'{APP_DATA_DIR_NAME}_webui'):
            if not args.no_tray:
                _ensure_tray_unless_pending()
            from wafer.app.webui.entry import run_headless, run_ui
            if args.no_ui:
                from wafer.plugin.install_wait import wait_for_install_headless

                wait_for_install_headless()
                _load_plugins()
                run_headless(host, port, open_browser=not args.no_browser)
            else:
                app = _create_app()
                _wait_install_then_load_plugins(app)
                from wafer.plugin.loader import get_command_registry
                get_command_registry().activate('webui')
                run_ui(app, host, port, open_browser=not args.no_browser)
    except FileExistsError:
        AppLogger.info('WebUI is already running.')

def main():
    parser = argparse.ArgumentParser(description='Script with three run modes')
    parser.add_argument('--version', action='version', version=f'Wafer {__version__}')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--tray', action='store_true', help='run tray process (background manager)')
    group.add_argument('--viewer', action='store_true', help='run new viewer')
    group.add_argument('--webui', action='store_true', help='run WebUI server')
    group.add_argument('--indexer', nargs='?', const=True, help='run indexer for each settings. make new with optional string')
    group.add_argument('--collector', nargs='?', const=True, help='run collector process')
    group.add_argument('--parser', nargs='?', const=True, help='run parser process')
    parser.add_argument('--plugin', type=str, default='image', help='collector/parser plugin name')
    parser.add_argument('--parent-pid', type=int, default=None)
    parser.add_argument('--slot', type=str, default=None, help='window slot ID for viewer')
    parser.add_argument('--pick', action='store_true', help='viewer: choose the workspace to open first')
    parser.add_argument('--seed-slot', type=str, default=None, help='viewer --pick: slot ID that new workspaces copy their layout from')
    parser.add_argument('--host', default=None, help='webui bind host (overrides webui_settings.ini)')
    parser.add_argument('--port', type=int, default=None, help='webui bind port (overrides webui_settings.ini)')
    parser.add_argument('--no-browser', action='store_true', help='webui: do not open the browser on start')
    parser.add_argument('--no-ui', action='store_true', help='webui: run headless without management window')
    parser.add_argument('--no-tray', action='store_true', help='webui: do not spawn the tray process')
    parser.add_argument('--open-path', default=None, help='viewer --slot: file to open once the workspace is restored')
    parser.add_argument('--open-database', default=None, help='viewer --open-path: database to open the file in')
    parser.add_argument('path', nargs='?', help='file to open through the workspace picker')
    args = parser.parse_args()
    if not any([args.tray, args.viewer, args.webui, args.indexer, args.collector, args.parser]):
        from wafer.app.viewer.workspace_launch import claim_workspace, first_restore_slot_id, is_openable_path, restore_session
        if args.path and is_openable_path(args.path):
            _entry_launcher(args.path)
            return
        app = _create_app()
        if os.environ.pop('WAFER_REPLACE_TRAY', None):
            AppProcess.terminate_cmd('--tray', wait=True)
        _ensure_tray_unless_pending()
        _sync_explorer_menu()
        first_slot_id = first_restore_slot_id()
        lock = claim_workspace(first_slot_id)
        if lock is None:
            restore_session(first_slot_id)
            sys.exit(0)
        _wait_install_then_load_plugins(app)
        restore_session(first_slot_id)
        _entry_viewer(app, lock=lock)
        return
    if args.tray:
        _entry_tray()
    elif args.webui:
        _entry_webui(args)
    elif args.indexer:
        if isinstance(args.indexer, str):
            _load_plugins()
            _entry_indexer(args.indexer, parent_pid=args.parent_pid)
        else:
            AppProcess.ensure_tray()
    elif args.collector:
        if isinstance(args.collector, str):
            _load_plugins()
            _entry_collector(args.collector, args.plugin, parent_pid=args.parent_pid)
        else:
            AppLogger.warning('--collector requires a db name')
    elif args.parser:
        if isinstance(args.parser, str):
            _load_plugins()
            _entry_parser(args.parser, args.plugin, parent_pid=args.parent_pid)
        else:
            AppLogger.warning('--parser requires a db name')
    elif args.viewer:
        app = _create_app()
        open_request = _open_request(args)
        lock = None
        if not args.pick:
            from wafer.app.viewer.workspace_launch import claim_or_hand_over
            lock = claim_or_hand_over(args.slot, open_request)
            if lock is None:
                sys.exit(0)
        _wait_install_then_load_plugins(app)
        _entry_viewer(app, lock=lock, pick=args.pick, seed_slot=args.seed_slot, open_request=open_request)
if __name__ == '__main__':
    atexit.register(lambda: AppLogger.info(f'process exit (pid={os.getpid()})'))
    try:
        main()
    except SystemExit:
        raise
    except BaseException:
        import traceback
        AppLogger.error(f'fatal crash in main():\n{traceback.format_exc()}')
        raise
