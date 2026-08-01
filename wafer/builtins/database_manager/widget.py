import os

from PySide6 import QtWidgets, QtCore, QtGui
from ...utils.formatting import dpix
from ...utils.logs import AppLogger
from ...utils.notifier import Notifier
from ...utils.paths import (
    list_setting_db_names,
    setting_db_path,
    data_db_path,
)
from ...core.color.theme import ThemeManager
from ...core.lang.manager import t
from ...core.db.setting_db import SettingDB
from ...core.platform.process import AppProcess
from ...ui.dialogs import ConfirmDialog, InputDialog
from ...core.qt.dispatcher import Dispatcher
from ...core.qt.icon_engine import themed_icon
from ...core.qt.thread import utility_pool
from ...plugin.panel.base import BasePanelPlugin


def _build_stylesheet() -> str:
    p = ThemeManager.instance().palette
    r = dpix(4)
    return f"""
        QPushButton#add_btn {{
            background: {p.accent};
            color: {p.accent_text};
            border: none;
            border-radius: {r}px;
            padding: {dpix(2)}px {dpix(8)}px;
            font-weight: bold;
        }}
        QPushButton#add_btn:hover {{
            background: {p.bg_hover};
        }}
        QPushButton#remove_btn, QPushButton#folder_add_btn {{
            background: {p.bg_secondary};
            border: 1px solid {p.border_default};
            border-radius: {r}px;
            padding: {dpix(2)}px {dpix(8)}px;
        }}
        QPushButton#remove_btn:hover, QPushButton#folder_add_btn:hover {{
            background: {p.bg_hover};
        }}
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
        QPushButton#delete_db_btn {{
            color: {p.error};
            background: {p.bg_secondary};
            border: 1px solid {p.error};
            border-radius: {r}px;
            padding: {dpix(2)}px {dpix(8)}px;
            font-weight: bold;
        }}
        QPushButton#delete_db_btn:hover {{
            background: {p.error};
            color: {p.accent_text};
        }}
        QListWidget {{
            background: {p.bg_primary};
            border: 1px solid {p.border_default};
            border-radius: {r}px;
        }}
        QListWidget::item:selected {{
            background: {p.bg_pressed};
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


class DatabaseManagerWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(_build_stylesheet())

        self._dispatcher = Dispatcher(utility_pool)
        self._initial_paths: dict[str, tuple[list[str], list[str]]] = {}

        self._db_list = QtWidgets.QListWidget()
        self._db_list.setMinimumHeight(dpix(60))
        self._db_list.currentTextChanged.connect(self._on_db_selected)

        add_db_btn = QtWidgets.QPushButton()
        add_db_btn.setIcon(themed_icon("plus"))
        add_db_btn.setObjectName("add_btn")
        add_db_btn.setToolTip(t("Add Database"))
        add_db_btn.clicked.connect(self._add_database)

        del_db_btn = QtWidgets.QPushButton()
        del_db_btn.setIcon(themed_icon("minus"))
        del_db_btn.setObjectName("delete_db_btn")
        del_db_btn.setToolTip(t("Delete Database"))
        del_db_btn.clicked.connect(self._delete_database)

        db_btn_layout = QtWidgets.QHBoxLayout()
        db_btn_layout.addStretch()
        db_btn_layout.addWidget(add_db_btn)
        db_btn_layout.addWidget(del_db_btn)

        db_group = QtWidgets.QGroupBox(t("Databases"))
        db_group_layout = QtWidgets.QVBoxLayout(db_group)
        db_group_layout.addWidget(self._db_list)
        db_group_layout.addLayout(db_btn_layout)

        self._detail_stack = QtWidgets.QStackedWidget()
        self._empty_label = QtWidgets.QLabel(t("Select a database"))
        self._empty_label.setAlignment(QtCore.Qt.AlignCenter)
        self._detail_stack.addWidget(self._empty_label)

        self._detail_widget = _DatabaseDetailWidget()
        self._detail_stack.addWidget(self._detail_widget)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        splitter.addWidget(db_group)
        splitter.addWidget(self._detail_stack)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setChildrenCollapsible(False)
        db_group.setMinimumHeight(dpix(130))
        self._detail_stack.setMinimumHeight(dpix(260))
        self._paths_splitter = splitter

        save_btn = QtWidgets.QPushButton(t("Save"))
        save_btn.setObjectName("save_btn")
        revert_btn = QtWidgets.QPushButton(t("Revert"))
        revert_btn.setObjectName("cancel_btn")
        save_btn.clicked.connect(self._on_save)
        revert_btn.clicked.connect(self._on_revert)

        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(revert_btn)

        paths_container = QtWidgets.QWidget()
        paths_layout = QtWidgets.QVBoxLayout(paths_container)
        paths_layout.setContentsMargins(0, 0, 0, 0)
        paths_layout.setSpacing(dpix(6))
        paths_layout.addWidget(self._paths_splitter, 1)
        paths_layout.addLayout(btn_layout)

        from .data_tab import DataTab

        self._data_tab = DataTab(self._dispatcher)
        self._data_tab.apply_requested.connect(self._apply_data_actions)

        self._tabs = QtWidgets.QTabWidget()
        self._tabs.addTab(self._scrollable(paths_container), t("Paths"))
        self._tabs.addTab(self._scrollable(self._data_tab), t("Data"))

        layout = QtWidgets.QVBoxLayout(self)
        p = dpix(6)
        layout.setContentsMargins(p, p, p, p)
        layout.setSpacing(p)
        layout.addWidget(self._tabs, 1)

        self._refresh_db_list()
        self._snapshot_all()

    def _save_ui_state(self) -> dict:
        state = {}
        for key, splitter in [
            ("paths_splitter", self._paths_splitter),
            ("detail_splitter", self._detail_widget.splitter),
            ("data_splitter", self._data_tab.splitter),
        ]:
            sizes = splitter.sizes()
            if any(sizes):
                state[key] = sizes
        return state

    def _restore_ui_state(self, state: dict):
        if "paths_splitter" in state:
            self._paths_splitter.setSizes(state["paths_splitter"])
        if "detail_splitter" in state:
            self._detail_widget.splitter.setSizes(state["detail_splitter"])
        if "data_splitter" in state:
            self._data_tab.splitter.setSizes(state["data_splitter"])

    def _snapshot_all(self):
        self._initial_paths.clear()
        for i in range(self._db_list.count()):
            name = self._db_list.item(i).text()
            sdb = SettingDB(setting_db_path(name))
            self._initial_paths[name] = (
                list(sdb.get_all_parent_folders()),
                list(sdb.get_all_ignore_folders()),
            )

    def _refresh_db_list(self):
        current = self._db_list.currentItem()
        current_name = current.text() if current else None
        self._db_list.clear()
        names = list_setting_db_names()
        for name in names:
            self._db_list.addItem(name)
        if current_name and current_name in names:
            items = self._db_list.findItems(current_name, QtCore.Qt.MatchExactly)
            if items:
                self._db_list.setCurrentItem(items[0])
        elif names:
            self._db_list.setCurrentRow(0)

    def _on_db_selected(self, name: str):
        if not name:
            self._detail_stack.setCurrentWidget(self._empty_label)
            return
        self._detail_widget.load(name)
        self._detail_stack.setCurrentWidget(self._detail_widget)

    def _add_database(self):
        text = InputDialog.get_text(
            t("Enter a name for the new database:"),
            title=t("Create Database"),
            buttons=(t("Create"), t("Cancel")),
            parent=self,
        )
        if not text or not text.strip():
            return
        text = text.strip()
        if text in list_setting_db_names():
            return

        def _seed_and_start():
            from ...plugin.settings import PluginSettings

            defaults = PluginSettings().resolve_default_collectors()
            sdb = SettingDB(setting_db_path(text))
            sdb.set_enabled_collectors(defaults)
            AppProcess.new_main("--indexer", text)

            def _on_done():
                self._refresh_db_list()
                self._initial_paths[text] = ([], [])
                items = self._db_list.findItems(text, QtCore.Qt.MatchExactly)
                if items:
                    self._db_list.setCurrentItem(items[0])
                AppLogger.info(f"[DatabaseManager] Created database: {text}")

            self._dispatcher.invoke(_on_done)

        self._dispatcher.post(_seed_and_start)

    def _delete_database(self):
        current = self._db_list.currentItem()
        if not current:
            return
        db_name = current.text()
        if self._db_list.count() <= 1:
            return
        ret = ConfirmDialog.ask(
            f'Delete database "{db_name}"?\nThis cannot be undone.',
            title=t("Delete Database"),
            buttons=(t("Delete"), t("Cancel")),
            parent=self,
        )
        if ret != "Delete":
            return
        from ...core.commands.binding.instance_registry import InstanceRegistry

        node = InstanceRegistry.instance().resolve_node()
        if node:
            node.send_reliable("db.delete", db_name, dst="indexer", db=db_name)
            self._initial_paths.pop(db_name, None)
            AppLogger.info(f"[DatabaseManager] Deleted database: {db_name}")
            self._refresh_db_list()
        else:

            def _remove_db_files():
                import os

                for path in (data_db_path(db_name), setting_db_path(db_name)):
                    if os.path.isfile(path):
                        os.remove(path)
                    for suffix in ("-wal", "-shm"):
                        wal = path + suffix
                        if os.path.isfile(wal):
                            os.remove(wal)

                def _on_done():
                    self._initial_paths.pop(db_name, None)
                    AppLogger.info(f"[DatabaseManager] Deleted database: {db_name}")
                    self._refresh_db_list()

                self._dispatcher.invoke(_on_done)

            self._dispatcher.post(_remove_db_files)

    def has_changes(self) -> bool:
        return self._detail_widget.has_changes(self._initial_paths)

    def _on_save(self):
        if not self.has_changes():
            Notifier.info(t("No changes to save"))
            return
        changed = self._detail_widget.commit(self._initial_paths)
        AppLogger.info(f"[DatabaseManager] Saved path changes for: {sorted(changed)}")
        from ...core.commands.binding.instance_registry import InstanceRegistry

        node = InstanceRegistry.instance().resolve_node()
        if node and changed:
            node.send_coalesced("rescan")
        self._snapshot_all()
        self._detail_widget.reset(self._initial_paths)
        current = self._db_list.currentItem()
        if current:
            self._detail_widget.load(current.text())
        Notifier.info(f"Database settings saved ({len(changed)} changed)")

    def _on_revert(self):
        if not self.has_changes():
            return
        self._detail_widget.reset(self._initial_paths)
        current = self._db_list.currentItem()
        if current:
            self._detail_widget.load(current.text())

    def _apply_data_actions(self, actions: list[tuple[str, str, bool, bool]]):
        from ...core.db.recollect import Recollect

        sent = 0
        for db, collector, delete, re_collect in actions:
            sent += Recollect.reset(db_scope=[db], collector=collector, delete=delete, re_collect=re_collect)
        if not sent:
            return
        self._data_tab.clear_checks()
        AppLogger.info(f"[DatabaseManager] Sent data changes for {len(actions)} pairs")

    @staticmethod
    def _scrollable(widget: QtWidgets.QWidget) -> QtWidgets.QScrollArea:
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setWidget(widget)
        return scroll


class _DatabaseDetailWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._db_name = None
        self._buffers: dict[str, tuple[list[str], list[str]]] = {}

        self._source_list = QtWidgets.QListWidget()
        self._source_list.setMinimumHeight(dpix(50))
        self._source_list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self._source_list.installEventFilter(self)
        add_src_btn = QtWidgets.QPushButton()
        add_src_btn.setIcon(themed_icon("plus"))
        add_src_btn.setObjectName("folder_add_btn")
        add_src_btn.setToolTip(t("Add Source Folder"))
        add_src_btn.clicked.connect(self._add_source)
        rm_src_btn = QtWidgets.QPushButton()
        rm_src_btn.setIcon(themed_icon("minus"))
        rm_src_btn.setObjectName("remove_btn")
        rm_src_btn.setToolTip(t("Remove Selected"))
        rm_src_btn.clicked.connect(self._remove_source)

        src_btn_layout = QtWidgets.QHBoxLayout()
        src_btn_layout.addStretch()
        src_btn_layout.addWidget(add_src_btn)
        src_btn_layout.addWidget(rm_src_btn)

        src_group = QtWidgets.QGroupBox(t("Source Folders"))
        src_layout = QtWidgets.QVBoxLayout(src_group)
        src_layout.addWidget(self._source_list)
        src_layout.addLayout(src_btn_layout)

        self._ignore_list = QtWidgets.QListWidget()
        self._ignore_list.setMinimumHeight(dpix(50))
        self._ignore_list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self._ignore_list.installEventFilter(self)
        add_ign_btn = QtWidgets.QPushButton()
        add_ign_btn.setIcon(themed_icon("plus"))
        add_ign_btn.setObjectName("folder_add_btn")
        add_ign_btn.setToolTip(t("Add Ignore Folder"))
        add_ign_btn.clicked.connect(self._add_ignore)
        rm_ign_btn = QtWidgets.QPushButton()
        rm_ign_btn.setIcon(themed_icon("minus"))
        rm_ign_btn.setObjectName("remove_btn")
        rm_ign_btn.setToolTip(t("Remove Selected"))
        rm_ign_btn.clicked.connect(self._remove_ignore)

        ign_btn_layout = QtWidgets.QHBoxLayout()
        ign_btn_layout.addStretch()
        ign_btn_layout.addWidget(add_ign_btn)
        ign_btn_layout.addWidget(rm_ign_btn)

        ign_group = QtWidgets.QGroupBox(t("Ignored Folders"))
        ign_layout = QtWidgets.QVBoxLayout(ign_group)
        ign_layout.addWidget(self._ignore_list)
        ign_layout.addLayout(ign_btn_layout)

        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        self.splitter.addWidget(src_group)
        self.splitter.addWidget(ign_group)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setChildrenCollapsible(False)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.splitter)

    def _save_current_to_buffer(self):
        if self._db_name:
            sources = [self._source_list.item(i).text() for i in range(self._source_list.count())]
            ignores = [self._ignore_list.item(i).text() for i in range(self._ignore_list.count())]
            self._buffers[self._db_name] = (sources, ignores)

    def load(self, db_name: str):
        self._save_current_to_buffer()
        self._db_name = db_name
        if db_name in self._buffers:
            sources, ignores = self._buffers[db_name]
        else:
            sdb = SettingDB(setting_db_path(db_name))
            sources = list(sdb.get_all_parent_folders())
            ignores = list(sdb.get_all_ignore_folders())
            self._buffers[db_name] = (sources, ignores)
        self._source_list.clear()
        for path in sources:
            self._source_list.addItem(path)
        self._ignore_list.clear()
        for path in ignores:
            self._ignore_list.addItem(path)

    def has_changes(self, initial_paths: dict[str, tuple[list[str], list[str]]]) -> bool:
        self._save_current_to_buffer()
        for name, (buf_src, buf_ign) in self._buffers.items():
            initial = initial_paths.get(name, ([], []))
            if buf_src != initial[0] or buf_ign != initial[1]:
                return True
        return False

    def commit(self, initial_paths: dict[str, tuple[list[str], list[str]]]) -> list[str]:
        self._save_current_to_buffer()
        changed = []
        for name, (buf_src, buf_ign) in self._buffers.items():
            initial = initial_paths.get(name, ([], []))
            if buf_src == initial[0] and buf_ign == initial[1]:
                continue
            sdb = SettingDB(setting_db_path(name))
            if buf_src != initial[0]:
                sdb.sync_parent_folders(buf_src)
            if buf_ign != initial[1]:
                sdb.sync_ignore_folders(buf_ign)
            changed.append(name)
        return changed

    def revert(self, initial_paths: dict[str, tuple[list[str], list[str]]]):
        self._buffers.clear()
        for name, (sources, ignores) in initial_paths.items():
            self._buffers[name] = (list(sources), list(ignores))

    def reset(self, initial_paths: dict[str, tuple[list[str], list[str]]]):
        self._db_name = None
        self.revert(initial_paths)

    def _add_source(self):
        if not self._db_name:
            return
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            f'Add Source Folder to "{self._db_name}"',
        )
        if not folder:
            return
        existing = [self._source_list.item(i).text() for i in range(self._source_list.count())]
        if folder not in existing:
            self._source_list.addItem(folder)

    def _remove_source(self):
        for item in self._source_list.selectedItems():
            self._source_list.takeItem(self._source_list.row(item))

    def _add_ignore(self):
        if not self._db_name:
            return
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            f'Add Ignore Folder to "{self._db_name}"',
        )
        if not folder:
            return
        existing = [self._ignore_list.item(i).text() for i in range(self._ignore_list.count())]
        if folder not in existing:
            self._ignore_list.addItem(folder)

    def _remove_ignore(self):
        for item in self._ignore_list.selectedItems():
            self._ignore_list.takeItem(self._ignore_list.row(item))

    def eventFilter(self, obj, event):
        if event.type() != QtCore.QEvent.KeyPress:
            return super().eventFilter(obj, event)
        if obj not in (self._source_list, self._ignore_list):
            return super().eventFilter(obj, event)
        if event.matches(QtGui.QKeySequence.Paste):
            self._paste_paths(obj)
            return True
        if event.matches(QtGui.QKeySequence.Copy):
            self._copy_paths(obj)
            return True
        return super().eventFilter(obj, event)

    def _paste_paths(self, list_widget: QtWidgets.QListWidget):
        clipboard = QtWidgets.QApplication.clipboard()
        text = clipboard.text()
        if not text:
            return
        existing = {list_widget.item(i).text() for i in range(list_widget.count())}
        for line in text.replace(";", "\n").splitlines():
            path = line.strip()
            if not path or path in existing:
                continue
            if os.path.isdir(path):
                list_widget.addItem(path)
                existing.add(path)

    def _copy_paths(self, list_widget: QtWidgets.QListWidget):
        selected = [item.text() for item in list_widget.selectedItems()]
        if selected:
            QtWidgets.QApplication.clipboard().setText("\n".join(selected))


class DatabaseManagerPlugin(BasePanelPlugin):
    NAME = "database_manager"
    DISPLAY_NAME = "Database Manager"
    CLOSABLE = True
    PRIORITY = 0
    SOURCE = "Builtin"

    def __init__(self):
        self._widget_ref: DatabaseManagerWidget | None = None
        self._cached_state: dict = {}

    def save_ui_state(self):
        w = self._widget_ref
        if w is not None:
            try:
                return w._save_ui_state()
            except RuntimeError as e:
                AppLogger.warning("[DatabaseManager] save_state failed", exc=e)
        return dict(self._cached_state)

    def restore_ui_state(self, state):
        self._cached_state = state
        w = self._widget_ref
        if w is not None:
            try:
                w._restore_ui_state(state)
            except RuntimeError as e:
                AppLogger.warning("[DatabaseManager] restore_state failed", exc=e)

    def create_widget(self):
        w = DatabaseManagerWidget()
        self._widget_ref = w
        w.destroyed.connect(lambda: setattr(self, "_widget_ref", None))
        if self._cached_state:
            w._restore_ui_state(self._cached_state)
        return w
