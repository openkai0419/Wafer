from PySide6 import QtGui, QtWidgets

import wafer.utils.recent_colors as recent_colors


def _ensure_app():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    return app


def test_color_picker_widget_set_get_roundtrip():
    _ensure_app()
    from wafer.ui.widgets.color_picker import ColorPickerWidget

    w = ColorPickerWidget(initial="#336699", with_alpha=False)
    assert w.color().name() == "#336699"
    w.set_color("#a0b0c0")
    assert w.color().name() == "#a0b0c0"


def test_color_picker_widget_alpha_disabled_forces_opaque():
    _ensure_app()
    from wafer.ui.widgets.color_picker import ColorPickerWidget

    w = ColorPickerWidget(initial=QtGui.QColor(10, 20, 30, 128), with_alpha=False)
    assert w.color().alpha() == 255


def test_color_picker_widget_alpha_enabled_preserves_alpha():
    _ensure_app()
    from wafer.ui.widgets.color_picker import ColorPickerWidget

    c = QtGui.QColor(10, 20, 30, 128)
    w = ColorPickerWidget(initial=c, with_alpha=True)
    assert w.color().alpha() == 128


def test_color_picker_widget_color_changed_signal():
    _ensure_app()
    from wafer.ui.widgets.color_picker import ColorPickerWidget

    w = ColorPickerWidget(initial="#000000")
    received = []
    w.colorChanged.connect(lambda c: received.append(c.name()))
    w.set_color("#ff0000")
    assert received and received[-1] == "#ff0000"


def test_color_picker_widget_hex_invalid_resets():
    _ensure_app()
    from wafer.ui.widgets.color_picker import ColorPickerWidget

    w = ColorPickerWidget(initial="#112233")
    w._hex_edit.setText("not-a-color")
    w._on_hex_changed()
    assert w.color().name() == "#112233"


def test_recent_colors_add_dedup_and_limit(tmp_path, monkeypatch):
    _ensure_app()
    store = {}
    monkeypatch.setattr(recent_colors.app_settings, "get", lambda key, default=None, value_type=None: store.get(key, default))
    monkeypatch.setattr(recent_colors.app_settings, "save_immediate", lambda key, value: store.__setitem__(key, value))

    for i in range(20):
        recent_colors.add(f"#{i:02x}0000", scope="test")
    items = recent_colors.load("test")
    assert len(items) == recent_colors.MAX_RECENT
    assert items[0] == "#130000"

    recent_colors.add("#130000", scope="test")
    items = recent_colors.load("test")
    assert items.count("#130000") == 1
    assert items[0] == "#130000"


def test_color_picker_dialog_returns_color_on_accept():
    _ensure_app()
    from wafer.ui.widgets.color_picker import ColorPickerDialog

    dlg = ColorPickerDialog(initial="#445566")
    dlg._picker.set_color("#aabbcc")
    dlg.accept()
    assert dlg.color().name() == "#aabbcc"
