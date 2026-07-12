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

from wafer.utils.paths import list_setting_db_names, resolve_data_path
from wafer.utils.process_lock import SafeProcessLock
from wafer.utils.logs import AppLogger


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
from wafer.utils.profiling import profiler
from wafer import __version__
from wafer.constants import APP_DATA_DIR_NAME, APP_ID, APP_NAME, DEFAULT_DB_NAME
from wafer.app.indexer.main_indexer import IndexerProcess
from wafer.plugin.loader import load_plugins, get_plugin_dir
from wafer.plugin.startup_install import run_pending_installs
from wafer.core.platform.process import AppProcess
from wafer.core.platform.process_checker import ParentProcessChecker
import wafer.constants as constants

def get_icon():
    from PySide6 import QtGui
    from wafer.utils.paths import get_resource_path
    icon = QtGui.QIcon(str(get_resource_path() / 'icon.ico'))
    if icon.isNull():
        icon = QtGui.QIcon()
    return icon

def set_app_user_model_id(app_id):
    if sys.platform == 'win32':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
set_app_user_model_id(APP_ID)


def _bootstrap_plugins_for_tray():
    run_pending_installs(get_plugin_dir())
    load_plugins()
    from wafer.plugin.loader import get_command_registry

    get_command_registry().activate('tray')


def _wait_install_then_load_plugins(app):
    from wafer.ui.install_waiter import wait_for_install_complete

    wait_for_install_complete(icon=get_icon(), app=app)
    load_plugins()


def _enable_shared_opengl_contexts():
    from PySide6 import QtCore

    QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_ShareOpenGLContexts, True)


def _create_app():
    from PySide6 import QtWidgets
    from wafer.core.qt.tooltip import install_instant_tooltips

    _enable_shared_opengl_contexts()
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    install_instant_tooltips(app)
    return app

def _entry_viewer(app=None, slot_id=None):
    setproctitle.setproctitle(f'{APP_NAME}')
    from wafer.app.viewer.mainwindow import MainWindow
    if constants.DEV_MODE:
        profiler.start()
    if app is None:
        app = _create_app()
    window = MainWindow(get_icon(), slot_id=slot_id)
    window.show()
    sys.exit(app.exec())

def _entry_tray():
    try:
        setproctitle.setproctitle(f'{APP_NAME}-tray')

        with SafeProcessLock(f'{APP_DATA_DIR_NAME}_tray'):
            _bootstrap_plugins_for_tray()
            from PySide6 import QtWidgets
            from wafer.app.tray.main_tray import TrayApp
            from wafer.core.qt.tooltip import install_instant_tooltips

            procs = AppProcess.get_by_args_subset('--indexer')
            AppProcess.terminate_and_wait(procs)
            AppLogger.info('TRAY RUNNING')

            _enable_shared_opengl_contexts()
            app = QtWidgets.QApplication(sys.argv)
            app.setQuitOnLastWindowClosed(False)
            app.setApplicationName(APP_NAME)
            install_instant_tooltips(app)
            app.aboutToQuit.connect(AppProcess.shutdown_children)
            tray_icon = TrayApp(get_icon())
            tray_icon.show()

            names = list_setting_db_names() or [DEFAULT_DB_NAME]
            my_pid = str(os.getpid())
            for name in names:
                AppProcess.new_main('--indexer', f'{name}', '--parent-pid', my_pid)

            sys.exit(app.exec())
    except FileExistsError:
        return

def _entry_indexer(name, parent_pid=None):
    try:
        setproctitle.setproctitle(f'{APP_NAME}-indexer-{name}')
        with SafeProcessLock(f'{APP_DATA_DIR_NAME}_{name}', parent_pid=parent_pid):
            AppLogger.info(f'indexer start: {name}')
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

def main():
    parser = argparse.ArgumentParser(description='Script with three run modes')
    parser.add_argument('--version', action='version', version=f'Wafer {__version__}')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--tray', action='store_true', help='run tray process (background manager)')
    group.add_argument('--viewer', action='store_true', help='run new viewer')
    group.add_argument('--indexer', nargs='?', const=True, help='run indexer for each settings. make new with optional string')
    group.add_argument('--collector', nargs='?', const=True, help='run collector process')
    group.add_argument('--parser', nargs='?', const=True, help='run parser process')
    parser.add_argument('--plugin', type=str, default='image', help='collector/parser plugin name')
    parser.add_argument('--parent-pid', type=int, default=None)
    parser.add_argument('--slot', type=str, default=None, help='window slot ID for viewer')
    args = parser.parse_args()
    if not any([args.tray, args.viewer, args.indexer, args.collector, args.parser]):
        app = _create_app()
        AppProcess.new_main('--tray')
        _wait_install_then_load_plugins(app)
        from wafer.core.workspace import WorkspaceStore
        restore_ids = WorkspaceStore.instance().get_restore_slot_ids()
        for sid in restore_ids[1:]:
            AppProcess.new_main('--viewer', '--slot', sid)
        _entry_viewer(app, slot_id=restore_ids[0] if restore_ids else None)
        return
    if args.tray:
        _entry_tray()
    elif args.indexer:
        if isinstance(args.indexer, str):
            load_plugins()
            _entry_indexer(args.indexer, parent_pid=args.parent_pid)
        else:
            AppProcess.new_main('--tray')
    elif args.collector:
        if isinstance(args.collector, str):
            load_plugins()
            _entry_collector(args.collector, args.plugin, parent_pid=args.parent_pid)
        else:
            AppLogger.warning('--collector requires a db name')
    elif args.parser:
        if isinstance(args.parser, str):
            load_plugins()
            _entry_parser(args.parser, args.plugin, parent_pid=args.parent_pid)
        else:
            AppLogger.warning('--parser requires a db name')
    elif args.viewer:
        app = _create_app()
        _wait_install_then_load_plugins(app)
        _entry_viewer(app, slot_id=args.slot)
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
