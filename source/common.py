import sys
import os
import glob
from pathlib import Path

from PySide6 import QtGui

def normalize_path(p):
    try:
        path = str(Path(p).resolve(strict=False))
    except Exception:
        path = str(Path(p).absolute())
    return path.replace("\\", "/")

def uipx(px: int, base_dpi: int = 96) -> int:
    screen = QtGui.QGuiApplication.primaryScreen()
    current_dpi = screen.logicalDotsPerInch()
    scale = current_dpi / base_dpi
    return int(px * scale)

def get_main_based_directory() -> Path:
    """
    実行ファイルまたは main.py のあるディレクトリを取得（PyInstaller対応）
    """
    if getattr(sys, 'frozen', False):
        # PyInstallerでバンドルされた実行ファイルから実行された場合
        return Path(sys.executable).resolve().parent
    else:
        # 通常のスクリプト実行（main.py）
        main_module = sys.modules.get('__main__')
        if hasattr(main_module, '__file__'):
            return Path(main_module.__file__).resolve().parent
        else:
            return Path.cwd()  # 対話モードなど
        
def get_or_create_path(relative_path):
    base_path = get_main_based_directory()
    full_path = base_path / relative_path 
    # ディレクトリが存在しなければ作成
    full_path.parent.mkdir(parents=True, exist_ok=True)
    return full_path