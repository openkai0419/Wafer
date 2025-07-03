import sys
import subprocess
import os
from PySide6 import QtWidgets, QtGui, QtCore
from source.image_viewer.mainwindow import MainWindow
from source.profiling import initialize_profiling, logger, profiler
from source.common import run_side_subprocess


def main():
    initialize_profiling()
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("AfterImage")
    window = MainWindow()
    window.show()
    run_side_subprocess("collector")
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
