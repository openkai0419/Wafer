import pytest
from source.app.viewer.grid.items import GridItemModel


@pytest.fixture
def items():
    vi = GridItemModel()
    vi.set_items(['a', 'b', 'c'], ['sa', 'sb', 'sc'], [1.0, 2.0, 3.0])
    return vi


def test_set_items_basic(items):
    assert items.count() == 3
    assert items.paths == ['a', 'b', 'c']
    assert items.sources == ['sa', 'sb', 'sc']
    assert items.aspect_ratios == [1.0, 2.0, 3.0]


def test_set_items_none_args():
    vi = GridItemModel()
    vi.set_items(None, None, None)
    assert vi.count() == 0
    assert vi.paths == []


def test_set_items_normalizes_lengths():
    vi = GridItemModel()
    vi.set_items(['a', 'b'], ['sa'], [1.0])
    assert len(vi.sources) == 2
    assert len(vi.aspect_ratios) == 2
    assert vi.sources[1] == ""
    assert vi.aspect_ratios[1] == 1.0


def test_clear(items):
    items.clear()
    assert items.count() == 0
    assert items.paths == []


def test_index_of_path(items):
    assert items.index_of_path('a') == 0
    assert items.index_of_path('b') == 1
    assert items.index_of_path('c') == 2
    assert items.index_of_path('x') is None


def test_path_at(items):
    assert items.path_at(0) == 'a'
    assert items.path_at(2) == 'c'
    assert items.path_at(5) is None
    assert items.path_at(None) is None
    assert items.path_at(-1) is None


def test_source_at(items):
    assert items.source_at(0) == 'sa'
    assert items.source_at(None) is None
    assert items.source_at(99) is None


def test_aspect_at(items):
    assert items.aspect_at(0) == 1.0
    assert items.aspect_at(2) == 3.0
    assert items.aspect_at(None) is None
    assert items.aspect_at(99) is None


def test_selection_basic(items):
    items.set_selected([0], last=0)
    assert items.selected_count() == 1
    assert items.is_selected(0)
    assert items.last_selected_index() == 0
    assert items.last_selected_path() == 'a'
    assert items.last_selected_source() == 'sa'


def test_toggle_selection(items):
    items.toggle_selection(1)
    assert items.is_selected(1)
    assert items.last_selected_index() == 1
    assert items.last_selected_path() == 'b'
    items.toggle_selection(1)
    assert not items.is_selected(1)


def test_clear_selection(items):
    items.set_selected([0, 1])
    items.clear_selection()
    assert items.selected_count() == 0
    assert items.last_selected_index() is None


def test_deselect(items):
    items.set_selected([0, 1])
    items.deselect(0)
    assert not items.is_selected(0)
    assert items.is_selected(1)


def test_add_selection(items):
    items.set_selected([0])
    items.add_selection([1, 2], last=1)
    assert items.selected_count() == 3
    assert items.last_selected_index() == 2


def test_add_selection_empty(items):
    items.add_selection([])
    assert items.selected_count() == 0


def test_remove_selection(items):
    items.set_selected([0, 1, 2])
    items.remove_selection({1, 2})
    assert items.selected_count() == 1
    assert items.is_selected(0)


def test_set_selected_empty_clears(items):
    items.set_selected([0])
    items.set_selected([])
    assert items.selected_count() == 0


def test_selected_paths(items):
    items.set_selected([0, 2])
    paths = items.selected_paths()
    assert set(paths) == {'a', 'c'}


def test_selected_sources(items):
    items.set_selected([0, 2])
    sources = items.selected_sources()
    assert set(sources) == {'sa', 'sc'}


def test_selection_noemit(items):
    received = []
    items.selectionChanged.connect(lambda s: received.append(s))
    with items.selection_noemit():
        items.toggle_selection(0)
        items.toggle_selection(1)
    assert received == []


def test_selection_cleared_on_set_items(items):
    items.set_selected([0, 1])
    items.set_items(['x', 'y'], ['sx', 'sy'], [1.0, 1.5])
    assert items.selected_count() == 0


def test_items_changed_signal():
    vi = GridItemModel()
    received = []
    vi.itemsChanged.connect(lambda: received.append(True))
    vi.set_items(['a'], ['sa'], [1.0])
    assert len(received) == 1


def test_selection_changed_signal():
    vi = GridItemModel()
    vi.set_items(['a', 'b'], ['sa', 'sb'], [1.0, 2.0])
    received = []
    vi.selectionChanged.connect(lambda s: received.append(s))
    vi.toggle_selection(0)
    assert len(received) == 1
