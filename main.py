import argparse
import io
import os
import signal
import sys
import threading

import setproctitle

if getattr(sys, 'frozen', False):
    if sys.stdout is None:
        sys.stdout = io.StringIO()
    if sys.stderr is None:
        sys.stderr = io.StringIO()

from wafer.utils.paths import list_setting_db_names
from wafer.utils.process_lock import SafeProcessLock
from wafer.utils.logs import AppLogger
from wafer.utils.profiling import profiler
from wafer import __version__
from wafer.constants import APP_DATA_DIR_NAME, APP_ID, APP_NAME, DEFAULT_DB_NAME
from wafer.app.indexer.main_indexer import IndexerProcess
from wafer.plugin.loader import load_plugins
from wafer.core.platform.process import AppProcess
from wafer.core.platform.process_checker import ParentProcessChecker
import wafer.constants as constants

def get_icon():
    from PySide6 import QtGui
    icon = QtGui.QIcon('_resources/icon.ico')
    if icon.isNull():
        icon = QtGui.QIcon()
    return icon

def set_app_user_model_id(app_id):
    if sys.platform == 'win32':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
set_app_user_model_id(APP_ID)


def _create_app():
    from PySide6 import QtWidgets
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    return app

def _entry_viewer(app=None, session_id=None):
    setproctitle.setproctitle(f'{APP_NAME}')
    from wafer.app.viewer.mainwindow import MainWindow
    profiler.start()
    if app is None:
        app = _create_app()
    window = MainWindow(get_icon(), session_id=session_id)
    window.show()
    sys.exit(app.exec())

def _entry_tray():
    try:
        setproctitle.setproctitle(f'{APP_NAME}-tray')
        profiler.set_enabled(False)
        from PySide6 import QtWidgets
        from wafer.app.tray.main_tray import TrayApp

        procs = AppProcess.get_by_args_subset('--indexer')
        AppProcess.terminate_and_wait(procs)

        with SafeProcessLock(f'{APP_DATA_DIR_NAME}_tray'):
            AppLogger.info('TRAY RUNNING')

            names = list_setting_db_names() or [DEFAULT_DB_NAME]
            my_pid = str(os.getpid())
            for name in names:
                AppProcess.new_main('--indexer', f'{name}', '--parent-pid', my_pid)

            app = QtWidgets.QApplication(sys.argv)
            app.setQuitOnLastWindowClosed(False)
            app.setApplicationName(APP_NAME)
            app.aboutToQuit.connect(AppProcess.shutdown_children)
            tray_icon = TrayApp(get_icon())
            tray_icon.show()
            sys.exit(app.exec())
    except FileExistsError:
        return

def _entry_indexer(name, parent_pid=None):
    try:
        setproctitle.setproctitle(f'{APP_NAME}-indexer-{name}')
        profiler.set_enabled(False)
        with SafeProcessLock(f'{APP_DATA_DIR_NAME}_{name}', parent_pid=parent_pid):
            AppLogger.info(f'indexer start: {name}')
            stop_event = threading.Event()
            indexer = IndexerProcess(name, stop_event=stop_event)
            indexer.start_watch()

            def shutdown():
                AppLogger.info('[Indexer] Shutting down...')
                indexer.stop()
                stop_event.set()

            signal.signal(signal.SIGINT, lambda s, f: shutdown())
            signal.signal(signal.SIGTERM, lambda s, f: shutdown())

            checker = None
            if parent_pid is not None:
                checker = ParentProcessChecker(parent_pid, on_orphan=shutdown)
                checker.start()

            AppLogger.info('[Indexer] Running. Press Ctrl+C to exit.')
            stop_event.wait()

            if checker:
                checker.stop()
    except FileExistsError:
        AppLogger.info(f"Indexer '{name}' is already running.")

def _entry_collector(name, plugin, parent_pid=None):
    try:
        setproctitle.setproctitle(f'{APP_NAME}-collector-{plugin}')
        profiler.set_enabled(False)
        from wafer.app.collector.worker import run_collector as _run
        _run(name, plugin, parent_pid=parent_pid)
    except FileExistsError:
        AppLogger.info(f"Collector '{plugin}' for '{name}' is already running.")

def _entry_detacher(name, plugin, parent_pid=None):
    try:
        setproctitle.setproctitle(f'{APP_NAME}-detacher-{plugin}')
        profiler.set_enabled(False)
        from wafer.app.detacher.worker import run_detacher as _run
        _run(name, plugin, parent_pid=parent_pid)
    except FileExistsError:
        AppLogger.info(f"Detacher '{plugin}' for '{name}' is already running.")

def main():
    parser = argparse.ArgumentParser(description='Script with three run modes')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--tray', action='store_true', help='run tray process (background manager)')
    group.add_argument('--viewer', action='store_true', help='run new viewer')
    group.add_argument('--indexer', nargs='?', const=True, help='run indexer for each settings. make new with optional string')
    group.add_argument('--collector', nargs='?', const=True, help='run collector process')
    group.add_argument('--detacher', nargs='?', const=True, help='run detacher process')
    parser.add_argument('--plugin', type=str, default='image', help='collector/detacher plugin name')
    parser.add_argument('--parent-pid', type=int, default=None)
    parser.add_argument('--session', type=str, default=None, help='session ID for viewer')
    parser.add_argument('--dev', action='store_true', help='enable developer mode')
    args = parser.parse_args()
    if args.dev:
        constants.DEV_MODE = True
    if not any([args.tray, args.viewer, args.indexer, args.collector, args.detacher]):
        app = _create_app()
        load_plugins()
        AppProcess.new_main('--tray')
        from wafer.core.session import SessionStore
        restore_ids = SessionStore().get_restore_session_ids()
        for sid in restore_ids[1:]:
            AppProcess.new_main('--viewer', '--session', sid)
        _entry_viewer(app, session_id=restore_ids[0] if restore_ids else None)
        return
    if args.tray:
        load_plugins()
        from wafer.plugin.loader import get_command_registry
        get_command_registry().activate('tray')
        _entry_tray()
    elif args.indexer:
        load_plugins()
        if isinstance(args.indexer, str):
            _entry_indexer(args.indexer, parent_pid=args.parent_pid)
        else:
            AppProcess.new_main('--tray')
    elif args.collector:
        load_plugins()
        if isinstance(args.collector, str):
            _entry_collector(args.collector, args.plugin, parent_pid=args.parent_pid)
        else:
            AppLogger.warning('--collector requires a db name')
    elif args.detacher:
        load_plugins()
        if isinstance(args.detacher, str):
            _entry_detacher(args.detacher, args.plugin, parent_pid=args.parent_pid)
        else:
            AppLogger.warning('--detacher requires a db name')
    elif args.viewer:
        app = _create_app()
        load_plugins()
        _entry_viewer(app, session_id=args.session)
if __name__ == '__main__':
    main()
