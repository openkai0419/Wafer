from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6 import QtGui
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings

from ...core.logs import AppLogger

if TYPE_CHECKING:
    from .markdown_browser import MarkdownBrowser


class ExternalLinkPage(QWebEnginePage):
    def __init__(self, browser: MarkdownBrowser, parent=None):
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
