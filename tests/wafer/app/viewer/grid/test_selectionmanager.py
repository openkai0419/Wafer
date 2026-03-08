import pytest
from wafer.app.viewer.grid.selectionmanager import SelectionManager


@pytest.fixture
def sm():
    return SelectionManager()


def test_initial_state(sm):
    assert sm.count() == 0
    assert sm.selected_indices() == set()
    assert sm.anchor_index() is None


def test_select(sm):
    sm.select(0)
    assert sm.is_selected(0)
    assert sm.count() == 1
    assert sm.anchor_index() == 0


def test_select_duplicate_does_not_duplicate(sm):
    sm.select(0)
    sm.select(0)
    assert sm.count() == 1


def test_deselect(sm):
    sm.select(0)
    sm.deselect(0)
    assert not sm.is_selected(0)
    assert sm.count() == 0
    assert sm.anchor_index() is None


def test_deselect_nonexistent(sm):
    sm.deselect(99)
    assert sm.count() == 0


def test_toggle_on_off(sm):
    sm.toggle(0)
    assert sm.is_selected(0)
    assert sm.anchor_index() == 0
    sm.toggle(0)
    assert not sm.is_selected(0)
    assert sm.anchor_index() is None


def test_clear(sm):
    sm.select(0)
    sm.select(1)
    sm.select(2)
    sm.clear()
    assert sm.count() == 0
    assert sm.anchor_index() is None


def test_clear_empty(sm):
    sm.clear()
    assert sm.count() == 0


def test_add_selection(sm):
    sm.add_selection([0, 1, 2])
    assert sm.count() == 3
    assert sm.anchor_index() == 0


def test_add_selection_with_last(sm):
    sm.add_selection([0, 1, 2], last=2)
    assert sm.anchor_index() == 2


def test_add_selection_merges(sm):
    sm.select(0)
    sm.add_selection([1, 2])
    assert sm.count() == 3
    assert sm.is_selected(0)


def test_remove_selection(sm):
    sm.add_selection([0, 1, 2])
    sm.remove_selection([1, 2])
    assert sm.count() == 1
    assert sm.is_selected(0)
    assert not sm.is_selected(1)


def test_remove_selection_clears_last(sm):
    sm.add_selection([0, 1, 2])
    sm.remove_selection([0])
    assert sm.anchor_index() is None


def test_remove_selection_no_overlap(sm):
    sm.select(0)
    sm.remove_selection([5, 6])
    assert sm.count() == 1


def test_set_selected(sm):
    sm.set_selected([3, 4, 5])
    assert sm.selected_indices() == {3, 4, 5}
    assert sm.anchor_index() == 3


def test_set_selected_replaces(sm):
    sm.select(0)
    sm.set_selected([3, 4])
    assert not sm.is_selected(0)
    assert sm.count() == 2


def test_set_anchor(sm):
    sm.select(0)
    sm.select(1)
    sm.set_anchor(0)
    assert sm.anchor_index() == 0


def test_noemit_blocks_signals(sm):
    received = []
    sm.selectionChanged.connect(lambda s: received.append(s))
    with sm.noemit():
        sm.select(0)
        sm.select(1)
    assert received == []


def test_noemit_restores_signals(sm):
    received = []
    sm.selectionChanged.connect(lambda s: received.append(s))
    with sm.noemit():
        sm.select(0)
    sm.select(1)
    assert len(received) == 1
    assert 1 in received[0]


def test_signal_on_select(sm):
    received = []
    sm.selectionChanged.connect(lambda s: received.append(s))
    sm.select(5)
    assert len(received) == 1
    assert 5 in received[0]


def test_signal_on_clear(sm):
    sm.select(0)
    sm.select(1)
    received = []
    sm.selectionChanged.connect(lambda s: received.append(s))
    sm.clear()
    assert len(received) == 1
    assert received[0] == {0, 1}


def test_signal_on_toggle(sm):
    received = []
    sm.selectionChanged.connect(lambda s: received.append(s))
    sm.toggle(3)
    sm.toggle(3)
    assert len(received) == 2
    assert all(3 in s for s in received)


def test_is_selected_false(sm):
    assert not sm.is_selected(99)
