def register_all(registries):
    from .grid import SystemThumbnailPlugin
    from .viewer import DefaultViewerPlugin
    from .filters import TextFilter, DirectoryFilter
    from .sorts import (
        NaturalPathSort, NaturalNameSort,
        ModifiedSort, CreatedSort, SizeSort, CollectedSort,
        RandomSort,
    )

    registries['grid'].register(SystemThumbnailPlugin)
    registries['viewer'].register(DefaultViewerPlugin)

    for cls in [TextFilter, DirectoryFilter]:
        registries['filter'].register(cls)
    for cls in [NaturalPathSort, NaturalNameSort,
                ModifiedSort, CreatedSort, SizeSort, CollectedSort,
                RandomSort]:
        registries['sort'].register(cls)
