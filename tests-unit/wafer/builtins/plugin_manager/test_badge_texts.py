from wafer.builtins.plugin_manager.badge_texts import (
    HEAVY_MULTI_WARNING_FOOTER,
    HEAVY_MULTI_WARNING_HEADER,
    HEAVY_WARNING_TITLE,
    heavy_multi_warning_text,
    heavy_warning_title,
    parser_requirement_question_text,
    parser_requirement_text,
    parser_requirement_title,
    required_collectors_text,
)


class TestBadgeTexts:
    def test_heavy_multi_warning_text_uses_shared_parts(self):
        text = heavy_multi_warning_text(["wd14", None, "florence"])

        assert text.startswith(HEAVY_MULTI_WARNING_HEADER)
        assert "- wd14" in text
        assert "- florence" in text
        assert text.endswith(HEAVY_MULTI_WARNING_FOOTER)
        assert heavy_warning_title() == HEAVY_WARNING_TITLE

    def test_required_collectors_text(self):
        assert required_collectors_text({}) == ""
        assert required_collectors_text({"exiftool": ["PNG:Comment"]}) == "Requires: exiftool (PNG:Comment)"
        assert required_collectors_text({"exiftool": ["A", "B"], "ffmpeg": ["C"]}) == "Requires: exiftool (A, B), ffmpeg (C)"

    def test_parser_requirement_title_varies_by_availability(self):
        assert parser_requirement_title(True) == "Enable Required Collector?"
        assert parser_requirement_title(False) == "Required Collector Unavailable"

    def test_parser_requirement_text_lists_required_and_missing(self):
        text = parser_requirement_text("novelai", "db1", {"exiftool": ["PNG:Comment"]}, [])
        assert "novelai" in text and "db1" in text
        assert "- exiftool (PNG:Comment)" in text
        assert "Enable these extensions first:" not in text

        text = parser_requirement_text("novelai", "db1", {"ffmpeg": ["fmt"]}, ["ffmpeg"])
        assert "Enable these extensions first:" in text
        assert "- ffmpeg" in text

    def test_parser_requirement_question_text_adds_prompt(self):
        text = parser_requirement_question_text("novelai", "db1", {"exiftool": ["PNG:Comment"]})
        assert "Do you want to enable the collector?" in text
        assert "Enable these extensions first:" not in text
