import os
import pytest
from wafer.builtins.plugin_manager.extensions_tab import _ExtensionCard


class TestExtensionCardReadme:
    def test_no_readme_hides_toggle(self, qtbot, tmp_path):
        folder = tmp_path / "ext_no_readme"
        folder.mkdir()
        card = _ExtensionCard("ext_no_readme", str(folder))
        qtbot.addWidget(card)
        assert card._readme_toggle is None
        assert card._readme_browser is None

    def test_readme_present_shows_toggle(self, qtbot, tmp_path):
        folder = tmp_path / "ext_with_readme"
        folder.mkdir()
        (folder / "README.md").write_text("# Hello\nWorld", encoding="utf-8")
        card = _ExtensionCard("ext_with_readme", str(folder))
        qtbot.addWidget(card)
        assert card._readme_toggle is not None
        assert card._readme_browser is not None
        assert card._readme_browser.isHidden()
        assert "\u25b6" in card._readme_toggle.text()

    def test_toggle_expands_and_collapses(self, qtbot, tmp_path):
        folder = tmp_path / "ext_toggle"
        folder.mkdir()
        (folder / "README.md").write_text("# Test\nContent here", encoding="utf-8")
        card = _ExtensionCard("ext_toggle", str(folder))
        qtbot.addWidget(card)
        card.show()

        card._toggle_readme()
        assert not card._readme_browser.isHidden()
        assert "\u25bc" in card._readme_toggle.text()
        assert card._readme_loaded

        card._toggle_readme()
        assert card._readme_browser.isHidden()
        assert "\u25b6" in card._readme_toggle.text()

    def test_readme_content_loaded_once(self, qtbot, tmp_path):
        folder = tmp_path / "ext_lazy"
        folder.mkdir()
        readme = folder / "README.md"
        readme.write_text("# First", encoding="utf-8")
        card = _ExtensionCard("ext_lazy", str(folder))
        qtbot.addWidget(card)

        assert not card._readme_loaded
        card._toggle_readme()
        assert card._readme_loaded
        first_html = card._readme_browser.rendered_html()

        readme.write_text("# Changed", encoding="utf-8")
        card._toggle_readme()
        card._toggle_readme()
        assert card._readme_browser.rendered_html() == first_html

    def test_readme_broken_file_shows_fallback(self, qtbot, tmp_path, monkeypatch):
        folder = tmp_path / "ext_broken"
        folder.mkdir()
        (folder / "README.md").write_text("content", encoding="utf-8")
        card = _ExtensionCard("ext_broken", str(folder))
        qtbot.addWidget(card)
        card.show()

        card._readme_path = str(tmp_path / "nonexistent.md")
        card._toggle_readme()
        assert not card._readme_browser.isHidden()
        assert "Failed to load" in card._readme_browser.rendered_html()

    def test_readme_markdown_rendering(self, qtbot, tmp_path):
        folder = tmp_path / "ext_md"
        folder.mkdir()
        md = "# Heading\n\n**bold** and *italic*\n\n- item1\n- item2\n"
        (folder / "README.md").write_text(md, encoding="utf-8")
        card = _ExtensionCard("ext_md", str(folder))
        qtbot.addWidget(card)

        card._toggle_readme()
        html = card._readme_browser.rendered_html()
        assert "Heading" in html
        assert "item1" in html
