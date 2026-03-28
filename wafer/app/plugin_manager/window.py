from PySide6 import QtWidgets, QtCore
from ...utils.formatting import dpix
from ...utils.logs import AppLogger
from ...plugin.settings import PluginSettings
from ...core.qt.dispatcher import Dispatcher
from ...core.qt.thread import utility_pool
from ...core.ipc.node import Node


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
        self.resize(dpix(600), dpix(500))

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
        self._tabs.addTab(self._collectors_tab, 'Collectors')

        from .viewers_tab import ViewersTab
        self._viewers_tab = ViewersTab(
            self._ext_tab.collect_enabled_plugins('viewer'),
            self._ext_tab.collect_enabled_plugins('grid'),
            self._settings.viewer_order(),
            self._settings.grid_order(),
        )
        self._tabs.addTab(self._viewers_tab, 'Viewers')

        from .data_tab import DataTab
        self._data_tab = DataTab(self._dispatcher)
        self._data_tab.purge_requested.connect(self._send_purge)
        self._tabs.addTab(self._data_tab, 'Data')

        self._ext_tab.enabled_changed.connect(self._sync_tabs)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        splitter.addWidget(self._ext_tab)
        splitter.addWidget(self._tabs)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)

        save_btn = QtWidgets.QPushButton('Save')
        cancel_btn = QtWidgets.QPushButton('Cancel')
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
        viewer_order = self._viewers_tab.get_viewer_order()
        grid_order = self._viewers_tab.get_grid_order()
        self._settings.set_enabled(enabled)
        self._settings.set_viewer_order(viewer_order)
        self._settings.set_grid_order(grid_order)
        AppLogger.info(
            f'[PluginManager] Saved: enabled={sorted(enabled)}, '
            f'viewer_order={viewer_order}, grid_order={grid_order}'
        )
        answer = QtWidgets.QMessageBox.question(
            self,
            'Restart Required',
            'Plugin settings have been saved.\nRestart now to apply changes?',
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.Yes,
        )
        self.close()
        if answer == QtWidgets.QMessageBox.Yes:
            self._restart_app()

    def _restart_app(self):
        from ...core.platform.process import AppProcess
        AppProcess.terminate_cmd('--tray')
        AppProcess.new_main('--tray')
        main_window = self.parent()
        session_id = getattr(main_window, 'session_id', None)
        args = ['--viewer']
        if session_id:
            args += ['--session', session_id]
        AppProcess.new_main(*args)
        if main_window:
            main_window.close()

    def _sync_tabs(self):
        self._viewers_tab.refresh(
            self._ext_tab.collect_enabled_plugins('viewer'),
            self._ext_tab.collect_enabled_plugins('grid'),
        )
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
