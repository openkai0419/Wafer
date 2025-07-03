import os
import sys
import subprocess
from pathlib import Path
from platformdirs import PlatformDirs
from typing import List
from natsort import natsorted, ns

from PySide6 import QtGui
#from .profiling import logger

# Supported image extensions
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp")
APP_NAME = "AfterImages"

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

def native_sort(files):
    return natsorted(files, alg=ns.LOCALE | ns.IGNORECASE)

def get_main_based_directory() -> Path:
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

def run_side_subprocess(name, *args, **kwargs):
    base_dir = get_main_based_directory()
    stdout = subprocess.DEVNULL
    stderr = subprocess.DEVNULL
    if getattr(sys, 'frozen', False):
        executalble =  base_dir / f"{Path(name).stem}.exe"
        command = [executalble, *args]
        creation_flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
    else:
        executalble =  base_dir / f"{Path(name).stem}.py"
        command = [sys.executable, executalble, *args]
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
        #logger.error(f"[Error] Failed to start {name}: {e}")
        return None

def get_or_create_path(relative_path):
    base_path = get_main_based_directory()
    full_path = base_path / relative_path 
    # ディレクトリが存在しなければ作成
    full_path.parent.mkdir(parents=True, exist_ok=True)
    return full_path

def _resolve_app_path( relative_path: str, base_dir: Path ) -> Path:
    path = base_dir / relative_path
    if path.suffix == "" or str(relative_path).endswith(("/", "\\")):
        path.mkdir(parents=True, exist_ok=True)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
    return path

def data_path(relative_path: str) -> Path:
    dirs = PlatformDirs(appname=None)
    base_dir = Path(dirs.user_data_dir) / APP_NAME
    return normalize_path(_resolve_app_path(relative_path, base_dir))

def config_path(relative_path: str) -> Path:
    dirs = PlatformDirs(appname=None)
    base_dir = Path(dirs.user_config_dir) / APP_NAME
    return normalize_path(_resolve_app_path(relative_path, base_dir))

def list_files(directory: str, extension: str) -> List[Path]:
    ext = extension.lower() if extension.startswith('.') else f".{extension.lower()}"
    return [
        normalize_path(f) for f in Path(directory).iterdir()
        if f.is_file() and f.suffix.lower() == ext
    ]