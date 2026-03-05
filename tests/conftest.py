import sys

from afterimages.plugin.loader import load_plugins, PluginLoader

_pre_load_modules = set(sys.modules.keys())
load_plugins(skip_install=True)
PluginLoader.register_extension_commands()

for mod_name in list(sys.modules.keys()):
    if mod_name not in _pre_load_modules and mod_name.split('.')[0] == 'numpy':
        del sys.modules[mod_name]
