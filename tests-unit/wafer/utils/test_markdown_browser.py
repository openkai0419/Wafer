import pytest
from pathlib import Path
from PySide6.QtWebEngineCore import QWebEngineSettings
from wafer.utils.markdown_browser import (
    MarkdownBrowser,
    _ExternalLinkPage,
    _preprocess_html_blocks,
)


class TestPreprocessHtmlBlocks:
    def test_adds_markdown_attr_to_div(self):
        result = _preprocess_html_blocks('<div align="center">\n\n# Hello\n\n</div>')
        assert 'markdown="1"' in result
        assert 'align="center"' in result

    def test_adds_markdown_attr_to_details(self):
        result = _preprocess_html_blocks("<details>\n<summary>Click</summary>\n</details>")
        assert '<details markdown="1">' in result
        assert '<summary markdown="1">' in result

    def test_skips_if_already_present(self):
        src = '<div markdown="1">\ntext\n</div>'
        assert _preprocess_html_blocks(src) == src

    def test_preserves_plain_markdown(self):
        src = "# Hello\n\n**bold**\n"
        assert _preprocess_html_blocks(src) == src


class TestMarkdownBrowser:
    def test_set_markdown_renders_html(self, qtbot):
        browser = MarkdownBrowser()
        qtbot.addWidget(browser)
        browser.set_markdown("# Hello\n\nWorld")
        assert "<h1>Hello</h1>" in browser.rendered_html()
        assert "World" in browser.rendered_html()
        assert "# Hello" in browser.source_markdown()

    def test_load_file_success(self, qtbot, tmp_path):
        md = tmp_path / "test.md"
        md.write_text("# Title\n\n- item1\n- item2\n", encoding="utf-8")
        browser = MarkdownBrowser()
        qtbot.addWidget(browser)
        result = browser.load_file(str(md))
        assert result is True
        assert "<h1>Title</h1>" in browser.rendered_html()
        assert "item1" in browser.rendered_html()

    def test_load_file_missing_shows_fallback(self, qtbot, tmp_path):
        browser = MarkdownBrowser()
        qtbot.addWidget(browser)
        result = browser.load_file(str(tmp_path / "missing.md"))
        assert result is False
        assert "Failed to load" in browser.rendered_html()

    def test_heading_levels(self, qtbot):
        browser = MarkdownBrowser()
        qtbot.addWidget(browser)
        browser.set_markdown("# H1\n\n## H2\n\n### H3\n")
        html = browser.rendered_html()
        assert "<h1>H1</h1>" in html
        assert "<h2>H2</h2>" in html
        assert "<h3>H3</h3>" in html

    def test_table_rendering(self, qtbot):
        md = "| A | B |\n|---|---|\n| 1 | 2 |\n"
        browser = MarkdownBrowser()
        qtbot.addWidget(browser)
        browser.set_markdown(md)
        html = browser.rendered_html()
        assert "<table>" in html
        assert "<th>A</th>" in html
        assert "<td>1</td>" in html

    def test_fenced_code_block(self, qtbot):
        md = "```python\nprint('hello')\n```\n"
        browser = MarkdownBrowser()
        qtbot.addWidget(browser)
        browser.set_markdown(md)
        assert "<code" in browser.rendered_html()
        assert "print" in browser.rendered_html()

    def test_links_handled_by_external_page(self, qtbot):
        browser = MarkdownBrowser()
        qtbot.addWidget(browser)
        assert isinstance(browser._page, _ExternalLinkPage)

    def test_md_in_html_extension(self, qtbot):
        md = '<div align="center">\n\n**bold text**\n\n</div>\n'
        browser = MarkdownBrowser()
        qtbot.addWidget(browser)
        browser.set_markdown(md)
        assert "<strong>bold text</strong>" in browser.rendered_html()

    def test_nested_list_2space_indent(self, qtbot):
        md = "- A\n  - B\n  - C\n- D\n"
        browser = MarkdownBrowser()
        qtbot.addWidget(browser)
        browser.set_markdown(md)
        html = browser.rendered_html()
        assert html.count("<ul>") >= 2

    def test_theme_change_re_renders(self, qtbot):
        browser = MarkdownBrowser()
        qtbot.addWidget(browser)
        browser.set_markdown("# Test")
        first_html = browser.rendered_html()
        browser._on_theme_changed(None)
        assert browser.rendered_html() == first_html

    def test_javascript_disabled(self, qtbot):
        browser = MarkdownBrowser()
        qtbot.addWidget(browser)
        js_enabled = browser._page.settings().testAttribute(
            QWebEngineSettings.WebAttribute.JavascriptEnabled
        )
        assert js_enabled is False

    def test_allowed_dir_set_on_first_load(self, qtbot, tmp_path):
        md = tmp_path / "test.md"
        md.write_text("# Test", encoding="utf-8")
        browser = MarkdownBrowser()
        qtbot.addWidget(browser)
        assert browser._allowed_dir is None
        browser.load_file(str(md))
        assert browser._allowed_dir == tmp_path

    def test_path_traversal_blocked(self, qtbot, tmp_path):
        sub = tmp_path / "docs"
        sub.mkdir()
        md = sub / "index.md"
        md.write_text("# In docs", encoding="utf-8")
        outside = tmp_path / "secret.md"
        outside.write_text("# Secret", encoding="utf-8")
        browser = MarkdownBrowser()
        qtbot.addWidget(browser)
        browser.load_file(str(md))
        assert browser._allowed_dir == sub
        from PySide6.QtCore import QUrl
        from PySide6.QtWebEngineCore import QWebEnginePage
        accepted = browser._page.acceptNavigationRequest(
            QUrl.fromLocalFile(str(outside)),
            QWebEnginePage.NavigationType.NavigationTypeLinkClicked,
            True,
        )
        assert accepted is False
        assert "In docs" in browser.rendered_html()

    def test_cleanup_disconnects_theme(self, qtbot):
        browser = MarkdownBrowser()
        qtbot.addWidget(browser)
        browser.cleanup()
        browser.cleanup()