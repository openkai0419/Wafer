from PySide6 import QtCore, QtWidgets

from wafer.qt.widgets import FlowLayout


class WrappingBox(QtWidgets.QWidget):
    def __init__(self, width: int, area: int):
        super().__init__()
        self.natural_width, self.area = width, area

    def sizeHint(self):
        return QtCore.QSize(self.natural_width, self.area // self.natural_width)

    def minimumSizeHint(self):
        return QtCore.QSize(10, 10)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self.area // max(width, 1)


def fixed(width: int, height: int = 20) -> QtWidgets.QWidget:
    widget = QtWidgets.QWidget()
    widget.setFixedSize(width, height)
    return widget


def test_items_wrap_onto_the_next_line(qtbot):
    host = QtWidgets.QWidget()
    qtbot.addWidget(host)
    layout = FlowLayout(host, spacing=5)
    for _ in range(3):
        layout.addWidget(fixed(40))
    assert layout.heightForWidth(200) == 20
    assert layout.heightForWidth(90) == 45


def test_hidden_items_take_no_space(qtbot):
    host = QtWidgets.QWidget()
    qtbot.addWidget(host)
    layout = FlowLayout(host, spacing=5)
    first, hidden, last = fixed(40), fixed(300), fixed(40)
    for widget in (first, hidden, last):
        layout.addWidget(widget)
    hidden.hide()
    host.show()
    assert layout.heightForWidth(100) == 20
    assert layout.minimumSize().width() == 40
    assert layout.single_line_size() == QtCore.QSize(85, 20)


def test_an_item_wider_than_the_line_is_narrowed_and_grows_taller(qtbot):
    host = QtWidgets.QWidget()
    qtbot.addWidget(host)
    layout = FlowLayout(host, spacing=5)
    box = WrappingBox(400, 400 * 20)
    layout.addWidget(box)
    host.resize(100, 300)
    host.show()
    layout.setGeometry(QtCore.QRect(0, 0, 100, 300))
    assert box.geometry() == QtCore.QRect(0, 0, 100, 80)
    assert layout.heightForWidth(100) == 80


def test_insert_widget_places_it_at_the_index(qtbot):
    host = QtWidgets.QWidget()
    qtbot.addWidget(host)
    layout = FlowLayout(host, spacing=5)
    first, last, middle = fixed(10), fixed(20), fixed(30)
    layout.addWidget(first)
    layout.addWidget(last)
    layout.insertWidget(layout.indexOf(last), middle)
    assert [layout.itemAt(i).widget() for i in range(layout.count())] == [first, middle, last]
    assert middle.parent() is host
