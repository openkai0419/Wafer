from __future__ import annotations

from typing import ClassVar

from PySide6 import QtCore, QtGui, QtWidgets

from ...core.lang.manager import t
from ...qt.common.dispatcher import Dispatcher
from ...qt.common.dpi import dpix
from ...qt.common.image import numpy_to_qimage
from ...qt.common.thread import utility_pool
from ..imageloader.handler import image_loader_resolver


class CollectorPreviewWidget(QtWidgets.QWidget):
    COLLECTOR: ClassVar[str] = ""
    PREVIEW_TIMEOUT: ClassVar[float] = 60.0
    DEVICE_TIMEOUT: ClassVar[float] = 10.0

    _preview_result = QtCore.Signal(object)
    _device_result = QtCore.Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dispatcher = Dispatcher(utility_pool, parent=self)
        self._preview_result.connect(self._on_preview_result)
        self._device_result.connect(self._on_device_result)
        self._original_pixmap: QtGui.QPixmap | None = None
        self._current_path = ""
        self._requesting = False
        self._preview_pending = False
        self._device_fetched = False
        self._device_ok = False

        self.thumb_label = QtWidgets.QLabel()
        self.thumb_label.setMinimumSize(dpix(64), dpix(64))
        self.thumb_label.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.thumb_label.setAlignment(QtCore.Qt.AlignCenter)
        self.thumb_label.setStyleSheet(f"border: 1px solid palette(mid); border-radius: {dpix(4)}px;")

        self.preview_btn = QtWidgets.QPushButton(t("Re Preview"))
        self.preview_btn.clicked.connect(self.request_preview)
        self.preview_btn.setEnabled(False)

        self.device_label = QtWidgets.QLabel(t("Requesting..."))
        self.device_label.setWordWrap(True)

        self.setAcceptDrops(True)

    def current_settings(self) -> dict:
        raise NotImplementedError

    def on_preview_started(self):
        pass

    def show_preview(self, result: dict):
        raise NotImplementedError

    def show_preview_error(self, error: str):
        raise NotImplementedError

    def device_text(self, device: str, name: str) -> str:
        return t("Device: {device}  ({name})").format(device=device.upper(), name=name)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._device_fetched:
            self._device_fetched = True
            self.request_device_info()

    def dragEnterEvent(self, event: QtGui.QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QtGui.QDropEvent):
        urls = event.mimeData().urls()
        path = urls[0].toLocalFile() if urls else ""
        if path:
            self.set_preview_path(path)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_thumb()

    def set_preview_path(self, path: str):
        self._current_path = path
        self.preview_btn.setEnabled(True)
        self._dispatcher.post(lambda: self._load_preview_thumb(path))
        self.request_preview()

    def _load_preview_thumb(self, path: str):
        arr = image_loader_resolver.load(path, 512)
        qimage = numpy_to_qimage(arr) if arr is not None else None
        self._dispatcher.invoke(lambda: self._show_preview_thumb(path, qimage))

    def _show_preview_thumb(self, path: str, qimage: QtGui.QImage | None):
        if path != self._current_path:
            return
        if qimage is None:
            self._original_pixmap = None
            self.thumb_label.setText(t("(no preview)"))
            return
        self._original_pixmap = QtGui.QPixmap.fromImage(qimage)
        self.update_thumb()

    def update_thumb(self):
        if self._original_pixmap is None:
            return
        scaled = self._original_pixmap.scaled(self.thumb_label.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
        self.thumb_label.setPixmap(scaled)

    def request_preview(self):
        if not self._current_path:
            return
        if self._requesting:
            self._preview_pending = True
            return
        self._requesting = True
        self.preview_btn.setEnabled(False)
        self.on_preview_started()
        path = self._current_path
        settings = self.current_settings()
        self._dispatcher.post(lambda: self._do_preview_request(path, settings))

    def _do_preview_request(self, path: str, settings: dict):
        self._preview_result.emit(self._request("preview", {"path": path, "settings": settings}, self.PREVIEW_TIMEOUT))

    @QtCore.Slot(object)
    def _on_preview_result(self, result: dict):
        self._requesting = False
        self.preview_btn.setEnabled(bool(self._current_path))
        if self._preview_pending:
            self._preview_pending = False
            self.request_preview()
            return
        error = result.get("error")
        if error:
            self.show_preview_error(error)
            return
        self.show_preview(result)
        if not self._device_ok:
            self.request_device_info()

    def request_device_info(self):
        self.device_label.setText(t("Requesting..."))
        self._dispatcher.post(self._do_device_request)

    def _do_device_request(self):
        result = self._request("device_info", {}, self.DEVICE_TIMEOUT)
        error = result.get("error")
        self._device_result.emit({"device": "unknown", "device_name": error} if error else result)

    @QtCore.Slot(object)
    def _on_device_result(self, result: dict):
        device = result.get("device", "unknown")
        self._device_ok = device != "unknown"
        self.device_label.setText(self.device_text(device, result.get("device_name", "")))

    def _request(self, action: str, payload: dict, timeout: float) -> dict:
        from ...qt.commands.binding.instance_registry import InstanceRegistry

        node = InstanceRegistry.instance().resolve_node()
        if not node:
            return {"error": "No IPC node"}
        reply = node.request(
            "service.request",
            {"action": f"{self.COLLECTOR}.{action}", **payload},
            dst=f"collector-{self.COLLECTOR}",
            timeout=timeout,
        )
        if reply is None:
            return {"error": "Collector not running or timed out"}
        if not isinstance(reply.payload, dict):
            return {"error": "Unexpected response"}
        return reply.payload
