def register_all(registries):
    from .grid import SystemThumbnailPlugin
    from .viewer import DefaultViewerPlugin
    from .filters import TextFilter, DirectoryFilter
    from .sorts import (
        NaturalPathSort, NaturalNameSort,
        ModifiedSort, CreatedSort, SizeSort, CollectedSort,
        RandomSort,
    )
    from .layouts import JustifiedLayout, MasonryLayout
    from .rename_sources import (
        NameSource, FixedSource, SequentialSource,
        MetaSource, DateSource, RandomSource, ExtSource,
    )
    from .commands.tray import TrayMenu
    from .commands.app import PluginManagerCommands, DatabaseManagerCommands
    from .devlog import DevLogPanelPlugin
    from .database_manager.widget import DatabaseManagerPlugin
    from .plugin_manager.widget import PluginManagerPlugin
    from .batch_renamer.widget import BatchRenamerPlugin

    registries['grid'].register(SystemThumbnailPlugin)
    registries['viewer'].register(DefaultViewerPlugin)

    for cls in [TextFilter, DirectoryFilter]:
        registries['filter'].register(cls)
    for cls in [NaturalPathSort, NaturalNameSort,
                ModifiedSort, CreatedSort, SizeSort, CollectedSort,
                RandomSort]:
        registries['sort'].register(cls)
    for cls in [JustifiedLayout, MasonryLayout]:
        registries['layout'].register(cls)
    for cls in [NameSource, FixedSource, SequentialSource,
                MetaSource, DateSource, RandomSource, ExtSource]:
        registries['rename_source'].register(cls)
    for cls in [TrayMenu, PluginManagerCommands, DatabaseManagerCommands]:
        registries['command'].register(cls)
    for cls in [DevLogPanelPlugin, DatabaseManagerPlugin, PluginManagerPlugin,
                 BatchRenamerPlugin]:
        registries['panel'].register(cls)
