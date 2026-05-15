from wafer.plugin.registry import FilePluginRegistry, BasePlugin
from wafer.plugin.grid.handler import grid_resolver, WIDGET, IMAGE
from wafer.plugin.viewer.handler import viewer_resolver
from wafer.plugin.collector.handler import collector_resolver


class TestGridPriorityResolution:
    def test_animated_resolves_before_image_for_gif(self):
        chain = grid_resolver.resolve_merged_chain("test.gif")
        names = [p.NAME for p, kind in chain]
        if "animated" in names and "image" in names:
            assert names.index("animated") < names.index("image")

    def test_animated_resolves_before_image_for_webp(self):
        chain = grid_resolver.resolve_merged_chain("test.webp")
        names = [p.NAME for p, kind in chain]
        if "animated" in names and "image" in names:
            assert names.index("animated") < names.index("image")

    def test_image_resolves_before_system_thumbnail(self):
        chain = grid_resolver.resolve_merged_chain("test.jpg")
        names = [p.NAME for p, kind in chain]
        assert names.index("image") < names.index("system_thumbnail")

    def test_system_thumbnail_always_last(self):
        for ext in [".jpg", ".png", ".gif", ".webp", ".mp4", ".xyz"]:
            chain = grid_resolver.resolve_merged_chain(f"test{ext}")
            if chain:
                assert chain[-1][0].NAME == "system_thumbnail"

    def test_video_resolves_for_mp4(self):
        chain = grid_resolver.resolve_merged_chain("test.mp4")
        names = [p.NAME for p, kind in chain]
        assert "video" in names

    def test_video_does_not_resolve_for_jpg(self):
        chain = grid_resolver.resolve_merged_chain("test.jpg")
        names = [p.NAME for p, kind in chain]
        assert "video" not in names

    def test_highest_priority_wins_in_resolve(self):
        resolved = grid_resolver.resolve("test.jpg")
        chain = grid_resolver.resolve_merged_chain("test.jpg")
        widget_chain = [p for p, kind in chain if kind == WIDGET]
        if widget_chain:
            assert resolved == widget_chain[0]

    def test_unknown_extension_only_system_thumbnail(self):
        chain = grid_resolver.resolve_merged_chain("test.xyz_unknown_ext")
        non_fallback = [p for p, kind in chain if p.EXTENSIONS != ()]
        assert len(non_fallback) == 0


class TestViewerPriorityResolution:
    def test_animated_viewer_before_image_for_gif(self):
        chain = viewer_resolver.registry.resolve_chain("test.gif")
        names = [p.NAME for p in chain]
        if "animated" in names and "image" in names:
            assert names.index("animated") < names.index("image")

    def test_image_fallback_viewer_for_jpg(self):
        chain = viewer_resolver.registry.resolve_chain("test.jpg")
        names = [p.NAME for p in chain]
        assert names == ["image"]

    def test_video_viewer_for_mp4(self):
        chain = viewer_resolver.registry.resolve_chain("test.mp4")
        names = [p.NAME for p in chain]
        assert "video" in names


class TestCollectorResolution:
    def test_exif_matches_image_extensions(self):
        for ext in [".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif"]:
            collectors = collector_resolver.collectors_for_path(f"test{ext}")
            assert "exiftool" in collectors

    def test_exif_does_not_match_text(self):
        collectors = collector_resolver.collectors_for_path("readme.txt")
        assert "exiftool" not in collectors

    def test_exif_does_not_match_unknown(self):
        collectors = collector_resolver.collectors_for_path("data.xyz_no_plugin")
        assert "exiftool" not in collectors


class TestRegistryPriorityOrdering:
    def test_custom_registry_ordering(self):
        registry = FilePluginRegistry()

        class Low(BasePlugin):
            NAME = "_pr_low"
            EXTENSIONS = (".test",)
            PRIORITY = 10

        class Mid(BasePlugin):
            NAME = "_pr_mid"
            EXTENSIONS = (".test",)
            PRIORITY = 50

        class High(BasePlugin):
            NAME = "_pr_high"
            EXTENSIONS = (".test",)
            PRIORITY = 100

        class Fallback(BasePlugin):
            NAME = "_pr_fallback"
            EXTENSIONS = ()
            PRIORITY = -100

        registry.register(Low)
        registry.register(High)
        registry.register(Mid)
        registry.register(Fallback)

        chain = registry.resolve_chain("file.test")
        names = [p.NAME for p in chain]
        assert names.index("_pr_high") < names.index("_pr_mid") < names.index("_pr_low") < names.index("_pr_fallback")

    def test_fallback_matches_any_extension(self):
        registry = FilePluginRegistry()

        class Fallback(BasePlugin):
            NAME = "_fb"
            EXTENSIONS = ()
            PRIORITY = -100

        registry.register(Fallback)
        assert registry.resolve("any.xyz") == Fallback
        assert registry.resolve("file.abc") == Fallback

    def test_specific_extension_wins_over_fallback(self):
        registry = FilePluginRegistry()

        class Specific(BasePlugin):
            NAME = "_specific"
            EXTENSIONS = (".png",)
            PRIORITY = 50

        class Fallback(BasePlugin):
            NAME = "_fb"
            EXTENSIONS = ()
            PRIORITY = -100

        registry.register(Fallback)
        registry.register(Specific)
        assert registry.resolve("image.png") == Specific

    def test_name_overwrite_replaces_old(self):
        registry = FilePluginRegistry()

        class V1(BasePlugin):
            NAME = "_versioned"
            EXTENSIONS = (".v",)
            PRIORITY = 10

        class V2(BasePlugin):
            NAME = "_versioned"
            EXTENSIONS = (".v",)
            PRIORITY = 100

        registry.register(V1)
        registry.register(V2)
        all_plugins = registry.list_all()
        versioned = [p for p in all_plugins if p.NAME == "_versioned"]
        assert len(versioned) == 1
        assert versioned[0].PRIORITY == 100
