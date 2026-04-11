import pytest
from PySide6 import QtWidgets
from extensions.exiftool.meta_panel import ExifToolMetaPanelPlugin, _ExifToolMetaWidget


def test_plugin_attributes():
    plugin = ExifToolMetaPanelPlugin()
    assert plugin.PREFIX == "exiftool"
    assert plugin.NAME == "exiftool_meta_panel"
    assert plugin.DEFAULT_ENABLED is True


def test_create_widget_and_update(qtbot):
    plugin = ExifToolMetaPanelPlugin()
    parent = QtWidgets.QWidget()
    qtbot.addWidget(parent)
    w = plugin.create_widget(parent)
    assert isinstance(w, _ExifToolMetaWidget)
    plugin.update_data({"width": "100", "height": "200"})
    assert w._data == {"width": "100", "height": "200"}


def test_filter_by_key(qtbot):
    w = _ExifToolMetaWidget()
    qtbot.addWidget(w)
    w.set_data({"width": "100", "height": "200", "model": "Canon"})
    w._apply_filter("width")
    assert w._filtered_keys == ["width"]


def test_filter_by_value(qtbot):
    w = _ExifToolMetaWidget()
    qtbot.addWidget(w)
    w.set_data({"width": "100", "height": "200", "model": "Canon"})
    w._apply_filter("canon")
    assert w._filtered_keys == ["model"]


def test_filter_empty_shows_all(qtbot):
    w = _ExifToolMetaWidget()
    qtbot.addWidget(w)
    data = {"width": "100", "height": "200"}
    w.set_data(data)
    w._apply_filter("")
    assert set(w._filtered_keys) == set(data.keys())


def test_status_label_visibility(qtbot):
    w = _ExifToolMetaWidget()
    qtbot.addWidget(w)
    w.set_data({"width": "100", "height": "200", "model": "Canon"})
    w._apply_filter("")
    assert w._status_label.isHidden()
    w._apply_filter("width")
    assert not w._status_label.isHidden()
    assert "1 / 3" in w._status_label.text()
