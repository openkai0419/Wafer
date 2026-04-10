import re
from pathlib import Path
import markdown as _md
from PySide6 import QtWidgets, QtGui, QtCore
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from ..core.color.theme import ThemeManager
from .paths import get_resource_path
from .logs import AppLogger

_MD_EXTENSIONS = ["tables", "fenced_code", "md_in_html", "sane_lists"]
_MD_TAB_LENGTH = 2

_HTML_BLOCK_TAGS = re.compile(
    r"(<(?:div|details|summary|section|article|aside|header|footer"
    r"|nav|figure|figcaption))(\s[^>]*)?(>)"
)

_css_cache: dict[str, str] = {}


def _load_github_css(dark: bool) -> str:
    key = "dark" if dark else "light"
    if key not in _css_cache:
        name = f"github-markdown-{key}.css"
        path = get_resource_path() / name
        _css_cache[key] = path.read_text(encoding="utf-8")
    return _css_cache[key]


def _preprocess_html_blocks(text: str) -> str:
    def _add_md_attr(m: re.Match) -> str:
        tag_open, attrs, close = m.group(1), m.group(2) or "", m.group(3)
        if "markdown=" in attrs:
            return m.group(0)
        return f'{tag_open}{attrs} markdown="1"{close}'

    return _HTML_BLOCK_TAGS.sub(_add_md_attr, text)


def render_to_html(text: str) -> str:
    preprocessed = _preprocess_html_blocks(text)
    return _md.markdown(preprocessed, extensions=_MD_EXTENSIONS, tab_length=_MD_TAB_LENGTH)


def _build_full_html(body_html: str, dark: bool) -> str:
    css = _load_github_css(dark)
    return f'<!DOCTYPE html><html><head><meta charset="utf-8"><style>{css}</style></head><body class="markdown-body" style="padding:16px 32px;">{body_html}</body></html>'


class _ExternalLinkPage(QWebEnginePage):
    def __init__(self, browser: "MarkdownBrowser", parent=None):
        super().__init__(parent)
        self._browser = browser
        self.settings().setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, False)

    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        if nav_type != QWebEnginePage.NavigationType.NavigationTypeLinkClicked:
            return super().acceptNavigationRequest(url, nav_type, is_main_frame)
        if url.isLocalFile() and url.toLocalFile().lower().endswith(".md"):
            target = Path(url.toLocalFile()).resolve()
            base_dir = self._browser._allowed_dir
            if base_dir and not target.is_relative_to(base_dir):
                AppLogger.warning(f"Blocked navigation outside base directory: {target}")
                return False
            self._browser.load_file(str(target))
            return False
        QtGui.QDesktopServices.openUrl(url)
        return False


class MarkdownBrowser(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._view = QWebEngineView(self)
        self._page = _ExternalLinkPage(self, self._view)
        self._view.setPage(self._page)
        self._view.setZoomFactor(0.8)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._view)
        self._source_md = ""
        self._rendered_html = ""
        self._base_url = QtCore.QUrl()
        self._allowed_dir: Path | None = None
        self._theme_conn = ThemeManager.instance().on_theme_changed.connect(self._on_theme_changed)
        self.destroyed.connect(self._disconnect_theme)

    def load_file(self, path: str) -> bool:
        try:
            p = Path(path).resolve()
            if self._allowed_dir is None:
                self._allowed_dir = p.parent
            self._base_url = QtCore.QUrl.fromLocalFile(str(p.parent) + "/")
            with open(p, encoding="utf-8") as f:
                self.set_markdown(f.read())
            return True
        except Exception as e:
            AppLogger.warning(f"Failed to load markdown: {path}", exc=e)
            self._source_md = ""
            self._rendered_html = "(Failed to load file)"
            dark = ThemeManager.instance().is_dark
            self._view.setHtml(_build_full_html("<p>(Failed to load file)</p>", dark))
            return False

    def set_markdown(self, text: str):
        self._source_md = text
        body = render_to_html(text)
        self._apply_body(body)

    def apply_loaded(self, source_md: str, body_html: str, base_url: QtCore.QUrl, allowed_dir: Path):
        self._source_md = source_md
        if self._allowed_dir is None:
            self._allowed_dir = allowed_dir
        self._base_url = base_url
        self._apply_body(body_html)

    def _apply_body(self, body_html: str):
        self._rendered_html = body_html
        dark = ThemeManager.instance().is_dark
        self._view.setHtml(_build_full_html(body_html, dark), self._base_url)

    def source_markdown(self) -> str:
        return self._source_md

    def rendered_html(self) -> str:
        return self._rendered_html

    def _on_theme_changed(self, _palette):
        if self._source_md:
            self.set_markdown(self._source_md)

    def _disconnect_theme(self):
        tm = ThemeManager.instance()
        with tm.on_theme_changed._lock:
            try:
                tm.on_theme_changed._callbacks.remove(self._on_theme_changed)
            except ValueError:
                pass

    def cleanup(self):
        self._disconnect_theme()
