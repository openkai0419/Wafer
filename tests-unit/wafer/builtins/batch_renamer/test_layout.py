import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6 import QtWidgets
from PySide6.QtCore import Qt

from wafer.builtins.batch_renamer.layout import (
    DIRECTIONS,
    OrientedSplitter,
    normalise_direction,
)


@pytest.fixture
def panes(qtbot):
    first = QtWidgets.QWidget()
    second = QtWidgets.QWidget()
    return first, second


def test_normalise_direction_defaults():
    assert normalise_direction("XX") == "TB"
    assert normalise_direction("XX", "LR") == "LR"
    for token in DIRECTIONS:
        assert normalise_direction(token) == token


def test_tb_is_vertical_first_leads(panes):
    first, second = panes
    split = OrientedSplitter(first, second, "TB")
    assert split.orientation() == Qt.Vertical
    assert split.widget(0) is first
    assert split.widget(1) is second


def test_lr_is_horizontal(panes):
    first, second = panes
    split = OrientedSplitter(first, second, "LR")
    assert split.orientation() == Qt.Horizontal
    assert split.widget(0) is first


def test_reversed_directions_swap_visual_order(panes):
    first, second = panes
    split = OrientedSplitter(first, second, "BT")
    assert split.orientation() == Qt.Vertical
    assert split.widget(0) is second
    assert split.widget(1) is first
    split.set_direction("RL")
    assert split.orientation() == Qt.Horizontal
    assert split.widget(0) is second


def test_ordered_sizes_roundtrip_reversed(panes, qtbot):
    first, second = panes
    split = OrientedSplitter(first, second, "RL")
    split.resize(600, 200)
    split.apply_ordered_sizes([400, 100])
    split.show()
    qtbot.waitExposed(split)
    logical = split.ordered_sizes()
    assert logical[0] > logical[1]


def test_pending_sizes_applied_on_show(panes, qtbot):
    first, second = panes
    split = OrientedSplitter(first, second, "TB")
    split.apply_ordered_sizes([300, 100])
    split.resize(600, 400)
    split.show()
    qtbot.waitExposed(split)
    assert split.sizes()[0] > split.sizes()[1]
