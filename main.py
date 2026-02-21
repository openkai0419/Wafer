import argparse
import os
import signal
import sys
import threading
from source.common.funcs import get_setting_file_names
from source.common.mutex import SafeProcessLock
from source.common.logs import AppLogger
from source.common.profiling import profiler
from source.constants import APP_FILE_NAME, APP_ID, APP_NAME, default_db_name
import source.constants as constants
from source.image_indexer.main_indexer import IndexerProcess
from source.os.process import Proc
from source.io.bootstrap import import_all 

import_all()

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
        from source.image_tray.main_tray import TrayApp
        with SafeProcessLock(f'{APP_FILE_NAME}_communicator'):
            AppLogger.info('COMMUNICATOR RUNNING')
            app = QtWidgets.QApplication(sys.argv)
            app.setQuitOnLastWindowClosed(False)
            app.setApplicationName(APP_NAME)
            app.aboutToQuit.connect(lambda: Proc.terminate_cmd('--indexer'))
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
        with SafeProcessLock(f'{APP_FILE_NAME}_{name}', parent_pid=parent_pid):
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
    Proc.terminate_cmd('--indexer')
    names = get_setting_file_names()
    if not names:
        names = [default_db_name]
    my_pid = str(os.getpid())
    for name in names:
        Proc.new_main('--indexer', f'{name}', '--parent-pid', my_pid)
    run_communicator()

def run_viewer():
    from PySide6 import QtWidgets
    from source.image_viewer.mainwindow import MainWindow
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    window = MainWindow(get_icon())
    window.show()
    sys.exit(app.exec())

def run_collector(name, plugin, parent_pid=None):
    try:
        profiler.set_enabled(False)
        from source.image_collector.worker import run_collector as _run
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
    parser.add_argument('--plugin', type=str, default='image', help='collector plugin name')
    parser.add_argument('--parent-pid', type=int, default=None)
    parser.add_argument('--dev', action='store_true', help='enable developer mode')
    args = parser.parse_args()
    if args.dev:
        constants.DEV_MODE = True
    if not any([args.communicator, args.viewer, args.indexer, args.collector]):
        Proc.new_main('--communicator')
        run_viewer()
        return
    if args.communicator:
        run_all_indexers()
    elif args.indexer:
        if isinstance(args.indexer, str):
            run_indexer(args.indexer, parent_pid=args.parent_pid)
        else:
            Proc.new_main('--communicator')
    elif args.collector:
        if isinstance(args.collector, str):
            run_collector(args.collector, args.plugin, parent_pid=args.parent_pid)
        else:
            AppLogger.warning('--collector requires a db name')
    elif args.viewer:
        run_viewer()
if __name__ == '__main__':
    main()
