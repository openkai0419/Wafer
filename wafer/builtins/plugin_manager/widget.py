from PySide6 import QtWidgets, QtCore
from ...utils.formatting import dpix
from ...utils.logs import AppLogger
from ...utils.notifier import Notifier
from ...plugin.settings import PluginSettings
from ...plugin.panel.base import BasePanelPlugin
from ...core.color.theme import ThemeManager
from ...core.qt.dispatcher import Dispatcher
from ...core.qt.thread import utility_pool
from ...core.commands.bridge import Command


def _hex_rgb(hex_color: str) -> str:
    return f'{int(hex_color[1:3], 16)},{int(hex_color[3:5], 16)},{int(hex_color[5:7], 16)}'


def _build_stylesheet() -> str:
    p = ThemeManager.instance().palette
    r = dpix(4)
    return f"""
        QPushButton#save_btn {{
            background: {p.accent};
            color: {p.accent_text};
            border: none;
            border-radius: {r}px;
            padding: {dpix(5)}px {dpix(20)}px;
            font-weight: bold;
        }}
        QPushButton#save_btn:hover {{
            background: {p.bg_hover};
        }}
        QPushButton#cancel_btn {{
            background: {p.bg_secondary};
            border: 1px solid {p.border_default};
            border-radius: {r}px;
            padding: {dpix(5)}px {dpix(20)}px;
        }}
        QPushButton#cancel_btn:hover {{
            background: {p.bg_hover};
        }}
        QFrame#extension_card {{
            background: {p.bg_secondary};
            border: 1px solid {p.border_default};
            border-radius: {dpix(6)}px;
        }}
        QLabel#section_header {{
            font-weight: bold;
            font-size: {dpix(12)}px;
        }}
        QPushButton#status_btn {{
            font-size: {dpix(10)}px;
            font-weight: bold;
            border-radius: {r}px;
            padding: {dpix(2)}px {dpix(10)}px;
        }}
        QPushButton#status_btn[status="installed"] {{
            background: rgba({_hex_rgb(p.success)}, 0.12);
            color: {p.success};
            border: 1px solid rgba({_hex_rgb(p.success)}, 0.3);
        }}
        QPushButton#status_btn[status="no_deps"] {{
            background: transparent;
            color: {p.text_muted};
            border: 1px solid {p.border_default};
        }}
        QPushButton#status_btn[status="install"] {{
            background: {p.accent};
            color: {p.accent_text};
            border: none;
        }}
        QPushButton#status_btn[status="install"]:hover {{
            background: {p.bg_hover};
        }}
        QPushButton#status_btn[status="installing"] {{
            background: transparent;
            color: {p.accent};
            border: 1px solid {p.accent};
        }}
        QPushButton#status_btn[status="failed"] {{
            background: rgba({_hex_rgb(p.error)}, 0.12);
            color: {p.error};
            border: 1px solid rgba({_hex_rgb(p.error)}, 0.3);
        }}
        QPushButton#status_btn[status="failed"]:hover {{
            background: {p.error};
            color: {p.accent_text};
        }}
        QPushButton#purge_btn {{
            background: rgba({_hex_rgb(p.error)}, 0.1);
            color: {p.error};
            border: 1px solid rgba({_hex_rgb(p.error)}, 0.3);
            border-radius: {r}px;
            padding: {dpix(4)}px {dpix(12)}px;
            font-weight: bold;
        }}
        QPushButton#purge_btn:hover {{
            background: {p.error};
            color: {p.accent_text};
        }}
        QGroupBox {{
            font-weight: bold;
            border: 1px solid {p.border_default};
            border-radius: {dpix(6)}px;
            margin-top: {dpix(12)}px;
            padding-top: {dpix(12)}px;
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: {dpix(10)}px;
            padding: 0 {dpix(5)}px;
        }}
    """


class PluginManagerWidget(QtWidgets.QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(_build_stylesheet())

        self._settings = PluginSettings()
        self._dispatcher = Dispatcher(utility_pool)

        from .extensions_tab import ExtensionsTab
        self._ext_tab = ExtensionsTab(
            self._settings.enabled_names(),
            self._dispatcher,
        )

        self._tabs = QtWidgets.QTabWidget()

        from .collectors_tab import CollectorsTab
        collector_names = self._collect_worker_names()
        self._collectors_tab = CollectorsTab(collector_names)
        self._collectors_tab.purge_requested.connect(self._send_purge)
        self._tabs.addTab(self._scrollable(self._collectors_tab), 'Collectors')

        from .viewers_tab import OrderTab, REGISTRY_KEYS
        registry_data = {
            key: self._ext_tab.collect_enabled_plugins(key)
            for key in REGISTRY_KEYS
        }
        saved_orders = {
            key: self._settings.priority_order(key)
            for key in REGISTRY_KEYS
        }
        builtin_command_names = self._compute_builtin_command_names(registry_data)
        self._order_tab = OrderTab(registry_data, saved_orders, builtin_command_names)

        self._initial_enabled = self._settings.enabled_names() or set()
        self._initial_orders = dict(saved_orders)
        self._tabs.addTab(self._scrollable(self._order_tab), 'Order')

        self._ext_tab.enabled_changed.connect(self._sync_tabs)

        self._splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        self._splitter.addWidget(self._ext_tab)
        self._splitter.addWidget(self._tabs)
        self._splitter.setStretchFactor(0, 1)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setChildrenCollapsible(False)
        self._ext_tab.setMinimumHeight(dpix(220))
        self._tabs.setMinimumHeight(dpix(120))

        save_btn = QtWidgets.QPushButton('Save')
        save_btn.setObjectName('save_btn')
        revert_btn = QtWidgets.QPushButton('Cancel')
        revert_btn.setObjectName('cancel_btn')
        save_btn.clicked.connect(self._on_save)
        revert_btn.clicked.connect(self._on_revert)

        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(revert_btn)

        layout = QtWidgets.QVBoxLayout(self)
        p = dpix(6)
        layout.setContentsMargins(p, p, p, p)
        layout.setSpacing(p)
        layout.addWidget(self._splitter, 1)
        layout.addLayout(btn_layout)

    def _has_plugin_changes(self, enabled, orders):
        if enabled != self._initial_enabled:
            return True
        if orders != self._initial_orders:
            return True
        return False

    def _on_save(self):
        if not self._collectors_tab.confirm_and_save():
            return
        enabled = self._ext_tab.collect_enabled()
        orders = self._order_tab.get_orders()
        has_changes = (
            self._has_plugin_changes(enabled, orders)
            or self._collectors_tab.has_changes()
        )
        if not has_changes:
            Notifier.info('No changes to save')
            return
        self._settings.set_enabled(enabled)
        for key, order in orders.items():
            self._settings.set_priority_order(key, order)
        AppLogger.info(
            f'[PluginManager] Saved: enabled={sorted(enabled)}, '
            f'orders={orders}'
        )
        self._initial_enabled = set(enabled)
        self._initial_orders = dict(orders)
        msg = QtWidgets.QMessageBox(
            QtWidgets.QMessageBox.Question,
            'Restart Required',
            'Plugin settings have been saved.\nRestart is required.',
            parent=self,
        )
        restart_btn = msg.addButton('Restart', QtWidgets.QMessageBox.AcceptRole)
        msg.addButton('Not Now', QtWidgets.QMessageBox.RejectRole)
        msg.setDefaultButton(restart_btn)
        msg.exec()
        if msg.clickedButton() == restart_btn:
            Command.run("setting.restart_all")

    def _on_revert(self):
        self._ext_tab.revert(self._initial_enabled)
        self._sync_tabs()
        Notifier.info('Changes reverted')

    @staticmethod
    def _compute_builtin_command_names(registry_data: dict) -> set[str]:
        from ...plugin.loader import get_command_registry
        ext_cmd_classes = set(registry_data.get('command', []))
        return {
            cls.NAME for cls in get_command_registry().list_all()
            if cls not in ext_cmd_classes and cls.NAME
        }

    def _sync_tabs(self):
        from .viewers_tab import REGISTRY_KEYS
        registry_data = {
            key: self._ext_tab.collect_enabled_plugins(key)
            for key in REGISTRY_KEYS
        }
        self._order_tab.refresh(
            registry_data,
            self._compute_builtin_command_names(registry_data),
        )
        self._collectors_tab.refresh(self._collect_worker_names())

    def _collect_worker_names(self) -> list[str]:
        names = [cls.NAME for cls in self._ext_tab.collect_enabled_plugins('collector')]
        names += [cls.NAME for cls in self._ext_tab.collect_enabled_plugins('detacher')]
        return names

    def _send_purge(self, pairs: list[tuple[str, str]], re_collect: bool):
        from ...core.commands.binding.instance_registry import InstanceRegistry
        node = InstanceRegistry.instance().resolve_node()
        if not node:
            AppLogger.warning('[PluginManager] No IPC node available for purge')
            return
        for db, collector in pairs:
            node.send_reliable(
                'purge.collector',
                {'collector': collector, 're_collect': re_collect},
                dst='indexer',
                db=db,
            )
        AppLogger.info(f'[PluginManager] Sent purge for {len(pairs)} pairs')

    def closeEvent(self, event):
        self._ext_tab.cancel_pending()
        super().closeEvent(event)

    def add_tab(self, widget, title: str):
        self._tabs.addTab(widget, title)

    @staticmethod
    def _scrollable(widget: QtWidgets.QWidget) -> QtWidgets.QScrollArea:
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setWidget(widget)
        return scroll


class PluginManagerPlugin(BasePanelPlugin):
    NAME = "plugin_manager"
    DISPLAY_NAME = "Plugin Manager"
    CLOSABLE = True
    PRIORITY = 0

    def create_widget(self):
        return PluginManagerWidget()
