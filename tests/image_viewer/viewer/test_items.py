import py_compile

from source.image_viewer.viewer.items import ViewerItems


def test_compile():
    py_compile.compile('source/image_viewer/viewer/items.py')


def test_navigation_next_prev():
    items = ViewerItems()
    items.set_items(['a', 'b', 'c'], ['sa', 'sb', 'sc'], [1.0, 2.0, 3.0])

    assert items.current_index() is None
    assert items.next_index() == 1
    assert items.prev_index() == 0

    items.set_current_index(1)
    assert items.current_index() == 1
    assert items.next_path() == 'c'
    assert items.prev_path() == 'a'

    assert items.move_current_next() == 'c'
    assert items.current_index() == 2

    assert items.move_current_next(loop=True) == 'a'
    assert items.current_index() == 0

    assert items.move_current_prev(loop=True) == 'c'
    assert items.current_index() == 2


def test_selection_updates_current_index():
    items = ViewerItems()
    items.set_items(['a', 'b'], ['sa', 'sb'], [1.0, 2.0])
    items.set_selected([0], last=0)
    assert items.current_index() == 0
    items.toggle_selection(1)
    assert items.current_index() == 1
