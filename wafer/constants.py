import os as _os

DEFAULT_DB_NAME = "default"
APP_DATA_DIR_NAME = "Wafer"
APP_NAME = "Wafer"
APP_ID = "opk.file.wafer"
TRAY_LOCK_NAME = f"{APP_DATA_DIR_NAME}_tray"
VIRTUAL_PATH_SEPARATOR = "::"

DEV_MODE = _os.environ.get("WAFER_DEV") == "1"

_MEMWATCH = _os.environ.get("WAFER_MEMWATCH", "").lower()
MEMWATCH = _MEMWATCH in ("1", "on", "trace")
MEMWATCH_TRACE = _MEMWATCH == "trace"
