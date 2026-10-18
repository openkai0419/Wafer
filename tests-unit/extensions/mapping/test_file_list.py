import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from extensions.mapping.file_list import FileList


class Owner:
    def thumbnail(self, path):
        return None

    def context_for_selection(self):
        return {"paths": ["y"]}


def make_list(qtbot):
    widget = FileList(Owner())
    qtbot.addWidget(widget)
    widget.resize(300, 400)
    widget.show()
    widget.set_rows([f"c:/{name}.png" for name in "abcdef"], np.array([2, 0, 1, 5, 4, 3]), [QtGui.QColor("red")] * 6)
    return widget


def click(qtbot, widget, position, modifiers=QtCore.Qt.NoModifier, button=QtCore.Qt.LeftButton):
    rect = widget.visualRect(widget.model().index(position, 0))
    qtbot.mouseClick(widget.viewport(), button, modifiers, rect.center())


def test_rows_follow_order_and_selection_roundtrip(qtbot):
    widget = make_list(qtbot)
    model = widget.model()
    assert [model.index(r, 0).data() for r in range(3)] == ["c.png", "a.png", "b.png"]
    emitted = []
    widget.selection_changed.connect(lambda: emitted.append(1))
    widget.select_rows([0, 1])
    assert widget.selected_rows() == [0, 1] and emitted == []
    click(qtbot, widget, 0)
    assert widget.selected_rows() == [2] and emitted
    assert widget.extend_context(None, None) == {"paths": ["y"]}
    widget.close()


def test_ctrl_toggles_and_shift_selects_a_range_in_list_order(qtbot):
    widget = make_list(qtbot)
    click(qtbot, widget, 1)
    click(qtbot, widget, 3, QtCore.Qt.ShiftModifier)
    assert widget.selected_rows() == [0, 1, 5]
    click(qtbot, widget, 1, QtCore.Qt.ControlModifier)
    assert widget.selected_rows() == [1, 5]
    click(qtbot, widget, 1, QtCore.Qt.ControlModifier)
    click(qtbot, widget, 4, QtCore.Qt.ControlModifier | QtCore.Qt.ShiftModifier)
    assert widget.selected_rows() == [0, 1, 4, 5]
    widget.close()


def test_right_click_selects_only_an_unselected_row(qtbot):
    widget = make_list(qtbot)
    widget.select_rows([0, 1])
    click(qtbot, widget, 1, button=QtCore.Qt.RightButton)
    assert widget.selected_rows() == [0, 1]
    click(qtbot, widget, 3, button=QtCore.Qt.RightButton)
    assert widget.selected_rows() == [5]
    widget.close()


def test_drag_selects_the_rows_passed(qtbot):
    widget = make_list(qtbot)
    viewport = widget.viewport()
    start = widget.visualRect(widget.model().index(0, 0)).center()
    end = widget.visualRect(widget.model().index(2, 0)).center()
    qtbot.mousePress(viewport, QtCore.Qt.LeftButton, pos=start)
    event = QtGui.QMouseEvent(QtCore.QEvent.MouseMove, QtCore.QPointF(end), QtCore.QPointF(viewport.mapToGlobal(end)), QtCore.Qt.LeftButton, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier)
    QtWidgets.QApplication.sendEvent(viewport, event)
    qtbot.mouseRelease(viewport, QtCore.Qt.LeftButton, pos=end)
    assert widget.selected_rows() == [0, 1, 2]
    widget.close()


def test_arrow_keys_move_the_selection(qtbot):
    widget = make_list(qtbot)
    click(qtbot, widget, 0)
    qtbot.keyClick(widget, QtCore.Qt.Key_Down)
    assert widget.selected_rows() == [0]
    qtbot.keyClick(widget, QtCore.Qt.Key_Down, QtCore.Qt.ShiftModifier)
    assert widget.selected_rows() == [0, 1]
    widget.close()


def test_selected_rows_are_painted_highlighted(qtbot):
    widget = make_list(qtbot)
    plain = widget.viewport().grab().toImage()
    widget.select_rows([2])
    assert widget.viewport().grab().toImage() != plain
    widget.close()


def test_update_path_emits_data_changed_for_the_row(qtbot):
    widget = FileList(Owner())
    qtbot.addWidget(widget)
    widget.set_rows(["c:/a.png", "c:/b.png", "c:/c.png"], np.array([2, 0, 1]), [QtGui.QColor("red")] * 3)
    changed = []
    widget.file_model.dataChanged.connect(lambda top, bottom, roles: changed.append(top.row()))
    widget.update_path("c:/a.png")
    widget.update_path("c:/missing.png")
    assert changed == [1]


def test_large_thumbnails_are_shrunk_to_the_icon_size(qtbot):
    class BigOwner(Owner):
        def __init__(self):
            self.pixmap = QtGui.QPixmap(512, 256)
            self.pixmap.fill(QtGui.QColor("blue"))

        def thumbnail(self, path):
            return self.pixmap

    widget = FileList(BigOwner())
    qtbot.addWidget(widget)
    widget.set_rows(["c:/a.png", "c:/b.png"], np.array([0, 1]), [QtGui.QColor("red")] * 2)
    icon = widget.model().index(0, 0).data(QtCore.Qt.DecorationRole)
    limit = widget.iconSize().width() + 1
    assert icon.width() / icon.devicePixelRatio() <= limit and icon.height() / icon.devicePixelRatio() <= limit
    assert widget.model().index(0, 0).data(QtCore.Qt.DecorationRole).cacheKey() == icon.cacheKey()


def test_set_groups_reorders_and_recolors_without_losing_the_selection(qtbot):
    widget = make_list(qtbot)
    widget.select_rows([1, 4])
    blue = QtGui.QColor("blue")
    widget.set_groups(np.array([5, 4, 3, 2, 1, 0]), [blue] * 6)
    model = widget.model()
    assert [model.index(r, 0).data() for r in range(3)] == ["f.png", "e.png", "d.png"]
    assert widget.selected_rows() == [1, 4]
    assert model.index(0, 0).data(QtCore.Qt.DecorationRole) is not None or model.colors[5] == blue
    assert widget.path_positions["c:/a.png"] == 5
    widget.close()
