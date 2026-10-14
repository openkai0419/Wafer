import numpy as np
import pytest
from PySide6 import QtCore, QtGui, QtWidgets

from extensions.mapping.map_view import MapView
from extensions.mapping.session import MapDiagnostics, MapResult


class Owner:
    def __init__(self):
        self.requested = []
        self.hovers = []

    def thumbnail(self, path):
        self.requested.append(path)
        return None

    def context_for_selection(self):
        return {"paths": ["x"]}

    def handle_drag_enter(self, event):
        event.ignore()

    def handle_drop(self, event):
        event.ignore()

    def show_hover(self, path, global_pos):
        self.hovers.append(path)

    def hide_hover(self):
        self.hovers.append(None)


def result(count=6, labels=True, outlier_rows=()):
    positions = np.array([[i / (count - 1), (i % 2) * 1.0] for i in range(count)], dtype=np.float32)
    unset = np.zeros(count, dtype=bool)
    unset[-1] = True
    positions[-1] = np.nan
    group = np.array([0, 0, 0, 1, 1, -1], dtype=np.int32)[:count] if labels else None
    return MapResult(
        [f"c:/{i}.png" for i in range(count)],
        positions,
        np.isin(np.arange(count), list(outlier_rows)),
        unset,
        group,
        {0: ["cat"], 1: ["dog"]} if labels else {},
        np.arange(count),
        MapDiagnostics(),
    )


@pytest.fixture()
def view(qtbot):
    owner = Owner()
    widget = MapView(owner)
    qtbot.addWidget(widget)
    widget.resize(400, 400)
    widget.show()
    yield widget
    widget.close()


def colors(count):
    return [QtGui.QColor.fromHsvF(i / count, 0.5, 0.9) for i in range(count)]


def test_show_result_creates_items_and_labels(view):
    view.show_result(result(), colors(6), show_groups=True, keep_view=False)
    assert len(view.point_items()) == 6
    assert [label.text for label in view.label_items()] == ["cat", "dog"]
    view.show_result(result(), colors(6), show_groups=False, keep_view=True)
    assert view.label_items() == []


def test_select_rows_is_silent_and_select_group_emits(view, qtbot):
    view.show_result(result(), colors(6), show_groups=True, keep_view=False)
    emitted = []
    view.selection_changed.connect(lambda: emitted.append(1))
    view.select_rows([1, 2])
    assert view.selected_rows() == [1, 2] and emitted == []
    view.select_group(0)
    assert view.selected_rows() == [0, 1, 2] and emitted


def test_rubber_band_drag_selects(view, qtbot):
    view.show_result(result(), colors(6), show_groups=False, keep_view=False)
    viewport = view.viewport()
    start = view.mapFromScene(QtCore.QPointF(0, 0)) - QtCore.QPoint(15, 15)
    end = view.mapFromScene(QtCore.QPointF(400, 1000)) + QtCore.QPoint(15, 15)
    qtbot.mousePress(viewport, QtCore.Qt.LeftButton, pos=start)
    qtbot.mouseMove(viewport, pos=end)
    qtbot.mouseRelease(viewport, QtCore.Qt.LeftButton, pos=end)
    assert {0, 1, 2} <= set(view.selected_rows())


def test_thumbnails_requested_only_when_zoomed(view, qtbot):
    view.show_result(result(), colors(6), show_groups=False, keep_view=False)
    view.set_thumbnail_zoom(2.0)
    view.viewport().repaint()
    assert view.owner.requested == []
    view.set_thumbnail_zoom(0.5)
    view.viewport().repaint()
    assert view.owner.requested


def test_extend_context_delegates_to_owner(view):
    assert view.extend_context(None, None) == {"paths": ["x"]}


def point_pos(view, row):
    return view.mapFromScene(view.point_items()[row].pos())


def test_drag_starting_on_a_point_selects_several(view, qtbot):
    view.show_result(result(), colors(6), show_groups=False, keep_view=False)
    viewport = view.viewport()
    start = point_pos(view, 0)
    end = view.mapFromScene(QtCore.QPointF(400, 1000)) + QtCore.QPoint(15, 15)
    assert view.itemAt(start) is view.point_items()[0]
    emitted = []
    view.selection_changed.connect(lambda: emitted.append(view.selected_rows()))
    qtbot.mousePress(viewport, QtCore.Qt.LeftButton, pos=start)
    qtbot.mouseMove(viewport, pos=end)
    qtbot.mouseRelease(viewport, QtCore.Qt.LeftButton, pos=end)
    assert {0, 1, 2} <= set(view.selected_rows())
    assert emitted[-1] == view.selected_rows()


def test_click_on_a_point_selects_only_it(view, qtbot):
    view.show_result(result(), colors(6), show_groups=False, keep_view=False)
    view.select_rows([0, 2])
    emitted = []
    view.selection_changed.connect(lambda: emitted.append(view.selected_rows()))
    qtbot.mouseClick(view.viewport(), QtCore.Qt.LeftButton, pos=point_pos(view, 1))
    assert view.selected_rows() == [1]
    assert emitted == [[1]]
    qtbot.mouseClick(view.viewport(), QtCore.Qt.LeftButton, pos=QtCore.QPoint(2, 2))
    assert view.selected_rows() == []
    assert emitted[-1] == []


def test_ctrl_click_toggles_a_point(view, qtbot):
    view.show_result(result(), colors(6), show_groups=False, keep_view=False)
    view.select_rows([0])
    ctrl = QtCore.Qt.ControlModifier
    qtbot.mouseClick(view.viewport(), QtCore.Qt.LeftButton, ctrl, point_pos(view, 1))
    assert view.selected_rows() == [0, 1]
    qtbot.mouseClick(view.viewport(), QtCore.Qt.LeftButton, ctrl, point_pos(view, 1))
    assert view.selected_rows() == [0]


def test_clicking_a_group_label_selects_the_group(view, qtbot):
    view.show_result(result(), colors(6), show_groups=True, keep_view=False)
    label = view.label_items()[1]
    qtbot.mouseClick(view.viewport(), QtCore.Qt.LeftButton, pos=view.mapFromScene(label.pos()) + QtCore.QPoint(0, int(label.offset())))
    assert view.selected_rows() == [3, 4]


def render_point(view, row):
    image = QtGui.QImage(48, 48, QtGui.QImage.Format_ARGB32)
    image.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(image)
    painter.translate(24, 24)
    view.paint_point(painter, view.point_items()[row])
    painter.end()
    return image


@pytest.mark.parametrize("thumbnail_zoom", [2.0, 0.5])
def test_outlier_is_drawn_with_a_ring_even_when_unselected(view, thumbnail_zoom):
    view.set_thumbnail_zoom(thumbnail_zoom)
    view.show_result(result(), colors(6), show_groups=False, keep_view=False)
    plain = render_point(view, 1)
    view.show_result(result(outlier_rows=[1]), colors(6), show_groups=False, keep_view=True)
    assert render_point(view, 1) != plain


def test_image_scale_changes_extent_and_clamps(view):
    view.show_result(result(), colors(6), show_groups=False, keep_view=False)
    base = view.item_extent()
    view.set_image_scale(2.0)
    assert view.item_extent() == pytest.approx(base * 2)
    view.set_image_scale(99)
    assert view.image_scale == 4.0
    view.set_image_scale(0)
    assert view.image_scale == 0.5


def test_ctrl_wheel_does_not_zoom_map(view):
    view.show_result(result(), colors(6), show_groups=False, keep_view=False)
    before = view.transform().m11()
    position = QtCore.QPointF(10, 10)
    event = QtGui.QWheelEvent(position, position, QtCore.QPoint(), QtCore.QPoint(0, 120), QtCore.Qt.NoButton, QtCore.Qt.ControlModifier, QtCore.Qt.NoScrollPhase, False)
    view.wheelEvent(event)
    assert view.transform().m11() == before


def test_plain_wheel_zooms_map(view):
    view.show_result(result(), colors(6), show_groups=False, keep_view=False)
    before = view.transform().m11()
    position = QtCore.QPointF(10, 10)
    event = QtGui.QWheelEvent(position, position, QtCore.QPoint(), QtCore.QPoint(0, 120), QtCore.Qt.NoButton, QtCore.Qt.NoModifier, QtCore.Qt.NoScrollPhase, False)
    view.wheelEvent(event)
    assert view.transform().m11() > before


def test_group_mode_expands_click_and_rows(view, qtbot):
    view.show_result(result(), colors(6), show_groups=True, keep_view=False)
    view.set_selection_mode("group")
    qtbot.mouseClick(view.viewport(), QtCore.Qt.LeftButton, pos=point_pos(view, 0))
    assert view.selected_rows() == [0, 1, 2]
    assert view.expand_to_groups([3, 5]) == [3, 4, 5]


def test_group_mode_ctrl_click_toggles_whole_group(view, qtbot):
    view.show_result(result(), colors(6), show_groups=True, keep_view=False)
    view.set_selection_mode("group")
    view.select_rows([0, 1, 2])
    ctrl = QtCore.Qt.ControlModifier
    qtbot.mouseClick(view.viewport(), QtCore.Qt.LeftButton, ctrl, point_pos(view, 3))
    assert view.selected_rows() == [0, 1, 2, 3, 4]
    qtbot.mouseClick(view.viewport(), QtCore.Qt.LeftButton, ctrl, point_pos(view, 1))
    assert view.selected_rows() == [3, 4]


def test_single_mode_click_does_not_expand(view, qtbot):
    view.show_result(result(), colors(6), show_groups=True, keep_view=False)
    qtbot.mouseClick(view.viewport(), QtCore.Qt.LeftButton, pos=point_pos(view, 0))
    assert view.selected_rows() == [0]


def hover_at(view, position):
    viewport = view.viewport()
    event = QtGui.QMouseEvent(
        QtCore.QEvent.MouseMove,
        QtCore.QPointF(position),
        QtCore.QPointF(viewport.mapToGlobal(position)),
        QtCore.Qt.NoButton,
        QtCore.Qt.NoButton,
        QtCore.Qt.NoModifier,
    )
    QtWidgets.QApplication.sendEvent(viewport, event)


def test_hover_reports_point_under_cursor(view):
    view.show_result(result(), colors(6), show_groups=False, keep_view=False)
    hover_at(view, point_pos(view, 1))
    assert view.owner.hovers[-1] == "c:/1.png"
    hover_at(view, QtCore.QPoint(1, 1))
    assert view.owner.hovers[-1] is None


def test_press_hides_hover(view, qtbot):
    view.show_result(result(), colors(6), show_groups=False, keep_view=False)
    hover_at(view, point_pos(view, 1))
    assert view.owner.hovers[-1] == "c:/1.png"
    qtbot.mousePress(view.viewport(), QtCore.Qt.LeftButton, pos=point_pos(view, 1))
    assert view.owner.hovers[-1] is None
    qtbot.mouseRelease(view.viewport(), QtCore.Qt.LeftButton, pos=point_pos(view, 1))


def test_labels_sit_below_lowest_member(view):
    view.show_result(result(), colors(6), show_groups=True, keep_view=False)
    label = view.label_items()[0]
    lowest = max(point_pos(view, row).y() for row in (0, 1, 2))
    label_top = view.mapFromScene(label.scenePos()).y() + label.boundingRect().top()
    assert label_top > lowest + view.item_extent() / 2
