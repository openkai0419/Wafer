from __future__ import annotations

from PySide6 import QtWidgets, QtCore

from wafer.plugin import BasePanelPlugin, CollectorPreviewWidget
from wafer.plugin.key_filter_dialog import FilterSaveConfirmDialog
from wafer.qt.common.dpi import dpix
from wafer.qt.common.notifier import Notifier
from wafer.core.common.paths import list_setting_db_names
from wafer.core.lang.manager import t
from .settings import TAG_MAP, florence_config

_DELETE_KEYS = [f"florence.{tag}" for tag in TAG_MAP.values()]


class FlorenceSettingsPanelPlugin(BasePanelPlugin):
    NAME = "florence_settings"
    DISPLAY_NAME = "Florence-2 Settings"
    DEFAULT_ENABLED = True
    CLOSABLE = True
    PRIORITY = 50
    plugin_config = florence_config

    def create_widget(self) -> QtWidgets.QWidget:
        return FlorenceSettingsWidget()


class FlorenceSettingsWidget(CollectorPreviewWidget):
    COLLECTOR = "florence"
    PREVIEW_TIMEOUT = 60.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = florence_config.load()

        preview_group = QtWidgets.QGroupBox(t("Preview"))

        self._result_label = QtWidgets.QLabel(t("Drop a file here"))
        self._result_label.setWordWrap(True)
        self._result_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self._result_label.setMinimumHeight(dpix(60))

        preview_layout = QtWidgets.QVBoxLayout(preview_group)
        preview_layout.setContentsMargins(dpix(6), dpix(6), dpix(6), dpix(6))
        preview_layout.addWidget(self.thumb_label, 1)
        preview_layout.addWidget(self._result_label)
        preview_layout.addWidget(self.preview_btn)

        settings_group = QtWidgets.QGroupBox(t("Settings"))
        form = QtWidgets.QFormLayout(settings_group)
        form.setContentsMargins(dpix(6), dpix(6), dpix(6), dpix(6))

        self._variant_combo = QtWidgets.QComboBox()
        self._variant_combo.addItems(["base", "large"])
        self._variant_combo.setCurrentText(self._settings.get("model_variant", "base"))
        form.addRow(t("Model:"), self._variant_combo)

        self._caption_cb = QtWidgets.QCheckBox(t("CAPTION"))
        self._caption_cb.setChecked(self._settings.get("enable_caption", True))
        form.addRow(t("Tasks:"), self._caption_cb)

        self._detailed_cb = QtWidgets.QCheckBox(t("DETAILED_CAPTION"))
        self._detailed_cb.setChecked(self._settings.get("enable_detailed", True))
        form.addRow("", self._detailed_cb)

        self._more_detailed_cb = QtWidgets.QCheckBox(t("MORE_DETAILED_CAPTION"))
        self._more_detailed_cb.setChecked(self._settings.get("enable_more_detailed", True))
        form.addRow("", self._more_detailed_cb)

        self._tokens_spin = QtWidgets.QSpinBox()
        self._tokens_spin.setRange(64, 4096)
        self._tokens_spin.setValue(self._settings.get("max_new_tokens", 1024))
        form.addRow(t("Max Tokens:"), self._tokens_spin)

        self._beams_spin = QtWidgets.QSpinBox()
        self._beams_spin.setRange(1, 10)
        self._beams_spin.setValue(self._settings.get("num_beams", 3))
        form.addRow(t("Num Beams:"), self._beams_spin)

        device_group = QtWidgets.QGroupBox(t("Device Info"))
        device_layout = QtWidgets.QVBoxLayout(device_group)
        device_layout.setContentsMargins(dpix(6), dpix(6), dpix(6), dpix(6))
        device_layout.addWidget(self.device_label)

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
        layout.addWidget(device_group)
        layout.addLayout(btn_layout)

        self._saved_settings = dict(self._settings)

    def current_settings(self) -> dict:
        return {
            "model_variant": self._variant_combo.currentText(),
            "enable_caption": self._caption_cb.isChecked(),
            "enable_detailed": self._detailed_cb.isChecked(),
            "enable_more_detailed": self._more_detailed_cb.isChecked(),
            "max_new_tokens": self._tokens_spin.value(),
            "num_beams": self._beams_spin.value(),
        }

    def on_preview_started(self):
        self._result_label.setText(t("Generating captions..."))

    def show_preview_error(self, error: str):
        self._result_label.setText(f"Error: {error}")

    def show_preview(self, result: dict):
        tags = result.get("tags", {})
        if not tags:
            self._result_label.setText("(no results)")
            return
        self._result_label.setText("<br><br>".join(f"<b>{key}:</b> {text}" for key, text in tags.items()))

    def device_text(self, device: str, name: str) -> str:
        return f"{super().device_text(device, name)}\nModel: Florence-2 (Microsoft)"

    def _on_save(self):
        values = self.current_settings()
        if values == self._saved_settings:
            return

        dlg = FilterSaveConfirmDialog(
            ["florence"],
            parent=self,
            title="Save Florence-2 Settings",
            intro="Settings have been modified.\nThis will apply to all databases.",
            delete_label="Delete existing Florence data",
            delete_default=True,
            recollect_default=True,
        )
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        do_delete = dlg.delete_data()
        do_recollect = dlg.recollect()

        florence_config.save_and_notify("florence", **values)
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

        variant = values["model_variant"]
        if do_delete:
            action = "saved + delete & recollect" if do_recollect else "saved + delete"
        else:
            action = "saved"
        Notifier.info(f"Florence-2 settings {action} (model={variant}, beams={values['num_beams']})")

    def _on_reset(self):
        self._variant_combo.setCurrentText("base")
        self._caption_cb.setChecked(True)
        self._detailed_cb.setChecked(True)
        self._more_detailed_cb.setChecked(True)
        self._tokens_spin.setValue(1024)
        self._beams_spin.setValue(3)

    def _on_revert(self):
        s = self._saved_settings
        self._variant_combo.setCurrentText(s.get("model_variant", "base"))
        self._caption_cb.setChecked(s.get("enable_caption", True))
        self._detailed_cb.setChecked(s.get("enable_detailed", True))
        self._more_detailed_cb.setChecked(s.get("enable_more_detailed", True))
        self._tokens_spin.setValue(s.get("max_new_tokens", 1024))
        self._beams_spin.setValue(s.get("num_beams", 3))

    @staticmethod
    def _send_delete_and_recollect(db_names: list[str], *, delete: bool, re_collect: bool):
        from wafer.core.db.recollect import Recollect

        keys = list(_DELETE_KEYS) if delete else []
        Recollect.reset(db_scope=list(db_names), collector="florence", keys=keys, re_collect=re_collect)
