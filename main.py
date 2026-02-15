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
from source.image_collector.main_collector import CollectorProcess
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
            app.aboutToQuit.connect(lambda: Proc.terminate_cmd('--collector'))
            tray_icon = TrayApp(get_icon())
            tray_icon.show()
            sys.exit(app.exec())
    except FileExistsError:
        return
    except:
        raise

def run_collector(name, parent_pid=None):
    try:
        profiler.set_enabled(False)
        with SafeProcessLock(f'{APP_FILE_NAME}_{name}', parent_pid=parent_pid):
            AppLogger.info(f'collector start :{name}')
            collector = CollectorProcess(name)
            collector.start_watch()
            stop_event = threading.Event()

            def shutdown_handler(sig, frame):
                AppLogger.info('[Collector] Shutting down...')
                collector.stop()
                stop_event.set()
            signal.signal(signal.SIGINT, shutdown_handler)
            signal.signal(signal.SIGTERM, shutdown_handler)
            AppLogger.info('[Collector] Running. Press Ctrl+C to exit.')
            stop_event.wait()
    except FileExistsError:
        AppLogger.info(f"Collector '{name}' is already running.")
    except:
        raise

def run_all_collectors():
    Proc.terminate_cmd('--collector')
    names = get_setting_file_names()
    if not names:
        names = [default_db_name]
    my_pid = str(os.getpid())
    for name in names:
        Proc.new_main('--collector', f'{name}', '--parent-pid', my_pid)
    run_communicator()

def run_viewer():
    from PySide6 import QtWidgets
    from source.image_viewer.mainwindow import MainWindow
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    window = MainWindow(get_icon())
    window.show()
    sys.exit(app.exec())

def main():
    parser = argparse.ArgumentParser(description='Script with three run modes')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--communicator', action='store_true', help='run communicator. it will be solo')
    group.add_argument('--viewer', action='store_true', help='run new viewer')
    group.add_argument('--collector', nargs='?', const=True, help='run collector for each settings. make new with optional string')
    parser.add_argument('--parent-pid', type=int, default=None)
    parser.add_argument('--dev', action='store_true', help='enable developer mode')
    args = parser.parse_args()
    if args.dev:
        constants.DEV_MODE = True
    if not any([args.communicator, args.viewer, args.collector]):
        Proc.new_main('--communicator')
        run_viewer()
        return
    if args.communicator:
        run_all_collectors()
    elif args.collector:
        if isinstance(args.collector, str):
            run_collector(args.collector, parent_pid=args.parent_pid)
        else:
            Proc.new_main('--communicator')
    elif args.viewer:
        run_viewer()
if __name__ == '__main__':
    main()
