from PySide6.QtCore import Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QPushButton, QTabWidget, QVBoxLayout
from ..common.funcs import uipx
from .base_setting import SettingsTabBase
from ..lang.manager import TranslatorMixin

class SettingsWindow(QDialog, TranslatorMixin):
    settings_applied = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.t.tr('Settings'))
        self.setModal(False)
        self.resize(500, 400)
        self.tabs = QTabWidget()
        self.tab_widgets = []
        self.ok_button = QPushButton('OK')
        self.cancel_button = QPushButton(self.t.tr('Cancel'))
        self.apply_button = QPushButton(self.t.tr('Apply'))
        self.ok_button.clicked.connect(self.on_ok_clicked)
        self.cancel_button.clicked.connect(self.on_cancel_clicked)
        self.apply_button.clicked.connect(self.on_apply_clicked)
        psize = uipx(4)
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        button_layout.setSpacing(psize)
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.addWidget(self.ok_button)
        button_layout.addWidget(self.cancel_button)
        button_layout.addWidget(self.apply_button)
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(psize * 1.5)
        main_layout.setContentsMargins(psize * 2, psize, psize * 2, psize * 3)
        main_layout.addWidget(self.tabs)
        main_layout.addLayout(button_layout)

    def add_tab(self, widget):
        self.tabs.addTab(widget, widget.name)
        self.tab_widgets.append(widget)
        widget.installEventFilter(self)

    def apply_all(self):
        for tab in self.tab_widgets:
            if tab.has_unsaved_changes():
                tab.apply_settings()
        self.settings_applied.emit()

    def on_ok_clicked(self):
        self.apply_all()
        self.close()

    def on_cancel_clicked(self):
        self.close()

    def on_apply_clicked(self):
        self.apply_all()
