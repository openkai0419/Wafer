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
    from . import log_panel, filters, imageloader, layouts, rename_sources, sorts, viewer
    from .batch_renamer import (
        engine as _br_engine,
        overlay as _br_overlay,
        popup as _br_popup,
        table as _br_table,
        widget as _br_widget,
    )
    from .commands import (
        tools as _cmd_tools,
        database as _cmd_database,
        debug as _cmd_debug,
        file as _cmd_file,
        content_viewer as _cmd_content_viewer,
        foldertree as _cmd_foldertree,
        grid as _cmd_grid,
        image_viewer as _cmd_image_viewer,
        menu,
        panel as _cmd_panel,
        query as _cmd_query,
        profile as _cmd_profile,
        setting as _cmd_setting,
        tray,
        window as _cmd_window,
    )
    from .database_manager import data_tab, widget as _dm_widget
    from .plugin_manager import (
        collectors_tab,
        extensions_tab,
        viewers_tab,
        widget as _pm_widget,
    )

    return [
        log_panel,
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
        _cmd_tools,
        _cmd_database,
        _cmd_debug,
        _cmd_file,
        _cmd_content_viewer,
        _cmd_foldertree,
        _cmd_grid,
        _cmd_image_viewer,
        menu,
        _cmd_panel,
        _cmd_query,
        _cmd_profile,
        _cmd_setting,
        tray,
        _cmd_window,
        _dm_widget,
        collectors_tab,
        data_tab,
        extensions_tab,
        viewers_tab,
        _pm_widget,
    ]
