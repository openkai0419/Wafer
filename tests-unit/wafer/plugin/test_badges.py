from wafer.plugin.badges import ExtensionBadge, resolve_badge, badge_sort_key, KNOWN_EXTENSIONS


class TestResolveBadge:
    def test_preferred(self):
        assert resolve_badge("image") == ExtensionBadge.PREFERRED
        assert resolve_badge("video") == ExtensionBadge.PREFERRED
        assert resolve_badge("animated") == ExtensionBadge.PREFERRED

    def test_heavy(self):
        assert resolve_badge("wd14") == ExtensionBadge.HEAVY
        assert resolve_badge("florence") == ExtensionBadge.HEAVY

    def test_normal(self):
        assert resolve_badge("exiftool") is None
        assert resolve_badge("ffmpeg") is None
        assert resolve_badge("zip") is None
        assert resolve_badge("text_generation") is None
        assert resolve_badge("additional_filters") is None
        assert resolve_badge("additional_layout") is None

    def test_external(self):
        assert resolve_badge("some_unknown_ext") == ExtensionBadge.EXTERNAL
        assert resolve_badge("my_custom_plugin") == ExtensionBadge.EXTERNAL


class TestBadgeSortKey:
    def test_ordering(self):
        assert badge_sort_key("image") < badge_sort_key("exiftool")
        assert badge_sort_key("exiftool") < badge_sort_key("wd14")
        assert badge_sort_key("wd14") < badge_sort_key("unknown_ext")

    def test_preferred_is_first(self):
        assert badge_sort_key("image") == 0

    def test_normal_is_second(self):
        assert badge_sort_key("exiftool") == 1

    def test_heavy_is_third(self):
        assert badge_sort_key("florence") == 2

    def test_external_is_last(self):
        assert badge_sort_key("random_plugin") == 3

    def test_sort_stability(self):
        folders = ["florence", "image", "exiftool", "unknown", "wd14", "video", "ffmpeg", "zip"]
        sorted_folders = sorted(folders, key=lambda f: (badge_sort_key(f), f))
        expected = ["image", "video", "exiftool", "ffmpeg", "zip", "florence", "wd14", "unknown"]
        assert sorted_folders == expected


class TestKnownExtensions:
    def test_all_known_entries_present(self):
        expected = {"image", "video", "animated", "color", "exiftool", "ffmpeg", "text_generation",
                    "additional_filters", "additional_layout", "wd14", "florence", "zip"}
        assert set(KNOWN_EXTENSIONS.keys()) == expected
