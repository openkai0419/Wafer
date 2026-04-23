from wafer.builtins.plugin_manager.readme_summary import extract_readme_summary


def _write(folder, name, content):
    p = folder / name
    p.write_text(content, encoding="utf-8")
    return p


class TestExtractReadmeSummary:
    def test_missing_readme(self, tmp_path):
        assert extract_readme_summary(str(tmp_path)) == ""

    def test_standard_format(self, tmp_path):
        _write(tmp_path, "README.md", "## Image Extension\n\nCore extension for static image browsing.\n\n### Features\n- foo\n")
        assert extract_readme_summary(str(tmp_path)) == "Core extension for static image browsing."

    def test_no_heading(self, tmp_path):
        _write(tmp_path, "README.md", "Just a description line.\n\nMore stuff later.\n")
        assert extract_readme_summary(str(tmp_path)) == "Just a description line."

    def test_only_headings(self, tmp_path):
        _write(tmp_path, "README.md", "# Title\n\n## Subtitle\n\n### Section\n")
        assert extract_readme_summary(str(tmp_path)) == ""

    def test_emphasis_stripped(self, tmp_path):
        _write(tmp_path, "README.md", "## Title\n\nUses **bold** and *italic* and `code`.\n")
        assert extract_readme_summary(str(tmp_path)) == "Uses bold and italic and code."

    def test_links_stripped(self, tmp_path):
        _write(tmp_path, "README.md", "## Title\n\nSee [docs](https://example.com) for details.\n")
        assert extract_readme_summary(str(tmp_path)) == "See docs for details."

    def test_multiline_paragraph_joined(self, tmp_path):
        _write(tmp_path, "README.md", "## Title\n\nLine one\nline two\nline three.\n\nNext paragraph.\n")
        assert extract_readme_summary(str(tmp_path)) == "Line one line two line three."

    def test_skips_bullets_before_text(self, tmp_path):
        _write(tmp_path, "README.md", "## Title\n\n- bullet item\n\nReal description here.\n")
        assert extract_readme_summary(str(tmp_path)) == "Real description here."

    def test_lowercase_filename(self, tmp_path):
        _write(tmp_path, "readme.md", "## Title\n\nLowercase readme works.\n")
        assert extract_readme_summary(str(tmp_path)) == "Lowercase readme works."
