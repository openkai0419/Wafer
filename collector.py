import sys
from PySide6 import QtWidgets, QtGui, QtCore

from source.mutex import SafeProcessLock

from source.image_collector.main_tray import TrayApp
from source.profiling import init_env

logger, profiler = init_env()

def main():
    try:
        with SafeProcessLock("my_collector"):
            app = QtWidgets.QApplication(sys.argv)
            icon = QtGui.QIcon.fromTheme("folder")
            if icon.isNull():
                icon = QtGui.QIcon()
            folders_to_watch = [
                r"M:\\collect\\picture\\ーNovelAI\\1_7_NAI4",
                r"M:\\collect\\picture\\ーNovelAI\\1_8_NAI4.5",
                r"C:\\Users\\openk\\Downloads",
                r"M:\\collect\\picture\\ーNovelAI\\1_6_XL",
            ]
            tray_icon = TrayApp(icon, folders_to_watch)
            tray_icon.show()
            sys.exit(app.exec())
    except FileExistsError:
        logger.info("Collector はすでに起動中です。")
    except:
        raise

if __name__ == "__main__":
    main()
