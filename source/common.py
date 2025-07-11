import os
import sys
import subprocess
from pathlib import Path
from platformdirs import PlatformDirs
from natsort import natsorted, ns
from typing import List, Tuple, Optional, TypeVar

from PySide6 import QtGui
#from .profiling import logger
from .constants import APP_FILE_NAME, APP_NAME

# Supported image extensions
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp")

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

def split_last(lst: List):
    return (lst[:-1], lst[-1]) if lst else ([], None)

def is_dark_theme():
    palette = QtGui.QGuiApplication.palette()
    bg_color = palette.color(QtGui.QPalette.Window)
    # 明度を計算
    return bg_color.value() < 128

# paths
def get_data_db(name):
    return data_path(f"data/{name}.db")

def get_setting_db(name):
    return data_path(f"dirs/{name}.db")

def get_data_file_names():
    return [get_name_without_ext(a) for a in list_files(data_path(f"data/"), ".db")]

def get_setting_file_names():
    return [get_name_without_ext(a) for a in list_files(data_path(f"dirs/"), ".db")]

def get_resource_path() -> Path:
    return get_main_based_directory() / "_resources"

def get_name_without_ext(path):
    return os.path.splitext(os.path.basename(path))[0]

def new_main(*args):
    if getattr(sys, 'frozen', False):
        # exe
        main_path = sys.executable
        cmd = [main_path] + list(args)
    else:
        # python
        main_path = os.path.abspath(sys.argv[0])
        cmd = [sys.executable, main_path] + list(args)
    print(main_path, cmd)
    env = os.environ.copy()
    subprocess.Popen(cmd, env=env)

def get_main_based_directory() -> Path:
    if getattr(sys, 'frozen', False):
        # Running from PyInstaller bundle
        return Path(sys.executable).resolve().parent
    else:
        # Normal script execution (main.py)
        main_module = sys.modules.get('__main__')
        if hasattr(main_module, '__file__'):
            return Path(main_module.__file__).resolve().parent
        else:
            return Path.cwd()  # interactive mode etc

# settingdirs
def _resolve_app_path( relative_path: str, base_dir: Path ) -> Path:
    path = base_dir / relative_path
    if path.suffix == "" or str(relative_path).endswith(("/", "\\")):
        path.mkdir(parents=True, exist_ok=True)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
    return path

def data_path(relative_path: str) -> Path:
    dirs = PlatformDirs(appname=None)
    base_dir = Path(dirs.user_data_dir) / APP_FILE_NAME
    return normalize_path(_resolve_app_path(relative_path, base_dir))

def config_path(relative_path: str) -> Path:
    dirs = PlatformDirs(appname=None)
    base_dir = Path(dirs.user_config_dir) / APP_FILE_NAME
    return normalize_path(_resolve_app_path(relative_path, base_dir))

def list_files(directory: str, extension: str) -> List[Path]:
    ext = extension.lower() if extension.startswith('.') else f".{extension.lower()}"
    return [
        normalize_path(f) for f in Path(directory).iterdir()
        if f.is_file() and f.suffix.lower() == ext
    ]