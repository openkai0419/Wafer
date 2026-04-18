import inspect


def register_all(registries):
    from ..plugin.loader import _get_registry_map

    registry_map = _get_registry_map()
    for mod in _import_builtin_modules():
        for registry_key, cls in _discover_builtins(mod, registry_map):
            registry = registries.get(registry_key)
            if registry is not None:
                registry.register(cls)


def _discover_builtins(module, registry_map) -> list[tuple[str, type]]:
    found = []
    for _, obj in inspect.getmembers(module, inspect.isclass):
        if not hasattr(obj, "NAME"):
            continue
        if obj.__module__ != module.__name__:
            continue
        for base_cls, registry_key in registry_map.items():
            if issubclass(obj, base_cls) and obj is not base_cls:
                found.append((registry_key, obj))
    return found


def _import_builtin_modules():
    from . import devlog, filters, imageloader, layouts, rename_sources, sorts, viewer
    from .batch_renamer import (
        engine as _br_engine,
        overlay as _br_overlay,
        popup as _br_popup,
        table as _br_table,
        widget as _br_widget,
    )
    from .commands import (
        app as _cmd_app,
        database_commands,
        debug_commands,
        file_commands,
        file_viewer,
        foldertree_commands,
        grid_commands,
        image_view,
        menu,
        panel_commands,
        query_commands,
        profile_commands,
        setting_commands,
        tray,
        window_commands,
    )
    from .database_manager import data_tab, widget as _dm_widget
    from .plugin_manager import (
        collectors_tab,
        extensions_tab,
        viewers_tab,
        widget as _pm_widget,
    )

    return [
        devlog,
        filters,
        imageloader,
        layouts,
        rename_sources,
        sorts,
        viewer,
        _br_engine,
        _br_overlay,
        _br_popup,
        _br_table,
        _br_widget,
        _cmd_app,
        database_commands,
        debug_commands,
        file_commands,
        file_viewer,
        foldertree_commands,
        grid_commands,
        image_view,
        menu,
        panel_commands,
        query_commands,
        profile_commands,
        setting_commands,
        tray,
        window_commands,
        _dm_widget,
        collectors_tab,
        data_tab,
        extensions_tab,
        viewers_tab,
        _pm_widget,
    ]
