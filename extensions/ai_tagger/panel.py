from __future__ import annotations

import html

from PySide6 import QtWidgets, QtCore, QtGui

from wafer.plugin import BasePanelPlugin
from wafer.utils.formatting import dpix
from wafer.utils.logs import AppLogger
from wafer.utils.notifier import Notifier
from wafer.utils.paths import list_setting_db_names
from wafer.core.lang.manager import t
from wafer.core.qt.dispatcher import Dispatcher
from .settings import wd14_config

_DST = "collector-wd14"
_REQUEST_TIMEOUT = 60.0


class WD14SettingsPanelPlugin(BasePanelPlugin):
    NAME = "wd14_settings"
    DISPLAY_NAME = "WD14 Tagger Settings"
    DEFAULT_ENABLED = True
    CLOSABLE = True
    PRIORITY = 50

    def create_widget(self) -> QtWidgets.QWidget:
        return WD14SettingsWidget()


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

        preview_group = QtWidgets.QGroupBox(t("Preview"))
        self._thumb_label = QtWidgets.QLabel()
        self._thumb_label.setMinimumSize(dpix(64), dpix(64))
        self._thumb_label.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding,
        )
        self._thumb_label.setAlignment(QtCore.Qt.AlignCenter)
        self._thumb_label.setStyleSheet(
            f"border: 1px solid palette(mid); border-radius: {dpix(4)}px;"
        )

        self._tag_result_label = QtWidgets.QLabel(t("Drop a file here"))
        self._tag_result_label.setWordWrap(True)
        self._tag_result_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self._tag_result_label.setMinimumHeight(dpix(60))

        self._preview_btn = QtWidgets.QPushButton(t("Re Preview"))
        self._preview_btn.clicked.connect(self._on_preview_clicked)
        self._preview_btn.setEnabled(False)

        preview_layout = QtWidgets.QVBoxLayout(preview_group)
        preview_layout.setContentsMargins(dpix(6), dpix(6), dpix(6), dpix(6))
        preview_layout.addWidget(self._thumb_label, 1)
        preview_layout.addWidget(self._tag_result_label)
        preview_layout.addWidget(self._preview_btn)

        settings_group = QtWidgets.QGroupBox(t("Thresholds"))
        form = QtWidgets.QFormLayout(settings_group)
        form.setContentsMargins(dpix(6), dpix(6), dpix(6), dpix(6))

        self._general_spin = QtWidgets.QDoubleSpinBox()
        self._general_spin.setRange(0.001, 1.0)
        self._general_spin.setDecimals(3)
        self._general_spin.setSingleStep(0.001)
        self._general_spin.setValue(self._settings.get("general_threshold", 0.057))
        form.addRow(t("General Threshold:"), self._general_spin)

        self._character_spin = QtWidgets.QDoubleSpinBox()
        self._character_spin.setRange(0.001, 1.0)
        self._character_spin.setDecimals(3)
        self._character_spin.setSingleStep(0.01)
        self._character_spin.setValue(self._settings.get("character_threshold", 0.8))
        form.addRow(t("Character Threshold:"), self._character_spin)

        tag_group = QtWidgets.QGroupBox(t("Tag Output"))
        tag_layout = QtWidgets.QVBoxLayout(tag_group)
        tag_layout.setContentsMargins(dpix(6), dpix(6), dpix(6), dpix(6))
        tag_layout.setSpacing(dpix(4))

        self._cb_rating = QtWidgets.QCheckBox(t("Rating (top rating name)"))
        self._cb_rating.setChecked(self._settings.get("enable_rating", True))
        tag_layout.addWidget(self._cb_rating)

        self._cb_rating_score = QtWidgets.QCheckBox(t("Rating Score (confidence)"))
        self._cb_rating_score.setChecked(self._settings.get("enable_rating_score", True))
        tag_layout.addWidget(self._cb_rating_score)

        self._cb_character = QtWidgets.QCheckBox(t("Character Tags"))
        self._cb_character.setChecked(self._settings.get("enable_character", True))
        tag_layout.addWidget(self._cb_character)

        self._cb_tags = QtWidgets.QCheckBox(t("General Tags"))
        self._cb_tags.setChecked(self._settings.get("enable_tags", True))
        tag_layout.addWidget(self._cb_tags)

        device_group = QtWidgets.QGroupBox(t("Device Info"))
        self._device_label = QtWidgets.QLabel(t("Requesting..."))
        self._device_label.setWordWrap(True)
        device_layout = QtWidgets.QVBoxLayout(device_group)
        device_layout.setContentsMargins(dpix(6), dpix(6), dpix(6), dpix(6))
        device_layout.addWidget(self._device_label)

        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.addStretch()

        reset_btn = QtWidgets.QPushButton(t("Reset Defaults"))
        reset_btn.clicked.connect(self._on_reset)
        btn_layout.addWidget(reset_btn)

        save_btn = QtWidgets.QPushButton(t("Save"))
        save_btn.clicked.connect(self._on_save)
        btn_layout.addWidget(save_btn)

        revert_btn = QtWidgets.QPushButton(t("Revert"))
        revert_btn.clicked.connect(self._on_revert)
        btn_layout.addWidget(revert_btn)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(dpix(8), dpix(8), dpix(8), dpix(8))
        layout.setSpacing(dpix(6))
        layout.addWidget(preview_group, 1)
        layout.addWidget(settings_group)
        layout.addWidget(tag_group)
        layout.addWidget(device_group)
        layout.addLayout(btn_layout)

        self.setAcceptDrops(True)
        self._current_path: str = ""
        self._requesting = False
        self._device_fetched = False
        self._device_ok = False
        self._saved_settings = dict(self._settings)

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
            label_size, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation,
        )
        self._thumb_label.setPixmap(scaled)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_thumb()

    def _current_settings(self) -> dict:
        return {
            "general_threshold": self._general_spin.value(),
            "character_threshold": self._character_spin.value(),
            "enable_rating": self._cb_rating.isChecked(),
            "enable_rating_score": self._cb_rating_score.isChecked(),
            "enable_character": self._cb_character.isChecked(),
            "enable_tags": self._cb_tags.isChecked(),
        }

    def _on_preview_clicked(self):
        if not self._current_path or self._requesting:
            return
        self._requesting = True
        self._preview_btn.setEnabled(False)
        self._tag_result_label.setText(t("Generating tags..."))
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
            self._tag_result_label.setText(t("Error: {error}").format(error=error))
            return

        lines = []
        rating = result.get("rating", "")
        rating_score = result.get("rating_score", "")
        if rating:
            score_str = f" ({html.escape(rating_score)})" if rating_score else ""
            lines.append(f"<b>Rating:</b> {html.escape(rating)}{score_str}")

        character = result.get("character", {})
        if character:
            char_items = [f"{html.escape(k)} ({v:.3f})" for k, v in character.items()]
            lines.append(f"<b>Character:</b> {', '.join(char_items)}")

        general = result.get("general", {})
        if general:
            top_tags = list(general.items())[:30]
            tag_items = [f"{html.escape(k)} ({v:.3f})" for k, v in top_tags]
            lines.append(f"<b>Tags:</b> {', '.join(tag_items)}")
            remaining = len(general) - 30
            if remaining > 0:
                lines.append(f"<i>... +{remaining} more tags</i>")

        self._tag_result_label.setText("<br>".join(lines) if lines else "(no tags)")

        if not self._device_ok:
            self._request_device_info()

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
        self._cb_rating.setChecked(d["enable_rating"])
        self._cb_rating_score.setChecked(d["enable_rating_score"])
        self._cb_character.setChecked(d["enable_character"])
        self._cb_tags.setChecked(d["enable_tags"])

    def _on_revert(self):
        self._general_spin.setValue(self._saved_settings.get("general_threshold", 0.057))
        self._character_spin.setValue(self._saved_settings.get("character_threshold", 0.8))
        self._cb_rating.setChecked(self._saved_settings.get("enable_rating", True))
        self._cb_rating_score.setChecked(self._saved_settings.get("enable_rating_score", True))
        self._cb_character.setChecked(self._saved_settings.get("enable_character", True))
        self._cb_tags.setChecked(self._saved_settings.get("enable_tags", True))
        Notifier.info(t("WD14 settings reverted"))

    @staticmethod
    def _send_delete_and_recollect(
        db_names: list[str], *, delete: bool, re_collect: bool
    ):
        from wafer.core.commands.binding.instance_registry import InstanceRegistry

        node = InstanceRegistry.instance().resolve_node()
        if not node:
            AppLogger.warning("[WD14Settings] No IPC node available")
            return
        keys = ["wd14.rating", "wd14.rating_score", "wd14.character", "wd14.tags"] if delete else []
        for db in db_names:
            node.send_reliable(
                "delete.keys",
                {"keys": keys, "collector": "wd14", "re_collect": re_collect},
                dst="indexer",
                db=db,
            )


class _WD14SaveConfirmDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("Save WD14 Settings"))

        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(dpix(8))
        layout.addWidget(
            QtWidgets.QLabel(
                t("Settings have been modified.\nThis will apply to all databases.")
            )
        )

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
