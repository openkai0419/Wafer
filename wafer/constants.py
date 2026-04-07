import os as _os

DEFAULT_DB_NAME = "default"
DEFAULT_SESSION_NAME = "Wafer"
APP_DATA_DIR_NAME = "Wafer"
APP_NAME = "Wafer"
APP_ID = "opk.file.wafer"
VIRTUAL_PATH_SEPARATOR = "::"

DEV_MODE = _os.environ.get("WAFER_DEV") == "1"
