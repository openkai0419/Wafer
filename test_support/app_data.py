import tempfile
from contextlib import contextmanager
from pathlib import Path

from platformdirs import PlatformDirs

import wafer.core.common.paths as paths
from wafer.constants import APP_DATA_DIR_NAME

REAL_APP_DATA_DIR = Path(PlatformDirs(appname=None).user_data_dir) / APP_DATA_DIR_NAME

_isolated_root = tempfile.TemporaryDirectory(prefix="wafer-test-", ignore_cleanup_errors=True)


class IsolatedPlatformDirs:
    def __init__(self, appname=None):
        self.user_data_dir = _isolated_root.name
        self.user_config_dir = _isolated_root.name


def isolate_app_data():
    paths.PlatformDirs = IsolatedPlatformDirs


@contextmanager
def real_app_data():
    isolated = paths.PlatformDirs
    paths.PlatformDirs = PlatformDirs
    try:
        yield
    finally:
        paths.PlatformDirs = isolated
