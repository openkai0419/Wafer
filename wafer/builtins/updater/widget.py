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
from . import stage, state
from .service import UpdateCheckResult, UpdateInfo, check_for_updates, validate_external_url
from .stage import StageCancelled
from .versioning import normalize_version


PANEL_DISPLAY_NAME = "Update"


def _hex_rgb(hex_color: str) -> str:
    return f"{int(hex_color[1:3], 16)},{int(hex_color[3:5], 16)},{int(hex_color[5:7], 16)}"


def _phase_status(phase: str) -> str:
    if phase == "extract":
        return t("Extracting update...")
    if phase == "verify":
        return t("Verifying update...")
    if phase == "prepare":
        return t("Preparing to apply...")
    return t("Finalizing...")


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
        QLabel#update_progress_label {{
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
        QPushButton#primary_update_btn:disabled {{
            background: {p.bg_secondary};
            color: {p.text_muted};
            border: 1px solid {p.border_default};
            font-weight: normal;
        }}
        QPushButton#primary_update_btn[actionState="cancel"] {{
            background: rgba({_hex_rgb(p.warning)}, 0.15);
            color: {p.warning};
            border: 1px solid rgba({_hex_rgb(p.warning)}, 0.4);
        }}
        QPushButton#primary_update_btn[actionState="cancel"]:hover {{
            background: rgba({_hex_rgb(p.warning)}, 0.28);
        }}
        QPushButton#primary_update_btn[actionState="cancelling"]:disabled {{
            background: {p.bg_secondary};
            color: {p.warning};
            border: 1px solid rgba({_hex_rgb(p.warning)}, 0.3);
            font-weight: bold;
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
        QPushButton#secondary_update_btn:disabled {{
            background: {p.bg_secondary};
            color: {p.text_muted};
            border: 1px solid {p.border_default};
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
        self._stage_in_progress = False
        self._cancel_requested = False
        self._stage_phase = "download"
        self._last_percent = -1

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

        self._primary_btn = _button("save", t("Download the update in the background"), t("Download Update"))
        self._primary_btn.setObjectName("primary_update_btn")
        self._primary_btn.setProperty("actionState", "disabled")
        self._primary_btn.clicked.connect(self._on_primary_action_clicked)

        self._progress = QtWidgets.QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setTextVisible(False)
        self._progress.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)

        self._progress_label = QtWidgets.QLabel()
        self._progress_label.setObjectName("update_progress_label")

        self._progress_row = QtWidgets.QWidget()
        progress_row = QtWidgets.QHBoxLayout(self._progress_row)
        progress_row.setContentsMargins(0, 0, 0, 0)
        progress_row.setSpacing(dpix(6))
        progress_row.addWidget(self._progress, 1)
        progress_row.addWidget(self._progress_label)
        self._progress_row.hide()

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
        button_row.addWidget(self._primary_btn)
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
        layout.addWidget(self._progress_row)
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
        self._open_btn.hide()
        self._skip_btn.setEnabled(False)
        self._later_btn.setEnabled(True)
        self._primary_btn.show()
        self._progress_row.hide()
        self._update_action_buttons()

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
            result = check_for_updates()
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
            self._update_action_buttons()
            return

        self.set_update_info(result.info, explicit=explicit)

    def set_update_info(self, info: UpdateInfo, *, explicit: bool = False, record_state: bool = True) -> None:
        self._info = info
        self._check_in_progress = False
        self._refresh_requested = True
        self._check_btn.setEnabled(True)
        if record_state:
            state.record_latest_result(info.latest_version)
        self._title.setText(t("New Update Available: v{version}", version=info.latest_version) if info.is_newer else t("Up to Date"))
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
        self._browser.set_markdown(info.release_notes or "")
        self._skip_btn.setEnabled(info.is_newer)
        self._later_btn.setEnabled(True)
        self._update_action_buttons()

    def _update_action_buttons(self) -> None:
        self._primary_btn.setVisible(True)
        self._open_btn.setVisible(False)
        self._open_btn.setEnabled(False)

        state_name = self._primary_action_state()
        if state_name == "download_page":
            self._primary_btn.setVisible(False)
            self._open_btn.setVisible(True)
            self._open_btn.setEnabled(True)
            self._status.setText(t("This release must be updated manually. Open the download page to get it."))
            self._status.show()
            return

        if state_name == "git":
            self._apply_primary_button(
                text=t("Use git pull instead"),
                tooltip=t("This installation is managed by git. Run git pull to update."),
                enabled=False,
                icon_name="refresh",
                action_state="guidance",
            )
            return

        if state_name == "restart":
            self._apply_primary_button(
                text=t("Restart to Update"),
                tooltip=t("Restart Wafer to apply the downloaded update"),
                enabled=True,
                icon_name="refresh",
                action_state="restart",
            )
            return

        if state_name == "cancel":
            self._apply_primary_button(
                text=t("Cancel Download"),
                tooltip=t("Cancel the update download"),
                enabled=True,
                icon_name="save",
                action_state="cancel",
            )
            return

        if state_name == "cancelling":
            self._apply_primary_button(
                text=t("Cancel Download"),
                tooltip=t("Cancelling the update download"),
                enabled=False,
                icon_name="save",
                action_state="cancelling",
            )
            return

        if state_name == "finalizing":
            self._apply_primary_button(
                text=t("Restart to Update"),
                tooltip=t("Finishing the update; you can restart once it is ready"),
                enabled=False,
                icon_name="refresh",
                action_state="disabled",
            )
            return

        tooltip = t("Download the update in the background") if state_name == "download" else t("No update is available for download")
        if self._check_in_progress:
            tooltip = t("Checking for updates...")
        self._apply_primary_button(
            text=t("Download Update"),
            tooltip=tooltip,
            enabled=state_name == "download",
            icon_name="save",
            action_state="download" if state_name == "download" else "disabled",
        )

    def _primary_action_state(self) -> str:
        if stage.update_mode() != "portable":
            return "git"
        info = self._info
        newer = bool(info and info.is_newer)
        staged = stage.staged_version()
        ready = bool(newer and staged and staged == normalize_version(info.latest_version))
        if ready:
            return "restart"
        if self._stage_in_progress:
            if self._stage_phase != "download":
                return "finalizing"
            return "cancelling" if self._cancel_requested else "cancel"
        if newer:
            return "download" if info.supports_in_app_update else "download_page"
        return "disabled-download"

    def _apply_primary_button(
        self,
        *,
        text: str,
        tooltip: str,
        enabled: bool,
        icon_name: str,
        action_state: str,
    ) -> None:
        self._primary_btn.setText(text)
        self._primary_btn.setToolTip(tooltip)
        self._primary_btn.setEnabled(enabled)
        self._primary_btn.setIcon(themed_icon(icon_name))
        self._primary_btn.setProperty("actionState", action_state)
        self._primary_btn.setCursor(QtCore.Qt.PointingHandCursor if enabled else QtCore.Qt.ArrowCursor)
        self._refresh_button_style(self._primary_btn)

    def _on_primary_action_clicked(self) -> None:
        state_name = self._primary_action_state()
        if state_name == "restart":
            self._restart_to_apply()
            return
        if state_name == "cancel":
            self._cancel_requested = True
            self._progress.setRange(0, 0)
            self._progress_label.setText(t("Cancelling..."))
            self._update_action_buttons()
            return
        if state_name != "download":
            return
        info = self._info
        if info is None or not info.is_newer:
            return
        self._stage_in_progress = True
        self._cancel_requested = False
        self._stage_phase = "download"
        self._last_percent = -1
        self._check_btn.setEnabled(False)
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress_label.setText("0%")
        self._progress_row.show()
        self._status.hide()
        self._update_action_buttons()
        tag, version = info.tag_name, info.latest_version

        def task():
            try:
                staged = stage.stage_update(tag, version, on_progress=self._on_download_progress, on_phase=self._on_stage_phase, is_cancelled=lambda: self._cancel_requested)
                self._dispatcher.invoke(lambda: self._on_stage_finished(staged, ""))
            except StageCancelled:
                self._dispatcher.invoke(lambda: self._on_stage_finished("", t("Download cancelled")))
            except Exception as e:
                AppLogger.error(f"[Updater] Failed to stage update: {e}", exc=e)
                self._dispatcher.invoke(lambda e=e: self._on_stage_finished("", str(e)))

        self._dispatcher.post(task, priority=5)

    def _on_download_progress(self, done: int, total: int) -> None:
        percent = int(done * 100 / total) if total > 0 else 0
        if percent != self._last_percent:
            self._last_percent = percent
            self._dispatcher.invoke(lambda p=percent: self._set_download_percent(p))

    def _set_download_percent(self, percent: int) -> None:
        self._progress.setValue(percent)
        self._progress_label.setText(f"{percent}%")

    def _on_stage_phase(self, phase: str) -> None:
        self._dispatcher.invoke(lambda: self._apply_stage_phase(phase))

    def _apply_stage_phase(self, phase: str) -> None:
        if not self._stage_in_progress or self._cancel_requested:
            return
        self._stage_phase = phase
        if phase == "download":
            self._progress.setRange(0, 100)
            self._progress_label.setText(f"{max(self._last_percent, 0)}%")
        else:
            self._progress.setRange(0, 0)
            self._progress_label.setText(_phase_status(phase))
        self._status.hide()
        self._progress_row.show()
        self._update_action_buttons()

    def _on_stage_finished(self, version: str, error: str) -> None:
        self._stage_in_progress = False
        self._cancel_requested = False
        self._stage_phase = "download"
        self._check_btn.setEnabled(True)
        self._progress.setRange(0, 100)
        self._progress_label.setText("")
        self._progress_row.hide()
        self._status.setText(t("Update v{version} is ready. Restart to apply", version=version) if version else error)
        self._status.setVisible(bool(version or error))
        self._update_action_buttons()

    def _restart_to_apply(self) -> None:
        main_window = InstanceRegistry.instance().get_one("MainWindow")
        if main_window is None:
            return
        if not stage.restart_into_launcher(main_window):
            AppLogger.warning("[Updater] Restart was requested but no staged update is available")
            self._update_action_buttons()

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
    NAME = "updater"
    DISPLAY_NAME = PANEL_DISPLAY_NAME
    PRIORITY = 32
    SOURCE = "Builtin"

    def startup(self) -> None:
        from .startup import schedule_startup_update_check

        schedule_startup_update_check()

    def create_widget(self):
        return UpdateNotifierWidget()
