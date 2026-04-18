from __future__ import annotations

from PySide6 import QtWidgets, QtCore, QtGui

from wafer.plugin import BasePanelPlugin
from wafer.plugin.collector.base import BaseCollector
from wafer.plugin.grid.handler import load_thumbnail
from wafer.utils.formatting import dpix
from wafer.utils.logs import AppLogger
from wafer.utils.notifier import Notifier
from wafer.utils.paths import list_setting_db_names
from wafer.core.lang.manager import t
from wafer.core.qt.dispatcher import Dispatcher
from .settings import blip_config

_DST = "collector-blip"
_REQUEST_TIMEOUT = 60.0


class BlipSettingsPanelPlugin(BasePanelPlugin):
    NAME = "blip_settings"
    DISPLAY_NAME = "BLIP Settings"
    DEFAULT_ENABLED = True
    CLOSABLE = True
    PRIORITY = 50

    def create_widget(self) -> QtWidgets.QWidget:
        return BlipSettingsWidget()


class BlipSettingsWidget(QtWidgets.QWidget):
    _preview_result = QtCore.Signal(dict)
    _device_result = QtCore.Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = blip_config.load()
        self._dispatcher = Dispatcher()
        self._preview_result.connect(self._on_preview_result)
        self._device_result.connect(self._on_device_result)

        preview_group = QtWidgets.QGroupBox(t("Preview"))
        self._thumb_label = QtWidgets.QLabel()
        self._thumb_label.setFixedSize(dpix(128), dpix(128))
        self._thumb_label.setAlignment(QtCore.Qt.AlignCenter)
        self._thumb_label.setStyleSheet(f"border: 1px solid palette(mid); border-radius: {dpix(4)}px;")

        self._caption_label = QtWidgets.QLabel(t("Drop a file here or click Preview"))
        self._caption_label.setWordWrap(True)
        self._caption_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self._caption_label.setMinimumHeight(dpix(40))

        self._preview_btn = QtWidgets.QPushButton(t("Preview"))
        self._preview_btn.clicked.connect(self._on_preview_clicked)
        self._preview_btn.setEnabled(False)

        preview_top = QtWidgets.QHBoxLayout()
        preview_top.addWidget(self._thumb_label)
        pv_right = QtWidgets.QVBoxLayout()
        pv_right.addWidget(self._caption_label, 1)
        pv_right.addWidget(self._preview_btn)
        preview_top.addLayout(pv_right, 1)

        preview_layout = QtWidgets.QVBoxLayout(preview_group)
        preview_layout.setContentsMargins(dpix(6), dpix(6), dpix(6), dpix(6))
        preview_layout.addLayout(preview_top)

        settings_group = QtWidgets.QGroupBox(t("Settings"))
        form = QtWidgets.QFormLayout(settings_group)
        form.setContentsMargins(dpix(6), dpix(6), dpix(6), dpix(6))

        self._min_spin = QtWidgets.QSpinBox()
        self._min_spin.setRange(1, 200)
        self._min_spin.setValue(self._settings.get("min_length", 5))
        form.addRow(t("Min Length:"), self._min_spin)

        self._max_spin = QtWidgets.QSpinBox()
        self._max_spin.setRange(1, 500)
        self._max_spin.setValue(self._settings.get("max_length", 50))
        form.addRow(t("Max Length:"), self._max_spin)

        self._beams_spin = QtWidgets.QSpinBox()
        self._beams_spin.setRange(1, 10)
        self._beams_spin.setValue(self._settings.get("num_beams", 3))
        form.addRow(t("Num Beams:"), self._beams_spin)

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

        save_btn = QtWidgets.QPushButton(t("Save && Re-collect"))
        save_btn.clicked.connect(self._on_save)
        btn_layout.addWidget(save_btn)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(dpix(8), dpix(8), dpix(8), dpix(8))
        layout.setSpacing(dpix(6))
        layout.addWidget(preview_group)
        layout.addWidget(settings_group)
        layout.addWidget(device_group)
        layout.addStretch()
        layout.addLayout(btn_layout)

        self.setAcceptDrops(True)
        self._current_path: str = ""
        self._requesting = False
        self._device_fetched = False

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
        qimage = load_thumbnail(path, self._thumb_label.size())
        if qimage is not None and not qimage.isNull():
            self._thumb_label.setPixmap(QtGui.QPixmap.fromImage(qimage))
        else:
            self._thumb_label.setText(t("(no preview)"))
        self._caption_label.setText(t("Click Preview to generate caption"))

    def _current_settings(self) -> dict:
        return {
            "min_length": self._min_spin.value(),
            "max_length": self._max_spin.value(),
            "num_beams": self._beams_spin.value(),
        }

    def _on_preview_clicked(self):
        if not self._current_path or self._requesting:
            return
        self._requesting = True
        self._preview_btn.setEnabled(False)
        self._caption_label.setText(t("Generating caption..."))
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
            {"action": "blip.preview", "path": path, "settings": settings},
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
            self._caption_label.setText(f"Error: {error}")
            return
        caption = result.get("caption", "")
        self._caption_label.setText(caption if caption else "(empty caption)")

    def _request_device_info(self):
        self._device_label.setText("Requesting...")
        self._dispatcher.post(self._do_device_request)

    def _do_device_request(self):
        from wafer.core.commands.binding.instance_registry import InstanceRegistry

        node = InstanceRegistry.instance().resolve_node()
        if not node:
            self._device_result.emit({"device": "unknown", "device_name": "No IPC node"})
            return
        reply = node.request(
            "service.request",
            {"action": "blip.device_info"},
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
        self._device_label.setText(f"Device: {device.upper()}  ({name})\nModel: blip-large (Salesforce)")

    def _on_save(self):
        values = self._current_settings()
        blip_config.save_and_notify("blip", **values)
        self._settings = values

        db_names = list_setting_db_names()
        if db_names:
            self._send_delete_and_recollect(db_names)

        Notifier.info(f"BLIP settings saved (min={values['min_length']}, max={values['max_length']}, beams={values['num_beams']})")

    def _on_reset(self):
        self._min_spin.setValue(5)
        self._max_spin.setValue(50)
        self._beams_spin.setValue(3)

    @staticmethod
    def _send_delete_and_recollect(db_names: list[str]):
        from wafer.core.commands.binding.instance_registry import InstanceRegistry

        node = InstanceRegistry.instance().resolve_node()
        if not node:
            AppLogger.warning("[BlipSettings] No IPC node available")
            return
        for db in db_names:
            node.send_reliable(
                "delete.keys",
                {"keys": ["blip.caption"], "collector": "blip", "re_collect": True},
                dst="indexer",
                db=db,
            )
