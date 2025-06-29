import sys
from PySide6 import QtWidgets, QtGui, QtCore

from source.mutex import SafeProcessLock

from source.image_collector.main_tray import TrayApp
from source.profiling import initialize_profiling, logger, profiler

initialize_profiling()

def main():
    try:
        with SafeProcessLock("my_collector"):
            app = QtWidgets.QApplication(sys.argv)
            icon = QtGui.QIcon.fromTheme("folder")
            if icon.isNull():
                icon = QtGui.QIcon()
            tray_icon = TrayApp(icon)
            tray_icon.show()
            sys.exit(app.exec())
    except FileExistsError:
        logger.info("Collector はすでに起動中です。")
    except:
        raise

if __name__ == "__main__":
    main()
