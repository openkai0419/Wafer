from wafer.builtins.plugin_manager.badge_texts import (
    BADGE_TOOLTIPS,
    HEAVY_BADGE_TOOLTIP,
    HEAVY_INSTALL_TITLE,
    HEAVY_MULTI_WARNING_FOOTER,
    HEAVY_MULTI_WARNING_HEADER,
    HEAVY_WARNING_TITLE,
    badge_tooltip_text,
    heavy_install_confirm_text,
    heavy_install_title,
    heavy_multi_warning_text,
    heavy_warning_title,
)
from wafer.plugin.badges import ExtensionBadge


class TestBadgeTexts:
    def test_badge_tooltips_are_centralized(self):
        assert BADGE_TOOLTIPS[ExtensionBadge.HEAVY] == HEAVY_BADGE_TOOLTIP
        assert badge_tooltip_text(ExtensionBadge.HEAVY) == HEAVY_BADGE_TOOLTIP

    def test_heavy_install_text_reuses_tooltip(self):
        assert heavy_install_title() == HEAVY_INSTALL_TITLE
        assert heavy_install_confirm_text() == f"{HEAVY_BADGE_TOOLTIP}\nContinue?"

    def test_heavy_multi_warning_text_uses_shared_parts(self):
        text = heavy_multi_warning_text(["wd14", None, "florence"])

        assert text.startswith(HEAVY_MULTI_WARNING_HEADER)
        assert "- wd14" in text
        assert "- florence" in text
        assert text.endswith(HEAVY_MULTI_WARNING_FOOTER)
        assert heavy_warning_title() == HEAVY_WARNING_TITLE