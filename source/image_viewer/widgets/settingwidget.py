import sys
import os
from PySide6 import QtWidgets, QtGui, QtCore

from ..thread import main_thread
from ..viewer_settings import main_setting
from ...core.query import MetaQuery
from ...profiling import init_env
logger, profiler = init_env()

class FolderComboSignals(QtCore.QObject):
    finished = QtCore.Signal(list)

class FolderComboUpdateWorker(QtCore.QRunnable):
    def __init__(self, engine, selected_path):
        super().__init__()
        self.signals = FolderComboSignals()
        self.engine = engine
        self.selected_path = selected_path
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    @QtCore.Slot()
    def run(self):
        if self._cancelled:
            return
        results = self.engine.list_all_keys(MetaQuery(directories=self.selected_path), sort_by_freq=True, include_freq=True)
        if not self._cancelled:
            self.signals.finished.emit(results)


class CheckableCombo(QtWidgets.QToolButton):
    action_changed = QtCore.Signal()

    def __init__(self, items=None, parent=None):
        super().__init__(parent)
        self.setText("絞り込み")
        self.setPopupMode(QtWidgets.QToolButton.InstantPopup)

        self.menu = QtWidgets.QMenu(self)
        self.actions = []
        self.previous_key = main_setting.get("query/keys", ["__filepath__"])

        if items:
            for name, data in items:
                self.add_item(name, data)

        self.setMenu(self.menu)

    def add_item(self, label, data):
        action = QtGui.QAction(label, self)
        action.setData(data)
        action.setCheckable(True)
        if data in self.previous_key:
            action.setChecked(True)
        action.toggled.connect(self.on_key_changed)

        self.menu.addAction(action)
        self.actions.append(action)

    @QtCore.Slot(list)
    def remake(self, datas):
        self.setUpdatesEnabled(False)
        self.menu.clear()
        self.actions.clear()

        defi = None
        for i,( key, count) in enumerate(datas):
            self.add_item(f"{key} ({count})", key)
            if key == "__filepath__":
                defi = i
        if len(self.checked_items()) == 0:
            if len(self.actions) != 0:
                if defi is not None:
                    self.actions[defi].setChecked(True)

        self.setUpdatesEnabled(True)

    def on_key_changed(self):
        self.previous_key = self.checked_items()
        main_setting.set("query/keys", self.previous_key)
        self.action_changed.emit()

    def checked_items(self):
        return [a.data() for a in self.actions if a.isChecked()]
    
class SearchOptionPopup(QtWidgets.QDialog):
    settingchanged = QtCore.Signal()

    def __init__(self, pos_parent, parent=None):
        super().__init__(parent)
        self.pos_parent = pos_parent
        self.setWindowTitle("検索オプション")
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.Tool)
        self.setLayout(QtWidgets.QVBoxLayout())

        self.setup()
    
    def setup(self):
        layout = self.layout()

        self.query_type_combo = QtWidgets.QComboBox()
        self.sort_display_map = {
            "GLOB": "GLOB",
            "LIKE": "LIKE",
        }
        default = main_setting.get("query/query_mode", "GLOB")
        for i, (key, label) in enumerate(self.sort_display_map.items()):
            self.query_type_combo.addItem(label, userData=key)
            if default == key:
                self.query_type_combo.setCurrentIndex(i)
        self.query_type_combo.currentIndexChanged.connect(lambda: self.settingchanged.emit())

        self.keyword_group = QtWidgets.QButtonGroup()
        self.and_radio = QtWidgets.QRadioButton("AND")
        self.or_radio = QtWidgets.QRadioButton("OR")
        default = main_setting.get("query/keyword_mode", "AND")
        if default == "AND":
            self.and_radio.setChecked(True)
        else:
            self.or_radio.setChecked(True)
        self.keyword_group.addButton(self.and_radio)
        self.keyword_group.addButton(self.or_radio)
        self.and_radio.toggled.connect(lambda: self.settingchanged.emit())
        self.or_radio.toggled.connect(lambda: self.settingchanged.emit())

        self.sort_by_combo = QtWidgets.QComboBox()
        self.sort_display_map = {
            "name": "ファイルパス",
            "created": "作成日",
            "modified": "更新日",
            "size": "サイズ",
            "random": "ランダム", 
        }
        default = main_setting.get("query/sort_by", "name")
        for i, (key, label) in enumerate(self.sort_display_map.items()):
            self.sort_by_combo.addItem(label, userData=key)
            if default == key:
                self.sort_by_combo.setCurrentIndex(i)
        self.sort_by_combo.currentIndexChanged.connect(lambda: self.settingchanged.emit())

        self.order_group = QtWidgets.QButtonGroup()
        self.asc_radio = QtWidgets.QRadioButton("昇順")
        self.desc_radio = QtWidgets.QRadioButton("降順")
        default = main_setting.get("query/ascending", True)
        if default:
            self.asc_radio.setChecked(True)
        else:
            self.desc_radio.setChecked(True)
        self.asc_radio.setChecked(True)
        self.order_group.addButton(self.asc_radio)
        self.order_group.addButton(self.desc_radio)
        self.asc_radio.toggled.connect(lambda: self.settingchanged.emit())
        self.desc_radio.toggled.connect(lambda: self.settingchanged.emit())

        self.splittext = QtWidgets.QLineEdit()
        self.splittext.setText(main_setting.get("query/splittext",","))
        self.splittext.textChanged.connect(lambda: self.settingchanged.emit())

        layout.addWidget(self.query_type_combo)
        
        hlayout1 = QtWidgets.QHBoxLayout()
        layout.addLayout(hlayout1)
        hlayout1.addWidget(self.and_radio)
        hlayout1.addWidget(self.or_radio)
        
        hlayout3 = QtWidgets.QHBoxLayout()
        layout.addLayout(hlayout3)
        hlayout3.addWidget(QtWidgets.QLabel("検索用の分割文字:"))
        hlayout3.addWidget(self.splittext)
        
        layout.addWidget(QtWidgets.QLabel("ソート:"))
        layout.addWidget(self.sort_by_combo)
        hlayout2 = QtWidgets.QHBoxLayout()
        layout.addLayout(hlayout2)
        hlayout2.addWidget(self.asc_radio)
        hlayout2.addWidget(self.desc_radio)

    def move_to(self):
        button_pos = self.pos_parent.mapToGlobal(QtCore.QPoint(0, self.pos_parent.height()))
        x = button_pos.x() + self.pos_parent.rect().width() - self.rect().width()
        y = button_pos.y()
        self.move(x, y)

    def get_settings(self):
        sort_by = self.sort_by_combo.currentData()
        kwargs = {
            "query_mode": self.query_type_combo.currentData(),
            "keyword_mode":"AND" if self.and_radio.isChecked() else "OR",
            "sort_by": sort_by,
            "ascending":self.asc_radio.isChecked() if sort_by != "name" else not self.asc_radio.isChecked(),
        }
        main_setting.set("query/query_mode", kwargs["query_mode"])
        main_setting.set("query/keyword_mode", kwargs["keyword_mode"])
        main_setting.set("query/sort_by", kwargs["sort_by"])
        main_setting.set("query/ascending", self.asc_radio.isChecked())
        return kwargs
    
    def get_splittext(self): 
        return self.splittext.text() or ","

class SingleRowOption(QtWidgets.QWidget, ):
    settingchanged = QtCore.Signal()

    def __init__(self, root, parent=None):
        super().__init__(parent)
        self.root = root
        self._folder_worker = None 
        self.setup()

    def setup(self):
        # --- 検索バーとオプション ---
        self.layout = QtWidgets.QHBoxLayout()
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        self.setLayout(self.layout)
        self.search_bar = QtWidgets.QLineEdit()
        self.search_bar.setPlaceholderText("検索ワードを入力...")
        self.search_bar.setText(main_setting.get("query/keywords", None))
        self.search_bar.textChanged.connect(lambda: self.settingchanged.emit())

        self.option_button = QtWidgets.QPushButton(" 検索設定 ▼ ")
        self.option_button.clicked.connect(self.toggle_option_popup)

        self.keys_combo = QtWidgets.QComboBox()
        self.keys_combo = CheckableCombo()
        self.keys_combo.action_changed.connect(lambda: self.settingchanged.emit())

        self.run_folder_worker()

        self.layout.addWidget(self.keys_combo)
        self.layout.addWidget(self.search_bar)
        self.layout.addWidget(self.option_button)

        # --- ポップアップオプションUI ---
        self.option_popup = SearchOptionPopup(self.option_button, self)
        self.option_popup.settingchanged.connect(lambda: self.settingchanged.emit())

    @profiler.profile
    def toggle_option_popup(self):
        if self.option_popup.isVisible():
            self.option_popup.hide()
        else:
            self.option_popup.move_to()
            self.option_popup.show()

    def on_move_event(self):
        if self.option_popup and self.option_popup.isVisible():
            self.option_popup.move_to()

    def run_folder_worker(self):
        if self.root.run_folder:
            if self._folder_worker:
                self._folder_worker.cancel()
                
            self._folder_worker = FolderComboUpdateWorker(self.root.engine, self.root.folder_view.get_selected())
            self._folder_worker.signals.finished.connect(self.keys_combo.remake)
            main_thread.start(self._folder_worker,6)
            self.root.run_folder = False
    
    def get_values(self):
        kwargs = self.option_popup.get_settings()
        keys = self.keys_combo.previous_key
        kwargs.update({
            "keys": keys if keys else main_setting.get("query/keys"),
            "keywords": self.search_bar.text(),
            "splittext": self.option_popup.get_splittext()
        })
        main_setting.set("query/keywords", kwargs["keywords"])
        main_setting.set("query/splittext", kwargs["splittext"])
        return kwargs
