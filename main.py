import sys
from PySide6 import QtWidgets, QtGui, QtCore
from source.image_viewer.mainwindow import MainWindow
from source.profiling import initialize_profiling, logger, profiler
from source.common import run_side_subprocess
from source.constants import APP_NAME

def main():
    run_side_subprocess("collector")
    initialize_profiling()
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
