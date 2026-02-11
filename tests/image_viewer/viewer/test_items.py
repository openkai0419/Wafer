import py_compile

from source.image_viewer.viewer.items import ViewerItems


def test_compile():
    py_compile.compile('source/image_viewer/viewer/items.py')


def test_navigation_next_prev():
    items = ViewerItems()
    items.set_items(['a', 'b', 'c'], ['sa', 'sb', 'sc'], [1.0, 2.0, 3.0])
    assert items.index_of_path('a') == 0
    assert items.index_of_path('b') == 1
    assert items.index_of_path('c') == 2
    assert items.index_of_path('x') is None
    assert items.path_at(0) == 'a'
    assert items.path_at(2) == 'c'
    assert items.path_at(5) is None


def test_selection_and_last_selected():
    items = ViewerItems()
    items.set_items(['a', 'b'], ['sa', 'sb'], [1.0, 2.0])
    items.set_selected([0], last=0)
    assert items.last_selected_index() == 0
    assert items.last_selected_path() == 'a'
    items.toggle_selection(1)
    assert items.last_selected_index() == 1
    assert items.last_selected_path() == 'b'
