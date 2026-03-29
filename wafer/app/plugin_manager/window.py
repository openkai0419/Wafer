from PySide6 import QtWidgets, QtCore
from ...utils.formatting import dpix, is_dark_theme
from ...utils.logs import AppLogger
from ...plugin.settings import PluginSettings
from ...core.qt.dispatcher import Dispatcher
from ...core.qt.thread import utility_pool
from ...core.ipc.node import Node
from ...core.commands.bridge import ActionKit


def _hex_rgb(hex_color: str) -> str:
    return f'{int(hex_color[1:3], 16)},{int(hex_color[3:5], 16)},{int(hex_color[5:7], 16)}'


def _build_stylesheet() -> str:
    dark = is_dark_theme()
    if dark:
        card_bg = '#2a2a2a'
        card_border = '#3a3a3a'
        accent = '#4fc3f7'
        accent_hover = '#29b6f6'
        success = '#66bb6a'
        error = '#ef5350'
        disabled_text = '#666'
        btn_bg = '#353535'
        btn_border = '#444'
        btn_hover = '#404040'
    else:
        card_bg = '#f5f5f5'
        card_border = '#e0e0e0'
        accent = '#1976d2'
        accent_hover = '#1565c0'
        success = '#43a047'
        error = '#e53935'
        disabled_text = '#aaa'
        btn_bg = '#f0f0f0'
        btn_border = '#ccc'
        btn_hover = '#e0e0e0'
    r = dpix(4)
    return f"""
        QPushButton#save_btn {{
            background: {accent};
            color: white;
            border: none;
            border-radius: {r}px;
            padding: {dpix(5)}px {dpix(20)}px;
            font-weight: bold;
        }}
        QPushButton#save_btn:hover {{
            background: {accent_hover};
        }}
        QPushButton#cancel_btn {{
            background: {btn_bg};
            border: 1px solid {btn_border};
            border-radius: {r}px;
            padding: {dpix(5)}px {dpix(20)}px;
        }}
        QPushButton#cancel_btn:hover {{
            background: {btn_hover};
        }}
        QFrame#extension_card {{
            background: {card_bg};
            border: 1px solid {card_border};
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
            background: rgba({_hex_rgb(success)}, 0.12);
            color: {success};
            border: 1px solid rgba({_hex_rgb(success)}, 0.3);
        }}
        QPushButton#status_btn[status="no_deps"] {{
            background: transparent;
            color: {disabled_text};
            border: 1px solid {card_border};
        }}
        QPushButton#status_btn[status="install"] {{
            background: {accent};
            color: white;
            border: none;
        }}
        QPushButton#status_btn[status="install"]:hover {{
            background: {accent_hover};
        }}
        QPushButton#status_btn[status="installing"] {{
            background: transparent;
            color: {accent};
            border: 1px solid {accent};
        }}
        QPushButton#status_btn[status="failed"] {{
            background: rgba({_hex_rgb(error)}, 0.12);
            color: {error};
            border: 1px solid rgba({_hex_rgb(error)}, 0.3);
        }}
        QPushButton#status_btn[status="failed"]:hover {{
            background: {error};
            color: white;
        }}
        QPushButton#purge_btn {{
            background: rgba({_hex_rgb(error)}, 0.1);
            color: {error};
            border: 1px solid rgba({_hex_rgb(error)}, 0.3);
            border-radius: {r}px;
            padding: {dpix(4)}px {dpix(12)}px;
            font-weight: bold;
        }}
        QPushButton#purge_btn:hover {{
            background: {error};
            color: white;
        }}
        QGroupBox {{
            font-weight: bold;
            border: 1px solid {card_border};
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


class PluginManagerDialog(QtWidgets.QDialog):
    _instance = None

    @classmethod
    def open(cls, parent=None, node=None):
        if cls._instance is not None:
            cls._instance.raise_()
            cls._instance.activateWindow()
            return cls._instance
        dlg = cls(parent=parent, node=node)
        cls._instance = dlg
        dlg.show()
        return dlg

    def __init__(self, parent=None, node=None):
        super().__init__(parent)
        self.setWindowTitle('Plugin Manager')
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.Window)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        self.resize(dpix(1000), dpix(550))
        self.setStyleSheet(_build_stylesheet())

        self._settings = PluginSettings()
        self._dispatcher = Dispatcher(utility_pool)
        self._node = node

        from .extensions_tab import ExtensionsTab
        self._ext_tab = ExtensionsTab(
            self._settings.enabled_names(),
            self._dispatcher,
        )

        self._tabs = QtWidgets.QTabWidget()

        from .collectors_tab import CollectorsTab
        collector_names = [cls.NAME for cls in self._ext_tab.collect_enabled_plugins('collector')]
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
        self._order_tab = OrderTab(registry_data, saved_orders)
        self._tabs.addTab(self._scrollable(self._order_tab), 'Order')

        from .data_tab import DataTab
        self._data_tab = DataTab(self._dispatcher)
        self._data_tab.purge_requested.connect(self._send_purge)
        self._tabs.addTab(self._scrollable(self._data_tab), 'Data')

        self._ext_tab.enabled_changed.connect(self._sync_tabs)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        splitter.addWidget(self._ext_tab)
        splitter.addWidget(self._tabs)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setChildrenCollapsible(False)
        self._ext_tab.setMinimumHeight(dpix(120))
        self._tabs.setMinimumHeight(dpix(120))

        save_btn = QtWidgets.QPushButton('Save')
        save_btn.setObjectName('save_btn')
        cancel_btn = QtWidgets.QPushButton('Cancel')
        cancel_btn.setObjectName('cancel_btn')
        save_btn.clicked.connect(self._on_save)
        cancel_btn.clicked.connect(self.close)

        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)

        layout = QtWidgets.QVBoxLayout(self)
        p = dpix(6)
        layout.setContentsMargins(p, p, p, p)
        layout.setSpacing(p)
        layout.addWidget(splitter, 1)
        layout.addLayout(btn_layout)

    def _on_save(self):
        if not self._collectors_tab.confirm_and_save():
            return
        enabled = self._ext_tab.collect_enabled()
        orders = self._order_tab.get_orders()
        self._settings.set_enabled(enabled)
        for key, order in orders.items():
            self._settings.set_priority_order(key, order)
        AppLogger.info(
            f'[PluginManager] Saved: enabled={sorted(enabled)}, '
            f'orders={orders}'
        )
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
        self.close()
        if msg.clickedButton() == restart_btn:
            ActionKit.Command.run("setting.restart_all")

    def _sync_tabs(self):
        from .viewers_tab import REGISTRY_KEYS
        registry_data = {
            key: self._ext_tab.collect_enabled_plugins(key)
            for key in REGISTRY_KEYS
        }
        self._order_tab.refresh(registry_data)
        collector_names = [cls.NAME for cls in self._ext_tab.collect_enabled_plugins('collector')]
        self._collectors_tab.refresh(collector_names)

    def _send_purge(self, pairs: list[tuple[str, str]], re_collect: bool):
        if not self._node:
            AppLogger.warning('[PluginManager] No IPC node available for purge')
            return
        for db, collector in pairs:
            self._node.send_reliable(
                'purge.collector',
                {'collector': collector, 're_collect': re_collect},
                dst='indexer',
                db=db,
            )
        AppLogger.info(f'[PluginManager] Sent purge for {len(pairs)} pairs')

    def closeEvent(self, event):
        self._ext_tab.cancel_pending()
        PluginManagerDialog._instance = None
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
