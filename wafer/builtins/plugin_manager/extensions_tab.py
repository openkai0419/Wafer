import os
from pathlib import Path
from PySide6 import QtWidgets, QtCore
from ...utils.formatting import dpix
from ...utils.logs import AppLogger
from ...utils.markdown_browser import MarkdownBrowser, render_to_html
from ...core.color.theme import ThemeManager
from ...plugin.loader import get_plugin_dir, PluginLoader, qualify_plugin_name
from ...plugin.installer import needs_setup, install_extension
from ...core.qt.dispatcher import Dispatcher, CancelSlot

_MAX_MD_FILES = 10


_REGISTRY_LABELS = {
    "viewer": "Viewer",
    "grid": "Grid",
    "collector": "Collector",
    "filter": "Filter",
    "sort": "Sort",
    "layout": "Layout",
    "rename_source": "Rename",
    "command": "Command",
    "panel": "Panel",
}

_TAG_COLORS = {
    "viewer": "#81c784",
    "grid": "#ce93d8",
    "collector": "#f48fb1",
    "command": "#ffb74d",
    "layout": "#80cbc4",
    "filter": "#4fc3f7",
    "sort": "#90a4ae",
    "rename_source": "#bcaaa4",
    "panel": "#fff176",
}


def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    r = int(hex_color[1:3], 16)
    g = int(hex_color[3:5], 16)
    b = int(hex_color[5:7], 16)
    return f"rgba({r},{g},{b},{alpha})"


class _PluginRow(QtWidgets.QWidget):
    def __init__(self, registry_key: str, plugin_cls: type, checked: bool, parent=None):
        super().__init__(parent)
        self.checkbox = QtWidgets.QCheckBox()
        self.checkbox.setChecked(checked)
        self.panel_btn = None

        tag_color = _TAG_COLORS.get(registry_key, "#90a4ae")
        tag_text = _REGISTRY_LABELS.get(registry_key, registry_key)
        tag = QtWidgets.QLabel(tag_text)
        tag.setStyleSheet(f"color: {tag_color}; background: {_hex_to_rgba(tag_color, 0.15)}; font-size: {dpix(11)}px; font-weight: bold; padding: {dpix(2)}px {dpix(6)}px; border-radius: {dpix(3)}px;")
        tag.setMinimumWidth(dpix(68))
        tag.setAlignment(QtCore.Qt.AlignCenter)

        name_label = QtWidgets.QLabel(plugin_cls.NAME)

        extensions = getattr(plugin_cls, "EXTENSIONS", ())
        ext_text = ", ".join(extensions) if extensions else ""
        ext_label = QtWidgets.QLabel(ext_text)
        ext_label.setStyleSheet(f"color: #888; font-size: {dpix(11)}px;")

        row_layout = QtWidgets.QHBoxLayout(self)
        row_layout.setContentsMargins(dpix(4), dpix(1), dpix(4), dpix(1))
        row_layout.setSpacing(dpix(6))
        row_layout.addWidget(tag)
        row_layout.addWidget(self.checkbox)
        row_layout.addWidget(name_label)
        row_layout.addWidget(ext_label)
        row_layout.addStretch()

        if registry_key == "panel":
            display = getattr(plugin_cls, "DISPLAY_NAME", "") or plugin_cls.NAME
            btn = QtWidgets.QPushButton("Open")
            btn.setToolTip(f"Open {display}")
            btn.setFixedHeight(dpix(22))
            btn.setCursor(QtCore.Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=None, n=display: self._toggle_panel(n))
            from ...plugin.panel.handler import panel_registry

            registered = panel_registry.get(plugin_cls.NAME) is not None
            btn.setEnabled(registered)
            if not registered:
                btn.setCursor(QtCore.Qt.ArrowCursor)
            row_layout.addWidget(btn)
            self.panel_btn = btn

    @staticmethod
    def _toggle_panel(panel_name: str):
        from ...core.commands.bridge import Command

        slug = panel_name.lower().replace(" ", "_")
        Command.run(f"panel.toggle_{slug}")


class _ExtensionCard(QtWidgets.QFrame):
    def __init__(self, folder_name: str, folder_path: str, dispatcher: Dispatcher, md_files: list[str], parent=None):
        super().__init__(parent)
        self.folder_name = folder_name
        self.folder_path = folder_path
        self._dispatcher = dispatcher
        self.setObjectName("extension_card")
        self._rows: list[tuple[_PluginRow, str]] = []
        self._plugins: list[tuple[str, type]] = []
        self._plugin_area = QtWidgets.QVBoxLayout()
        self._plugin_area.setSpacing(dpix(2))

        self._name_label = QtWidgets.QLabel(folder_name)
        self._name_label.setStyleSheet(f"font-weight: bold; font-size: {dpix(13)}px;")

        self._status_btn = QtWidgets.QPushButton()
        self._status_btn.setObjectName("status_btn")
        self._status_btn.setFixedHeight(dpix(24))
        self._status_btn.setMinimumWidth(dpix(120))
        self._status_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self._status_btn.clicked.connect(self._on_install_clicked)

        self._progress = QtWidgets.QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setFixedHeight(dpix(4))
        self._progress.setTextVisible(False)
        self._progress.hide()

        header = QtWidgets.QHBoxLayout()
        header.addWidget(self._name_label)
        header.addStretch()
        header.addWidget(self._status_btn)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(dpix(10), dpix(8), dpix(10), dpix(8))
        layout.setSpacing(dpix(4))
        layout.addLayout(header)
        layout.addWidget(self._progress)
        layout.addLayout(self._plugin_area)

        self._md_entries: list[tuple[QtWidgets.QLabel, MarkdownBrowser, str, bool]] = []
        if md_files:
            accent = ThemeManager.instance().palette.accent
            for md_name in md_files:
                md_path = os.path.join(folder_path, md_name)
                toggle = QtWidgets.QLabel(f"\u25b6 {md_name}")
                toggle.setCursor(QtCore.Qt.PointingHandCursor)
                toggle.setStyleSheet(f"color: {accent}; font-size: {dpix(11)}px; padding: {dpix(2)}px 0;")
                browser = MarkdownBrowser()
                browser.setMinimumHeight(dpix(200))
                browser.setMaximumHeight(dpix(600))
                browser.hide()
                toggle.mousePressEvent = lambda _, p=md_path, t=toggle, b=browser: self._toggle_md(p, t, b)
                self._md_entries.append((toggle, browser, md_path, False))
                layout.addWidget(toggle)
                layout.addWidget(browser)

        self._install_callback = None
        self._checkbox_changed_callback = None

    def set_install_callback(self, cb):
        self._install_callback = cb

    def set_checkbox_changed_callback(self, cb):
        self._checkbox_changed_callback = cb

    def _apply_status(self, text: str, status: str, enabled: bool):
        self._status_btn.setText(text)
        self._status_btn.setEnabled(enabled)
        self._status_btn.setProperty("status", status)
        self._status_btn.style().unpolish(self._status_btn)
        self._status_btn.style().polish(self._status_btn)
        self._status_btn.setCursor(QtCore.Qt.PointingHandCursor if enabled else QtCore.Qt.ArrowCursor)

    def set_installed(self, has_requirements: bool = True):
        if has_requirements:
            self._apply_status("Installed", "installed", False)
        else:
            self._apply_status("No Dependencies", "no_deps", False)
        self._progress.hide()

    def set_needs_install(self):
        self._apply_status("Install", "install", True)
        self._progress.hide()
        self._clear_plugin_area()

    def set_installing(self):
        self._apply_status("Installing…", "installing", False)
        self._progress.show()

    def set_install_failed(self):
        self._apply_status("Retry", "failed", True)
        self._progress.hide()

    def set_plugins(self, plugins: list[tuple[str, type]], enabled: set[str] | None):
        self._clear_plugin_area()
        self._rows.clear()
        self._plugins = list(plugins)
        for registry_key, plugin_cls in plugins:
            qualified = qualify_plugin_name(registry_key, plugin_cls)
            if enabled is not None:
                checked = qualified in enabled
            else:
                checked = getattr(plugin_cls, "DEFAULT_ENABLED", False)
            row = _PluginRow(registry_key, plugin_cls, checked)
            row.checkbox.stateChanged.connect(self._on_checkbox_changed)
            self._rows.append((row, qualified))
            self._plugin_area.addWidget(row)

    def get_enabled_names(self) -> set[str]:
        return {name for row, name in self._rows if row.checkbox.isChecked()}

    def get_enabled_plugins(self, registry_key: str) -> list[type]:
        enabled = self.get_enabled_names()
        return [cls for key, cls in self._plugins if key == registry_key and qualify_plugin_name(key, cls) in enabled]

    def _clear_plugin_area(self):
        while self._plugin_area.count():
            item = self._plugin_area.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _toggle_md(self, md_path: str, toggle: QtWidgets.QLabel, browser: MarkdownBrowser):
        md_name = os.path.basename(md_path)
        if browser.isVisible():
            browser.hide()
            toggle.setText(f"\u25b6 {md_name}")
        else:
            for i, (t, b, p, loaded) in enumerate(self._md_entries):
                if p == md_path and not loaded:
                    self._md_entries[i] = (t, b, p, True)
                    self._load_md_async(md_path, browser)
                    break
            browser.show()
            toggle.setText(f"\u25bc {md_name}")

    def _load_md_async(self, md_path: str, browser: MarkdownBrowser):
        def task():
            try:
                p = Path(md_path).resolve()
                with open(p, encoding="utf-8") as f:
                    text = f.read()
                body_html = render_to_html(text)
                base_url = QtCore.QUrl.fromLocalFile(str(p.parent) + "/")
                self._dispatcher.invoke(lambda: browser.apply_loaded(text, body_html, base_url, p.parent))
            except Exception as e:
                AppLogger.warning(f"Failed to load markdown async: {md_path}", exc=e)

        self._dispatcher.post(task, priority=5)

    def _on_install_clicked(self):
        if self._install_callback:
            self._install_callback(self)

    def _on_checkbox_changed(self):
        if self._checkbox_changed_callback:
            self._checkbox_changed_callback()


class ExtensionsTab(QtWidgets.QWidget):
    enabled_changed = QtCore.Signal()

    def __init__(self, enabled_names: set[str] | None, dispatcher: Dispatcher, parent=None):
        super().__init__(parent)
        self._enabled = enabled_names
        self._dispatcher = dispatcher
        self._install_cancels: dict[str, CancelSlot] = {}
        self._cards: dict[str, _ExtensionCard] = {}

        self._scroll = QtWidgets.QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self._container = QtWidgets.QWidget()
        self._cards_layout = QtWidgets.QVBoxLayout(self._container)
        self._cards_layout.setSpacing(dpix(8))
        self._cards_layout.addStretch()
        self._scroll.setWidget(self._container)

        layout = QtWidgets.QVBoxLayout(self)
        p = dpix(2)
        layout.setContentsMargins(p, p, p, 0)
        layout.setSpacing(dpix(6))
        desc = QtWidgets.QLabel("Extensions")
        desc.setObjectName("section_header")
        layout.addWidget(desc)
        layout.addWidget(self._scroll, 1)

        self._scan_extensions()

    def _scan_extensions(self):
        plugin_dir = get_plugin_dir()

        def scan_task():
            if not os.path.isdir(plugin_dir):
                return []
            results = []
            for name in sorted(os.listdir(plugin_dir)):
                folder = os.path.join(plugin_dir, name)
                if not os.path.isdir(folder) or name.startswith(".") or name == "__pycache__":
                    continue
                md_files = sorted(
                    f for f in os.listdir(folder)
                    if f.lower().endswith(".md") and not f.startswith((".", "_")) and os.path.isfile(os.path.join(folder, f))
                )[:_MAX_MD_FILES]
                need_install = needs_setup(folder)
                has_req = os.path.isfile(os.path.join(folder, "requirements.txt"))
                results.append((name, folder, md_files, need_install, has_req))
            return results

        def on_scan_complete(results):
            for name, folder, md_files, need_install, has_req in results:
                card = _ExtensionCard(name, folder, self._dispatcher, md_files)
                card.set_install_callback(self._install_extension)
                card.set_checkbox_changed_callback(self._on_plugin_toggled)
                self._cards[name] = card
                self._cards_layout.insertWidget(self._cards_layout.count() - 1, card)

                if need_install:
                    card.set_needs_install()
                else:
                    card.set_installed(has_req)
                    self._discover_async(card)

        def task():
            results = scan_task()
            self._dispatcher.invoke(lambda: on_scan_complete(results))

        self._dispatcher.post(task, priority=5)

    def _discover_async(self, card: _ExtensionCard):
        folder = card.folder_path

        def task():
            try:
                plugins = PluginLoader.discover_extension(folder)
            except Exception as e:
                AppLogger.warning(f"[PluginManager] discover failed: {card.folder_name}", exc=e)
                return
            self._dispatcher.invoke(lambda: self._on_discover_complete(card, plugins))

        self._dispatcher.post(task, priority=5)

    def _on_discover_complete(self, card: _ExtensionCard, plugins: list[tuple[str, type]]):
        card.set_plugins(plugins, self._enabled)
        self.enabled_changed.emit()

    def _install_extension(self, card: _ExtensionCard):
        card.set_installing()
        slot = self._install_cancels.get(card.folder_name)
        if slot is None:
            slot = CancelSlot()
            self._install_cancels[card.folder_name] = slot
        cancel = slot.renew()

        def task():
            try:
                extensions_dir = get_plugin_dir()
                success, post_install_ok, plugins = install_extension(
                    card.folder_path,
                    extensions_dir,
                    is_cancelled=cancel.is_cancelled,
                )
                if cancel.is_cancelled():
                    return
                self._dispatcher.invoke(lambda: self._on_install_complete(card, success, plugins, post_install_ok))
            except Exception as e:
                AppLogger.warning(f"[PluginManager] install failed: {card.folder_name}", exc=e)
                if not cancel.is_cancelled():
                    self._dispatcher.invoke(lambda: self._on_install_complete(card, False, []))

        self._dispatcher.post(task, priority=3, cancel=cancel)

    def _on_install_complete(self, card: _ExtensionCard, success: bool, plugins: list, post_install_ok: bool = True):
        if success:
            if post_install_ok:
                card.set_installed()
            else:
                card.set_install_failed()
            card.set_plugins(plugins, self._enabled)
            self.enabled_changed.emit()
        else:
            card.set_install_failed()

    def _on_plugin_toggled(self):
        self.enabled_changed.emit()

    def collect_enabled(self) -> set[str]:
        result = set()
        for card in self._cards.values():
            result |= card.get_enabled_names()
        return result

    def collect_enabled_plugins(self, registry_key: str) -> list[type]:
        result = []
        for card in self._cards.values():
            result.extend(card.get_enabled_plugins(registry_key))
        return result

    def cancel_pending(self):
        for slot in self._install_cancels.values():
            slot.renew()
        self._install_cancels.clear()

    def revert(self, enabled_names: set[str]):
        self._enabled = set(enabled_names)
        for card in self._cards.values():
            for row, qualified in card._rows:
                row.checkbox.blockSignals(True)
                row.checkbox.setChecked(qualified in self._enabled)
                row.checkbox.blockSignals(False)
