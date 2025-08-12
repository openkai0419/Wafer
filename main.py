import sys
import signal
import argparse
import threading

from source.image_collector.main_collector import CollectorProcess
from source.common.profiling import initialize_profiling, logger, profiler
from source.constants import APP_FILE_NAME, APP_NAME, default_db_name, APP_ID
from source.common.funcs import get_setting_file_names, new_main, split_last
from source.common.mutex import SafeProcessLock

def get_icon():
    from PySide6 import QtGui

    icon = QtGui.QIcon("_resources/icon.ico")
    if icon.isNull():
        icon = QtGui.QIcon()
    return icon

def set_app_user_model_id(app_id: str):
    """Set AppUserModelID on Windows so the taskbar groups icons."""
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)

set_app_user_model_id(APP_ID)

def run_communicator():
    try:
        #logger.setLevel(30)
        profiler.set_enabled(False)
        from PySide6 import QtWidgets
        from source.image_tray.main_tray import TrayApp

        with SafeProcessLock(f"{APP_FILE_NAME}_communicator"):
            logger.info("COMMUNICATOR RUNNING")
            app = QtWidgets.QApplication(sys.argv)
            app.setQuitOnLastWindowClosed(False)
            app.setApplicationName(APP_NAME)
            tray_icon = TrayApp(get_icon())
            tray_icon.show()
            sys.exit(app.exec())
    except FileExistsError:
        return
    except:
        raise

def run_collector(name):
    try:
        logger.setLevel(30)
        profiler.set_enabled(False)
        with SafeProcessLock(f"{APP_FILE_NAME}_{name}"):
            initialize_profiling()
            logger.info(f"collector start :{name}")

            collector = CollectorProcess(name)

            stop_event = threading.Event()

            def shutdown_handler(sig, frame):
                logger.info("\n[Collector] Shutting down...")
                collector.stop()
                stop_event.set()

            signal.signal(signal.SIGINT, shutdown_handler)
            signal.signal(signal.SIGTERM, shutdown_handler)

            logger.info("[Collector] Running. Press Ctrl+C to exit.")
            stop_event.wait()

            collector.stop()

    except FileExistsError:
        logger.info(f"Collector '{name}' is already running.")
    except:
        raise

def run_all_collectors():
    names = get_setting_file_names()
    if not names:
        names = [default_db_name]
    for name in names:
        new_main("--collector", f"{name}")
    run_communicator()

def run_viewer():
    from PySide6 import QtWidgets
    from source.image_viewer.mainwindow import MainWindow

    initialize_profiling()
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    window = MainWindow(get_icon())
    window.show()
    sys.exit(app.exec())

def main():
    parser = argparse.ArgumentParser(description="Script with three run modes")
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--communicator', action='store_true', help='run communicator. it will be solo')
    group.add_argument('--viewer', action='store_true', help='run new viewer')
    group.add_argument('--collector', nargs='?', const=True, help='run collector for each settings. make new with optional string')

    args = parser.parse_args()

    # run all three if no args
    if not any(vars(args).values()):
        new_main("--collector")
        run_viewer()
        return

    if args.communicator:
        run_communicator()

    elif args.collector:
        if isinstance(args.collector, str):
            new_main("--communicator")
            run_collector(args.collector)
        else:
            run_all_collectors()

    elif args.viewer:
        run_viewer()

if __name__ == "__main__":
    main()
