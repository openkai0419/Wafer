from PySide6 import QtWidgets
from extensions.ffmpeg.meta_panel import FFmpegMetaPanelPlugin
from wafer.ui.panel.searchable_meta_widget import SearchableMetaWidget


def test_plugin_attributes():
    plugin = FFmpegMetaPanelPlugin()
    assert plugin.PREFIX == "ffmpeg"
    assert plugin.NAME == "ffmpeg_meta_panel"
    assert plugin.DEFAULT_ENABLED is True


def test_create_widget_and_update(qtbot):
    plugin = FFmpegMetaPanelPlugin()
    parent = QtWidgets.QWidget()
    qtbot.addWidget(parent)
    w = plugin.create_card(parent)
    assert plugin._widget is not None
    assert isinstance(plugin._widget, SearchableMetaWidget)
    plugin.update_data({"codec": "h264", "duration": "120.5"})
    assert plugin._widget._data == {"codec": "h264", "duration": "120.5"}


def test_update_data_reflects_in_widget(qtbot):
    plugin = FFmpegMetaPanelPlugin()
    parent = QtWidgets.QWidget()
    qtbot.addWidget(parent)
    plugin.create_card(parent)
    plugin.update_data({"bitrate": "5000", "fps": "30"})
    assert "bitrate" in plugin._widget._data
    assert "fps" in plugin._widget._data
