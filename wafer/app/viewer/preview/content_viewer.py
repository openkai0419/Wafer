from PySide6 import QtCore, QtWidgets

from ....utils.formatting import dpix
from ....core.color.theme import ThemeManager
from ....core.lang.manager import t
from ....plugin.viewer.handler import viewer_resolver
from .image_viewer import ImageDisplayWidget


_DEFAULT_WIDGET_NAME = "_default"
_PLACEHOLDER_PAGE = "_placeholder"


class ContentViewerWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._stack = QtWidgets.QStackedWidget(self)
        self._stack.setMinimumSize(dpix(200), dpix(200))

        self._placeholder = QtWidgets.QLabel()
        self._placeholder.setAlignment(QtCore.Qt.AlignCenter)
        self._placeholder.setWordWrap(True)
        self._update_placeholder_style()
        self._stack.addWidget(self._placeholder)

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

        self._current_plugin_name: str = _PLACEHOLDER_PAGE
        self._stack.setCurrentWidget(self._placeholder)

        ThemeManager.instance().on_theme_changed.connect(lambda _: self._update_placeholder_style())

    def _update_placeholder_style(self):
        p = ThemeManager.instance().palette
        fs = dpix(14)
        self._placeholder.setText(t("No file selected"))
        self._placeholder.setStyleSheet(f"QLabel {{ color: {p.text_muted}; font-size: {fs}px; }}")

    def clear(self):
        if self._current_plugin_name == _DEFAULT_WIDGET_NAME:
            self.image_viewer.clear()
        elif self._current_plugin_name != _PLACEHOLDER_PAGE:
            viewer_resolver.deactivate(self._current_plugin_name)
        self._stack.setCurrentWidget(self._placeholder)
        self._current_plugin_name = _PLACEHOLDER_PAGE

    def switch_to(self, plugin_name: str):
        if plugin_name == self._current_plugin_name:
            return
        prev_name = self._current_plugin_name
        if prev_name == _DEFAULT_WIDGET_NAME:
            self.image_viewer.clear()
        elif prev_name != _PLACEHOLDER_PAGE:
            viewer_resolver.deactivate(prev_name)
        widget = self._widget_map.get(plugin_name)
        if widget is None:
            plugin_name = _DEFAULT_WIDGET_NAME
            widget = self.image_viewer
        self._stack.setCurrentWidget(widget)
        self._current_plugin_name = plugin_name
        if plugin_name != _DEFAULT_WIDGET_NAME:
            viewer_resolver.activate(plugin_name)
