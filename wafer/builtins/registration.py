import importlib
import inspect
import os
import sys


def register_all(registries):
    from ..plugin.loader import _get_registry_map
    registry_map = _get_registry_map()
    builtins_dir = os.path.dirname(os.path.abspath(__file__))
    for mod in _import_builtin_modules(builtins_dir):
        for registry_key, cls in _discover_builtins(mod, registry_map):
            registry = registries.get(registry_key)
            if registry is not None:
                registry.register(cls)


def _discover_builtins(module, registry_map) -> list[tuple[str, type]]:
    found = []
    for _, obj in inspect.getmembers(module, inspect.isclass):
        if not hasattr(obj, 'NAME'):
            continue
        if obj.__module__ != module.__name__:
            continue
        for base_cls, registry_key in registry_map.items():
            if issubclass(obj, base_cls) and obj is not base_cls:
                found.append((registry_key, obj))
    return found


def _import_builtin_modules(builtins_dir: str):
    pkg_name = __package__
    modules = []
    for filename in sorted(os.listdir(builtins_dir)):
        if filename.startswith('_') or filename == 'registration.py':
            continue
        filepath = os.path.join(builtins_dir, filename)
        if filename.endswith('.py'):
            mod_name = f'{pkg_name}.{filename[:-3]}'
            mod = _safe_import(mod_name)
            if mod:
                modules.append(mod)
        elif os.path.isdir(filepath) and os.path.isfile(os.path.join(filepath, '__init__.py')):
            sub_pkg = f'{pkg_name}.{filename}'
            _safe_import(sub_pkg)
            for sub in sorted(os.listdir(filepath)):
                if sub.startswith('_') or not sub.endswith('.py'):
                    continue
                mod_name = f'{sub_pkg}.{sub[:-3]}'
                mod = _safe_import(mod_name)
                if mod:
                    modules.append(mod)
    return modules


def _safe_import(mod_name: str):
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    try:
        return importlib.import_module(mod_name)
    except Exception:
        return None
