from PySide6 import QtWidgets

from wafer.qt.commands.command.menu_item import CommandMenuRow


def test_the_options_button_is_an_icon_not_a_glyph(qtbot):
    menu = QtWidgets.QMenu()
    qtbot.addWidget(menu)
    row = CommandMenuRow(menu, "Row", "", None, True, menu)

    row.ensure_initialized()

    assert row._options_btn.text() == ""
    assert not row._options_btn.icon().isNull()
