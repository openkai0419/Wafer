import os
from pathlib import Path
from platformdirs import PlatformDirs
from ...constants import APP_DATA_DIR_NAME
from .profile import PROFILE_PREFIX, TOOLS_PROFILE, current_profile, same_profile

DEBUG_PROFILES_DIR_NAME = f"{APP_DATA_DIR_NAME}-debug"
STAGING_SUFFIX = ".wafer-partial"


def is_staging_file(path) -> bool:
    return str(path).lower().endswith(STAGING_SUFFIX)


def normalize_path(p):
    path = os.path.abspath(p).replace("\\", "/")
    if path[1:2] == ":":
        return path[0].upper() + path[1:]
    return path


def parent_folder(path: str) -> str:
    return os.path.dirname(path).replace("\\", "/")


def child_prefix(folder: str) -> str:
    return folder if folder.endswith("/") else f"{folder}/"


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


def containing_dir(path) -> str:
    ap = os.path.abspath(str(path))
    return ap if safe_is_dir(ap) else os.path.dirname(ap)


def safe_getsize(p) -> int | None:
    try:
        return os.path.getsize(p)
    except OSError:
        return None


def data_db_path(name):
    return resolve_data_path(f"data/{name}.db")


def setting_db_path(name):
    return resolve_data_path(f"dirs/{name}.db")


def db_name_from_path(dbpath):
    if not dbpath:
        return ""
    return stem(dbpath)


def list_data_db_names():
    return [stem(a) for a in list_files(resolve_data_path("data/"), ".db")]


def list_setting_db_names():
    return [stem(a) for a in list_files(resolve_data_path("dirs/"), ".db")]


def get_resource_path():
    return get_app_root_dir() / "_resources"


def stem(path):
    return os.path.splitext(os.path.basename(path))[0]


def get_app_root_dir():
    return Path(__file__).resolve().parent.parent.parent.parent


def get_plugin_dir() -> str:
    return os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "extensions"))


def get_launcher_path():
    launcher = get_app_root_dir() / f"{APP_DATA_DIR_NAME}.exe"
    return launcher if launcher.is_file() else None


def _resolve_app_path(relative_path, base_dir):
    path = base_dir / relative_path
    if path.suffix == "" or str(relative_path).endswith(("/", "\\")):
        path.mkdir(parents=True, exist_ok=True)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
    return path


def profile_data_root(profile: str | None) -> Path:
    base = Path(PlatformDirs(appname=None).user_data_dir)
    return base / APP_DATA_DIR_NAME if profile is None else base / DEBUG_PROFILES_DIR_NAME / profile


def profile_config_root(profile: str | None) -> Path:
    base = Path(PlatformDirs(appname=None).user_config_dir)
    return base / APP_DATA_DIR_NAME if profile is None else base / DEBUG_PROFILES_DIR_NAME / profile


def debug_profiles_dir() -> Path:
    return Path(PlatformDirs(appname=None).user_data_dir) / DEBUG_PROFILES_DIR_NAME


def sample_root() -> Path:
    override = os.environ.get("WAFER_DEBUG_SAMPLE_ROOT")
    if override:
        return Path(override)
    return Path(os.path.realpath(get_app_root_dir() / ".sample"))


def scratch_root(profile: str) -> Path:
    return profile_data_root(profile) / "scratch"


def _guard_key(path) -> str:
    return os.path.normcase(normalize_path(os.path.realpath(path))).replace("\\", "/")


def _is_within(path: str, root: Path) -> bool:
    target = _guard_key(path)
    base = _guard_key(root)
    return target == base or target.startswith(child_prefix(base))


def _is_in_any_profile_scratch(path: str) -> bool:
    target = Path(_guard_key(path))
    base = Path(_guard_key(debug_profiles_dir()))
    if not target.is_relative_to(base):
        return False
    parts = target.relative_to(base).parts
    return len(parts) >= 2 and parts[0].startswith(PROFILE_PREFIX) and parts[1] == os.path.normcase(scratch_root(parts[0]).name)


def profile_allows_folder(path: str) -> bool:
    profile = current_profile()
    if profile is None:
        return True
    if same_profile(profile, TOOLS_PROFILE) and _is_in_any_profile_scratch(path):
        return True
    return _is_within(path, sample_root()) or _is_within(path, scratch_root(profile))


def profile_allows_file_write(path: str) -> bool:
    profile = current_profile()
    if profile is None:
        return True
    return _is_within(path, scratch_root(profile))


def resolve_data_path(relative_path):
    base_dir = profile_data_root(current_profile())
    return normalize_path(_resolve_app_path(relative_path, base_dir))


def resolve_cache_path(relative_path):
    return resolve_data_path(f".cache/{relative_path}")


def resolve_temp_path(relative_path):
    return resolve_data_path(f".temp/{relative_path}")


def resolve_config_path(relative_path):
    base_dir = profile_config_root(current_profile())
    return normalize_path(_resolve_app_path(relative_path, base_dir))


def list_files(directory, extension):
    ext = extension.lower() if extension.startswith(".") else f".{extension.lower()}"
    return [normalize_path(f) for f in Path(directory).iterdir() if f.is_file() and f.suffix.lower() == ext]
