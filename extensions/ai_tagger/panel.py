from __future__ import annotations

import html

from PySide6 import QtWidgets, QtCore, QtGui

from wafer.plugin import BasePanelPlugin
from wafer.core.qt.icon_engine import themed_icon
from wafer.utils.formatting import dpix
from wafer.utils.logs import AppLogger
from wafer.utils.notifier import Notifier
from wafer.utils.paths import list_setting_db_names
from wafer.core.lang.manager import t
from wafer.core.qt.dispatcher import Dispatcher
from .settings import parse_blacklist, wd14_config

_DST = "collector-wd14"
_REQUEST_TIMEOUT = 60.0

_ALL_WD14_KEYS = [
    "wd14.rating",
    "wd14.rating_score",
    "wd14.rating_general",
    "wd14.rating_sensitive",
    "wd14.rating_questionable",
    "wd14.rating_explicit",
    "wd14.character",
    "wd14.tags",
]


class WD14SettingsPanelPlugin(BasePanelPlugin):
    NAME = "wd14_settings"
    DISPLAY_NAME = "WD14 Tagger Settings"
    DEFAULT_ENABLED = True
    CLOSABLE = True
    PRIORITY = 50

    def __init__(self):
        self._widget_ref: WD14SettingsWidget | None = None
        self._cached_state: dict = {}

    def save_state(self):
        w = self._widget_ref
        if w is not None:
            try:
                return w.save_ui_state()
            except RuntimeError as e:
                AppLogger.warning("[WD14Settings] save_state failed", exc=e)
        return dict(self._cached_state)

    def restore_state(self, state):
        self._cached_state = state
        w = self._widget_ref
        if w is not None:
            try:
                w.restore_ui_state(state)
            except RuntimeError as e:
                AppLogger.warning("[WD14Settings] restore_state failed", exc=e)

    def create_widget(self) -> QtWidgets.QWidget:
        w = WD14SettingsWidget()
        self._widget_ref = w
        w.destroyed.connect(lambda: setattr(self, "_widget_ref", None))
        if self._cached_state:
            w.restore_ui_state(self._cached_state)
        return w


class WD14SettingsWidget(QtWidgets.QWidget):
    _preview_result = QtCore.Signal(dict)
    _device_result = QtCore.Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = wd14_config.load()
        self._dispatcher = Dispatcher()
        self._preview_result.connect(self._on_preview_result)
        self._device_result.connect(self._on_device_result)

        self._original_pixmap: QtGui.QPixmap | None = None
        self._last_raw: dict | None = None
        self._blacklist: list[str] = parse_blacklist(self._settings.get("tag_blacklist", ""))

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(dpix(8), dpix(8), dpix(8), dpix(8))
        root.setSpacing(dpix(6))

        self._vsplitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        self._vsplitter.splitterMoved.connect(lambda *_: self._update_thumb())

        # ── Top pane: horizontal split (image | outputs) ──
        self._hsplitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self._hsplitter.splitterMoved.connect(lambda *_: self._update_thumb())

        from wafer.core.color.theme import ThemeManager

        muted = ThemeManager.instance().palette.text_muted

        left_container = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left_container)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(dpix(4))

        self._thumb_label = QtWidgets.QLabel(t("Drop a file here for preview"))
        self._thumb_label.setMinimumSize(dpix(64), dpix(64))
        self._thumb_label.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self._thumb_label.setAlignment(QtCore.Qt.AlignCenter)
        self._thumb_label.setStyleSheet(f"border: 1px solid palette(mid); border-radius: {dpix(4)}px; color: {muted};")
        left_layout.addWidget(self._thumb_label, 1)

        self._preview_btn = QtWidgets.QPushButton(t("Re Preview"))
        self._preview_btn.clicked.connect(self._on_preview_clicked)
        self._preview_btn.setEnabled(False)
        left_layout.addWidget(self._preview_btn)

        self._hsplitter.addWidget(left_container)

        right_scroll = QtWidgets.QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        right_inner = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right_inner)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(dpix(6))
        right_scroll.setWidget(right_inner)

        filtered_group = QtWidgets.QGroupBox(t("Output"))
        filt_group_layout = QtWidgets.QVBoxLayout(filtered_group)
        filt_group_layout.setContentsMargins(dpix(4), dpix(4), dpix(4), dpix(4))
        self._filtered_label = self._make_result_label()
        filt_group_layout.addWidget(self._filtered_label)
        right_layout.addWidget(filtered_group)

        raw_group = QtWidgets.QGroupBox(t("Raw"))
        raw_group_layout = QtWidgets.QVBoxLayout(raw_group)
        raw_group_layout.setContentsMargins(dpix(4), dpix(4), dpix(4), dpix(4))
        self._raw_label = self._make_result_label()
        self._raw_label.linkActivated.connect(self._on_raw_tag_clicked)
        raw_group_layout.addWidget(self._raw_label)
        right_layout.addWidget(raw_group)

        right_layout.addStretch()
        self._hsplitter.addWidget(right_scroll)
        self._hsplitter.setStretchFactor(0, 1)
        self._hsplitter.setStretchFactor(1, 1)

        self._vsplitter.addWidget(self._hsplitter)

        # ── Bottom pane (settings) ──
        bottom_scroll = QtWidgets.QScrollArea()
        bottom_scroll.setWidgetResizable(True)
        bottom_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        bottom_inner = QtWidgets.QWidget()
        bottom_outer_layout = QtWidgets.QVBoxLayout(bottom_inner)
        bottom_outer_layout.setContentsMargins(0, 0, 0, 0)
        bottom_outer_layout.setSpacing(0)
        bottom_scroll.setWidget(bottom_inner)

        settings_frame = QtWidgets.QFrame()
        settings_frame.setObjectName("settings_frame")
        settings_frame.setStyleSheet(f"QFrame#settings_frame {{ background: {ThemeManager.instance().palette.bg_secondary}; border: 1px solid palette(mid); border-radius: {dpix(4)}px; }}")
        bottom_layout = QtWidgets.QVBoxLayout(settings_frame)
        bottom_layout.setContentsMargins(dpix(6), dpix(6), dpix(6), dpix(6))
        bottom_layout.setSpacing(dpix(6))

        header = QtWidgets.QHBoxLayout()
        settings_label = QtWidgets.QLabel(t("Settings"))
        settings_label.setStyleSheet(f"font-weight: bold; font-size: {dpix(13)}px;")
        header.addWidget(settings_label)
        header.addStretch()
        reset_btn = QtWidgets.QPushButton(t("Reset Defaults"))
        reset_btn.setFixedHeight(dpix(24))
        reset_btn.clicked.connect(self._on_reset)
        header.addWidget(reset_btn)
        save_btn = QtWidgets.QPushButton(t("Save"))
        save_btn.setFixedHeight(dpix(24))
        save_btn.clicked.connect(self._on_save)
        header.addWidget(save_btn)
        revert_btn = QtWidgets.QPushButton(t("Revert"))
        revert_btn.setFixedHeight(dpix(24))
        revert_btn.clicked.connect(self._on_revert)
        header.addWidget(revert_btn)
        bottom_layout.addLayout(header)

        self._rating_group = QtWidgets.QGroupBox(t("Rating"))
        self._rating_group.setCheckable(True)
        self._rating_group.setChecked(self._settings.get("enable_rating", True))
        self._rating_group.toggled.connect(self._update_filtered_display)
        rating_vbox = QtWidgets.QVBoxLayout(self._rating_group)
        rating_vbox.setContentsMargins(dpix(6), dpix(6), dpix(6), dpix(6))
        rating_vbox.setSpacing(dpix(4))
        self._rating_btn_group = QtWidgets.QButtonGroup(self)
        self._rb_name = QtWidgets.QRadioButton(t("Top name only  →  rating"))
        self._rb_top = QtWidgets.QRadioButton(t("Top + score  →  rating, rating_score"))
        self._rb_all = QtWidgets.QRadioButton(t("All individual  →  rating_general, ..."))
        self._rating_btn_group.addButton(self._rb_name, 0)
        self._rating_btn_group.addButton(self._rb_top, 1)
        self._rating_btn_group.addButton(self._rb_all, 2)
        rating_vbox.addWidget(self._rb_name)
        rating_vbox.addWidget(self._rb_top)
        rating_vbox.addWidget(self._rb_all)
        mode = self._settings.get("rating_mode", "top")
        {"name": self._rb_name, "top": self._rb_top, "all": self._rb_all}.get(mode, self._rb_top).setChecked(True)
        self._rating_btn_group.idToggled.connect(lambda *_: self._update_filtered_display())
        bottom_layout.addWidget(self._rating_group)

        self._char_group = QtWidgets.QGroupBox(t("Character"))
        self._char_group.setCheckable(True)
        self._char_group.setChecked(self._settings.get("enable_character", True))
        self._char_group.toggled.connect(self._update_filtered_display)
        char_form = QtWidgets.QFormLayout(self._char_group)
        char_form.setContentsMargins(dpix(6), dpix(6), dpix(6), dpix(6))
        self._character_spin = QtWidgets.QDoubleSpinBox()
        self._character_spin.setRange(0.001, 1.0)
        self._character_spin.setDecimals(3)
        self._character_spin.setSingleStep(0.01)
        self._character_spin.setValue(self._settings.get("character_threshold", 0.8))
        self._character_spin.valueChanged.connect(self._update_filtered_display)
        char_form.addRow(t("Threshold:"), self._character_spin)
        bottom_layout.addWidget(self._char_group)

        self._gen_group = QtWidgets.QGroupBox(t("General"))
        self._gen_group.setCheckable(True)
        self._gen_group.setChecked(self._settings.get("enable_tags", True))
        self._gen_group.toggled.connect(self._update_filtered_display)
        gen_form = QtWidgets.QFormLayout(self._gen_group)
        gen_form.setContentsMargins(dpix(6), dpix(6), dpix(6), dpix(6))
        self._general_spin = QtWidgets.QDoubleSpinBox()
        self._general_spin.setRange(0.001, 1.0)
        self._general_spin.setDecimals(3)
        self._general_spin.setSingleStep(0.001)
        self._general_spin.setValue(self._settings.get("general_threshold", 0.057))
        self._general_spin.valueChanged.connect(self._update_filtered_display)
        gen_form.addRow(t("Threshold:"), self._general_spin)
        bottom_layout.addWidget(self._gen_group)

        self._bl_group = QtWidgets.QGroupBox(t("Tag Blacklist"))
        self._bl_group.setCheckable(True)
        self._bl_group.setChecked(self._settings.get("enable_blacklist", True))
        self._bl_group.toggled.connect(self._update_filtered_display)
        bl_layout = QtWidgets.QVBoxLayout(self._bl_group)
        bl_layout.setContentsMargins(dpix(6), dpix(6), dpix(6), dpix(6))
        bl_layout.setSpacing(dpix(4))
        self._chip_container = _FlowWidget()
        bl_layout.addWidget(self._chip_container)
        self._rebuild_chips()
        hint = QtWidgets.QLabel(t("Click tags in Raw preview to toggle"))
        hint.setStyleSheet("color: palette(mid);")
        bl_layout.addWidget(hint)
        clear_btn = QtWidgets.QPushButton(t("Clear All"))
        clear_btn.clicked.connect(self._clear_blacklist)
        bl_layout.addWidget(clear_btn, alignment=QtCore.Qt.AlignLeft)
        bottom_layout.addWidget(self._bl_group)

        device_group = QtWidgets.QGroupBox(t("Device Info"))
        self._device_label = QtWidgets.QLabel(t("Requesting..."))
        self._device_label.setWordWrap(True)
        device_vbox = QtWidgets.QVBoxLayout(device_group)
        device_vbox.setContentsMargins(dpix(6), dpix(6), dpix(6), dpix(6))
        device_vbox.addWidget(self._device_label)
        bottom_layout.addWidget(device_group)

        bottom_outer_layout.addWidget(settings_frame)
        bottom_outer_layout.addStretch()

        self._vsplitter.addWidget(bottom_scroll)
        self._vsplitter.setStretchFactor(0, 1)
        self._vsplitter.setStretchFactor(1, 0)
        root.addWidget(self._vsplitter, 1)

        self.setAcceptDrops(True)
        self._current_path: str = ""
        self._requesting = False
        self._device_fetched = False
        self._device_ok = False
        self._saved_settings = dict(self._settings)
        self._saved_blacklist = list(self._blacklist)

    @staticmethod
    def _make_result_label() -> QtWidgets.QLabel:
        lbl = QtWidgets.QLabel()
        lbl.setWordWrap(True)
        lbl.setTextFormat(QtCore.Qt.RichText)
        lbl.setTextInteractionFlags(QtCore.Qt.TextBrowserInteraction)
        lbl.setOpenExternalLinks(False)
        lbl.setMinimumHeight(dpix(40))
        return lbl

    @staticmethod
    def _format_kv(key: str, value_html: str) -> str:
        return (
            f"<tr>"
            f'<td style="vertical-align:top; padding-right:{dpix(8)}px; padding-bottom:{dpix(4)}px; white-space:nowrap;">'
            f"<b>{key}</b></td>"
            f'<td style="vertical-align:top; padding-bottom:{dpix(4)}px;">{value_html}</td>'
            f"</tr>"
        )

    @staticmethod
    def _wrap_kv_table(rows: list[str]) -> str:
        return f'<table cellspacing="0" cellpadding="0">{"".join(rows)}</table>'

    # ── Rating mode helpers ──

    def _rating_mode(self) -> str:
        checked = self._rating_btn_group.checkedId()
        return {0: "name", 1: "top", 2: "all"}.get(checked, "top")

    # ── Blacklist management ──

    def _toggle_blacklist(self, tag: str):
        tag = tag.strip()
        if not tag:
            return
        if tag in self._blacklist:
            self._blacklist.remove(tag)
        else:
            self._blacklist.append(tag)
        self._rebuild_chips()
        self._update_raw_display()
        self._update_filtered_display()

    def _remove_from_blacklist(self, tag: str):
        if tag in self._blacklist:
            self._blacklist.remove(tag)
            self._rebuild_chips()
            self._update_raw_display()
            self._update_filtered_display()

    def _clear_blacklist(self):
        if not self._blacklist:
            return
        self._blacklist.clear()
        self._rebuild_chips()
        self._update_raw_display()
        self._update_filtered_display()

    def _rebuild_chips(self):
        self._chip_container.clear()
        for tag in self._blacklist:
            chip = _TagChip(tag)
            chip.removed.connect(self._remove_from_blacklist)
            self._chip_container.add_widget(chip)

    # ── Preview display ──

    def _update_raw_display(self):
        raw = self._last_raw
        if raw is None:
            return
        blackset = set(self._blacklist)
        parts: list[str] = []

        ratings = raw.get("ratings", {})
        if ratings:
            items = [f"{html.escape(name)}({score:.4f})" for name, score in ratings.items()]
            parts.append(self._format_kv("Rating", ", ".join(items)))

        character = raw.get("character", {})
        if character:
            items = [f"{html.escape(k)}({v:.3f})" for k, v in character.items()]
            parts.append(self._format_kv("Character", ", ".join(items)))

        general = raw.get("general", {})
        if general:
            items = []
            for k, v in general.items():
                escaped = html.escape(k)
                if k in blackset:
                    items.append(f'<a href="bl:{escaped}" style="color:gray; text-decoration:line-through">{escaped}({v:.3f})</a>')
                else:
                    items.append(f'<a href="bl:{escaped}" style="text-decoration:none">{escaped}({v:.3f})</a>')
            parts.append(self._format_kv("Tags", ", ".join(items)))

        self._raw_label.setText(self._wrap_kv_table(parts) if parts else t("(no tags)"))

    def _update_filtered_display(self, *_args):
        raw = self._last_raw
        if raw is None:
            return
        blackset = set(self._blacklist) if self._bl_group.isChecked() else set()
        gen_th = self._general_spin.value()
        char_th = self._character_spin.value()
        parts: list[str] = []

        ratings = raw.get("ratings", {})
        if ratings and self._rating_group.isChecked():
            mode = self._rating_mode()
            if mode == "name":
                top = max(ratings, key=ratings.get)
                parts.append(self._format_kv("rating", html.escape(top)))
            elif mode == "top":
                top = max(ratings, key=ratings.get)
                parts.append(self._format_kv("rating", html.escape(top)))
                parts.append(self._format_kv("rating_score", f"{ratings[top]:.4f}"))
            elif mode == "all":
                for name, score in ratings.items():
                    parts.append(self._format_kv(f"rating_{html.escape(name)}", f"{score:.4f}"))

        character = raw.get("character", {})
        if character and self._char_group.isChecked():
            filtered = {k: v for k, v in character.items() if v >= char_th}
            if filtered:
                parts.append(self._format_kv("character", ", ".join(html.escape(k) for k in filtered)))

        general = raw.get("general", {})
        if general and self._gen_group.isChecked():
            filtered = [k for k, v in general.items() if v >= gen_th and k not in blackset]
            if filtered:
                parts.append(self._format_kv("tags", ", ".join(html.escape(k) for k in filtered)))

        self._filtered_label.setText(self._wrap_kv_table(parts) if parts else t("(no tags)"))

    # ── Events ──

    def showEvent(self, event):
        super().showEvent(event)
        if not self._device_fetched:
            self._device_fetched = True
            self._request_device_info()

    def dragEnterEvent(self, event: QtGui.QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QtGui.QDropEvent):
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if path:
                self._set_preview_path(path)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_thumb()

    def save_ui_state(self) -> dict:
        state = {}
        for key, sp in [("hsplitter", self._hsplitter), ("vsplitter", self._vsplitter)]:
            sizes = sp.sizes()
            if any(sizes):
                state[key] = sizes
        return state

    def restore_ui_state(self, state: dict):
        if "hsplitter" in state:
            self._hsplitter.setSizes(state["hsplitter"])
        if "vsplitter" in state:
            self._vsplitter.setSizes(state["vsplitter"])

    def _set_preview_path(self, path: str):
        self._current_path = path
        self._preview_btn.setEnabled(True)
        pixmap = QtGui.QPixmap(path)
        if not pixmap.isNull():
            self._original_pixmap = pixmap
            self._update_thumb()
        else:
            self._original_pixmap = None
            self._thumb_label.setText(t("(no preview)"))
        self._on_preview_clicked()

    def _update_thumb(self):
        if self._original_pixmap is None:
            return
        label_size = self._thumb_label.size()
        scaled = self._original_pixmap.scaled(
            label_size,
            QtCore.Qt.KeepAspectRatio,
            QtCore.Qt.SmoothTransformation,
        )
        self._thumb_label.setPixmap(scaled)

    # ── Settings gathering ──

    def _current_settings(self) -> dict:
        return {
            "general_threshold": self._general_spin.value(),
            "character_threshold": self._character_spin.value(),
            "enable_rating": self._rating_group.isChecked(),
            "rating_mode": self._rating_mode(),
            "enable_character": self._char_group.isChecked(),
            "enable_tags": self._gen_group.isChecked(),
            "enable_blacklist": self._bl_group.isChecked(),
            "tag_blacklist": ", ".join(self._blacklist),
        }

    # ── Preview IPC ──

    def _on_preview_clicked(self):
        if not self._current_path or self._requesting:
            return
        self._requesting = True
        self._preview_btn.setEnabled(False)
        self._raw_label.setText(t("Generating tags..."))
        self._filtered_label.setText("")
        path = self._current_path
        settings = self._current_settings()
        self._dispatcher.post(lambda: self._do_preview_request(path, settings))

    def _do_preview_request(self, path: str, settings: dict):
        from wafer.core.commands.binding.instance_registry import InstanceRegistry

        node = InstanceRegistry.instance().resolve_node()
        if not node:
            self._preview_result.emit({"error": "No IPC node"})
            return
        reply = node.request(
            "service.request",
            {"action": "wd14.preview", "path": path, "settings": settings},
            dst=_DST,
            timeout=_REQUEST_TIMEOUT,
        )
        if reply is None:
            self._preview_result.emit({"error": "Collector not running or timed out"})
        elif isinstance(reply.payload, dict):
            self._preview_result.emit(reply.payload)
        else:
            self._preview_result.emit({"error": "Unexpected response"})

    @QtCore.Slot(dict)
    def _on_preview_result(self, result: dict):
        self._requesting = False
        self._preview_btn.setEnabled(bool(self._current_path))
        error = result.get("error")
        if error:
            self._raw_label.setText(t("Error: {error}").format(error=error))
            self._filtered_label.setText("")
            return

        self._last_raw = result
        self._update_raw_display()
        self._update_filtered_display()

        if not self._device_ok:
            self._request_device_info()

    def _on_raw_tag_clicked(self, link: str):
        if link.startswith("bl:"):
            self._toggle_blacklist(html.unescape(link[3:]))

    # ── Device info ──

    def _request_device_info(self):
        self._device_label.setText(t("Requesting..."))
        self._dispatcher.post(self._do_device_request)

    def _do_device_request(self):
        from wafer.core.commands.binding.instance_registry import InstanceRegistry

        node = InstanceRegistry.instance().resolve_node()
        if not node:
            self._device_result.emit({"device": "unknown", "device_name": "No IPC node"})
            return
        reply = node.request(
            "service.request",
            {"action": "wd14.device_info"},
            dst=_DST,
            timeout=10.0,
        )
        if reply is None:
            self._device_result.emit({"device": "unknown", "device_name": "Collector not running"})
        elif isinstance(reply.payload, dict):
            self._device_result.emit(reply.payload)
        else:
            self._device_result.emit({"device": "unknown", "device_name": "Unexpected response"})

    @QtCore.Slot(dict)
    def _on_device_result(self, result: dict):
        device = result.get("device", "unknown")
        name = result.get("device_name", "")
        self._device_ok = device != "unknown"
        self._device_label.setText(t("Device: {device}  ({name})\nModel: wd-swinv2-tagger-v3 (SmilingWolf)").format(device=device.upper(), name=name))

    # ── Save / Reset / Revert ──

    def _on_save(self):
        values = self._current_settings()
        has_changes = values != self._saved_settings

        do_delete = False
        do_recollect = False
        if has_changes:
            dlg = _WD14SaveConfirmDialog(parent=self)
            if dlg.exec() != QtWidgets.QDialog.Accepted:
                return
            do_delete = dlg.delete_data()
            do_recollect = dlg.recollect()

        if has_changes:
            wd14_config.save_and_notify("wd14", **values)
        else:
            wd14_config.save(**values)
        self._settings = values
        self._saved_settings = dict(values)
        self._saved_blacklist = list(self._blacklist)

        if do_delete or do_recollect:
            db_names = list_setting_db_names()
            if db_names:
                self._send_delete_and_recollect(
                    db_names,
                    delete=do_delete,
                    re_collect=do_recollect,
                )

        if do_delete:
            action = "saved + delete & recollect" if do_recollect else "saved + delete"
        else:
            action = "saved"
        Notifier.info(f"WD14 settings {action}")

    def _on_reset(self):
        d = wd14_config._defaults
        self._general_spin.setValue(d["general_threshold"])
        self._character_spin.setValue(d["character_threshold"])
        self._rating_group.setChecked(d["enable_rating"])
        {"name": self._rb_name, "top": self._rb_top, "all": self._rb_all}[d["rating_mode"]].setChecked(True)
        self._char_group.setChecked(d["enable_character"])
        self._gen_group.setChecked(d["enable_tags"])
        self._bl_group.setChecked(d.get("enable_blacklist", True))
        self._blacklist = parse_blacklist(d["tag_blacklist"])
        self._rebuild_chips()
        self._update_raw_display()
        self._update_filtered_display()

    def _on_revert(self):
        s = self._saved_settings
        self._general_spin.setValue(s.get("general_threshold", 0.057))
        self._character_spin.setValue(s.get("character_threshold", 0.8))
        self._rating_group.setChecked(s.get("enable_rating", True))
        mode = s.get("rating_mode", "top")
        {"name": self._rb_name, "top": self._rb_top, "all": self._rb_all}.get(mode, self._rb_top).setChecked(True)
        self._char_group.setChecked(s.get("enable_character", True))
        self._gen_group.setChecked(s.get("enable_tags", True))
        self._bl_group.setChecked(s.get("enable_blacklist", True))
        self._blacklist = list(self._saved_blacklist)
        self._rebuild_chips()
        self._update_raw_display()
        self._update_filtered_display()
        Notifier.info(t("WD14 settings reverted"))

    @staticmethod
    def _send_delete_and_recollect(db_names: list[str], *, delete: bool, re_collect: bool):
        from wafer.core.commands.binding.instance_registry import InstanceRegistry

        node = InstanceRegistry.instance().resolve_node()
        if not node:
            AppLogger.warning("[WD14Settings] No IPC node available")
            return
        keys = list(_ALL_WD14_KEYS) if delete else []
        for db in db_names:
            node.send_reliable(
                "delete.keys",
                {"keys": keys, "collector": "wd14", "re_collect": re_collect},
                dst="indexer",
                db=db,
            )


# ── Flow layout for blacklist chips ──


class _FlowWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._widgets: list[QtWidgets.QWidget] = []
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)

    def add_widget(self, w: QtWidgets.QWidget):
        w.setParent(self)
        self._widgets.append(w)
        w.show()
        self._relayout()

    def clear(self):
        for w in self._widgets:
            w.setParent(None)
            w.deleteLater()
        self._widgets.clear()
        self._relayout()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout()

    def _relayout(self):
        spacing = dpix(4)
        x, y, row_h = 0, 0, 0
        width = self.width() or dpix(200)
        for w in self._widgets:
            hint = w.sizeHint()
            if x + hint.width() > width and x > 0:
                x = 0
                y += row_h + spacing
                row_h = 0
            w.move(x, y)
            w.resize(hint)
            x += hint.width() + spacing
            row_h = max(row_h, hint.height())
        total = y + row_h if self._widgets else 0
        self.setMinimumHeight(total)

    def sizeHint(self):
        self._relayout()
        return QtCore.QSize(self.width(), self.minimumHeight())


class _TagChip(QtWidgets.QFrame):
    removed = QtCore.Signal(str)

    def __init__(self, tag: str, parent=None):
        super().__init__(parent)
        self._tag = tag
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.setStyleSheet(f"_TagChip {{ border: 1px solid palette(mid); border-radius: {dpix(8)}px; padding: {dpix(1)}px {dpix(4)}px; }}")
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(dpix(4), dpix(1), dpix(2), dpix(1))
        lay.setSpacing(dpix(2))
        lbl = QtWidgets.QLabel(tag)
        lay.addWidget(lbl)
        btn = QtWidgets.QToolButton()
        btn.setIcon(themed_icon("cross"))
        btn.setAutoRaise(True)
        btn.setFixedSize(dpix(16), dpix(16))
        btn.setIconSize(QtCore.QSize(dpix(10), dpix(10)))
        btn.clicked.connect(lambda: self.removed.emit(self._tag))
        lay.addWidget(btn)

    def sizeHint(self):
        return super().sizeHint()


class _WD14SaveConfirmDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("Save WD14 Settings"))

        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(dpix(8))
        layout.addWidget(QtWidgets.QLabel(t("Settings have been modified.\nThis will apply to all databases.")))

        self._delete_cb = QtWidgets.QCheckBox(t("Delete existing WD14 data"))
        self._delete_cb.setChecked(True)
        self._recollect_cb = QtWidgets.QCheckBox(t("Re-collect after deletion"))
        self._recollect_cb.setChecked(True)
        self._delete_cb.toggled.connect(self._recollect_cb.setEnabled)
        layout.addWidget(self._delete_cb)
        layout.addWidget(self._recollect_cb)

        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.addStretch()
        save_btn = QtWidgets.QPushButton(t("Save"))
        cancel_btn = QtWidgets.QPushButton(t("Cancel"))
        save_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def delete_data(self) -> bool:
        return self._delete_cb.isChecked()

    def recollect(self) -> bool:
        return self._delete_cb.isChecked() and self._recollect_cb.isChecked()
