import os
from enum import Enum
from pathlib import Path
from PySide6 import QtWidgets, QtCore, QtGui
from ...utils.formatting import dpix
from ...utils.logs import AppLogger
from ...utils.markdown_browser import MarkdownBrowser, render_to_html
from ...core.color.theme import ThemeManager
from ...core.lang.manager import t
from ...core.qt.color_utils import mix_colors
from ...plugin.loader import get_plugin_dir, PluginLoader, qualify_plugin_name
from ...plugin.settings import PluginSettings
from ...ui.widgets.eliding import ElidingLabel
from ...plugin.kinds import PLUGIN_KIND_COLLECTOR, PLUGIN_KIND_PANEL, PLUGIN_KIND_PARSER, plugin_kind_color, plugin_kind_label
from ...plugin.installer import (
    InstallState,
    RestartScope,
    resolve_install_state,
)
from ...plugin import failed_installs, installer_queue
from ...plugin.badges import ExtensionBadge, resolve_badge, badge_sort_key
from ...core.qt.icon_engine import themed_icon
from ...core.qt.dispatcher import Dispatcher
from .badge_texts import badge_tooltip_text, heavy_install_confirm_text, heavy_install_title
from .readme_summary import extract_readme_summary

_MAX_MD_FILES = 10
_PLUGIN_KIND_BADGE_WIDTH = 76


class CardStatus(Enum):
    NO_DEPS = "no_deps"
    NOT_INSTALLED = "not_installed"
    NEEDS_SETUP = "needs_setup"
    INSTALLING = "installing"
    POST_INSTALLING = "post_installing"
    CANCELLING = "cancelling"
    INSTALLED = "installed"
    FAILED = "failed"
    RESTART_REQUIRED = "restart_required"


_CARD_STATUS_CONFIG: dict[CardStatus, tuple[str, str, bool]] = {
    CardStatus.NO_DEPS: ("No Dependencies", "no_deps", False),
    CardStatus.NOT_INSTALLED: ("Install", "install", True),
    CardStatus.NEEDS_SETUP: ("Setup", "setup", True),
    CardStatus.INSTALLING: ("Installing\u2026", "installing", False),
    CardStatus.POST_INSTALLING: ("Setting up\u2026", "installing", False),
    CardStatus.CANCELLING: ("Cancelling\u2026", "cancelling", False),
    CardStatus.INSTALLED: ("Installed", "installed", False),
    CardStatus.FAILED: ("Retry", "failed", True),
    CardStatus.RESTART_REQUIRED: ("Restart Required", "deferred", False),
}


def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    r = int(hex_color[1:3], 16)
    g = int(hex_color[3:5], 16)
    b = int(hex_color[5:7], 16)
    return f"rgba({r},{g},{b},{alpha})"


class _InstantTooltipLabel(QtWidgets.QLabel):
    def enterEvent(self, event):
        text = self.toolTip()
        if text:
            QtWidgets.QToolTip.showText(QtGui.QCursor.pos(), text, self, self.rect())
        super().enterEvent(event)


class _PluginRow(QtWidgets.QWidget):
    def __init__(self, registry_key: str, plugin_cls: type, checked: bool, parent=None):
        super().__init__(parent)
        self.checkbox = QtWidgets.QCheckBox()
        self.checkbox.setChecked(checked)
        self.panel_btn = None

        tag_color = plugin_kind_color(registry_key)
        tag_text = plugin_kind_label(registry_key)
        tag = QtWidgets.QLabel(tag_text)
        tag.setObjectName("plugin_kind_badge")
        tag.setStyleSheet(f"color: {tag_color}; background: {_hex_to_rgba(tag_color, 0.15)}; font-size: {dpix(11)}px; font-weight: bold; padding: {dpix(2)}px {dpix(6)}px; border-radius: {dpix(3)}px;")
        tag.setFixedWidth(dpix(_PLUGIN_KIND_BADGE_WIDTH))
        tag.setAlignment(QtCore.Qt.AlignCenter)

        name_label = QtWidgets.QLabel(plugin_cls.NAME)

        trigger_keys = getattr(plugin_cls, "TRIGGER_KEYS", ())
        if trigger_keys:
            from ...plugin.parser.base import required_collectors
            from .badge_texts import required_collectors_text

            required = required_collectors(trigger_keys)
            ext_text = required_collectors_text(required)
            ext_tooltip = ext_text
        else:
            extensions = getattr(plugin_cls, "EXTENSIONS", ())
            ext_text = ", ".join(extensions) if extensions else ""
            ext_tooltip = ""
        ext_label = ElidingLabel(ext_text, minimum_hint_width=dpix(40), horizontal_policy=QtWidgets.QSizePolicy.Expanding)
        ext_label.setStyleSheet(f"color: #888; font-size: {dpix(11)}px;")
        if ext_tooltip:
            ext_label.setToolTip(ext_tooltip)

        row_layout = QtWidgets.QHBoxLayout(self)
        row_layout.setContentsMargins(dpix(4), dpix(1), dpix(4), dpix(1))
        row_layout.setSpacing(dpix(6))
        row_layout.addWidget(tag)
        row_layout.addWidget(self.checkbox)
        row_layout.addWidget(name_label)
        row_layout.addWidget(ext_label)

        if registry_key == PLUGIN_KIND_PANEL:
            display = getattr(plugin_cls, "DISPLAY_NAME", "") or plugin_cls.NAME
            btn = QtWidgets.QPushButton(t("Open"))
            btn.setObjectName("open_panel_btn")
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


_BADGE_CONFIG: dict[ExtensionBadge, tuple[str, str | None]] = {
    ExtensionBadge.PREFERRED: ("star", "success"),
    ExtensionBadge.HEAVY: ("warning_triangle", None),
    ExtensionBadge.EXTERNAL: ("external_link", None),
}

_BADGE_ICON_SIZE: dict[ExtensionBadge, int] = {
    ExtensionBadge.PREFERRED: 14,
    ExtensionBadge.HEAVY: 13,
    ExtensionBadge.EXTERNAL: 13,
}


class _ExtensionCard(QtWidgets.QFrame):
    def __init__(self, folder_name: str, folder_path: str, dispatcher: Dispatcher, md_files: list[str], summary: str = "", parent=None):
        super().__init__(parent)
        self.folder_name = folder_name
        self.folder_path = folder_path
        self.badge = resolve_badge(folder_name)
        self._dispatcher = dispatcher
        self.setObjectName("extension_card")
        self._rows: list[tuple[_PluginRow, str, type]] = []
        self._plugins: list[tuple[str, type]] = []
        self._plugin_area = QtWidgets.QVBoxLayout()
        self._plugin_area.setSpacing(dpix(2))

        self._name_label = QtWidgets.QLabel(folder_name)
        self._name_label.setStyleSheet(f"font-weight: bold; font-size: {dpix(13)}px;")

        self._summary_label = QtWidgets.QLabel(summary)
        self._summary_label.setStyleSheet(f"color: #888; font-size: {dpix(11)}px;")
        self._summary_label.setWordWrap(True)
        self._summary_label.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        self._summary_label.setContentsMargins(0, 0, 0, 0)
        if not summary:
            self._summary_label.hide()

        self._status_btn = QtWidgets.QPushButton()
        self._status_btn.setObjectName("status_btn")
        self._status_btn.setFixedHeight(dpix(24))
        self._status_btn.setMinimumWidth(dpix(120))
        self._status_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self._status_btn.clicked.connect(self._on_install_clicked)

        self._install_cancel_btn = QtWidgets.QPushButton(t("Cancel"))
        self._install_cancel_btn.setObjectName("install_cancel_btn")
        self._install_cancel_btn.setFixedHeight(dpix(24))
        self._install_cancel_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self._install_cancel_btn.clicked.connect(self._on_cancel_clicked)
        self._install_cancel_btn.hide()

        self._progress = QtWidgets.QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setFixedHeight(dpix(4))
        self._progress.setTextVisible(False)
        self._progress.hide()

        self._detail_label = QtWidgets.QLabel()
        self._detail_label.setStyleSheet(f"color: #999; font-size: {dpix(11)}px;")
        self._detail_label.hide()

        self._log_toggle = QtWidgets.QLabel(f"\u25b6 {t('Show Log')}")
        self._log_toggle.setCursor(QtCore.Qt.PointingHandCursor)
        accent = ThemeManager.instance().palette.accent
        self._log_toggle.setStyleSheet(f"color: {accent}; font-size: {dpix(11)}px; padding: {dpix(1)}px 0;")
        self._log_toggle.mousePressEvent = lambda _: self._toggle_log()
        self._log_toggle.hide()

        self._log_view = QtWidgets.QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setMaximumHeight(dpix(200))
        self._log_view.setStyleSheet(f"font-family: Consolas, monospace; font-size: {dpix(11)}px;")
        self._log_view.hide()
        self._log_expanded = False

        header = QtWidgets.QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(dpix(3))
        badge_cfg = _BADGE_CONFIG.get(self.badge) if self.badge is not None else None
        if badge_cfg:
            icon_key, tint = badge_cfg
            badge_label = _InstantTooltipLabel()
            icon_px = _BADGE_ICON_SIZE.get(self.badge, 13)
            icon_size = dpix(icon_px)
            badge_color = self._badge_color(tint)
            badge_label.setPixmap(themed_icon(icon_key, color=badge_color).pixmap(icon_size, icon_size))
            badge_label.setToolTip(badge_tooltip_text(self.badge))
            badge_label.setFixedSize(icon_size, icon_size)
            badge_label.setAlignment(QtCore.Qt.AlignCenter)
            header.addWidget(badge_label, 0, QtCore.Qt.AlignVCenter)
            self._name_label.setStyleSheet(f"font-weight: bold; font-size: {dpix(13)}px; color: {badge_color.name()};")
        header.addWidget(self._name_label, 0, QtCore.Qt.AlignVCenter)
        header.addStretch()
        header.addWidget(self._install_cancel_btn)
        header.addWidget(self._status_btn)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(dpix(10), dpix(8), dpix(10), dpix(8))
        layout.setSpacing(dpix(4))
        title_block = QtWidgets.QVBoxLayout()
        title_block.setContentsMargins(0, 0, 0, 0)
        title_block.setSpacing(dpix(1))
        title_block.addLayout(header)
        title_block.addWidget(self._summary_label)
        layout.addLayout(title_block)
        layout.addWidget(self._progress)
        layout.addWidget(self._detail_label)
        layout.addWidget(self._log_toggle)
        layout.addWidget(self._log_view)
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
        self._cancel_callback = None
        self._checkbox_changed_callback = None

    @staticmethod
    def _badge_color(tint: str | None) -> QtGui.QColor:
        palette = ThemeManager.instance().palette
        base = QtGui.QColor(palette.text_primary)
        if tint is None:
            return mix_colors(base, palette.warning, 0.6)
        if tint == "success":
            return mix_colors(base, palette.success, 0.6)
        return mix_colors(base, tint, 0.22)

    def set_install_callback(self, cb):
        self._install_callback = cb

    def set_cancel_callback(self, cb):
        self._cancel_callback = cb

    def set_checkbox_changed_callback(self, cb):
        self._checkbox_changed_callback = cb

    def _apply_status(self, text: str, status: str, enabled: bool):
        self._status_btn.setText(text)
        self._status_btn.setEnabled(enabled)
        self._status_btn.setProperty("status", status)
        self._status_btn.style().unpolish(self._status_btn)
        self._status_btn.style().polish(self._status_btn)
        self._status_btn.setCursor(QtCore.Qt.PointingHandCursor if enabled else QtCore.Qt.ArrowCursor)

    def set_status(self, status: CardStatus, restart_scope: RestartScope = RestartScope.NONE):
        cfg = _CARD_STATUS_CONFIG[status]
        text = t(cfg[0])
        if status == CardStatus.RESTART_REQUIRED:
            if restart_scope == RestartScope.VIEWER:
                text = t("Viewer Restart Required")
            elif restart_scope == RestartScope.TRAY:
                text = t("Background Restart Required")
        self._apply_status(text, cfg[1], cfg[2])
        installing = status in (CardStatus.INSTALLING, CardStatus.POST_INSTALLING)
        cancelling = status == CardStatus.CANCELLING
        if installing or cancelling:
            self._progress.show()
            self._detail_label.show()
            self._log_toggle.show()
        else:
            self._progress.hide()
            self._detail_label.hide()
            if not self._log_view.document().isEmpty():
                self._log_toggle.show()
            else:
                self._log_toggle.hide()
                self._log_view.hide()
        if installing:
            self._install_cancel_btn.setEnabled(True)
            self._install_cancel_btn.setText(t("Cancel"))
            self._install_cancel_btn.show()
        elif cancelling:
            self._install_cancel_btn.setEnabled(False)
            self._install_cancel_btn.setText(t("Cancelling\u2026"))
            self._install_cancel_btn.show()
        else:
            self._install_cancel_btn.hide()
        if status == CardStatus.NOT_INSTALLED:
            self._clear_plugin_area()

    def set_phase(self, text: str):
        self._detail_label.setText(text)

    def append_log(self, line: str):
        self._log_view.appendPlainText(line)
        if self._log_expanded:
            sb = self._log_view.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _toggle_log(self):
        if self._log_view.isVisible():
            self._log_view.hide()
            self._log_expanded = False
            self._log_toggle.setText(f"\u25b6 {t('Show Log')}")
        else:
            self._log_view.show()
            self._log_expanded = True
            self._log_toggle.setText(f"\u25bc {t('Hide Log')}")
            sb = self._log_view.verticalScrollBar()
            sb.setValue(sb.maximum())

    def set_plugins(
        self,
        plugins: list[tuple[str, type]],
        enabled_overrides: dict[str, bool] | None,
        legacy_enabled: set[str] | None = None,
    ):
        self._clear_plugin_area()
        self._rows.clear()
        self._plugins = list(plugins)
        for registry_key, plugin_cls in plugins:
            qualified = qualify_plugin_name(registry_key, plugin_cls)
            checked = PluginSettings.resolve_enabled(qualified, plugin_cls, enabled_overrides, legacy_enabled)
            row = _PluginRow(registry_key, plugin_cls, checked)
            row.checkbox.stateChanged.connect(self._on_checkbox_changed)
            self._rows.append((row, qualified, plugin_cls))
            self._plugin_area.addWidget(row)

    def get_enabled_names(self) -> set[str]:
        return {name for row, name, _plugin_cls in self._rows if row.checkbox.isChecked()}

    def get_enabled_overrides(self) -> dict[str, bool]:
        result = {}
        for row, qualified, plugin_cls in self._rows:
            override = PluginSettings.enabled_override(qualified, plugin_cls, row.checkbox.isChecked())
            if override is not None:
                result[override[0]] = override[1]
        return result

    def iter_plugin_states(self):
        for row, qualified, plugin_cls in self._rows:
            yield qualified, plugin_cls, row.checkbox.isChecked()

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

                def apply_loaded():
                    import shiboken6

                    if not shiboken6.isValid(browser):
                        return
                    browser.apply_loaded(text, body_html, base_url, p.parent)

                self._dispatcher.invoke(apply_loaded)
            except Exception as e:
                AppLogger.warning(f"Failed to load markdown async: {md_path}", exc=e)

        self._dispatcher.post(task, priority=5)

    def _on_install_clicked(self):
        if self._install_callback:
            self._install_callback(self)

    def _on_cancel_clicked(self):
        if self._cancel_callback:
            self._cancel_callback(self)

    def _on_checkbox_changed(self):
        if self._checkbox_changed_callback:
            self._checkbox_changed_callback()


class ExtensionsTab(QtWidgets.QWidget):
    enabled_changed = QtCore.Signal()

    def __init__(
        self,
        enabled_overrides: dict[str, bool] | set[str] | None,
        dispatcher: Dispatcher,
        legacy_enabled: set[str] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self._enabled_overrides = dict(enabled_overrides) if isinstance(enabled_overrides, dict) else {}
        self._legacy_enabled = set(enabled_overrides) if isinstance(enabled_overrides, set) and legacy_enabled is None else legacy_enabled
        self._dispatcher = dispatcher
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
                md_files = sorted(f for f in os.listdir(folder) if f.lower().endswith(".md") and not f.startswith((".", "_")) and os.path.isfile(os.path.join(folder, f)))[:_MAX_MD_FILES]
                summary = extract_readme_summary(folder)
                state = resolve_install_state(folder)
                results.append((name, folder, md_files, summary, state))
            return results

        def on_scan_complete(results):
            state_to_card = {
                InstallState.NO_DEPS: CardStatus.NO_DEPS,
                InstallState.NOT_INSTALLED: CardStatus.NOT_INSTALLED,
                InstallState.NEEDS_POST_INSTALL: CardStatus.NEEDS_SETUP,
                InstallState.INSTALLED: CardStatus.INSTALLED,
            }
            queued = installer_queue.queued_names(plugin_dir)
            failed = failed_installs.failed_names(plugin_dir)
            results.sort(key=lambda r: (badge_sort_key(r[0]), r[0]))
            separator_inserted = False
            for name, folder, md_files, summary, state in results:
                badge = resolve_badge(name)
                if badge == ExtensionBadge.EXTERNAL and not separator_inserted:
                    separator_inserted = True
                    sep = QtWidgets.QFrame()
                    sep.setFrameShape(QtWidgets.QFrame.HLine)
                    sep.setFrameShadow(QtWidgets.QFrame.Sunken)
                    self._cards_layout.insertWidget(self._cards_layout.count() - 1, sep)
                card = _ExtensionCard(name, folder, self._dispatcher, md_files, summary)
                card.set_install_callback(self._install_extension)
                card.set_cancel_callback(self._cancel_extension)
                card.set_checkbox_changed_callback(self._on_plugin_toggled)
                self._cards[name] = card
                self._cards_layout.insertWidget(self._cards_layout.count() - 1, card)
                if name in queued:
                    card.set_status(CardStatus.RESTART_REQUIRED, RestartScope.ALL)
                elif name in failed:
                    info = failed_installs.failure_info(plugin_dir, name) or {}
                    card.set_status(CardStatus.FAILED)
                    reason = info.get("reason", "")
                    if reason:
                        card._status_btn.setToolTip(reason)
                else:
                    card.set_status(state_to_card[state])
                if state not in (InstallState.NOT_INSTALLED,):
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
        card.set_plugins(plugins, self._enabled_overrides, self._legacy_enabled)
        self.enabled_changed.emit()

    def _install_extension(self, card: _ExtensionCard):
        if card.badge == ExtensionBadge.HEAVY:
            message = QtWidgets.QMessageBox(self)
            message.setWindowTitle(heavy_install_title())
            message.setIcon(QtWidgets.QMessageBox.NoIcon)
            message.setText(heavy_install_confirm_text())
            message.setStandardButtons(QtWidgets.QMessageBox.Ok | QtWidgets.QMessageBox.Cancel)
            message.setDefaultButton(QtWidgets.QMessageBox.Cancel)
            if message.exec() != QtWidgets.QMessageBox.Ok:
                return
        installer_queue.enqueue(get_plugin_dir(), card.folder_name, card.folder_path)
        failed_installs.clear(get_plugin_dir(), [card.folder_name])
        card.set_status(CardStatus.RESTART_REQUIRED, RestartScope.ALL)
        self.enabled_changed.emit()

    def _cancel_extension(self, card: _ExtensionCard):
        if installer_queue.dequeue(get_plugin_dir(), card.folder_name):
            failed_installs.clear(get_plugin_dir(), [card.folder_name])
            state = resolve_install_state(card.folder_path)
            state_to_card = {
                InstallState.NO_DEPS: CardStatus.NO_DEPS,
                InstallState.NOT_INSTALLED: CardStatus.NOT_INSTALLED,
                InstallState.NEEDS_POST_INSTALL: CardStatus.NEEDS_SETUP,
                InstallState.INSTALLED: CardStatus.INSTALLED,
            }
            card.set_status(state_to_card.get(state, CardStatus.NOT_INSTALLED))
            self.enabled_changed.emit()

    def _on_plugin_toggled(self):
        self.enabled_changed.emit()

    def collect_enabled(self) -> set[str]:
        result = set()
        for card in self._cards.values():
            result |= card.get_enabled_names()
        return result

    def collect_enabled_overrides(self) -> dict[str, bool]:
        result = {}
        for card in self._cards.values():
            result.update(card.get_enabled_overrides())
        return result

    def iter_plugin_states(self):
        for card in self._cards.values():
            yield from card.iter_plugin_states()

    def collect_enabled_plugins(self, registry_key: str) -> list[type]:
        result = []
        for card in self._cards.values():
            result.extend(card.get_enabled_plugins(registry_key))
        return result

    def heavy_collector_map(self) -> dict[str, str]:
        result = {}
        for card in self._cards.values():
            if card.badge != ExtensionBadge.HEAVY:
                continue
            for key, cls in card._plugins:
                if key in (PLUGIN_KIND_COLLECTOR, PLUGIN_KIND_PARSER):
                    result[cls.NAME] = card.folder_name
        return result

    def cancel_pending(self):
        pass

    def revert(self, enabled_overrides: dict[str, bool], legacy_enabled: set[str] | None = None):
        self._enabled_overrides = dict(enabled_overrides)
        self._legacy_enabled = legacy_enabled
        for card in self._cards.values():
            for row, qualified, plugin_cls in card._rows:
                row.checkbox.blockSignals(True)
                row.checkbox.setChecked(PluginSettings.resolve_enabled(qualified, plugin_cls, self._enabled_overrides, self._legacy_enabled))
                row.checkbox.blockSignals(False)
