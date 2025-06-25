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