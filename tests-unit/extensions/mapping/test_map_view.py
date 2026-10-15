import numpy as np
import pytest
from PySide6 import QtCore, QtGui, QtWidgets

from extensions.mapping import map_view as map_view_module
from extensions.mapping.map_view import MapView
from extensions.mapping.session import MapDiagnostics, MapResult


class Owner:
    def __init__(self):
        self.requested = []
        self.hovers = []
        self.pixmaps = {}

    def map_thumbnails(self, paths, size):
        self.requested.append(list(paths))
        return [self.pixmaps.get(path) for path in paths]

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


def test_show_result_keeps_points_as_arrays_and_labels_as_items(view):
    view.show_result(result(), colors(6), show_groups=True, keep_view=False)
    assert view.positions.shape == (6, 2)
    assert [type(item).__name__ for item in view.scene().items()] == ["GroupLabelItem"] * 2
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
    return view.mapFromScene(QtCore.QPointF(*view.positions[row]))


def test_drag_starting_on_a_point_selects_several(view, qtbot):
    view.show_result(result(), colors(6), show_groups=False, keep_view=False)
    viewport = view.viewport()
    start = point_pos(view, 0)
    end = view.mapFromScene(QtCore.QPointF(400, 1000)) + QtCore.QPoint(15, 15)
    assert view.row_at(start) == 0
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
    view.viewport().repaint()
    center = point_pos(view, row)
    side = int(view.item_extent()) + 32
    return view.current_layer().toImage().copy(center.x() - side // 2, center.y() - side // 2, side, side)


@pytest.mark.parametrize("thumbnail_zoom", [2.0, 0.5])
def test_outlier_is_drawn_with_a_ring_even_when_unselected(view, thumbnail_zoom):
    image = QtGui.QPixmap(32, 32)
    image.fill(QtGui.QColor("white"))
    view.owner.pixmaps = {f"c:/{i}.png": image for i in range(6)}
    view.set_thumbnail_zoom(thumbnail_zoom)
    view.show_result(result(), colors(6), show_groups=False, keep_view=False)
    plain = render_point(view, 1)
    view.show_result(result(outlier_rows=[1]), colors(6), show_groups=False, keep_view=True)
    assert render_point(view, 1) != plain


def test_image_scale_changes_extent_and_clamps(view):
    view.show_result(result(), colors(6), show_groups=False, keep_view=False)
    base = view.point_size()
    view.set_image_scale(2.0)
    assert view.point_size() == pytest.approx(base * 2)
    view.set_image_scale(99)
    assert view.image_scale == 4.0
    view.set_image_scale(0)
    assert view.image_scale == map_view_module.MIN_IMAGE_SCALE


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


def image_result(count, spread=1.0):
    rng = np.random.default_rng(1)
    return MapResult(
        [f"c:/{i}.png" for i in range(count)],
        (rng.random((count, 2)) * spread).astype(np.float32),
        np.zeros(count, dtype=bool),
        np.zeros(count, dtype=bool),
        None,
        {},
        np.arange(count),
        MapDiagnostics(),
    )


def loaded_owner(view, count):
    pixmap = QtGui.QPixmap(16, 16)
    pixmap.fill(QtGui.QColor("white"))
    view.owner.pixmaps = {f"c:/{i}.png": pixmap for i in range(count)}


def test_images_are_capped_one_per_cell_and_the_rest_stay_dots(view):
    loaded_owner(view, 2000)
    view.set_thumbnail_zoom(0.5)
    view.show_result(image_result(2000), colors(2000), show_groups=False, keep_view=False)
    view.set_image_limit(50)
    view.viewport().repaint()
    assert 0 < len(view.image_rows) <= 50
    view.set_image_limit(10_000)
    view.set_image_spacing(1.0)
    view.viewport().repaint()
    cells = np.floor(view.device_positions()[view.image_rows] / view.item_extent()).astype(int)
    assert len({tuple(cell) for cell in cells}) == len(view.image_rows) < 2000
    spaced = len(view.image_rows)
    view.set_image_spacing(0.5)
    view.viewport().repaint()
    assert len(view.image_rows) > spaced


def test_selected_files_get_images_first(view):
    loaded_owner(view, 2000)
    view.set_thumbnail_zoom(0.5)
    view.show_result(image_result(2000, spread=0.01), colors(2000), show_groups=False, keep_view=False)
    view.set_image_limit(1)
    view.select_rows([1234])
    view.viewport().repaint()
    assert view.image_rows.tolist() == [1234]


def test_image_choice_is_stable_across_repaints(view):
    loaded_owner(view, 500)
    view.set_thumbnail_zoom(0.5)
    view.show_result(image_result(500), colors(500), show_groups=False, keep_view=False)
    view.viewport().repaint()
    first = sorted(view.image_rows.tolist())
    view.invalidate()
    view.viewport().repaint()
    assert sorted(view.image_rows.tolist()) == first


def test_hover_and_click_reach_points_drawn_as_dots(view):
    loaded_owner(view, 2000)
    view.set_thumbnail_zoom(0.5)
    view.show_result(image_result(2000), colors(2000), show_groups=False, keep_view=False)
    view.set_image_limit(0)
    view.viewport().repaint()
    assert len(view.image_rows) == 0
    row = view.row_at(point_pos(view, 7))
    assert row is not None
    hover_at(view, point_pos(view, 7))
    assert view.owner.hovers[-1] == view.paths[row]


def test_hit_test_prefers_the_image_under_the_cursor(view):
    loaded_owner(view, 6)
    view.set_thumbnail_zoom(0.5)
    view.show_result(result(labels=False), colors(6), show_groups=False, keep_view=False)
    view.viewport().repaint()
    row = int(view.image_rows[-1])
    left, top, right, bottom = view.image_rects[-1]
    assert view.row_at(QtCore.QPoint(int(left) + 2, int(top) + 2)) == row


def test_arrived_thumbnail_repaints_once_after_a_short_wait(view, qtbot):
    view.set_thumbnail_zoom(0.5)
    view.show_result(result(labels=False), colors(6), show_groups=False, keep_view=False)
    view.viewport().repaint()
    version = view.version
    view.update_path("c:/0.png")
    view.update_path("c:/1.png")
    view.update_path("c:/unknown.png")
    assert view.version == version and view.image_timer.isActive()
    qtbot.waitUntil(lambda: view.version == version + 1, timeout=2000)


def test_rows_in_rect_uses_viewport_pixels(view):
    view.show_result(result(labels=False), colors(6), show_groups=False, keep_view=False)
    pos = point_pos(view, 2)
    rect = QtCore.QRectF(pos.x() - 1, pos.y() - 1, 2, 2)
    assert 2 in view.rows_in_rect(rect).tolist()


def test_hover_follows_points_not_image_rectangles(view):
    loaded_owner(view, 6)
    view.set_thumbnail_zoom(0.5)
    view.show_result(result(labels=False), colors(6), show_groups=False, keep_view=False)
    view.viewport().repaint()
    row = int(view.image_rows[-1])
    left, top, right, bottom = view.image_rects[-1]
    hover_at(view, QtCore.QPoint(int(left) + 2, int(top) + 2))
    assert view.owner.hovers == [] or view.owner.hovers[-1] is None
    hover_at(view, point_pos(view, row))
    assert view.owner.hovers[-1] == view.paths[row]


def test_wheel_zoom_grows_points_and_images_with_the_plane(view):
    view.show_result(result(labels=False), colors(6), show_groups=False, keep_view=False)
    point, display = view.point_size(), view.display_size()
    position = QtCore.QPointF(200, 200)
    event = QtGui.QWheelEvent(position, position, QtCore.QPoint(), QtCore.QPoint(0, 240), QtCore.Qt.NoButton, QtCore.Qt.NoModifier, QtCore.Qt.NoScrollPhase, False)
    view.wheelEvent(event)
    assert view.point_size() == pytest.approx(point * view.zoom)
    assert view.display_size() == pytest.approx(display * view.zoom)


def test_images_start_at_the_thumbnail_size_where_they_switch_on(view):
    view.show_result(result(labels=False), colors(6), show_groups=False, keep_view=False)
    view.set_thumbnail_zoom(view.zoom)
    assert view.thumbnails
    assert view.display_size() == pytest.approx(64.0)


def test_zoomed_out_points_keep_a_minimum_size(view):
    view.show_result(result(labels=False), colors(6), show_groups=False, keep_view=False)
    view.scale(0.01, 0.01)
    assert view.point_size() == map_view_module.MIN_POINT_SIZE == 1.0


def test_tiny_points_are_drawn_as_single_pixels(view):
    view.show_result(result(labels=False), colors(6), show_groups=False, keep_view=False)
    view.set_image_scale(map_view_module.MIN_IMAGE_SCALE)
    assert view.point_size() == 1.0
    assert not render_point(view, 1).isNull()
