from PySide6.QtWidgets import (
    QWidget, QToolButton, QHBoxLayout, QSpacerItem,
    QSizePolicy, QApplication
)
from PySide6.QtGui import QIcon
import sys

class IconButtonBar(QWidget):
    def __init__(self):
        super().__init__()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)

        # 左寄せボタン
        self.left_buttons = []
        for icon_path in ["icons/open.png", "icons/save.png"]:
            btn = QToolButton()
            btn.setIcon(QIcon(icon_path))
            btn.setToolTip(icon_path)
            layout.addWidget(btn)
            self.left_buttons.append(btn)

        # スペーサー（左と右の間を埋める）
        spacer = QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum)
        layout.addItem(spacer)

        # 右寄せボタン
        self.right_buttons = []
        for icon_path in ["icons/settings.png", "icons/help.png"]:
            btn = QToolButton()
            btn.setIcon(QIcon(icon_path))
            btn.setToolTip(icon_path)
            layout.addWidget(btn)
            self.right_buttons.append(btn)

        self.setLayout(layout)

from PySide6.QtWidgets import (
    QApplication, QWidget, QScrollArea, QVBoxLayout, QGridLayout,
    QToolButton, QLabel, QSizePolicy, QStyle
)
from PySide6.QtCore import QSize
import sys

class StandardIconGallery(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Qt Standard Icon Gallery")

        layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        grid = QGridLayout(container)

        style = self.style()

        # QStyle.StandardPixmap のすべての enum メンバーを列挙
        icon_items = list(QStyle.StandardPixmap)

        row = 0
        col = 0
        max_col = 6

        for sp_enum in icon_items:
            icon = style.standardIcon(sp_enum)
            if icon.isNull():
                continue

            button = QToolButton()
            button.setIcon(icon)
            button.setIconSize(QSize(32, 32))
            button.setToolTip(sp_enum.name)
            button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

            label = QLabel(sp_enum.name)
            label.setWordWrap(True)

            grid.addWidget(button, row, col)
            grid.addWidget(label, row + 1, col)

            col += 1
            if col >= max_col:
                col = 0
                row += 2

        scroll.setWidget(container)
        layout.addWidget(scroll)
        self.setLayout(layout)

from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QScrollArea, QGridLayout,
    QLabel, QToolButton, QSizePolicy
)
from PySide6.QtGui import QIcon
from PySide6.QtCore import QSize
import sys

# 一般的なFreedesktopアイコン名一覧（よく使われるもの）
FREEDESKTOP_ICON_NAMES = [
    "accessories-calculator", "accessories-text-editor", "address-book-new",
    "application-exit", "appointment-new", "audio-volume-high", "audio-volume-low",
    "audio-volume-medium", "audio-volume-muted", "battery", "battery-caution",
    "battery-low", "call-start", "call-stop", "contact-new", "dialog-error",
    "dialog-information", "dialog-ok", "dialog-warning", "document-new",
    "document-open", "document-open-recent", "document-page-setup", "document-print",
    "document-properties", "document-revert", "document-save", "document-save-as",
    "edit-clear", "edit-copy", "edit-cut", "edit-delete", "edit-find", "edit-paste",
    "edit-redo", "edit-select-all", "edit-undo", "folder", "folder-new", "folder-open",
    "go-bottom", "go-down", "go-first", "go-home", "go-jump", "go-last",
    "go-next", "go-previous", "go-top", "go-up", "help-about", "help-contents",
    "help-faq", "insert-image", "insert-link", "insert-object", "insert-text",
    "list-add", "list-remove", "mail-forward", "mail-mark-important",
    "mail-mark-junk", "mail-mark-read", "mail-mark-unread", "mail-message-new",
    "mail-reply-all", "mail-reply-sender", "mail-send", "mail-send-receive",
    "media-eject", "media-playback-pause", "media-playback-start",
    "media-playback-stop", "media-record", "media-seek-backward",
    "media-seek-forward", "media-skip-backward", "media-skip-forward",
    "media-view-subtitles", "network-error", "network-idle", "network-offline",
    "network-receive", "network-transmit", "network-wireless", "office-calendar",
    "preferences-desktop", "preferences-desktop-accessibility",
    "preferences-desktop-font", "preferences-desktop-keyboard",
    "preferences-desktop-locale", "preferences-desktop-sound",
    "preferences-desktop-theme", "preferences-desktop-wallpaper",
    "preferences-system", "preferences-system-network", "printer",
    "process-stop", "system-lock-screen", "system-log-out",
    "system-run", "system-search", "system-shutdown", "system-software-update",
    "system-users", "user-trash", "utilities-terminal", "view-refresh",
    "view-restore", "view-sort-ascending", "view-sort-descending",
    "window-close", "zoom-fit-best", "zoom-in", "zoom-original", "zoom-out"
]

class ThemeIconGallery(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("QIcon.fromTheme() Available Icons")

        layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        grid = QGridLayout(container)

        icon_size = QSize(32, 32)
        row = 0
        col = 0
        max_col = 6

        for icon_name in sorted(FREEDESKTOP_ICON_NAMES):
            icon = QIcon.fromTheme(icon_name)
            if icon.isNull():
                continue  # この環境では利用不可

            button = QToolButton()
            button.setIcon(icon)
            button.setIconSize(icon_size)
            button.setToolTip(icon_name)
            button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

            label = QLabel(icon_name)
            label.setWordWrap(True)

            grid.addWidget(button, row, col)
            grid.addWidget(label, row + 1, col)

            col += 1
            if col >= max_col:
                col = 0
                row += 2

        scroll.setWidget(container)
        layout.addWidget(scroll)
        self.setLayout(layout)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = ThemeIconGallery()
    win.resize(900, 600)
    win.show()
    sys.exit(app.exec())