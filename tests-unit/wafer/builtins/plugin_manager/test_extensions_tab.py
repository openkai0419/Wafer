import os
import pytest
from unittest.mock import MagicMock
from PySide6 import QtCore
from wafer.builtins.plugin_manager.extensions_tab import _ExtensionCard
from wafer.core.qt.dispatcher import Dispatcher
from wafer.core.qt.thread import SimpleThreadPool


@pytest.fixture()
def dispatcher():
    pool = SimpleThreadPool("test")
    return Dispatcher(pool)


class TestExtensionCardMdFiles:
    def test_no_md_files(self, qtbot, tmp_path, dispatcher):
        folder = tmp_path / "ext_no_md"
        folder.mkdir()
        card = _ExtensionCard("ext_no_md", str(folder), dispatcher)
        qtbot.addWidget(card)
        assert card._md_entries == []

    def test_md_files_discovered(self, qtbot, tmp_path, dispatcher):
        folder = tmp_path / "ext_with_md"
        folder.mkdir()
        (folder / "README.md").write_text("# Hello", encoding="utf-8")
        (folder / "CHANGELOG.md").write_text("# Changes", encoding="utf-8")
        card = _ExtensionCard("ext_with_md", str(folder), dispatcher)
        qtbot.addWidget(card)
        assert len(card._md_entries) == 2
        paths = [entry[2] for entry in card._md_entries]
        assert any("CHANGELOG.md" in p for p in paths)
        assert any("README.md" in p for p in paths)

    def test_hidden_md_files_excluded(self, qtbot, tmp_path, dispatcher):
        folder = tmp_path / "ext_hidden"
        folder.mkdir()
        (folder / ".hidden.md").write_text("# Hidden", encoding="utf-8")
        (folder / "_private.md").write_text("# Private", encoding="utf-8")
        (folder / "README.md").write_text("# Visible", encoding="utf-8")
        card = _ExtensionCard("ext_hidden", str(folder), dispatcher)
        qtbot.addWidget(card)
        assert len(card._md_entries) == 1

    def test_toggle_md_shows_and_hides(self, qtbot, tmp_path, dispatcher):
        folder = tmp_path / "ext_toggle"
        folder.mkdir()
        (folder / "README.md").write_text("# Test", encoding="utf-8")
        card = _ExtensionCard("ext_toggle", str(folder), dispatcher)
        qtbot.addWidget(card)
        card.show()

        toggle, browser, md_path, loaded = card._md_entries[0]
        assert browser.isHidden()

        card._toggle_md(md_path, toggle, browser)
        assert not browser.isHidden()
        assert "\u25bc" in toggle.text()

        card._toggle_md(md_path, toggle, browser)
        assert browser.isHidden()
        assert "\u25b6" in toggle.text()

    def test_async_md_load(self, qtbot, tmp_path, dispatcher):
        folder = tmp_path / "ext_async"
        folder.mkdir()
        (folder / "README.md").write_text("# Async Test\n\nContent", encoding="utf-8")
        card = _ExtensionCard("ext_async", str(folder), dispatcher)
        qtbot.addWidget(card)
        card.show()

        toggle, browser, md_path, loaded = card._md_entries[0]
        assert not loaded

        card._toggle_md(md_path, toggle, browser)
        _, _, _, loaded_after = card._md_entries[0]
        assert loaded_after

        qtbot.waitUntil(lambda: browser.rendered_html() != "", timeout=5000)
        assert "<h1>Async Test</h1>" in browser.rendered_html()
        assert "Content" in browser.rendered_html()

    def test_md_loaded_only_once(self, qtbot, tmp_path, dispatcher):
        folder = tmp_path / "ext_once"
        folder.mkdir()
        (folder / "README.md").write_text("# First", encoding="utf-8")
        card = _ExtensionCard("ext_once", str(folder), dispatcher)
        qtbot.addWidget(card)
        card.show()

        toggle, browser, md_path, _ = card._md_entries[0]

        card._toggle_md(md_path, toggle, browser)
        qtbot.waitUntil(lambda: browser.rendered_html() != "", timeout=5000)
        first_html = browser.rendered_html()

        (folder / "README.md").write_text("# Changed", encoding="utf-8")
        card._toggle_md(md_path, toggle, browser)
        card._toggle_md(md_path, toggle, browser)

        from PySide6.QtCore import QThread
        QThread.msleep(200)
        QtCore.QCoreApplication.processEvents()
        assert browser.rendered_html() == first_html
