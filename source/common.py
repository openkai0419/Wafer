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
    """
    DPIスケーリングに基づいてピクセル値を補正する。
    
    Parameters:
        px (int): 論理的な基準ピクセル（通常デザイン基準の 96dpi 用）
        base_dpi (int): 基準DPI（通常は96）
    
    Returns:
        int: 実際のDPIに合わせたスケーリング後のピクセル値
    """
    screen = QtGui.QGuiApplication.primaryScreen()
    current_dpi = screen.logicalDotsPerInch()
    scale = current_dpi / base_dpi
    return int(px * scale)