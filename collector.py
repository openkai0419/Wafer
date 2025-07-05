import signal
import sys
import threading
from multiprocessing import Process, freeze_support
from PySide6 import QtWidgets, QtGui, QtCore

from source.image_collector.main_tray import TrayApp
from source.profiling import initialize_profiling, logger, profiler
from source.constants import APP_NAME, defualt_db_name
from source.common import get_setting_file_names, run_side_subprocess
from source.mutex import SafeProcessLock
from source.core.zmq import ZMQBroker

def run_communicator():
    try:
        initialize_profiling()
        shutdown_event = threading.Event()
        with SafeProcessLock(f"{APP_NAME}_communicator"):
            logger.info("communicator start")
            broker = ZMQBroker()

            def shutdown_handler(sig, frame):
                logger.info("\n[Broker] Shutting down...")
                broker.close()
                shutdown_event.set()
                sys.exit(0)

            signal.signal(signal.SIGINT, shutdown_handler)
            signal.signal(signal.SIGTERM, shutdown_handler)

            # Block main thread
            logger.info ("[Broker] Running. Press Ctrl+C to exit.")
            shutdown_event.wait() 
    except FileExistsError:
        return
    except:
        raise

def start(name):
    try:
        initialize_profiling()
        with SafeProcessLock(f"{APP_NAME}_{name}"):
            app = QtWidgets.QApplication(sys.argv)
            app.setQuitOnLastWindowClosed(False) 
            app.setApplicationName(APP_NAME)
            icon = QtGui.QIcon.fromTheme("folder")
            if icon.isNull():
                icon = QtGui.QIcon()
            tray_icon = TrayApp(icon, name)
            tray_icon.show()
            sys.exit(app.exec())
    except FileExistsError:
        logger.info(f"Collector : {name} はすでに起動中です。")
    except:
        raise

def main():
    p = Process(target=run_communicator)
    p.start()
    if len(sys.argv) < 2:
        names = get_setting_file_names()
        if not names:
            names = [defualt_db_name]
        for name in names:
            run_side_subprocess("collector", f"{name}")
    else:
        name = sys.argv[1]
        logger.info(f"starting : {name}")
        start(name)

if __name__ == "__main__":
    freeze_support()
    main()
