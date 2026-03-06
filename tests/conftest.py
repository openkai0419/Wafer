import sys

import pytest

from wayfer.utils.logs import set_suppress_dialog
from wayfer.plugin.loader import load_plugins, PluginLoader

set_suppress_dialog(True)

_pre_load_modules = set(sys.modules.keys())
load_plugins(skip_install=True)
PluginLoader.register_extension_commands()

for mod_name in list(sys.modules.keys()):
    if mod_name not in _pre_load_modules and mod_name.split('.')[0] == 'numpy':
        del sys.modules[mod_name]


@pytest.fixture(autouse=True, scope='session')
def _cleanup_background_resources():
    yield
    try:
        from wayfer.utils.profiling import profiler
        profiler.stop()
    except Exception:
        pass
    try:
        from wayfer.app.viewer.viewer_settings import app_settings
        app_settings.close()
    except Exception:
        pass
