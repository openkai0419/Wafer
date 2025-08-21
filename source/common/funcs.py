import os
import sys
import datetime
import math
from pathlib import Path
from natsort import natsorted, ns
from platformdirs import PlatformDirs
from PySide6 import QtGui
from ..constants import APP_FILE_NAME
IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp')

def normalize_path(p):
    try:
        path = str(Path(p).resolve(strict=False))
    except Exception:
        path = str(Path(p).absolute())
    return path.replace('\\', '/')

def uipx(px, base_dpi=96):
    screen = QtGui.QGuiApplication.primaryScreen()
    if screen is None:
        return px
    current_dpi = screen.logicalDotsPerInch()
    scale = current_dpi / base_dpi
    return int(px * scale)

def native_sort(files):
    return natsorted(files, alg=ns.LOCALE | ns.IGNORECASE)

def split_last(lst):
    return (lst[:-1], lst[-1]) if lst else ([], None)

def is_dark_theme():
    palette = QtGui.QGuiApplication.palette()
    bg_color = palette.color(QtGui.QPalette.Window)
    return bg_color.value() < 128



def get_data_db(name):
    return data_path(f'data/{name}.db')

def get_setting_db(name):
    return data_path(f'dirs/{name}.db')

def get_data_file_names():
    return [get_name_without_ext(a) for a in list_files(data_path(f'data/'), '.db')]

def get_setting_file_names():
    return [get_name_without_ext(a) for a in list_files(data_path(f'dirs/'), '.db')]

def get_resource_path():
    return get_main_based_directory() / '_resources'

def get_name_without_ext(path):
    return os.path.splitext(os.path.basename(path))[0]

def get_main_based_directory():
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    else:
        main_module = sys.modules.get('__main__')
        if hasattr(main_module, '__file__'):
            return Path(main_module.__file__).resolve().parent
        else:
            return Path.cwd()

def _resolve_app_path(relative_path, base_dir):
    path = base_dir / relative_path
    if path.suffix == '' or str(relative_path).endswith(('/', '\\')):
        path.mkdir(parents=True, exist_ok=True)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
    return path

def data_path(relative_path):
    dirs = PlatformDirs(appname=None)
    base_dir = Path(dirs.user_data_dir) / APP_FILE_NAME
    return normalize_path(_resolve_app_path(relative_path, base_dir))

def config_path(relative_path):
    dirs = PlatformDirs(appname=None)
    base_dir = Path(dirs.user_config_dir) / APP_FILE_NAME
    return normalize_path(_resolve_app_path(relative_path, base_dir))

def list_files(directory, extension):
    ext = extension.lower() if extension.startswith('.') else f'.{extension.lower()}'
    return [normalize_path(f) for f in Path(directory).iterdir() if f.is_file() and f.suffix.lower() == ext]




def human_time(ts: float) -> str:
    dt = datetime.datetime.fromtimestamp(ts)
    return dt.strftime("%Y-%m-%d %H:%M:%S")

def human_aspect(ratio: float, max_denominator: int = 100) -> str:
    if ratio <= 0:
        return "N/A"
    frac = math.floor(ratio * max_denominator + 0.5)
    # 分母を決定
    for den in range(1, max_denominator + 1):
        num = round(ratio * den)
        if abs(num / den - ratio) < 1e-6:
            g = math.gcd(num, den)
            return f"{num // g}:{den // g}"
    return f"{ratio:.2f}:1"

def human_aspect_string(ratio: float):
    return human_aspect(ratio)

def human_size(size: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    s = float(size)
    for unit in units:
        if s < 1024:
            return f"{s:.1f} {unit}"
        s /= 1024
    return f"{s:.1f} EB"

def human_size_string(size: int) -> str:
    return f"{human_size(size)} ({size:,} bytes)"