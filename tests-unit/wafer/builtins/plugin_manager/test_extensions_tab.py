import os
import pytest
import shiboken6
from unittest.mock import MagicMock
from PySide6 import QtCore, QtWidgets
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
        card = _ExtensionCard("ext_no_md", str(folder), dispatcher, md_files=[])
        qtbot.addWidget(card)
        assert card._md_entries == []

    def test_md_files_discovered(self, qtbot, tmp_path, dispatcher):
        folder = tmp_path / "ext_with_md"
        folder.mkdir()
        (folder / "README.md").write_text("# Hello", encoding="utf-8")
        (folder / "CHANGELOG.md").write_text("# Changes", encoding="utf-8")
        card = _ExtensionCard("ext_with_md", str(folder), dispatcher, md_files=["CHANGELOG.md", "README.md"])
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
        card = _ExtensionCard("ext_hidden", str(folder), dispatcher, md_files=["README.md"])
        qtbot.addWidget(card)
        assert len(card._md_entries) == 1

    def test_toggle_md_shows_and_hides(self, qtbot, tmp_path, dispatcher):
        folder = tmp_path / "ext_toggle"
        folder.mkdir()
        (folder / "README.md").write_text("# Test", encoding="utf-8")
        card = _ExtensionCard("ext_toggle", str(folder), dispatcher, md_files=["README.md"])
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
        card = _ExtensionCard("ext_async", str(folder), dispatcher, md_files=["README.md"])
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
        card = _ExtensionCard("ext_once", str(folder), dispatcher, md_files=["README.md"])
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

    def test_async_md_load_skips_deleted_browser(self, qtbot, tmp_path, dispatcher, monkeypatch):
        folder = tmp_path / "ext_deleted_browser"
        folder.mkdir()
        (folder / "README.md").write_text("# Deleted", encoding="utf-8")
        card = _ExtensionCard("ext_deleted_browser", str(folder), dispatcher, md_files=["README.md"])
        qtbot.addWidget(card)

        _, browser, md_path, _ = card._md_entries[0]
        apply_loaded = MagicMock()
        monkeypatch.setattr(browser, "apply_loaded", apply_loaded)

        browser.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
        QtWidgets.QApplication.instance().processEvents(QtCore.QEventLoop.AllEvents, 50)

        assert not shiboken6.isValid(browser)

        card._load_md_async(md_path, browser)
        qtbot.wait(300)
        QtCore.QCoreApplication.processEvents()

        apply_loaded.assert_not_called()


class TestActiveFolderNames:
    def test_filters_folders_without_enabled_plugins(self):
        from types import SimpleNamespace
        from wafer.builtins.plugin_manager.extensions_tab import ExtensionsTab

        cards = {
            "on_ext": SimpleNamespace(folder_name="on_ext", get_enabled_names=lambda: {"viewer:A"}),
            "off_ext": SimpleNamespace(folder_name="off_ext", get_enabled_names=lambda: set()),
        }
        fake = SimpleNamespace(_cards=cards)
        assert ExtensionsTab.active_folder_names(fake) == ["on_ext"]

    def test_sorted(self):
        from types import SimpleNamespace
        from wafer.builtins.plugin_manager.extensions_tab import ExtensionsTab

        cards = {
            "zeta": SimpleNamespace(folder_name="zeta", get_enabled_names=lambda: {"viewer:Z"}),
            "alpha": SimpleNamespace(folder_name="alpha", get_enabled_names=lambda: {"viewer:A"}),
        }
        fake = SimpleNamespace(_cards=cards)
        assert ExtensionsTab.active_folder_names(fake) == ["alpha", "zeta"]

