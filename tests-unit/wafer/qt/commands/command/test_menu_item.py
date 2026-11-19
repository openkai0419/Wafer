from PySide6 import QtCore, QtWidgets

from wafer.qt.commands.command.menu_item import CommandMenuRow


def test_the_options_button_is_drawn_as_a_hollow_square(qtbot):
    menu = QtWidgets.QMenu()
    qtbot.addWidget(menu)
    row = CommandMenuRow(menu, "Row", "", None, True, menu)

    row.ensure_initialized()

    assert row._options_btn.text() == ""
    image = row._options_btn.icon().pixmap(QtCore.QSize(16, 16)).toImage()
    w, h = image.width(), image.height()
    opaque = {(x, y) for x in range(w) for y in range(h) if image.pixelColor(x, y).alpha() > 128}
    xs = sorted({x for x, _ in opaque})
    ys = sorted({y for _, y in opaque})
    left, right, top, bottom = xs[0], xs[-1], ys[0], ys[-1]

    assert right - left == bottom - top
    assert all((x, top) in opaque and (x, bottom) in opaque for x in range(left, right + 1))
    assert all((left, y) in opaque and (right, y) in opaque for y in range(top, bottom + 1))
    assert ((left + right) // 2, (top + bottom) // 2) not in opaque
