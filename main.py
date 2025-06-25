import sys
import subprocess
import os
from PySide6 import QtWidgets, QtGui, QtCore
from source.image_viewer.mainwindow import MainWindow 
from source.profiling import init_env
logger, profiler = init_env()

def run_collector_subprocess():
    # 実行形態に応じて collector を切り替える
    if getattr(sys, 'frozen', False):
        # PyInstaller で exe 化された場合
        base_path = os.path.dirname(sys.executable)
        stdout = subprocess.DEVNULL
        stderr = subprocess.DEVNULL
        collector_path = os.path.join(base_path, "collector.exe")
        command = [collector_path]
        creation_flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
    else:
        # Pythonスクリプトとして実行
        base_path = os.path.dirname(os.path.abspath(__file__))
        stdout = subprocess.DEVNULL
        stderr = subprocess.DEVNULL
        collector_path = os.path.join(base_path, "collector.py")
        command = [sys.executable, collector_path]
        creation_flags = 0

    try:
        subprocess.Popen(
            command,
            stdout=stdout,
            stderr=stderr,
            stdin=subprocess.DEVNULL,
            creationflags=creation_flags
        )

    except Exception as e:
        logger.error(f"[Error] Failed to start collector: {e}")
        return None

def main():
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    window.show()
    run_collector_subprocess()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()