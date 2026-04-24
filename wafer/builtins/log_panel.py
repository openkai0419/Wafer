from __future__ import annotations

import os
from datetime import datetime

from PySide6 import QtCore, QtGui, QtWidgets

from ..plugin.panel.base import BasePanelPlugin
from ..utils.formatting import dpix
from ..core.lang.manager import t
from ..core.color.theme import ThemeManager

MAX_LOG_LINES = 2000

LEVELS = ["debug", "info", "warning", "error", "critical"]

_LOG_FONT = QtGui.QFont("Consolas", 9)
_LOG_FONT.setStyleHint(QtGui.QFont.Monospace)


def _level_colors() -> dict[str, QtGui.QColor]:
    p = ThemeManager.instance().palette
    return {
        "critical": QtGui.QColor(p.error),
        "error": QtGui.QColor(p.error),
        "warning": QtGui.QColor(p.warning),
        "info": QtGui.QColor(p.text_primary),
        "debug": QtGui.QColor(p.text_tertiary),
    }


def _log_style() -> str:
    p = ThemeManager.instance().palette
    return f"QPlainTextEdit {{ background-color: {p.bg_primary}; color: {p.text_primary}; }}"


def _parse_src(src: str) -> tuple[str, str]:
    parts = src.rsplit("-", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return src, ""


def _level_index(level: str) -> int:
    try:
        return LEVELS.index(level)
    except ValueError:
        return 0


class _LogTab(QtWidgets.QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumBlockCount(MAX_LOG_LINES)
        self.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        self.setFont(_LOG_FONT)
        self.setStyleSheet(_log_style())

    def apply_theme(self) -> None:
        self.setStyleSheet(_log_style())

    def append_entry(self, entry: dict, auto_scroll: bool):
        colors = _level_colors()
        color = colors.get(entry["level"], colors["info"])
        level_tag = entry["level"].upper().ljust(8)
        src_tag = f"[{entry['src']}]"
        line = f"{entry['time']} {level_tag} {src_tag} {entry['text']}"

        cursor = self.textCursor()
        cursor.movePosition(QtGui.QTextCursor.End)
        fmt = QtGui.QTextCharFormat()
        fmt.setForeground(color)
        cursor.insertText(line + "\n", fmt)

        if auto_scroll:
            self.setTextCursor(cursor)
            self.ensureCursorVisible()


class LogPanel(QtWidgets.QWidget):
    _instance: LogPanel | None = None
    _log_signal = QtCore.Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        LogPanel._instance = self
        self._log_signal.connect(self._on_log_signal)
        self._entries: list[dict] = []
        self._src_tabs: dict[str, _LogTab] = {}
        self._known_dbs: set[str] = set()
        self._build_ui()
        ThemeManager.instance().on_theme_changed.connect(self._on_theme_changed)

    def _on_theme_changed(self, _palette=None) -> None:
        self._all_tab.apply_theme()
        for tab in self._src_tabs.values():
            tab.apply_theme()
        self._rebuild_all_tabs()

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        toolbar = QtWidgets.QHBoxLayout()
        toolbar.setContentsMargins(dpix(4), dpix(2), dpix(4), dpix(2))

        self._level_combo = QtWidgets.QComboBox()
        self._level_combo.addItems(["ALL", "DEBUG", "INFO", "WARNING", "ERROR"])
        self._level_combo.setCurrentText("DEBUG")
        self._level_combo.currentTextChanged.connect(self._rebuild_all_tabs)
        toolbar.addWidget(QtWidgets.QLabel(t("Level:")))
        toolbar.addWidget(self._level_combo)

        self._db_combo = QtWidgets.QComboBox()
        self._db_combo.addItem("ALL")
        self._db_combo.currentTextChanged.connect(self._rebuild_all_tabs)
        toolbar.addWidget(QtWidgets.QLabel(t("DB:")))
        toolbar.addWidget(self._db_combo)

        toolbar.addStretch()

        self._auto_scroll = QtWidgets.QCheckBox(t("Auto Scroll"))
        self._auto_scroll.setChecked(True)
        toolbar.addWidget(self._auto_scroll)

        clear_btn = QtWidgets.QPushButton(t("Clear"))
        clear_btn.clicked.connect(self._clear)
        toolbar.addWidget(clear_btn)

        layout.addLayout(toolbar)

        self._tab_widget = QtWidgets.QTabWidget()
        self._tab_widget.setTabsClosable(False)
        self._all_tab = _LogTab()
        self._tab_widget.addTab(self._all_tab, t("All"))
        layout.addWidget(self._tab_widget)

    def append_log(self, level: str, text: str, src: str = "", db: str = ""):
        src = src or f"viewer-{os.getpid()}"
        entry = {
            "time": datetime.now().strftime("%H:%M:%S.%f")[:-3],
            "level": level,
            "text": text,
            "src": src,
            "db": db,
        }
        self._entries.append(entry)
        if len(self._entries) > MAX_LOG_LINES * 2:
            self._entries = self._entries[-MAX_LOG_LINES:]

        if db and db not in self._known_dbs:
            self._known_dbs.add(db)
            self._db_combo.addItem(db)

        if src not in self._src_tabs:
            tab = _LogTab()
            self._src_tabs[src] = tab
            role, pid = _parse_src(src)
            label = f"{role}:{pid}" if pid else src
            self._tab_widget.addTab(tab, label)

        if self._matches_filter(entry):
            auto = self._auto_scroll.isChecked()
            self._all_tab.append_entry(entry, auto)
            self._src_tabs[src].append_entry(entry, auto)

    def _matches_filter(self, entry: dict) -> bool:
        level_filter = self._level_combo.currentText()
        if level_filter != "ALL":
            if _level_index(entry["level"]) < _level_index(level_filter.lower()):
                return False

        db_filter = self._db_combo.currentText()
        return not (db_filter != "ALL" and entry["db"] != db_filter)

    def _rebuild_all_tabs(self):
        self._all_tab.clear()
        for tab in self._src_tabs.values():
            tab.clear()
        auto = self._auto_scroll.isChecked()
        for entry in self._entries:
            if self._matches_filter(entry):
                self._all_tab.append_entry(entry, auto)
                tab = self._src_tabs.get(entry["src"])
                if tab:
                    tab.append_entry(entry, auto)

    def _clear(self):
        self._entries.clear()
        self._all_tab.clear()
        for tab in self._src_tabs.values():
            tab.clear()

    def _on_log_signal(self, level: str, text: str):
        self.append_log(level, text)

    @classmethod
    def instance(cls) -> LogPanel | None:
        return cls._instance


class LogPanelPlugin(BasePanelPlugin):
    NAME = "log"
    DISPLAY_NAME = "Log"
    PRIORITY = 0
    DEFAULT_ENABLED = False
    SOURCE = "Builtin"

    def create_widget(self):
        from ..utils.logs import AppLogger

        panel = LogPanel()
        AppLogger.on_debug.connect(lambda t: panel._log_signal.emit("debug", t))
        AppLogger.on_info.connect(lambda t: panel._log_signal.emit("info", t))
        AppLogger.on_warning.connect(lambda t: panel._log_signal.emit("warning", t))
        AppLogger.on_error.connect(lambda t: panel._log_signal.emit("error", t))
        AppLogger.on_critical.connect(lambda t: panel._log_signal.emit("critical", t))
        return panel
