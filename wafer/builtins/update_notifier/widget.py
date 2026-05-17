from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from ..._version import __version__
from ...core.color.theme import ThemeManager
from ...core.commands.binding.instance_registry import InstanceRegistry
from ...core.lang.manager import t
from ...core.qt.dispatcher import Dispatcher
from ...core.qt.icon_engine import themed_icon
from ...core.qt.thread import utility_pool
from ...plugin.panel.base import BasePanelPlugin
from ...utils.formatting import dpix
from ...utils.logs import AppLogger
from ...utils.markdown_browser import MarkdownBrowser
from . import state
from .service import UpdateCheckResult, UpdateInfo, check_for_updates, validate_external_url


PANEL_DISPLAY_NAME = "Update"


def _button(icon_name: str, tooltip: str, text: str = "") -> QtWidgets.QPushButton:
    button = QtWidgets.QPushButton(text)
    button.setIcon(themed_icon(icon_name))
    button.setToolTip(tooltip)
    button.setCursor(QtCore.Qt.PointingHandCursor)
    return button


def _build_stylesheet() -> str:
    p = ThemeManager.instance().palette
    r = dpix(4)
    return f"""
        QLabel#update_title {{
            font-size: {dpix(16)}px;
            color: {p.text_primary};
        }}
        QLabel#update_title[updateAvailable="true"] {{
            font-size: {dpix(22)}px;
            color: {p.accent};
        }}
        QLabel#update_title[updateAvailable="false"] {{
            font-size: {dpix(16)}px;
            color: {p.text_primary};
        }}
        QLabel#update_status {{
            color: {p.text_secondary};
        }}
        QLabel#update_status[updateAvailable="true"] {{
            color: {p.accent};
            font-weight: bold;
        }}
        QLabel#update_status[updateAvailable="false"] {{
            color: {p.text_secondary};
            font-weight: normal;
        }}
        QLabel#update_meta {{
            color: {p.text_primary};
        }}
        QPushButton#primary_update_btn {{
            background: {p.accent};
            color: {p.accent_text};
            border: none;
            border-radius: {r}px;
            padding: {dpix(4)}px {dpix(10)}px;
            font-weight: bold;
        }}
        QPushButton#primary_update_btn:hover {{
            background: {p.bg_hover};
        }}
        QPushButton#secondary_update_btn {{
            background: {p.bg_secondary};
            border: 1px solid {p.border_default};
            border-radius: {r}px;
            padding: {dpix(4)}px {dpix(10)}px;
        }}
        QPushButton#secondary_update_btn:hover {{
            background: {p.bg_hover};
        }}
    """


class UpdateNotifierWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._dispatcher = Dispatcher(utility_pool, parent=self)
        self._result: UpdateCheckResult | None = None
        self._info: UpdateInfo | None = None
        self._check_in_progress = False
        self._refresh_requested = False

        self.setStyleSheet(_build_stylesheet())

        self._title = QtWidgets.QLabel("")
        self._title.setObjectName("update_title")
        self._title.hide()
        self._status = QtWidgets.QLabel("")
        self._status.setObjectName("update_status")
        self._status.setWordWrap(True)
        self._status.hide()

        self._current_label = QtWidgets.QLabel()
        self._latest_label = QtWidgets.QLabel()
        self._published_label = QtWidgets.QLabel()
        for label in (self._current_label, self._latest_label, self._published_label):
            label.setObjectName("update_meta")
            label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)

        self._auto_check = QtWidgets.QCheckBox(t("Check for updates on startup"))
        self._auto_check.setChecked(state.is_auto_check_enabled())
        self._auto_check.toggled.connect(state.set_auto_check_enabled)

        self._browser = MarkdownBrowser(self)
        self._browser.setMinimumHeight(dpix(120))

        self._open_btn = _button("external_link", t("Go to download page"), t("Go to Download"))
        self._open_btn.setObjectName("secondary_update_btn")
        self._open_btn.clicked.connect(self._open_download_page)

        self._skip_btn = _button("check", t("Skip automatic notification until the next version"), t("Skip until next version"))
        self._skip_btn.setObjectName("secondary_update_btn")
        self._skip_btn.clicked.connect(self._skip_this_version)

        self._later_btn = _button("history", t("Remind me later"), t("Remind Me Later"))
        self._later_btn.setObjectName("secondary_update_btn")
        self._later_btn.clicked.connect(self._close_panel)

        self._check_btn = _button("refresh", t("Check for updates"))
        self._check_btn.setObjectName("secondary_update_btn")
        self._check_btn.setFixedWidth(dpix(28))
        self._check_btn.clicked.connect(lambda: self.check_now(explicit=True))

        button_row = QtWidgets.QHBoxLayout()
        button_row.setSpacing(dpix(6))
        button_row.addWidget(self._check_btn)
        button_row.addStretch()
        button_row.addWidget(self._open_btn)
        button_row.addWidget(self._skip_btn)
        button_row.addWidget(self._later_btn)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(dpix(6), dpix(6), dpix(6), dpix(6))
        layout.setSpacing(dpix(8))
        layout.addWidget(self._title)
        layout.addWidget(self._status)
        layout.addWidget(self._latest_label)
        layout.addWidget(self._published_label)
        layout.addWidget(self._current_label)
        layout.addWidget(self._browser, 1)
        layout.addWidget(self._auto_check)
        layout.addSpacing(dpix(4))
        layout.addLayout(button_row)

        self._set_initial_state()

    def _set_initial_state(self) -> None:
        self._current_label.setText(t("Current : {version}", version=__version__))
        self._latest_label.setText(t("Latest : not checked"))
        self._published_label.setText(t("Published : -"))
        self._browser.set_markdown("")
        self._title.setText("...")
        self._title.hide()
        self._status.setText("...")
        self._status.hide()
        self._set_update_available(False)
        self._open_btn.setObjectName("secondary_update_btn")
        self._open_btn.setEnabled(False)
        self._skip_btn.setEnabled(False)
        self._later_btn.setEnabled(True)

    def showEvent(self, event):
        super().showEvent(event)
        QtCore.QTimer.singleShot(0, self.refresh_if_needed)

    def refresh_if_needed(self) -> None:
        if self._info is not None or self._check_in_progress or self._refresh_requested:
            return
        self._refresh_requested = True
        self.check_now(explicit=False)

    def check_now(self, *, explicit: bool = True) -> None:
        if self._check_in_progress:
            return
        self._check_in_progress = True
        self._refresh_requested = True
        self._title.hide()
        self._status.setText(t("Checking for updates..."))
        self._status.show()
        self._set_update_available(False)
        self._check_btn.setEnabled(False)

        def task():
            result = check_for_updates(current_version=__version__)
            self._dispatcher.invoke(lambda: self.apply_check_result(result, explicit=explicit))

        self._dispatcher.post(task, priority=5)

    def apply_check_result(self, result: UpdateCheckResult, *, explicit: bool = False) -> None:
        self._result = result
        self._check_in_progress = False
        self._check_btn.setEnabled(True)
        if result.info is None:
            self._info = None
            self._title.hide()
            self._status.setText(t("Update check failed: {error}", error=result.error or "unknown error"))
            self._status.show()
            self._set_update_available(False)
            self._latest_label.setText(t("Latest : not available"))
            self._published_label.setText(t("Published : -"))
            self._browser.set_markdown(result.error or "")
            self._open_btn.setEnabled(False)
            self._skip_btn.setEnabled(False)
            return

        self.set_update_info(result.info, explicit=explicit)

    def set_update_info(self, info: UpdateInfo, *, explicit: bool = False, record_state: bool = True) -> None:
        self._info = info
        self._check_in_progress = False
        self._refresh_requested = True
        self._check_btn.setEnabled(True)
        if record_state:
            state.record_latest_result(info.latest_version)
        self._title.setText(
            t("New Update Available: v{version}", version=info.latest_version)
            if info.is_newer
            else t("Up to Date")
        )
        self._title.show()
        self._set_update_available(info.is_newer)
        status = ""
        if info.from_cache:
            status = t("cached result")
        self._status.setText(status)
        self._status.setVisible(bool(status))
        self._current_label.setText(t("Current : {version}", version=info.current_version))
        self._latest_label.setText(t("Latest : {version}", version=info.latest_version))
        self._published_label.setText(t("Published : {date}", date=info.published_at) if info.published_at else "")
        self._browser.set_markdown(info.changelog_markdown or info.release_notes or "")
        self._open_btn.setEnabled(bool(info.download_url or info.release_url))
        self._open_btn.setObjectName("primary_update_btn" if info.is_newer else "secondary_update_btn")
        self._refresh_button_style(self._open_btn)
        self._skip_btn.setEnabled(info.is_newer)
        self._later_btn.setEnabled(True)

    def _set_update_available(self, available: bool) -> None:
        self._title.setProperty("updateAvailable", "true" if available else "false")
        self._status.setProperty("updateAvailable", "true" if available else "false")
        self._refresh_button_style(self._title)
        self._refresh_button_style(self._status)
        title_font = self._title.font()
        title_font.setWeight(QtGui.QFont.Weight.ExtraBold if available else QtGui.QFont.Weight.Normal)
        self._title.setFont(title_font)

    @staticmethod
    def _refresh_button_style(widget: QtWidgets.QWidget) -> None:
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()

    def _open_download_page(self) -> None:
        if self._info is None:
            return
        url = validate_external_url(self._info.release_url or self._info.download_url)
        if not url:
            AppLogger.warning("Update download page was blocked because the URL is not trusted")
            return
        QtGui.QDesktopServices.openUrl(QtCore.QUrl(url))

    def _skip_this_version(self) -> None:
        if self._info is None:
            return
        state.skip_version(self._info.latest_version)
        self._close_panel()

    def _close_panel(self) -> None:
        main_window = InstanceRegistry.instance().get_one("MainWindow")
        manager = getattr(main_window, "_layout_manager", None) if main_window else None
        if manager and manager.is_panel_visible(PANEL_DISPLAY_NAME):
            manager.toggle_panel(PANEL_DISPLAY_NAME)


class UpdateNotifierPlugin(BasePanelPlugin):
    NAME = "update_notifier"
    DISPLAY_NAME = PANEL_DISPLAY_NAME
    PRIORITY = 32
    SOURCE = "Builtin"

    def startup(self) -> None:
        from .startup import schedule_startup_update_check

        schedule_startup_update_check()

    def create_widget(self):
        return UpdateNotifierWidget()
