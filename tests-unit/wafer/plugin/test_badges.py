from wafer.plugin.badges import ExtensionBadge, resolve_badge, badge_sort_key, KNOWN_EXTENSIONS


class TestResolveBadge:
    def test_preferred(self):
        assert resolve_badge("image") == ExtensionBadge.PREFERRED
        assert resolve_badge("video") == ExtensionBadge.PREFERRED
        assert resolve_badge("animated") == ExtensionBadge.PREFERRED

    def test_heavy(self):
        assert resolve_badge("ai_tagger") == ExtensionBadge.HEAVY
        assert resolve_badge("florence") == ExtensionBadge.HEAVY

    def test_normal(self):
        assert resolve_badge("exiftool") is None
        assert resolve_badge("ffmpeg") is None
        assert resolve_badge("text_generation") is None
        assert resolve_badge("additional_filters") is None
        assert resolve_badge("additional_layout") is None

    def test_external(self):
        assert resolve_badge("some_unknown_ext") == ExtensionBadge.EXTERNAL
        assert resolve_badge("my_custom_plugin") == ExtensionBadge.EXTERNAL


class TestBadgeSortKey:
    def test_ordering(self):
        assert badge_sort_key("image") < badge_sort_key("exiftool")
        assert badge_sort_key("exiftool") < badge_sort_key("ai_tagger")
        assert badge_sort_key("ai_tagger") < badge_sort_key("unknown_ext")

    def test_preferred_is_first(self):
        assert badge_sort_key("image") == 0

    def test_normal_is_second(self):
        assert badge_sort_key("exiftool") == 1

    def test_heavy_is_third(self):
        assert badge_sort_key("florence") == 2

    def test_external_is_last(self):
        assert badge_sort_key("random_plugin") == 3

    def test_sort_stability(self):
        folders = ["florence", "image", "exiftool", "unknown", "ai_tagger", "video", "ffmpeg"]
        sorted_folders = sorted(folders, key=lambda f: (badge_sort_key(f), f))
        expected = ["image", "video", "exiftool", "ffmpeg", "ai_tagger", "florence", "unknown"]
        assert sorted_folders == expected


class TestKnownExtensions:
    def test_all_known_entries_present(self):
        expected = {"image", "video", "animated", "exiftool", "ffmpeg", "text_generation",
                    "additional_filters", "additional_layout", "ai_tagger", "florence"}
        assert set(KNOWN_EXTENSIONS.keys()) == expected
