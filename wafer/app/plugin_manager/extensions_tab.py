import os
from PySide6 import QtWidgets, QtCore
from ...utils.formatting import dpix
from ...utils.logs import AppLogger
from ...plugin.loader import get_plugin_dir, _needs_install, PluginLoader
from ...plugin.installer import install_requirements
from ...core.qt.dispatcher import Dispatcher, CancelSlot


_REGISTRY_LABELS = {
    'viewer': 'Viewer',
    'grid': 'Grid',
    'collector': 'Collector',
    'filter': 'Filter',
    'sort': 'Sort',
    'layout': 'Layout',
    'rename_source': 'Rename',
    'command': 'Command',
}


class _ExtensionCard(QtWidgets.QGroupBox):

    def __init__(self, folder_name: str, folder_path: str, parent=None):
        super().__init__(parent)
        self.folder_name = folder_name
        self.folder_path = folder_path
        self.setTitle(folder_name)
        self._checkboxes: list[tuple[QtWidgets.QCheckBox, str]] = []
        self._plugins: list[tuple[str, type]] = []
        self._plugin_area = QtWidgets.QVBoxLayout()

        self._badge = QtWidgets.QLabel()
        self._badge.setFixedHeight(dpix(20))

        self._install_btn = QtWidgets.QPushButton('Install')
        self._install_btn.setFixedWidth(dpix(80))
        self._install_btn.clicked.connect(self._on_install_clicked)
        self._install_btn.hide()

        self._progress = QtWidgets.QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setFixedHeight(dpix(14))
        self._progress.setTextVisible(False)
        self._progress.hide()

        header = QtWidgets.QHBoxLayout()
        header.addWidget(self._badge)
        header.addStretch()
        header.addWidget(self._install_btn)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(dpix(4))
        layout.addLayout(header)
        layout.addWidget(self._progress)
        layout.addLayout(self._plugin_area)

        self._install_callback = None
        self._checkbox_changed_callback = None

    def set_install_callback(self, cb):
        self._install_callback = cb

    def set_checkbox_changed_callback(self, cb):
        self._checkbox_changed_callback = cb

    def _set_badge(self, text: str, color: str):
        self._badge.setText(text)
        self._badge.setStyleSheet(
            f'color: {color}; font-weight: bold; font-size: {dpix(11)}px;'
        )

    def set_installed(self):
        has_req = os.path.isfile(os.path.join(self.folder_path, 'requirements.txt'))
        if has_req:
            self._set_badge('Ready', '#4caf50')
        else:
            self._set_badge('Ready', '#888')
        self._install_btn.hide()
        self._progress.hide()

    def set_needs_install(self):
        self._set_badge('Install Required', '#ff9800')
        self._install_btn.show()
        self._progress.hide()
        self._clear_plugin_area()

    def set_installing(self):
        self._install_btn.hide()
        self._set_badge('Installing...', '#2196f3')
        self._progress.show()

    def set_install_failed(self):
        self._progress.hide()
        self._set_badge('Failed', '#f44336')
        self._install_btn.setText('Retry')
        self._install_btn.show()

    def set_plugins(self, plugins: list[tuple[str, type]], enabled: set[str] | None):
        self._clear_plugin_area()
        self._checkboxes.clear()
        self._plugins = list(plugins)
        for registry_key, plugin_cls in plugins:
            label_type = _REGISTRY_LABELS.get(registry_key, registry_key)
            extensions = getattr(plugin_cls, 'EXTENSIONS', ())
            ext_str = ', '.join(extensions) if extensions else ''
            text = f'{label_type}: {plugin_cls.NAME} '
            if ext_str:
                text += f'  ({ext_str})'
            qualified = f'{registry_key}:{plugin_cls.NAME}'
            cb = QtWidgets.QCheckBox(text)
            if enabled is not None:
                cb.setChecked(qualified in enabled)
            else:
                cb.setChecked(getattr(plugin_cls, 'DEFAULT_ENABLED', True))
            cb.stateChanged.connect(self._on_checkbox_changed)
            self._checkboxes.append((cb, qualified))
            self._plugin_area.addWidget(cb)

    def get_enabled_names(self) -> set[str]:
        result = set()
        for cb, name in self._checkboxes:
            if cb.isChecked():
                result.add(name)
        return result

    def get_enabled_plugins(self, registry_key: str) -> list[type]:
        enabled = self.get_enabled_names()
        return [
            cls for key, cls in self._plugins
            if key == registry_key and f'{key}:{cls.NAME}' in enabled
        ]

    def _clear_plugin_area(self):
        while self._plugin_area.count():
            item = self._plugin_area.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

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
        self._container = QtWidgets.QWidget()
        self._cards_layout = QtWidgets.QVBoxLayout(self._container)
        self._cards_layout.setSpacing(dpix(6))
        self._cards_layout.addStretch()
        self._scroll.setWidget(self._container)

        layout = QtWidgets.QVBoxLayout(self)
        p = dpix(2)
        layout.setContentsMargins(p, p, p, 0)
        layout.setSpacing(dpix(4))
        desc = QtWidgets.QLabel('Installed extensions:')
        desc.setStyleSheet(f'font-weight: bold; font-size: {dpix(12)}px;')
        layout.addWidget(desc)
        layout.addWidget(self._scroll, 1)

        self._scan_extensions()

    def _scan_extensions(self):
        plugin_dir = get_plugin_dir()
        if not os.path.isdir(plugin_dir):
            return
        for name in sorted(os.listdir(plugin_dir)):
            folder = os.path.join(plugin_dir, name)
            if not os.path.isdir(folder) or name.startswith('.') or name == '__pycache__':
                continue
            card = _ExtensionCard(name, folder)
            card.set_install_callback(self._install_extension)
            card.set_checkbox_changed_callback(self._on_plugin_toggled)
            self._cards[name] = card
            self._cards_layout.insertWidget(self._cards_layout.count() - 1, card)

            if _needs_install(folder):
                card.set_needs_install()
            else:
                card.set_installed()
                self._discover_async(card)

    def _discover_async(self, card: _ExtensionCard):
        folder = card.folder_path

        def task():
            try:
                plugins = PluginLoader.discover_extension(folder)
            except Exception as e:
                AppLogger.warning(f'[PluginManager] discover failed: {card.folder_name}', exc=e)
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
                success = install_requirements(card.folder_path)
                if cancel.is_cancelled():
                    return
                if success:
                    plugins = PluginLoader.discover_extension(card.folder_path)
                    self._dispatcher.invoke(
                        lambda: self._on_install_complete(card, True, plugins)
                    )
                else:
                    self._dispatcher.invoke(
                        lambda: self._on_install_complete(card, False, [])
                    )
            except Exception as e:
                AppLogger.warning(
                    f'[PluginManager] install failed: {card.folder_name}', exc=e
                )
                if not cancel.is_cancelled():
                    self._dispatcher.invoke(lambda: self._on_install_complete(card, False, []))

        self._dispatcher.post(task, priority=3, cancel=cancel)

    def _on_install_complete(self, card: _ExtensionCard, success: bool, plugins: list):
        if success:
            card.set_installed()
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
