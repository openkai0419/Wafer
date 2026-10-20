import time

import numpy as np
import pytest
from PySide6 import QtCore, QtGui

from extensions.mapping.map_view import MapView
from extensions.mapping.session import MapDiagnostics, MapResult

SIZES = [10_000, 100_000]
ZOOMS = [2, 4, 16]
PAN_STEPS = 30
PAN_PIXELS = 12
VIEW_SIZE = (1200, 800)
INNER_SHARE = 0.8
IMAGE_CAP = 256


class Owner:
    def __init__(self):
        self.pixmap = QtGui.QPixmap(128, 96)
        self.pixmap.fill(QtGui.QColor("red"))

    def map_thumbnails(self, paths, size):
        return [self.pixmap] * len(paths)

    def hide_hover(self):
        pass


def clustered_result(count: int) -> MapResult:
    rng = np.random.default_rng(0)
    positions = np.clip(rng.normal(0.5, 0.2, (count, 2)), 0, 1).astype(np.float32)
    labels = rng.integers(0, 40, count).astype(np.int32)
    return MapResult([f"c:/{i}.png" for i in range(count)], positions, np.zeros(count, bool), np.zeros(count, bool), labels, np.arange(count), MapDiagnostics())


@pytest.fixture()
def view(qtbot):
    widget = MapView(Owner())
    qtbot.addWidget(widget)
    widget.resize(*VIEW_SIZE)
    widget.show()
    widget.set_image_cap(IMAGE_CAP)
    yield widget
    widget.close()


def zoom_to(view: MapView, zoom: float) -> None:
    view.resetTransform()
    view.fitInView(QtCore.QRectF(0, 0, 1000, 1000), QtCore.Qt.KeepAspectRatio)
    view.fit_scale = view.transform().m11()
    view.scale(zoom, zoom)
    view.invalidate()


def drawn_images(view: MapView) -> tuple[list[int], np.ndarray]:
    view.current_layer()
    return view.image_rows.tolist(), view.image_rects.copy()


def inner_rows(view: MapView, rows: set[int]) -> set[int]:
    size = view.viewport().size()
    margin = (1 - INNER_SHARE) / 2
    device = view.device_positions()
    low = np.array([size.width() * margin, size.height() * margin])
    high = np.array([size.width(), size.height()]) - low
    return {row for row in rows if (low <= device[row]).all() and (device[row] <= high).all()}


def overlapping_flips(before: list[int], after: list[int], rects: np.ndarray, ignored: int | None = None) -> int:
    rank_before = {row: index for index, row in enumerate(before)}
    kept = [index for index, row in enumerate(after) if row in rank_before and row != ignored]
    flips = 0
    for position, i in enumerate(kept):
        for j in kept[position + 1 :]:
            a, b = rects[i], rects[j]
            if a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3] and rank_before[after[i]] > rank_before[after[j]]:
                flips += 1
    return flips


@pytest.mark.parametrize("count", SIZES)
@pytest.mark.parametrize("zoom", ZOOMS)
def test_pan_frame_cost_and_stability(view, count, zoom):
    view.show_result(clustered_result(count), [QtGui.QColor("blue")] * count, keep_view=False)
    zoom_to(view, zoom)
    before, _ = drawn_images(view)
    times, replaced, flips, others = [], [], [], []
    for _ in range(PAN_STEPS):
        bar = view.horizontalScrollBar()
        bar.setValue(bar.value() + PAN_PIXELS)
        started = time.perf_counter()
        after, rects = drawn_images(view)
        times.append(time.perf_counter() - started)
        replaced.append(len(inner_rows(view, set(after) - set(before))))
        flips.append(overlapping_flips(before, after, rects))
        others.append(overlapping_flips(before, after, rects, after[-1] if after else None))
        before = after
    print(
        f"\n[MapView pan] files={count:,} zoom={zoom} images={len(before)} "
        f"frame={np.median(times) * 1000:.1f}ms max={max(times) * 1000:.1f}ms "
        f"replaced_inside={np.mean(replaced):.2f}/frame overlap_flips={np.mean(flips):.2f}/frame without_front={np.mean(others):.2f}/frame"
    )


@pytest.mark.parametrize("count", SIZES)
def test_zoom_frame_cost(view, count):
    view.show_result(clustered_result(count), [QtGui.QColor("blue")] * count, keep_view=False)
    zoom_to(view, 1)
    view.current_layer()
    times = []
    for _ in range(8):
        view.scale(1.25, 1.25)
        started = time.perf_counter()
        view.current_layer()
        times.append(time.perf_counter() - started)
    print(f"\n[MapView zoom] files={count:,} frame={np.median(times) * 1000:.1f}ms max={max(times) * 1000:.1f}ms")
