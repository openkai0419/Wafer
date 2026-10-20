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


def test_show_result_keeps_points_as_arrays_without_scene_items(view):
    view.show_result(result(), colors(6), keep_view=False)
    assert view.positions.shape == (6, 2)
    assert view.scene().items() == []


def test_select_rows_is_silent(view, qtbot):
    view.show_result(result(), colors(6), keep_view=False)
    emitted = []
    view.selection_changed.connect(lambda: emitted.append(1))
    view.select_rows([1, 2])
    assert view.selected_rows() == [1, 2] and emitted == []


def test_rubber_band_drag_selects(view, qtbot):
    view.show_result(result(), colors(6), keep_view=False)
    viewport = view.viewport()
    start = view.mapFromScene(QtCore.QPointF(0, 0)) - QtCore.QPoint(15, 15)
    end = view.mapFromScene(QtCore.QPointF(400, 1000)) + QtCore.QPoint(15, 15)
    qtbot.mousePress(viewport, QtCore.Qt.LeftButton, pos=start)
    qtbot.mouseMove(viewport, pos=end)
    qtbot.mouseRelease(viewport, QtCore.Qt.LeftButton, pos=end)
    assert {0, 1, 2} <= set(view.selected_rows())


def test_thumbnails_are_requested_only_while_shown(view, qtbot):
    view.show_result(result(), colors(6), keep_view=False)
    view.set_thumbnails_visible(False)
    view.viewport().repaint()
    assert view.owner.requested == []
    view.set_thumbnails_visible(True)
    view.viewport().repaint()
    assert view.owner.requested


def test_extend_context_delegates_to_owner(view):
    assert view.extend_context(None, None) == {"paths": ["x"]}


def point_pos(view, row):
    return view.mapFromScene(QtCore.QPointF(*view.positions[row]))


def test_drag_starting_on_a_point_selects_several(view, qtbot):
    view.show_result(result(), colors(6), keep_view=False)
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
    view.show_result(result(), colors(6), keep_view=False)
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
    view.show_result(result(), colors(6), keep_view=False)
    view.select_rows([0])
    ctrl = QtCore.Qt.ControlModifier
    qtbot.mouseClick(view.viewport(), QtCore.Qt.LeftButton, ctrl, point_pos(view, 1))
    assert view.selected_rows() == [0, 1]
    qtbot.mouseClick(view.viewport(), QtCore.Qt.LeftButton, ctrl, point_pos(view, 1))
    assert view.selected_rows() == [0]


def render_point(view, row):
    view.viewport().repaint()
    center = point_pos(view, row)
    side = int(view.item_extent()) + 32
    return view.current_layer().toImage().copy(center.x() - side // 2, center.y() - side // 2, side, side)


@pytest.mark.parametrize("thumbnails", [False, True])
def test_outlier_looks_different_even_when_unselected(view, thumbnails):
    image = QtGui.QPixmap(32, 32)
    image.fill(QtGui.QColor("white"))
    view.owner.pixmaps = {f"c:/{i}.png": image for i in range(6)}
    view.set_thumbnails_visible(thumbnails)
    view.show_result(result(), colors(6), keep_view=False)
    plain = render_point(view, 1)
    view.show_result(result(outlier_rows=[1]), colors(6), keep_view=True)
    assert render_point(view, 1) != plain


def test_outlier_dots_are_squares_of_the_same_size_without_a_ring(view):
    view.set_point_size(12)
    ring = round(map_view_module.dpix(map_view_module.RING) * view.devicePixelRatioF())
    dot_corner = ring * 2 + 1

    def alpha(at, selected, outlier):
        sprite = view.build_sprite(QtGui.QColor("red"), selected, outlier).toImage()
        return sprite.pixelColor(at, at).alpha()

    assert alpha(dot_corner, selected=False, outlier=True) == 255 and alpha(ring, selected=False, outlier=True) == 0
    assert alpha(dot_corner, selected=False, outlier=False) < 128


def test_image_scale_changes_extent_and_clamps(view):
    view.show_result(result(), colors(6), keep_view=False)
    point, display = view.point_size(), view.display_size()
    view.set_image_scale(2.0)
    assert view.point_size() == pytest.approx(point)
    assert view.display_size() == pytest.approx(display * 2)
    view.set_image_scale(99)
    assert view.image_scale == 4.0
    view.set_image_scale(0)
    assert view.image_scale == map_view_module.MIN_IMAGE_SCALE


def test_ctrl_wheel_does_not_zoom_map(view):
    view.show_result(result(), colors(6), keep_view=False)
    before = view.transform().m11()
    position = QtCore.QPointF(10, 10)
    event = QtGui.QWheelEvent(position, position, QtCore.QPoint(), QtCore.QPoint(0, 120), QtCore.Qt.NoButton, QtCore.Qt.ControlModifier, QtCore.Qt.NoScrollPhase, False)
    view.wheelEvent(event)
    assert view.transform().m11() == before


def test_plain_wheel_zooms_map(view):
    view.show_result(result(), colors(6), keep_view=False)
    before = view.transform().m11()
    position = QtCore.QPointF(10, 10)
    event = QtGui.QWheelEvent(position, position, QtCore.QPoint(), QtCore.QPoint(0, 120), QtCore.Qt.NoButton, QtCore.Qt.NoModifier, QtCore.Qt.NoScrollPhase, False)
    view.wheelEvent(event)
    assert view.transform().m11() > before


def test_group_mode_expands_click_and_rows(view, qtbot):
    view.show_result(result(), colors(6), keep_view=False)
    view.set_selection_mode("group")
    qtbot.mouseClick(view.viewport(), QtCore.Qt.LeftButton, pos=point_pos(view, 0))
    assert view.selected_rows() == [0, 1, 2]
    assert view.expand_to_groups([3, 5]) == [3, 4, 5]


def test_group_mode_ctrl_click_toggles_whole_group(view, qtbot):
    view.show_result(result(), colors(6), keep_view=False)
    view.set_selection_mode("group")
    view.select_rows([0, 1, 2])
    ctrl = QtCore.Qt.ControlModifier
    qtbot.mouseClick(view.viewport(), QtCore.Qt.LeftButton, ctrl, point_pos(view, 3))
    assert view.selected_rows() == [0, 1, 2, 3, 4]
    qtbot.mouseClick(view.viewport(), QtCore.Qt.LeftButton, ctrl, point_pos(view, 1))
    assert view.selected_rows() == [3, 4]


def test_single_mode_click_does_not_expand(view, qtbot):
    view.show_result(result(), colors(6), keep_view=False)
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
    view.show_result(result(), colors(6), keep_view=False)
    hover_at(view, point_pos(view, 1))
    assert view.owner.hovers[-1] == "c:/1.png"
    hover_at(view, QtCore.QPoint(1, 1))
    assert view.owner.hovers[-1] is None


def test_press_hides_hover(view, qtbot):
    view.show_result(result(), colors(6), keep_view=False)
    hover_at(view, point_pos(view, 1))
    assert view.owner.hovers[-1] == "c:/1.png"
    qtbot.mousePress(view.viewport(), QtCore.Qt.LeftButton, pos=point_pos(view, 1))
    assert view.owner.hovers[-1] is None
    qtbot.mouseRelease(view.viewport(), QtCore.Qt.LeftButton, pos=point_pos(view, 1))


def image_result(count, spread=1.0):
    rng = np.random.default_rng(1)
    return MapResult(
        [f"c:/{i}.png" for i in range(count)],
        (rng.random((count, 2)) * spread).astype(np.float32),
        np.zeros(count, dtype=bool),
        np.zeros(count, dtype=bool),
        None,
        np.arange(count),
        MapDiagnostics(),
    )


def loaded_owner(view, count):
    pixmap = QtGui.QPixmap(16, 16)
    pixmap.fill(QtGui.QColor("white"))
    view.owner.pixmaps = {f"c:/{i}.png": pixmap for i in range(count)}


def test_images_are_capped_one_per_cell_and_the_rest_stay_dots(view):
    loaded_owner(view, 2000)
    view.set_thumbnails_visible(True)
    view.show_result(image_result(2000), colors(2000), keep_view=False)
    view.set_image_limit(50)
    view.viewport().repaint()
    assert 0 < len(view.image_rows) <= 50
    view.set_image_limit(10_000)
    view.set_image_spacing(1.0)
    view.viewport().repaint()
    cells = np.floor(view.positions[view.image_rows] / (view.item_extent() / view.viewportTransform().m11())).astype(int)
    assert len({tuple(cell) for cell in cells}) == len(view.image_rows) < 2000
    spaced = len(view.image_rows)
    view.set_image_spacing(0.5)
    view.viewport().repaint()
    assert len(view.image_rows) > spaced


def test_selection_does_not_change_which_files_get_images(view):
    loaded_owner(view, 2000)
    view.set_thumbnails_visible(True)
    view.show_result(image_result(2000, spread=0.01), colors(2000), keep_view=False)
    view.set_image_limit(20)
    view.viewport().repaint()
    shown = sorted(view.image_rows.tolist())
    view.select_rows([row for row in range(2000) if row not in shown])
    view.viewport().repaint()
    assert sorted(view.image_rows.tolist()) == shown


def test_image_choice_is_stable_across_repaints(view):
    loaded_owner(view, 500)
    view.set_thumbnails_visible(True)
    view.show_result(image_result(500), colors(500), keep_view=False)
    view.viewport().repaint()
    first = sorted(view.image_rows.tolist())
    view.invalidate()
    view.viewport().repaint()
    assert sorted(view.image_rows.tolist()) == first


def colored_owner(view, count):
    pixmaps = {}
    for i in range(count):
        pixmap = QtGui.QPixmap(16, 12)
        pixmap.fill(QtGui.QColor.fromHsv(i * 37 % 360, 200, 120 + i % 120))
        pixmaps[f"c:/{i}.png"] = pixmap
    view.owner.pixmaps = pixmaps


def zoomed_map(view, count, zoom=4.0):
    colored_owner(view, count)
    view.set_thumbnails_visible(True)
    view.show_result(image_result(count), colors(count), keep_view=False)
    view.scale(zoom, zoom)
    view.viewport().repaint()


def pan(view, dx, dy=0):
    view.horizontalScrollBar().setValue(view.horizontalScrollBar().value() + dx)
    view.verticalScrollBar().setValue(view.verticalScrollBar().value() + dy)
    return view.current_layer()


def full_repaint(view, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(view, "update_layer", lambda *args: False)
        view.layer_key = (view.layer_key[0], None, None)
        return view.current_layer().toImage()


def inner_image_rows(view, share=0.6):
    size = view.viewport().size()
    margin = np.array([size.width(), size.height()]) * (1 - share) / 2
    device = view.device_positions()[view.image_rows]
    inside = ((device >= margin) & (device <= np.array([size.width(), size.height()]) - margin)).all(axis=1)
    return set(view.image_rows[inside].tolist())


def test_panning_repaints_only_what_changed_and_matches_a_full_repaint(view, monkeypatch):
    zoomed_map(view, 3000)
    view.select_rows(range(0, 3000, 3))
    view.current_layer()
    for dx, dy in ((7, 0), (0, -5), (-13, 9), (40, 3), *[(9, 2)] * 12, *[(-6, -7)] * 12):
        layer = pan(view, dx, dy)
        assert layer is view.layer
        assert layer.toImage() == full_repaint(view, monkeypatch)


def test_only_the_image_nearest_the_center_comes_to_the_front_and_stays_there(view):
    zoomed_map(view, 3000)
    first = int(view.image_rows[-1])
    center = np.array([view.viewport().width() / 2, view.viewport().height() / 2])
    device = view.device_positions()[view.image_rows]
    assert first == int(view.image_rows[np.argmin(((device - center) ** 2).sum(axis=1))])
    for _ in range(20):
        pan(view, 6)
        if int(view.image_rows[-1]) != first:
            break
    second = int(view.image_rows[-1])
    assert second != first
    rows = view.image_rows.tolist()
    assert first in rows and rows.index(first) == len(rows) - 2
    view.show_result(image_result(3000), colors(3000), keep_view=True)
    view.viewport().repaint()
    assert view.depth[second] > view.depth[first] > 0


def test_panning_keeps_the_images_in_the_middle(view):
    zoomed_map(view, 3000)
    for _ in range(10):
        middle = inner_image_rows(view)
        pan(view, 9, 4)
        assert middle <= set(view.image_rows.tolist())


def test_panning_in_from_the_corner_keeps_the_images_in_the_middle(view):
    zoomed_map(view, 3000)
    view.horizontalScrollBar().setValue(view.horizontalScrollBar().minimum())
    view.verticalScrollBar().setValue(view.verticalScrollBar().minimum())
    view.current_layer()
    target = round(view.image_limit * map_view_module.IMAGE_FILL_TARGET)
    for _ in range(40):
        middle = inner_image_rows(view)
        pan(view, 9, 9)
        assert middle <= set(view.image_rows.tolist())
        assert len(view.image_rows) <= view.image_limit
    assert len(view.image_rows) >= target * 0.9


def test_a_raised_image_stays_raised_only_while_the_next_result_has_it(view):
    zoomed_map(view, 3000)
    front = int(view.image_rows[-1])
    path = view.paths[front]
    view.show_result(image_result(3000), colors(3000), keep_view=True)
    assert view.depth[view.rows_by_path[path]] > 0
    view.show_result(image_result(10), colors(10), keep_view=True)
    view.show_result(image_result(3000), colors(3000), keep_view=True)
    assert view.depth[view.rows_by_path[path]] <= 0


@pytest.mark.parametrize("seed", range(4))
def test_point_index_finds_exactly_the_points_in_a_box(seed):
    rng = np.random.default_rng(seed)
    points = np.vstack([rng.normal(500, 150, (5000, 2)), rng.random((200, 2)) * (4000, 300) - (500, 0)])
    index = map_view_module.PointIndex(points)
    for _ in range(50):
        left, top = rng.random(2) * 4000 - 1000
        box = (left, top, left + rng.random() * 800, top + rng.random() * 800)
        expected = np.flatnonzero(map_view_module.inside(points, box))
        assert np.array_equal(np.sort(index.rows_in(box)), expected)
        assert index.count(box) >= expected.size


def test_hover_and_click_reach_points_drawn_as_dots(view):
    loaded_owner(view, 2000)
    view.set_thumbnails_visible(True)
    view.show_result(image_result(2000), colors(2000), keep_view=False)
    view.set_image_limit(0)
    view.viewport().repaint()
    assert len(view.image_rows) == 0
    row = view.row_at(point_pos(view, 7))
    assert row is not None
    hover_at(view, point_pos(view, 7))
    assert view.owner.hovers[-1] == view.paths[row]


def test_hit_test_prefers_the_image_under_the_cursor(view):
    loaded_owner(view, 6)
    view.set_thumbnails_visible(True)
    view.show_result(result(labels=False), colors(6), keep_view=False)
    view.viewport().repaint()
    row = int(view.image_rows[-1])
    left, top, right, bottom = view.image_rects[-1]
    assert view.row_at(QtCore.QPoint(int(left) + 2, int(top) + 2)) == row


def test_arrived_thumbnail_repaints_once_after_a_short_wait(view, qtbot):
    view.set_thumbnails_visible(True)
    view.show_result(result(labels=False), colors(6), keep_view=False)
    view.viewport().repaint()
    version = view.version
    view.update_path("c:/0.png")
    view.update_path("c:/1.png")
    view.update_path("c:/unknown.png")
    epoch = view.image_epoch
    assert view.version == version and view.image_timer.isActive()
    qtbot.waitUntil(lambda: view.image_epoch == epoch + 1, timeout=2000)
    assert view.version == version


def test_rows_in_rect_uses_viewport_pixels(view):
    view.show_result(result(labels=False), colors(6), keep_view=False)
    pos = point_pos(view, 2)
    rect = QtCore.QRectF(pos.x() - 1, pos.y() - 1, 2, 2)
    assert 2 in view.rows_in_rect(rect).tolist()


def test_hover_follows_points_not_image_rectangles(view):
    loaded_owner(view, 6)
    view.set_thumbnails_visible(True)
    view.show_result(result(labels=False), colors(6), keep_view=False)
    view.viewport().repaint()
    row = int(view.image_rows[-1])
    left, top, right, bottom = view.image_rects[-1]
    hover_at(view, QtCore.QPoint(int(left) + 2, int(top) + 2))
    assert view.owner.hovers == [] or view.owner.hovers[-1] is None
    hover_at(view, point_pos(view, row))
    assert view.owner.hovers[-1] == view.paths[row]


def test_wheel_zoom_grows_images_but_points_keep_their_set_size(view):
    view.show_result(result(labels=False), colors(6), keep_view=False)
    point, display = view.point_size(), view.display_size()
    position = QtCore.QPointF(200, 200)
    event = QtGui.QWheelEvent(position, position, QtCore.QPoint(), QtCore.QPoint(0, 240), QtCore.Qt.NoButton, QtCore.Qt.NoModifier, QtCore.Qt.NoScrollPhase, False)
    view.wheelEvent(event)
    assert view.point_size() == pytest.approx(point)
    assert view.display_size() == pytest.approx(display * view.zoom)


def test_images_show_at_every_zoom_and_grow_from_the_fit_size(view):
    view.show_result(result(labels=False), colors(6), keep_view=False)
    assert view.thumbnails and view.zoom == pytest.approx(1.0)
    assert view.display_size() == pytest.approx(map_view_module.FIT_IMAGE_SIZE)


def test_outliers_keep_their_place_outside_the_first_view(view):
    data = result(labels=False)
    data.positions[0] = (3.0, 0.5)
    view.show_result(data, colors(6), keep_view=False)
    assert view.positions[0, 0] == pytest.approx(3000.0)
    assert view.scene().sceneRect().contains(QtCore.QPointF(3000.0, 500.0))
    assert not view.viewport().rect().contains(point_pos(view, 0))
    assert view.viewport().rect().contains(point_pos(view, 1))


def test_waiting_files_sit_below_every_placed_point(view):
    data = result(labels=False)
    data.positions[0] = (0.5, 2.0)
    view.show_result(data, colors(6), keep_view=False)
    assert view.positions[5, 1] > view.positions[0, 1]


def test_images_stop_growing_at_the_hover_size(view):
    view.show_result(result(labels=False), colors(6), keep_view=False)
    view.set_image_cap(100)
    view.scale(50, 50)
    assert view.display_size() == pytest.approx(100.0)
    view.set_image_cap(0)
    assert view.display_size() > 100.0


def test_point_size_setting_is_clamped_to_one_pixel(view):
    view.show_result(result(labels=False), colors(6), keep_view=False)
    view.set_point_size(0)
    assert view.point_size() == map_view_module.MIN_POINT_SIZE
    view.set_point_size(6)
    assert view.point_size() == pytest.approx(map_view_module.dpix(6))


def drag_over(view, qtbot, left, right, modifiers=QtCore.Qt.NoModifier):
    viewport = view.viewport()
    start = view.mapFromScene(QtCore.QPointF(left, -50)) - QtCore.QPoint(5, 5)
    end = view.mapFromScene(QtCore.QPointF(right, 1050)) + QtCore.QPoint(5, 5)
    qtbot.mousePress(viewport, QtCore.Qt.LeftButton, modifiers, start)
    qtbot.mouseMove(viewport, pos=end)
    qtbot.mouseRelease(viewport, QtCore.Qt.LeftButton, modifiers, end)


def test_rubber_band_replaces_adds_with_shift_and_removes_with_ctrl(view, qtbot):
    view.set_thumbnails_visible(False)
    view.show_result(result(labels=False), colors(6), keep_view=False)
    view.select_rows([4])
    drag_over(view, qtbot, 0, 100)
    assert view.selected_rows() == [0]
    drag_over(view, qtbot, 300, 500, QtCore.Qt.ShiftModifier)
    assert view.selected_rows() == [0, 2]
    drag_over(view, qtbot, 700, 900, QtCore.Qt.AltModifier)
    assert view.selected_rows() == [0, 2, 4]
    drag_over(view, qtbot, 300, 900, QtCore.Qt.ControlModifier)
    assert view.selected_rows() == [0]


def test_shift_click_adds_and_ctrl_click_toggles(view, qtbot):
    view.show_result(result(labels=False), colors(6), keep_view=False)
    viewport = view.viewport()
    qtbot.mouseClick(viewport, QtCore.Qt.LeftButton, pos=point_pos(view, 0))
    qtbot.mouseClick(viewport, QtCore.Qt.LeftButton, QtCore.Qt.ShiftModifier, point_pos(view, 2))
    assert view.selected_rows() == [0, 2]
    qtbot.mouseClick(viewport, QtCore.Qt.LeftButton, QtCore.Qt.ShiftModifier, QtCore.QPoint(2, 2))
    assert view.selected_rows() == [0, 2]
    qtbot.mouseClick(viewport, QtCore.Qt.LeftButton, QtCore.Qt.ControlModifier, point_pos(view, 2))
    assert view.selected_rows() == [0]


def test_group_mode_applies_to_rubber_band_operations(view, qtbot):
    view.set_thumbnails_visible(False)
    view.show_result(result(), colors(6), keep_view=False)
    view.set_selection_mode("group")
    drag_over(view, qtbot, 0, 100)
    assert view.selected_rows() == [0, 1, 2]
    drag_over(view, qtbot, 700, 900, QtCore.Qt.ShiftModifier)
    assert view.selected_rows() == [0, 1, 2, 3, 4]
    drag_over(view, qtbot, 0, 100, QtCore.Qt.ControlModifier)
    assert view.selected_rows() == [3, 4]


def scene_view_rect(view):
    return view.mapToScene(view.viewport().rect()).boundingRect()


def test_frame_selection_fits_the_selected_points(view):
    view.show_result(result(labels=False), colors(6), keep_view=False)
    view.select_rows([2, 4])
    view.frame_selection()
    shown = scene_view_rect(view)
    assert all(shown.contains(QtCore.QPointF(*view.positions[row])) for row in (2, 4))
    assert not shown.contains(QtCore.QPointF(*view.positions[0]))
    assert view.zoom > 1.5


def test_frame_without_selection_fits_every_point(view):
    view.show_result(result(labels=False), colors(6), keep_view=False)
    view.scale(8, 8)
    view.frame_selection()
    shown = scene_view_rect(view)
    assert all(shown.contains(QtCore.QPointF(*point)) for point in view.positions)


def test_frame_on_a_single_point_zooms_in_around_it(view):
    view.show_result(result(labels=False), colors(6), keep_view=False)
    view.select_rows([2])
    view.frame_selection()
    shown = scene_view_rect(view)
    assert shown.contains(QtCore.QPointF(*view.positions[2])) and shown.width() < 100


def first_per_cell_by_rows(points, cell, limit):
    _, first = np.unique(np.floor(points / cell).astype(np.int64), axis=0, return_index=True)
    return np.sort(first)[:limit]


@pytest.mark.parametrize(
    ("points", "cell", "limit"),
    [
        (np.random.default_rng(0).random((20_000, 2)) * (1600, 1000) - 50, 1.0, 300),
        (np.random.default_rng(1).normal(0, 3, (20_000, 2)), 2.0, 300),
        (np.random.default_rng(2).random((500, 2)) * 10, 1.0, 300),
        (np.zeros((9000, 2)), 1.0, 300),
    ],
)
def test_first_per_cell_matches_the_full_scan(points, cell, limit):
    assert np.array_equal(map_view_module.first_per_cell(points, cell, limit), first_per_cell_by_rows(points, cell, limit))


def test_set_groups_replaces_colors_but_keeps_points_view_and_selection(view):
    view.show_result(result(), colors(6), keep_view=False)
    view.scale(2.0, 2.0)
    transform = view.transform()
    view.select_rows([1, 3])
    positions = view.positions.copy()
    regrouped = result()
    regrouped.labels = np.array([0, 1, 1, 2, 2, -1], dtype=np.int32)
    new_colors = [QtGui.QColor("red")] + [QtGui.QColor("green")] * 2 + [QtGui.QColor("blue")] * 2 + [QtGui.QColor("gray")]
    view.set_groups(regrouped, new_colors)
    assert view.transform() == transform and np.array_equal(view.positions, positions)
    assert view.selected_rows() == [1, 3]
    assert view.group_of.tolist() == [0, 1, 1, 2, 2, -1] and len(view.color_keys) == 4


def test_the_map_has_no_group_labels():
    from extensions.mapping import map_view as module
    from extensions.mapping.session import MapResult

    assert not hasattr(module, "GroupLabelItem") and not hasattr(module.MapView, "set_labels_visible")
    assert "group_terms" not in MapResult.__dataclass_fields__


def test_caption_sits_in_the_bottom_left_corner_of_the_map(view, qtbot):
    view.resize(400, 300)
    view.show()
    view.set_caption("nai · 12 files")
    assert view.caption.text() == "nai · 12 files" and view.caption.isVisible()
    corner = view.caption.geometry()
    assert corner.left() < 20 and view.viewport().height() - corner.bottom() < 20
    view.resize(500, 400)
    qtbot.waitUntil(lambda: view.viewport().height() - view.caption.geometry().bottom() < 20, timeout=1000)
    view.set_caption("")
    assert not view.caption.isVisible()
