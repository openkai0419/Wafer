import argparse
import os
import signal
import sys
import threading
from source.utils.paths import list_setting_db_names
from source.utils.process_lock import SafeProcessLock
from source.utils.logs import AppLogger
from source.utils.profiling import profiler
from source.constants import APP_DATA_DIR_NAME, APP_ID, APP_NAME, DEFAULT_DB_NAME
import source.constants as constants
from source.app.indexer.main_indexer import IndexerProcess
from source.plugin_core.loader import load_plugins
from source.core.platform.process import AppProcess

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


def run_communicator():
    try:
        profiler.set_enabled(False)
        from PySide6 import QtWidgets
        from source.app.tray.main_tray import TrayApp
        with SafeProcessLock(f'{APP_DATA_DIR_NAME}_communicator'):
            AppLogger.info('COMMUNICATOR RUNNING')
            app = QtWidgets.QApplication(sys.argv)
            app.setQuitOnLastWindowClosed(False)
            app.setApplicationName(APP_NAME)
            app.aboutToQuit.connect(lambda: AppProcess.terminate_cmd('--indexer'))
            tray_icon = TrayApp(get_icon())
            tray_icon.show()
            sys.exit(app.exec())
    except FileExistsError:
        return
    except:
        raise

def run_indexer(name, parent_pid=None):
    try:
        profiler.set_enabled(False)
        with SafeProcessLock(f'{APP_DATA_DIR_NAME}_{name}', parent_pid=parent_pid):
            AppLogger.info(f'indexer start: {name}')
            indexer = IndexerProcess(name)
            indexer.start_watch()
            stop_event = threading.Event()

            def shutdown_handler(sig, frame):
                AppLogger.info('[Indexer] Shutting down...')
                indexer.stop()
                stop_event.set()
            signal.signal(signal.SIGINT, shutdown_handler)
            signal.signal(signal.SIGTERM, shutdown_handler)
            AppLogger.info('[Indexer] Running. Press Ctrl+C to exit.')
            stop_event.wait()
    except FileExistsError:
        AppLogger.info(f"Indexer '{name}' is already running.")
    except:
        raise

def run_all_indexers():
    AppProcess.terminate_cmd('--indexer')
    names = list_setting_db_names()
    if not names:
        names = [DEFAULT_DB_NAME]
    my_pid = str(os.getpid())
    for name in names:
        AppProcess.new_main('--indexer', f'{name}', '--parent-pid', my_pid)
    run_communicator()

def _create_app():
    from PySide6 import QtWidgets
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    return app


def run_viewer(app=None):
    from PySide6 import QtWidgets
    from source.app.viewer.mainwindow import MainWindow
    if app is None:
        app = _create_app()
    window = MainWindow(get_icon())
    window.show()
    sys.exit(app.exec())

def run_collector(name, plugin, parent_pid=None):
    try:
        profiler.set_enabled(False)
        from source.app.collector.worker import run_collector as _run
        _run(name, plugin, parent_pid=parent_pid)
    except FileExistsError:
        AppLogger.info(f"Collector '{plugin}' for '{name}' is already running.")
    except:
        raise

def main():
    parser = argparse.ArgumentParser(description='Script with three run modes')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--communicator', action='store_true', help='run communicator. it will be solo')
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
        from source.plugin_core.loader import install_plugin_deps
        sys.exit(install_plugin_deps(args.install_deps))
    if not any([args.communicator, args.viewer, args.indexer, args.collector]):
        from source.plugin_core.loader import any_needs_install
        app = _create_app()
        if any_needs_install():
            from source.core.qt.splash import InstallSplash
            splash = InstallSplash(APP_NAME, get_icon())
            splash.show()
            load_plugins(on_progress=app.processEvents)
            splash.close()
        else:
            load_plugins()
        AppProcess.new_main('--communicator')
        run_viewer(app)
    if args.communicator:
        load_plugins(skip_install=True)
        run_all_indexers()
    elif args.indexer:
        load_plugins(skip_install=True)
        if isinstance(args.indexer, str):
            run_indexer(args.indexer, parent_pid=args.parent_pid)
        else:
            AppProcess.new_main('--communicator')
    elif args.collector:
        load_plugins(skip_install=True)
        if isinstance(args.collector, str):
            run_collector(args.collector, args.plugin, parent_pid=args.parent_pid)
        else:
            AppLogger.warning('--collector requires a db name')
    elif args.viewer:
        from source.plugin_core.loader import any_needs_install
        app = _create_app()
        if any_needs_install():
            from source.core.qt.splash import InstallSplash
            splash = InstallSplash(APP_NAME, get_icon())
            splash.show()
            load_plugins(on_progress=app.processEvents)
            splash.close()
        else:
            load_plugins()
        run_viewer(app)
if __name__ == '__main__':
    main()
