from PySide6 import QtWidgets

from ....utils.formatting import dpix
from ....plugin.viewer.handler import viewer_resolver
from .image_viewer import ImageDisplayWidget


_DEFAULT_WIDGET_NAME = "_default"


class ContentViewerWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._stack = QtWidgets.QStackedWidget(self)
        self._stack.setMinimumSize(dpix(200), dpix(200))

        self.image_viewer = ImageDisplayWidget()
        self._stack.addWidget(self.image_viewer)
        self._widget_map: dict[str, QtWidgets.QWidget] = {_DEFAULT_WIDGET_NAME: self.image_viewer}

        for name, plugin in viewer_resolver.viewer_plugins().items():
            self._stack.addWidget(plugin.widget)
            self._widget_map[name] = plugin.widget
        self._stack.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._stack)

        self._current_plugin_name: str = _DEFAULT_WIDGET_NAME

    def switch_to(self, plugin_name: str):
        if plugin_name == self._current_plugin_name:
            return
        prev_name = self._current_plugin_name
        if prev_name == _DEFAULT_WIDGET_NAME:
            self.image_viewer.clear()
        else:
            viewer_resolver.deactivate(prev_name)
        widget = self._widget_map.get(plugin_name)
        if widget is None:
            plugin_name = _DEFAULT_WIDGET_NAME
            widget = self.image_viewer
        self._stack.setCurrentWidget(widget)
        self._current_plugin_name = plugin_name
        if plugin_name != _DEFAULT_WIDGET_NAME:
            viewer_resolver.activate(plugin_name)
