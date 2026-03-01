import argparse
import os
import signal
import sys
import threading
from afterimages.utils.paths import list_setting_db_names
from afterimages.utils.process_lock import SafeProcessLock
from afterimages.utils.logs import AppLogger
from afterimages.utils.profiling import profiler
from afterimages.constants import APP_DATA_DIR_NAME, APP_ID, APP_NAME, DEFAULT_DB_NAME
import afterimages.constants as constants
from afterimages.app.indexer.main_indexer import IndexerProcess
from afterimages.plugin.loader import load_plugins
from afterimages.core.platform.process import AppProcess
from afterimages.core.platform.process_checker import ParentProcessChecker

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
    return app

def _load_plugins_with_splash(app):
    from afterimages.plugin.loader import any_needs_install
    if any_needs_install():
        from afterimages.core.qt.splash import InstallSplash
        splash = InstallSplash(APP_NAME, get_icon())
        splash.show()
        load_plugins(on_progress=app.processEvents)
        splash.close()
    else:
        load_plugins()


def _entry_viewer(app=None):
    from afterimages.app.viewer.mainwindow import MainWindow
    if app is None:
        app = _create_app()
    window = MainWindow(get_icon())
    window.show()
    sys.exit(app.exec())

def _entry_tray():
    try:
        profiler.set_enabled(False)
        from PySide6 import QtWidgets
        from afterimages.app.tray.main_tray import TrayApp

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
        profiler.set_enabled(False)
        with SafeProcessLock(f'{APP_DATA_DIR_NAME}_{name}', parent_pid=parent_pid):
            AppLogger.info(f'indexer start: {name}')
            indexer = IndexerProcess(name)
            indexer.start_watch()
            stop_event = threading.Event()

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
        profiler.set_enabled(False)
        from afterimages.app.collector.worker import run_collector as _run
        _run(name, plugin, parent_pid=parent_pid)
    except FileExistsError:
        AppLogger.info(f"Collector '{plugin}' for '{name}' is already running.")

def main():
    parser = argparse.ArgumentParser(description='Script with three run modes')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--tray', action='store_true', help='run tray process (background manager)')
    group.add_argument('--viewer', action='store_true', help='run new viewer')
    group.add_argument('--indexer', nargs='?', const=True, help='run indexer for each settings. make new with optional string')
    group.add_argument('--collector', nargs='?', const=True, help='run collector process')
    group.add_argument('--install-deps', type=str, default=None, help=argparse.SUPPRESS)
    parser.add_argument('--plugin', type=str, default='image', help='collector plugin name')
    parser.add_argument('--parent-pid', type=int, default=None)
    parser.add_argument('--dev', action='store_true', help='enable developer mode')
    args = parser.parse_args()
    if args.dev:
        constants.DEV_MODE = True
    if args.install_deps:
        from afterimages.plugin.loader import install_plugin_deps
        sys.exit(install_plugin_deps(args.install_deps))
    if not any([args.tray, args.viewer, args.indexer, args.collector]):
        app = _create_app()
        _load_plugins_with_splash(app)
        AppProcess.new_main('--tray')
        _entry_viewer(app)
    if args.tray:
        load_plugins(skip_install=True)
        _entry_tray()
    elif args.indexer:
        load_plugins(skip_install=True)
        if isinstance(args.indexer, str):
            _entry_indexer(args.indexer, parent_pid=args.parent_pid)
        else:
            AppProcess.new_main('--tray')
    elif args.collector:
        load_plugins(skip_install=True)
        if isinstance(args.collector, str):
            _entry_collector(args.collector, args.plugin, parent_pid=args.parent_pid)
        else:
            AppLogger.warning('--collector requires a db name')
    elif args.viewer:
        app = _create_app()
        _load_plugins_with_splash(app)
        _entry_viewer(app)
if __name__ == '__main__':
    main()
