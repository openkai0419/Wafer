import os
import sys
from pathlib import Path
from natsort import natsorted, ns
from platformdirs import PlatformDirs
from ..constants import APP_DATA_DIR_NAME


def normalize_path(p):
    try:
        path = str(Path(p).resolve(strict=False))
    except (OSError, ValueError):
        path = str(Path(p).absolute())
    return path.replace("\\", "/")


def safe_exists(p) -> bool:
    try:
        return os.path.exists(p)
    except OSError:
        return False


def safe_is_file(p) -> bool:
    try:
        return os.path.isfile(p)
    except OSError:
        return False


def safe_is_dir(p) -> bool:
    try:
        return os.path.isdir(p)
    except OSError:
        return False


def safe_getsize(p) -> int | None:
    try:
        return os.path.getsize(p)
    except OSError:
        return None


def natural_sort(files):
    return natsorted(files, alg=ns.LOCALE | ns.IGNORECASE)


def data_db_path(name):
    return resolve_data_path(f"data/{name}.db")


def setting_db_path(name):
    return resolve_data_path(f"dirs/{name}.db")


def list_data_db_names():
    return [stem(a) for a in list_files(resolve_data_path("data/"), ".db")]


def list_setting_db_names():
    return [stem(a) for a in list_files(resolve_data_path("dirs/"), ".db")]


def get_resource_path():
    p = get_app_root_dir() / "_resources"
    if not p.is_dir():
        cwd_p = Path.cwd() / "_resources"
        if cwd_p.is_dir():
            from .logs import AppLogger

            AppLogger.warning(f"_resources not found at {p}, falling back to cwd: {cwd_p}")
            return cwd_p
    return p


def stem(path):
    return os.path.splitext(os.path.basename(path))[0]


def get_app_root_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    else:
        main_module = sys.modules.get("__main__")
        if hasattr(main_module, "__file__"):
            return Path(main_module.__file__).resolve().parent
        else:
            return Path.cwd()


def _resolve_app_path(relative_path, base_dir):
    path = base_dir / relative_path
    if path.suffix == "" or str(relative_path).endswith(("/", "\\")):
        path.mkdir(parents=True, exist_ok=True)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
    return path


def resolve_data_path(relative_path):
    dirs = PlatformDirs(appname=None)
    base_dir = Path(dirs.user_data_dir) / APP_DATA_DIR_NAME
    return normalize_path(_resolve_app_path(relative_path, base_dir))


def resolve_config_path(relative_path):
    dirs = PlatformDirs(appname=None)
    base_dir = Path(dirs.user_config_dir) / APP_DATA_DIR_NAME
    return normalize_path(_resolve_app_path(relative_path, base_dir))


def list_files(directory, extension):
    ext = extension.lower() if extension.startswith(".") else f".{extension.lower()}"
    return [normalize_path(f) for f in Path(directory).iterdir() if f.is_file() and f.suffix.lower() == ext]
